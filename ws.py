"""WebSocket /ws und Debug-Endpoints.

Zweck: einzige Spielverbindung zum Browser (Design.md, "Vertrag"). Nimmt Events an,
validiert sie (protocol.parse_client_message), begrenzt die Rate pro Client und gibt
sie an den Hub. Ausgehende Aktionen sendet der Hub an alle registrierten Sockets.
Use-Cases:
- Browser-Spiel: Events hoch, Aktionen runter, Zustand beim Verbinden (on_connect)
- POST /debug/action (nur DEBUG_ENDPOINTS=1): beliebige Aktion broadcasten, z. B. eine
  Datei aus contract/examples/, um Frontend-Features ohne Agenten zu testen
"""

import logging
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

import config
import hub as hub_module
import protocol

log = logging.getLogger(__name__)
router = APIRouter()


def _hub() -> hub_module.Hub:
    """Aktueller Hub (Lookup zur Laufzeit, damit Tests einen eigenen einsetzen können)."""
    return hub_module.HUB


async def _send_error(ws: WebSocket, code: str, message: str) -> None:
    """error-Aktion an genau diesen Client schicken."""
    env = protocol.make_action("error", {"code": code, "message": message[:500]})
    await ws.send_text(env.model_dump_json())


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Spielverbindung: Zustand senden, dann Events empfangen, bis der Client geht."""
    await ws.accept()
    hub = _hub()
    hub.add_client(ws)
    try:
        for env in await hub.connect_messages():
            await ws.send_text(env.model_dump_json())
        window_start, count = time.monotonic(), 0
        while True:
            text = await ws.receive_text()
            now = time.monotonic()
            if now - window_start >= 1.0:
                window_start, count = now, 0
            count += 1
            if count > config.WS_MAX_EVENTS_PER_S:
                if count == config.WS_MAX_EVENTS_PER_S + 1:  # einmal pro Sekunde melden
                    await _send_error(
                        ws,
                        "rate_limited",
                        f"max. {config.WS_MAX_EVENTS_PER_S} Events/s",
                    )
                continue
            try:
                env, event = protocol.parse_client_message(text)
            except protocol.ProtocolError as e:
                code = (
                    "unknown_type"
                    if str(e).startswith("unknown_type")
                    else "invalid_message"
                )
                await _send_error(ws, code, str(e))
                continue
            await hub.publish_event(env, event)
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove_client(ws)


@router.post("/debug/action", include_in_schema=False)
async def debug_action(env: protocol.Envelope) -> dict:
    """Aktion (Server-Envelope) an alle Clients senden. 404 ohne DEBUG_ENDPOINTS=1."""
    if not config.DEBUG_ENDPOINTS:
        raise HTTPException(404, "Not Found")
    hub = _hub()
    try:
        sent = await hub.send_action(env.type, env.payload)
    except protocol.ProtocolError as e:
        raise HTTPException(422, str(e)) from e
    return {"sent": sent.model_dump(), "clients": hub.client_count}
