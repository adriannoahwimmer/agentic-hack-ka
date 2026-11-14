/**
 * Funk-Buttons: der Spieler funkt die Polizei an (betteln oder provozieren).
 *
 * Zweck: zwei HUD-Buttons unten rechts plus Tasten G (plead) und T (taunt). Ein Druck
 * wählt einen zufälligen Satz, schickt ihn per WS als "player_radio" {tone, text}
 * an den Server (Dispatcher-Agent reagiert), zeigt ihn als Untertitel und meldet ihn
 * per window-CustomEvent "player-radio" an das Agent-Overlay (ui/agentOverlay.js).
 * Gemeinsamer Cooldown 8 s (wie der Server), Buttons zeigen die Restzeit.
 * Reines DOM; der Timer läuft nur während des Cooldowns, nichts pro Frame.
 * Use-Cases:
 * - Spieler drückt G -> "Ich war das nicht, ich bin nur Tourist!" an den Dispatcher
 * - Spieler drückt T -> Trash-Talk, die Polizei reagiert gereizt
 * - ohne Pointer-Lock (Menü/Maus frei) sind die Buttons anklickbar
 */

const COOLDOWN_MS = 8000;
const SUBTITLE_MS = 3000;
const MAX_TEXT = 120;
const STYLE_ID = 'radio-buttons-style';

/** @type {Record<'plead'|'taunt', string[]>} */
const LINES = {
  plead: [
    'Ich war das nicht, ich bin nur Tourist!',
    'Ich hab nichts gemacht, ich wollte nur zum Schloss!',
    'Das ist ein Missverständnis, ich bin unschuldig!',
    'Bitte, ich hab doch nur Spätzle geholt!',
  ],
  taunt: [
    'Ihr fahrt wie meine Oma, Jungs!',
    'Ihr kriegt mich nie, nicht mal mit der Straßenbahn!',
    'Habt ihr euch im Fächer verfahren?',
    "Zu langsam! Versucht's mal mit Blaulicht UND Gas!",
  ],
};

/** Tasten und Beschriftung pro Ton. */
const BUTTONS = [
  { tone: 'plead', code: 'KeyG', key: 'G', label: 'Ich hab nichts gemacht!' },
  { tone: 'taunt', code: 'KeyT', key: 'T', label: 'Ihr kriegt mich nie!' },
];

const CSS = `
.rb-bar { position: fixed; right: 18px; bottom: 84px; display: flex; gap: 8px; pointer-events: none; z-index: 20; }
.rb-btn { pointer-events: auto; cursor: pointer; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; color: #f4f6f8; background: rgba(0,0,0,.6); border: 1px solid #ffffff33; border-radius: 6px;
  padding: 7px 12px; text-shadow: 0 1px 2px #000a; min-width: 150px; text-align: left; }
.rb-btn:hover:not(:disabled) { background: rgba(30,30,30,.75); border-color: #ffd23f; }
.rb-btn .rb-key { display: inline-block; font-weight: 800; color: #111; background: #ffd23f; border-radius: 3px;
  padding: 0 6px; margin-right: 8px; text-shadow: none; }
.rb-btn.rb-taunt .rb-key { background: #ff9f1c; }
.rb-btn:disabled { opacity: .45; cursor: default; }
`;

/**
 * Zufälligen Satz wählen, möglichst nicht denselben wie zuletzt.
 * @param {string[]} lines
 * @param {string|null} last
 * @returns {string}
 */
function pickLine(lines, last) {
  const pool = lines.length > 1 ? lines.filter((l) => l !== last) : lines;
  return pool[Math.floor(Math.random() * pool.length)];
}

/**
 * Feature-Einstieg: Buttons anlegen, Tasten G/T registrieren.
 * @param {import('../types.js').Ctx} ctx
 * @returns {{fire: (tone: 'plead'|'taunt') => boolean}}
 */
export function init(ctx) {
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  const bar = document.createElement('div');
  bar.className = 'rb-bar';
  (document.getElementById('hud') ?? document.body).appendChild(bar);

  /** @type {{tone: string, key: string, label: string, el: HTMLButtonElement, text: Text}[]} */
  const buttons = BUTTONS.map((b) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = `rb-btn rb-${b.tone}`;
    const key = document.createElement('span');
    key.className = 'rb-key';
    key.textContent = b.key;
    const text = document.createTextNode(b.label);
    el.append(key, text);
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      el.blur();
      fire(/** @type {'plead'|'taunt'} */ (b.tone));
    });
    bar.appendChild(el);
    return { ...b, el, text };
  });

  let cooldownUntil = 0;
  let timer = null;
  /** @type {Record<string, string|null>} */
  const lastLine = { plead: null, taunt: null };

  /** Beschriftung und disabled-Zustand an die Restzeit anpassen. */
  const updateButtons = () => {
    const left = Math.max(0, cooldownUntil - performance.now());
    const secs = Math.ceil(left / 1000);
    for (const b of buttons) {
      b.el.disabled = left > 0;
      b.text.textContent = left > 0 ? `${b.label} (${secs} s)` : b.label;
    }
    if (left <= 0 && timer) {
      clearInterval(timer);
      timer = null;
    }
  };

  /**
   * Funkspruch auslösen (Taste oder Klick). Im Cooldown passiert nichts.
   * @param {'plead'|'taunt'} tone
   * @returns {boolean} true, wenn gesendet
   */
  function fire(tone) {
    if (performance.now() < cooldownUntil) return false;
    const text = pickLine(LINES[tone], lastLine[tone]).slice(0, MAX_TEXT);
    lastLine[tone] = text;
    ctx.net.send('player_radio', { tone, text });
    ctx.hud.subtitle(`You: ${text}`, SUBTITLE_MS);
    window.dispatchEvent(new CustomEvent('player-radio', { detail: { tone, text } }));
    cooldownUntil = performance.now() + COOLDOWN_MS;
    updateButtons();
    if (!timer) timer = setInterval(updateButtons, 250);
    return true;
  }

  for (const b of buttons) {
    ctx.input.onKey(b.code, () => fire(/** @type {'plead'|'taunt'} */ (b.tone)));
  }
  return { fire };
}
