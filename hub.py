"""Event-/Action-Bus zwischen WebSocket, Spielzustand und Agenten.

Zweck: Registrierungspunkt für alle Backend-Features (Design.md, "Vertrag",
Registrierungspunkte). ws.py liefert Client-Events hier ab, Features abonnieren sie;
Features schicken Aktionen über send_action, der Hub validiert sie gegen protocol.py
und verteilt sie an Beobachter und alle verbundenen Browser.
Use-Cases:
- game_state/quests abonnieren Events (on_event) und liefern Snapshot-Extras
- Agenten senden set_wanted_level, spawn_units, radio_message, quest_update
- tts.py beobachtet ausgehende radio_message (on_action)
- genai_log-Zeilen gehen als agent_log an das Overlay (start)

Handler müssen schnell sein: kein LLM-Call im Handler, höchstens einen Task starten.
Fehler in einem Handler werden geloggt und stoppen die anderen nicht.
"""

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

import genai_log
import protocol
from protocol import Envelope

log = logging.getLogger(__name__)

EventHandler = Callable[
    [BaseModel, Envelope], Any
]  # fn(event, envelope), sync oder async
ActionListener = Callable[[BaseModel, Envelope], Any]  # fn(payload_model, envelope)
ConnectHook = Callable[[], Any]  # -> list[Envelope], sync oder async


async def _call(fn: Callable, *args) -> Any:
    """Sync- oder Async-Callable aufrufen und das Ergebnis liefern."""
    result = fn(*args)
    if inspect.isawaitable(result):
        result = await result
    return result


class Hub:
    """In-Process-Bus. Ein Exemplar pro Server (HUB); Tests bauen eigene."""

    def __init__(self) -> None:
        """Leeren Hub ohne Clients und Handler anlegen."""
        self._event_handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._action_listeners: dict[str, list[ActionListener]] = defaultdict(list)
        self._connect_hooks: list[ConnectHook] = []
        self._snapshot_providers: dict[str, Callable[[], Any]] = {}
        self._clients: set[Any] = set()
        self._unsubscribe_log: Callable[[], None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    # ---------------------------------------------------------------- Lebenszyklus
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Event-Loop merken und genai_log-Zeilen als agent_log weiterleiten."""
        self.loop = loop
        if self._unsubscribe_log is None:
            self._unsubscribe_log = genai_log.add_listener(self._forward_log_line)

    def stop(self) -> None:
        """Log-Weiterleitung beenden, Loop vergessen."""
        if self._unsubscribe_log is not None:
            self._unsubscribe_log()
            self._unsubscribe_log = None
        self.loop = None

    def _forward_log_line(self, line: protocol.GenaiLogLine) -> None:
        """genai_log-Listener: Zeile ohne prompt/config als agent_log senden."""
        self.send_action_threadsafe("agent_log", line.to_agent_log())

    # ---------------------------------------------------------------- Events
    def on_event(self, event_type: str, fn: EventHandler) -> None:
        """Handler für einen Event-Typ ('*' = alle) registrieren: fn(event, envelope)."""
        if event_type != "*" and event_type not in protocol.EVENT_MODELS:
            raise ValueError(f"Unbekannter Event-Typ: {event_type}")
        self._event_handlers[event_type].append(fn)

    async def publish_event(
        self, env: Envelope, event: BaseModel | None = None
    ) -> None:
        """Client-Event an alle Handler geben (in Registrierungsreihenfolge, dann '*')."""
        if event is None:
            event = protocol.EVENT_MODELS[env.type].model_validate(env.payload)
        for fn in [*self._event_handlers[env.type], *self._event_handlers["*"]]:
            try:
                await _call(fn, event, env)
            except Exception:
                log.exception("Event-Handler für %s fehlgeschlagen", env.type)

    # ---------------------------------------------------------------- Aktionen
    def on_action(self, action_type: str, fn: ActionListener) -> None:
        """Beobachter ausgehender Aktionen ('*' = alle): fn(payload_model, envelope)."""
        if action_type != "*" and action_type not in protocol.ACTION_MODELS:
            raise ValueError(f"Unbekannter Aktions-Typ: {action_type}")
        self._action_listeners[action_type].append(fn)

    async def send_action(
        self, action_type: str, payload: BaseModel | dict
    ) -> Envelope:
        """Aktion validieren, Beobachter informieren, an alle Clients senden.

        Wirft protocol.ProtocolError bei ungültiger Aktion (vor jedem Versand).
        """
        env = protocol.make_action(action_type, payload)
        model = protocol.ACTION_MODELS[action_type].model_validate(env.payload)
        for fn in [*self._action_listeners[action_type], *self._action_listeners["*"]]:
            try:
                await _call(fn, model, env)
            except Exception:
                log.exception("Aktions-Beobachter für %s fehlgeschlagen", action_type)
        await self.broadcast(env)
        return env

    def send_action_threadsafe(
        self, action_type: str, payload: BaseModel | dict
    ) -> bool:
        """send_action aus einem anderen Thread (z. B. generate im Worker). False ohne Loop."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return False
        future = asyncio.run_coroutine_threadsafe(
            self.send_action(action_type, payload), loop
        )
        future.add_done_callback(self._log_future_error)
        return True

    @staticmethod
    def _log_future_error(future) -> None:
        """Fehler aus send_action_threadsafe sichtbar machen."""
        if not future.cancelled() and future.exception() is not None:
            log.error("send_action_threadsafe fehlgeschlagen: %s", future.exception())

    # ---------------------------------------------------------------- Clients
    def add_client(self, client: Any) -> None:
        """Verbundenen Client (hat async send_text) aufnehmen. Nur ws.py."""
        self._clients.add(client)

    def remove_client(self, client: Any) -> None:
        """Client entfernen. Nur ws.py."""
        self._clients.discard(client)

    @property
    def client_count(self) -> int:
        """Anzahl verbundener Clients."""
        return len(self._clients)

    async def broadcast(self, env: Envelope) -> None:
        """Envelope an alle Clients senden; tote Verbindungen werden entfernt."""
        text = env.model_dump_json()
        for client in list(self._clients):
            try:
                await client.send_text(text)
            except Exception:  # noqa: BLE001 - Verbindung weg, Client verwerfen
                self._clients.discard(client)

    def on_connect(self, fn: ConnectHook) -> None:
        """Hook für neue Clients: fn() -> list[Envelope] (aktueller Zustand)."""
        self._connect_hooks.append(fn)

    async def connect_messages(self) -> list[Envelope]:
        """Alle Zustandsnachrichten für einen neuen Client einsammeln."""
        messages: list[Envelope] = []
        for fn in self._connect_hooks:
            try:
                messages += list(await _call(fn) or [])
            except Exception:
                log.exception("on_connect-Hook fehlgeschlagen")
        return messages

    # ---------------------------------------------------------------- Snapshot
    def register_snapshot_provider(self, name: str, fn: Callable[[], Any]) -> None:
        """Liefert Agent-Snapshots ein Extra unter extras[name]. Name nur einmal."""
        if name in self._snapshot_providers:
            raise ValueError(f"Snapshot-Provider {name!r} ist schon registriert")
        self._snapshot_providers[name] = fn

    def snapshot_extras(self) -> dict[str, Any]:
        """Extras aller Provider; Provider mit Fehler oder None fehlen einfach."""
        extras: dict[str, Any] = {}
        for name, fn in self._snapshot_providers.items():
            try:
                value = fn()
            except Exception:
                log.exception("Snapshot-Provider %s fehlgeschlagen", name)
                continue
            if value is not None:
                extras[name] = value
        return extras


HUB = Hub()
