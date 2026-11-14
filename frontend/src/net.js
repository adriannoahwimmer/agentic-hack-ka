/**
 * WebSocket-Client nach dem Vertrag (Design.md, "Vertrag").
 *
 * Zweck: einzige Verbindung zum Server unter /ws. Verpackt Events in die
 * Envelope {type, ts, payload}, verteilt eingehende Aktionen an registrierte
 * Handler und verbindet sich nach Abbrüchen selbst neu.
 * Use-Cases: core sendet Events (player_position, shot_fired, ...), Feature-Module
 * registrieren Handler für Aktionen (set_wanted_level, spawn_units, ...).
 */

/** Vertrag: player_position höchstens 2 Hz. */
export const POSITION_INTERVAL_MS = 500;
/** Vertrag: Schüsse werden pro 500 ms zu einem shot_fired gebündelt. */
export const SHOT_BUNDLE_MS = 500;

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 5000;

/**
 * Erzeugt einen WS-Client. Verbindet erst bei connect().
 * @param {{url?: string}} [options] Standard: ws(s)://<host>/ws (im Dev über den Vite-Proxy)
 * @returns {import('./types.js').Net}
 */
export function createNet(options = {}) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = options.url ?? `${proto}://${location.host}/ws`;
  /** @type {Map<string, Set<Function>>} */
  const handlers = new Map();
  const statusHandlers = new Set();
  const throttles = new Map();
  let socket = null;
  let connected = false;
  let reconnectDelay = RECONNECT_MIN_MS;

  /** Status an alle onStatus-Handler melden. */
  function setStatus(value) {
    connected = value;
    for (const fn of statusHandlers) {
      try { fn(value); } catch (err) { console.error('[net] status handler', err); }
    }
  }

  /** Eingehende Envelope an die Handler ihres Typs und an '*' verteilen. */
  function dispatch(raw) {
    let env;
    try { env = JSON.parse(raw); } catch { console.warn('[net] kein JSON', raw); return; }
    const targets = [...(handlers.get(env.type) ?? []), ...(handlers.get('*') ?? [])];
    if (targets.length === 0) console.debug('[net] unbehandelt', env.type, env.payload);
    for (const fn of targets) {
      try { fn(env.payload, env); } catch (err) { console.error(`[net] handler ${env.type}`, err); }
    }
  }

  /** Verbindung aufbauen; bei Abbruch mit 1-5 s Backoff neu verbinden. */
  function connect() {
    socket = new WebSocket(url);
    socket.addEventListener('open', () => { reconnectDelay = RECONNECT_MIN_MS; setStatus(true); });
    socket.addEventListener('message', (e) => dispatch(e.data));
    socket.addEventListener('close', () => {
      if (connected) setStatus(false);
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    });
  }

  /**
   * Event an den Server senden. Ohne Verbindung wird es verworfen (Events sind flüchtig).
   * @param {string} type
   * @param {object} payload
   */
  function send(type, payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({ type, ts: Date.now(), payload }));
    return true;
  }

  /**
   * Wie send, aber höchstens einmal pro minIntervalMs und Typ. Der letzte Wert
   * innerhalb des Intervalls wird am Ende nachgeschickt (trailing).
   */
  function sendThrottled(type, payload, minIntervalMs) {
    const now = Date.now();
    const st = throttles.get(type) ?? { last: 0, timer: null, pending: null };
    throttles.set(type, st);
    if (!st.timer && now - st.last >= minIntervalMs) {
      st.last = now;
      send(type, payload);
      return;
    }
    st.pending = payload;
    if (!st.timer) {
      st.timer = setTimeout(() => {
        st.timer = null;
        st.last = Date.now();
        const pending = st.pending;
        st.pending = null;
        if (pending) send(type, pending);
      }, Math.max(0, minIntervalMs - (now - st.last)));
    }
  }

  /**
   * Handler für einen Aktionstyp registrieren ('*' = alle). Gibt eine Abmeldefunktion zurück.
   * @param {string} type
   * @param {(payload: object, envelope: object) => void} fn
   */
  function on(type, fn) {
    if (!handlers.has(type)) handlers.set(type, new Set());
    handlers.get(type).add(fn);
    return () => handlers.get(type)?.delete(fn);
  }

  /** Verbindungsstatus beobachten (true = verbunden). Gibt eine Abmeldefunktion zurück. */
  function onStatus(fn) {
    statusHandlers.add(fn);
    return () => statusHandlers.delete(fn);
  }

  return {
    connect, send, sendThrottled, on, onStatus,
    get connected() { return connected; },
  };
}
