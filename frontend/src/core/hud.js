/**
 * HUD als DOM-Overlay über dem Canvas (Scheibe Welt).
 *
 * Zweck: ctx.hud mit `setWanted`, `toast`, `setObjective`, `subtitle`, `showDialog`,
 * `hideDialog` und `addPanel`, dazu Fadenkreuz, Waffe, Verbindungspunkt und Steuerhilfe.
 * Use-Cases: Fahndungssterne (Polizei), Funk-Untertitel (Quest/Radio), NPC-Dialog mit
 * Maps-Quellen (Pflicht: "Google Maps" mit translate="no" direkt unter dem Text),
 * Agent-Log-Panel (Phase 4). Spieltexte sind Englisch.
 */

const CSS = `
#hud [hidden] { display: none !important; }
#hud { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #f4f6f8; text-shadow: 0 1px 2px #000a; }
#hud .h-stars { position: fixed; top: 14px; right: 18px; font-size: 30px; letter-spacing: 2px; }
#hud .h-stars span { color: #ffffff30; transition: color .2s, transform .2s; display: inline-block; }
#hud .h-stars span.on { color: #ffd23f; }
#hud .h-stars.flash span.on { transform: scale(1.3); }
#hud .h-net { position: fixed; top: 22px; left: 16px; width: 10px; height: 10px; border-radius: 50%; background: #e63946; box-shadow: 0 0 6px #000; }
#hud .h-net.ok { background: #2ecc71; }
#hud .h-title { position: fixed; top: 16px; left: 34px; font-size: 13px; opacity: .8; }
#hud .h-objective { position: fixed; top: 40px; left: 16px; max-width: 360px; font-size: 16px; background: #0008; padding: 8px 12px; border-left: 3px solid #ffd23f; border-radius: 4px; }
#hud .h-toasts { position: fixed; top: 70px; left: 50%; transform: translateX(-50%); display: flex; flex-direction: column; gap: 6px; align-items: center; }
#hud .h-toast { background: #000b; padding: 8px 16px; border-radius: 6px; font-size: 18px; font-weight: 600; transition: opacity .4s; }
#hud .h-subtitle { position: fixed; bottom: 120px; left: 50%; transform: translateX(-50%); max-width: 70vw; text-align: center; font-size: 19px; background: #000a; padding: 6px 14px; border-radius: 4px; }
#hud .h-dialog { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); width: min(640px, 90vw); background: #101820ee; border: 1px solid #ffffff22; border-radius: 8px; padding: 14px 18px; pointer-events: auto; text-shadow: none; }
#hud .h-dialog .speaker { font-weight: 700; color: #ffd23f; margin-bottom: 6px; }
#hud .h-dialog .text { font-size: 16px; line-height: 1.45; white-space: pre-wrap; }
#hud .h-dialog .sources { margin-top: 8px; font-size: 13px; opacity: .85; }
#hud .h-dialog .sources a { color: #8ecae6; }
#hud .h-dialog .pending::after { content: "…"; animation: hblink 1s infinite; }
@keyframes hblink { 50% { opacity: .2; } }
#hud .h-cross { position: fixed; left: 50%; top: 50%; width: 18px; height: 18px; margin: -9px 0 0 -9px; }
#hud .h-cross::before, #hud .h-cross::after { content: ""; position: absolute; background: #fff; box-shadow: 0 0 2px #000; }
#hud .h-cross::before { left: 8px; top: 0; width: 2px; height: 18px; }
#hud .h-cross::after { top: 8px; left: 0; height: 2px; width: 18px; }
#hud .h-cross.hit::before, #hud .h-cross.hit::after { background: #e63946; }
#hud .h-weapon { position: fixed; right: 18px; bottom: 40px; font-size: 16px; background: #0008; padding: 6px 12px; border-radius: 4px; }
#hud .h-help { position: fixed; left: 16px; bottom: 12px; font-size: 12px; opacity: .75; }
#hud .h-panels { position: fixed; right: 18px; top: 60px; display: flex; flex-direction: column; gap: 8px; align-items: flex-end; pointer-events: auto; }
#hud .h-start { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 10px; background: #0007; font-size: 22px; }
#hud .h-start small { font-size: 14px; opacity: .8; }
`;

/**
 * Element mit Klasse anlegen und anhängen.
 * @param {HTMLElement} parent
 * @param {string} cls
 * @param {string} [text]
 */
function el(parent, cls, text = '') {
  const e = document.createElement('div');
  e.className = cls;
  e.textContent = text;
  parent.appendChild(e);
  return e;
}

/**
 * HUD aufbauen.
 * @param {HTMLElement} root #hud
 * @param {{wantedMax?: number}} [opts]
 */
export function createHud(root, opts = {}) {
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  const wantedMax = opts.wantedMax ?? 5;
  const net = el(root, 'h-net');
  el(root, 'h-title', 'Fächerstadt Agents');
  const stars = el(root, 'h-stars');
  const starEls = Array.from({ length: wantedMax }, () => {
    const s = document.createElement('span');
    s.textContent = '★';
    stars.appendChild(s);
    return s;
  });
  const objective = el(root, 'h-objective');
  objective.hidden = true;
  const toasts = el(root, 'h-toasts');
  const subtitle = el(root, 'h-subtitle');
  subtitle.hidden = true;
  const dialog = el(root, 'h-dialog');
  dialog.hidden = true;
  const cross = el(root, 'h-cross');
  const weapon = el(root, 'h-weapon', 'Pistol');
  el(root, 'h-help', 'WASD move · Shift sprint · Mouse aim · LMB shoot · 1 pistol / 2 SMG · F enter/exit car · Esc release mouse');
  const panels = el(root, 'h-panels');
  const start = el(root, 'h-start');
  start.innerHTML = '<div>Click to play</div><small>Karlsruhe, around the Palace · real OpenStreetMap data</small>';

  let subtitleTimer = null;
  let wantedLevel = 0;

  return {
    /** Fahndungsstufe 0..wantedMax anzeigen (kurzes Aufblinken bei Änderung). */
    setWanted(level) {
      const n = Math.max(0, Math.min(wantedMax, Math.round(level)));
      starEls.forEach((s, i) => s.classList.toggle('on', i < n));
      if (n !== wantedLevel) {
        stars.classList.add('flash');
        setTimeout(() => stars.classList.remove('flash'), 350);
      }
      wantedLevel = n;
    },
    /** Aktuelle Fahndungsstufe (wie zuletzt gesetzt). */
    wanted: () => wantedLevel,
    /** Kurze Meldung oben in der Mitte. */
    toast(text, ms = 2500) {
      const t = el(toasts, 'h-toast', text);
      setTimeout(() => { t.style.opacity = '0'; }, ms);
      setTimeout(() => t.remove(), ms + 450);
    },
    /** Missionsziel oben links; null blendet es aus. */
    setObjective(text) {
      objective.hidden = !text;
      objective.textContent = text ?? '';
    },
    /** Untertitel unten (z. B. Funkspruch). */
    subtitle(text, ms = 5000) {
      subtitle.hidden = false;
      subtitle.textContent = text;
      clearTimeout(subtitleTimer);
      subtitleTimer = setTimeout(() => { subtitle.hidden = true; }, ms);
    },
    /**
     * Dialog unten. `sources` (Maps Grounding) erscheint direkt unter dem Text als
     * "Source: Google Maps · <Titel-Link>". `pending` zeigt einen Warte-Indikator.
     */
    showDialog({ speaker, text, sources = [], pending = false }) {
      dialog.hidden = false;
      dialog.replaceChildren();
      el(dialog, 'speaker', speaker);
      const t = el(dialog, 'text', text ?? '');
      t.classList.toggle('pending', Boolean(pending));
      if (sources.length) {
        const s = el(dialog, 'sources');
        s.append('Source: ');
        const gm = document.createElement('span');
        gm.setAttribute('translate', 'no');
        gm.textContent = 'Google Maps';
        s.append(gm);
        for (const src of sources) {
          s.append(' · ');
          const a = document.createElement('a');
          a.href = src.uri;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.textContent = src.title;
          s.append(a);
        }
      }
    },
    /** Dialog schließen. */
    hideDialog() { dialog.hidden = true; },
    /** Panel rechts anlegen (z. B. Agent-Log); gibt das leere Element zurück. */
    addPanel(id) {
      const p = el(panels, `h-panel h-panel-${id}`);
      p.id = `panel-${id}`;
      return p;
    },
    /** Verbindungsstatus (grün/rot). */
    setConnected(ok) { net.classList.toggle('ok', ok); net.title = ok ? 'server connected' : 'server offline'; },
    /** Waffenanzeige. */
    setWeapon(name) { weapon.textContent = name; },
    /** Trefferanzeige am Fadenkreuz. */
    hitMarker() {
      cross.classList.add('hit');
      setTimeout(() => cross.classList.remove('hit'), 120);
    },
    /** Start-Overlay ("Click to play") ein/aus. */
    setStartVisible(v) { start.hidden = !v; },
  };
}
