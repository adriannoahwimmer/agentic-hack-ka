/**
 * Quest-NPCs: Figuren aus data/npcs.json, "Press E to talk", Dialog über POST /npc/talk.
 *
 * Zweck: Einstieg in den Demo-Pfad. Der Spieler spricht den NPC an, der Server
 * (agents/quest.py, Gemini oder Fallback) antwortet mit Text und ggf. einer Quest.
 * Die Quest selbst kommt zusätzlich als quest_update per WS (features/quest.js).
 * Use-Cases:
 * - Unter TALK_DISTANCE Metern erscheint der Hinweis, E startet das Gespräch
 * - Das Spiel läuft weiter, während der Agent denkt (Dialog mit pending)
 * - Quellen (Maps Grounding) stehen direkt unter dem Text (hud.showDialog)
 */
import npcs from '../../../data/npcs.json';

const TALK_DISTANCE = 3; // m
const HIDE_DISTANCE = 8; // m: Dialog schließt, wenn man weggeht
const DIALOG_MS = 12000;
const FIRST_LINE = 'Got any work for me?';

/**
 * Hinweis-Element "Press E to talk" (eigenes DOM, keine HUD-Änderung nötig).
 * @returns {HTMLElement}
 */
function createPrompt() {
  const el = document.createElement('div');
  el.textContent = 'Press E to talk';
  Object.assign(el.style, {
    position: 'fixed', left: '50%', bottom: '28%', transform: 'translateX(-50%)',
    padding: '6px 12px', background: 'rgba(0,0,0,0.6)', color: '#fff',
    font: '600 14px system-ui, sans-serif', borderRadius: '6px', pointerEvents: 'none',
    zIndex: 20,
  });
  el.hidden = true;
  document.body.append(el);
  return el;
}

/**
 * Feature-Einstieg: NPCs platzieren, Nähe prüfen, Gespräch auf E.
 * @param {import('../types.js').Ctx} ctx
 */
export function init(ctx) {
  const prompt = createPrompt();
  const placed = npcs.map((npc) => {
    const obj = ctx.models.person({ color: 0x6b4f2a });
    obj.position.set(npc.x, 0, npc.z);
    ctx.scene.add(obj);
    return { npc, obj, talks: 0 };
  });

  let near = null;
  let dialogFrom = null;
  let dialogTimer = null;
  let busy = false;

  /** Dialog schließen und Zustand zurücksetzen. */
  function closeDialog() {
    ctx.hud.hideDialog();
    clearTimeout(dialogTimer);
    dialogFrom = null;
  }

  /**
   * Gespräch mit einem NPC führen (POST /npc/talk).
   * @param {{npc: object, obj: object, talks: number}} entry
   */
  async function talk(entry) {
    if (busy) return;
    busy = true;
    const { npc } = entry;
    dialogFrom = entry;
    clearTimeout(dialogTimer);
    ctx.hud.showDialog({ speaker: npc.name, text: '…', pending: true });
    const p = ctx.player.position();
    try {
      const res = await fetch('/npc/talk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          npc_id: npc.id,
          player_text: entry.talks === 0 ? FIRST_LINE : '',
          x: p.x, z: p.z,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      entry.talks += 1;
      if (dialogFrom === entry) {
        ctx.hud.showDialog({ speaker: npc.name, text: data.text, sources: data.sources ?? [] });
      }
    } catch (err) {
      console.error('[npc] talk failed', err);
      if (dialogFrom === entry) ctx.hud.showDialog({ speaker: npc.name, text: "Not now. Come back later." });
    } finally {
      busy = false;
      dialogTimer = setTimeout(closeDialog, DIALOG_MS);
    }
  }

  ctx.input.onKey('KeyE', () => {
    if (near && !ctx.player.inVehicle()) talk(near);
  });

  ctx.onUpdate(() => {
    const p = ctx.player.position();
    near = null;
    for (const entry of placed) {
      const d = Math.hypot(entry.obj.position.x - p.x, entry.obj.position.z - p.z);
      if (d < TALK_DISTANCE) near = entry;
      // NPC dreht sich zum Spieler, wenn er in der Nähe ist
      if (d < 10) entry.obj.rotation.y = Math.atan2(p.x - entry.obj.position.x, p.z - entry.obj.position.z);
      if (dialogFrom === entry && d > HIDE_DISTANCE) closeDialog();
    }
    prompt.hidden = !near || ctx.player.inVehicle();
  });
}
