/**
 * Agent-Overlay: zeigt live, was die Gemini-Agenten entscheiden (Panel oben rechts).
 *
 * Zweck: macht die Agenten im Spiel (und im Demo-Video) sichtbar. Liest den WS-Typ
 * "agent_log" (Schema: contract/examples/agent_log.json) und listet die letzten
 * 5 Einträge: Agent-Name, Tool-Calls kompakt, "Warum: ...", Modell und Latenz.
 * Reines DOM, wird nur bei neuen Nachrichten neu gebaut, nichts pro Frame.
 * Use-Cases:
 * - Polizei-Dispatcher ruft set_wanted_level / spawn_units / radio_message -> Eintrag
 * - geskripteter Fallback (kind "fallback") -> oranges Tag "FALLBACK"
 * - Fehler (status "error") -> rotes Tag "ERROR" mit Fehlertext
 * - Spieler-Funkspruch per window-CustomEvent "player-radio" {tone, text} -> Eintrag "YOU"
 * - Taste L (KeyL) blendet das Panel ein/aus, standardmäßig sichtbar
 */

const MAX_ENTRIES = 5;
const STYLE_ID = 'agent-overlay-style';

const CSS = `
.ao-panel { position: fixed; top: 60px; right: 18px; width: min(430px, 40vw); max-height: calc(100vh - 220px); overflow: hidden;
  background: rgba(0,0,0,.6); border-radius: 8px; padding: 10px 12px; pointer-events: none; z-index: 20;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #f4f6f8; font-size: 15px; line-height: 1.3;
  text-shadow: 0 1px 2px #000a; }
.ao-panel[hidden] { display: none !important; }
.ao-head { font-size: 12px; letter-spacing: 1.5px; font-weight: 700; color: #9fd3ff; margin-bottom: 6px; }
.ao-head .ao-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #3ddc84; margin-right: 6px; vertical-align: 1px; }
.ao-empty { font-size: 14px; opacity: .7; }
.ao-entry { padding: 6px 8px; margin-top: 6px; border-left: 3px solid #9fd3ff; border-radius: 4px; background: rgba(255,255,255,.04); }
.ao-entry.ao-player { border-left-color: #ffd23f; }
.ao-entry.ao-fallback { border-left-color: #ff9f1c; }
.ao-entry.ao-error { border-left-color: #e63946; }
.ao-entry.ao-new { animation: ao-flash 1.2s ease-out; }
@keyframes ao-flash { 0% { background: rgba(255,210,63,.45); transform: translateX(-6px); } 100% { background: rgba(255,255,255,.04); transform: none; } }
.ao-name { font-size: 17px; font-weight: 800; letter-spacing: .5px; }
.ao-tag { display: inline-block; font-size: 11px; font-weight: 800; padding: 1px 6px; border-radius: 3px; margin-left: 8px; vertical-align: 2px; color: #111; text-shadow: none; }
.ao-tag.ao-t-fallback { background: #ff9f1c; }
.ao-tag.ao-t-error { background: #e63946; color: #fff; }
.ao-tag.ao-t-player { background: #ffd23f; }
.ao-call { font-family: ui-monospace, Consolas, monospace; font-size: 15px; color: #c8f7c5; }
.ao-text { font-size: 15px; }
.ao-why { font-size: 15px; font-style: italic; opacity: .9; }
.ao-err { font-size: 14px; color: #ff8a8a; }
.ao-meta { font-size: 12px; opacity: .65; margin-top: 2px; }
`;

/**
 * Text auf Höchstlänge kürzen (mit Auslassungszeichen).
 * @param {unknown} s
 * @param {number} max
 * @returns {string}
 */
function trunc(s, max) {
  const t = String(s ?? '').replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

/**
 * Anzeigename eines Agenten.
 * @param {string} agent Agent-Name aus dem Log (police, quest, npc, ...)
 * @returns {string}
 */
export function agentLabel(agent) {
  const a = String(agent ?? '').toLowerCase();
  if (a.startsWith('police')) return 'POLICE DISPATCHER';
  if (a.startsWith('quest') || a.startsWith('npc')) return 'KARL THE FIXER';
  return a ? a.toUpperCase() : 'AGENT';
}

/**
 * Einen Tool-Call kompakt als Zeile formatieren.
 * @param {{tool?: string, args?: object}} call
 * @returns {string}
 */
export function formatCall(call) {
  const tool = call?.tool ?? '?';
  const args = call?.args ?? {};
  if (tool === 'set_wanted_level') return `set_wanted_level ${args.level ?? '?'}`;
  if (tool === 'spawn_units') {
    const n = args.count ?? args.target_units ?? '?';
    return trunc(`spawn_units ${n}× ${args.unit_type ?? ''} ${args.tactic ?? ''}`, 60);
  }
  if (tool === 'radio_message') return `radio_message: "${trunc(args.text, 70)}"`;
  const rest = Object.entries(args)
    .filter(([k]) => k !== 'reason')
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' ');
  return trunc(`${tool} ${rest}`, 70);
}

/**
 * Begründung eines Eintrags finden: payload.reason, sonst das erste args.reason.
 * @param {object} p agent_log-Payload
 * @returns {string}
 */
function findReason(p) {
  if (p?.reason) return String(p.reason);
  const call = (p?.output?.calls ?? []).find((c) => c?.args?.reason);
  return call ? String(call.args.reason) : '';
}

/**
 * Kleines DOM-Element mit Klasse und Text anlegen (Text immer als textContent).
 * @param {string} cls
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function div(cls, text) {
  const e = document.createElement('div');
  e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/**
 * Ein Eintrag als DOM-Knoten bauen (agent_log oder Spieler-Funk).
 * @param {object} entry {kind: 'log'|'player', payload}
 * @param {boolean} isNew neuester Eintrag -> Hervorhebung
 * @returns {HTMLElement}
 */
function renderEntry(entry, isNew) {
  const box = div('ao-entry');
  if (isNew) box.classList.add('ao-new');
  const name = div('ao-name');
  box.appendChild(name);

  if (entry.kind === 'player') {
    box.classList.add('ao-player');
    name.textContent = 'YOU';
    const tag = document.createElement('span');
    tag.className = 'ao-tag ao-t-player';
    tag.textContent = entry.payload.tone === 'taunt' ? 'TAUNT' : 'PLEAD';
    name.appendChild(tag);
    box.appendChild(div('ao-text', `"${trunc(entry.payload.text, 120)}"`));
    return box;
  }

  const p = entry.payload ?? {};
  name.textContent = agentLabel(p.agent);
  const isError = p.status === 'error';
  const isFallback = p.kind === 'fallback';
  if (isFallback) {
    box.classList.add('ao-fallback');
    const tag = document.createElement('span');
    tag.className = 'ao-tag ao-t-fallback';
    tag.textContent = 'FALLBACK';
    name.appendChild(tag);
  }
  if (isError) {
    box.classList.add('ao-error');
    const tag = document.createElement('span');
    tag.className = 'ao-tag ao-t-error';
    tag.textContent = 'ERROR';
    name.appendChild(tag);
  }

  const calls = p.output?.calls ?? [];
  for (const c of calls.slice(0, 4)) box.appendChild(div('ao-call', formatCall(c)));
  if (calls.length > 4) box.appendChild(div('ao-call', `+${calls.length - 4} more`));
  if (!calls.length && p.output?.text) box.appendChild(div('ao-text', trunc(p.output.text, 110)));

  const why = findReason(p);
  if (why) box.appendChild(div('ao-why', `Warum: ${trunc(why, 100)}`));
  if (isError && p.error) {
    const err = typeof p.error === 'object' ? (p.error.message ?? p.error.code ?? JSON.stringify(p.error)) : p.error;
    box.appendChild(div('ao-err', trunc(err, 100)));
  }

  const meta = [p.model, Number.isFinite(p.latency_ms) ? `${Math.round(p.latency_ms)} ms` : null]
    .filter(Boolean)
    .join(' · ');
  if (meta) box.appendChild(div('ao-meta', meta));
  return box;
}

/**
 * Feature-Einstieg: Panel anlegen, agent_log und "player-radio" abonnieren, Taste L.
 * @param {import('../types.js').Ctx} ctx
 * @returns {{push: (entry: {kind: 'log'|'player', payload: object}) => void, toggle: () => void}}
 */
export function init(ctx) {
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  const panel = div('ao-panel');
  const head = div('ao-head');
  const dot = document.createElement('span');
  dot.className = 'ao-dot';
  head.appendChild(dot);
  head.appendChild(document.createTextNode('POLICE DISPATCHER · KARL THE FIXER'));
  const list = div('ao-list');
  list.appendChild(div('ao-empty', 'Waiting for agent decisions… (L to hide)'));
  panel.appendChild(head);
  panel.appendChild(list);
  (document.getElementById('hud') ?? document.body).appendChild(panel);

  /** @type {{kind: 'log'|'player', payload: object}[]} neueste zuerst */
  const entries = [];

  /** Liste neu bauen (nur bei neuen Einträgen aufgerufen). */
  const render = () => {
    list.replaceChildren(...entries.map((e, i) => renderEntry(e, i === 0)));
  };

  /**
   * Neuen Eintrag vorne einfügen und neu rendern.
   * @param {{kind: 'log'|'player', payload: object}} entry
   */
  const push = (entry) => {
    entries.unshift(entry);
    if (entries.length > MAX_ENTRIES) entries.length = MAX_ENTRIES;
    render();
  };

  /** Panel ein-/ausblenden. */
  const toggle = () => {
    panel.hidden = !panel.hidden;
  };

  ctx.net.on('agent_log', (payload) => {
    if (payload) push({ kind: 'log', payload });
  });

  window.addEventListener('player-radio', (ev) => {
    const d = /** @type {CustomEvent} */ (ev).detail;
    if (d?.text) push({ kind: 'player', payload: { tone: d.tone, text: d.text } });
  });

  ctx.input.onKey('KeyL', toggle);
  return { push, toggle };
}

/**
 * Spieler-Funkspruch ins Overlay schreiben, ohne Import-Kopplung (über das CustomEvent).
 * @param {'plead'|'taunt'} tone
 * @param {string} text
 */
export function pushPlayerRadio(tone, text) {
  window.dispatchEvent(new CustomEvent('player-radio', { detail: { tone, text } }));
}
