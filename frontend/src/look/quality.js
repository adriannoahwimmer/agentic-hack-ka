/**
 * Qualitätsstufen und adaptive Qualität (Look-Pass, W4).
 *
 * Zweck: Das Demo-Laptop hat eine Intel HD 620. Die Grafik passt sich an: Pixel-Ratio, Schatten,
 * Post-FX und AO in vier Stufen. Intel-GPUs starten auf "medium", Software-Renderer auf
 * "lowest". Liegt die Bildrate über ein 2-s-Fenster unter 30 fps, geht es eine Stufe runter
 * (nie automatisch hoch, sonst pendelt es).
 * Use-Cases: `?q=high|medium|low|lowest` erzwingt eine Startstufe; Q schaltet die Stufe
 * reihum durch (manuell, für die Demo-Probe). P und O (look/index.js) gelten zusätzlich.
 */

/** Stufen von hoch nach niedrig. pr = Obergrenze der Pixel-Ratio, shadow = Map-Größe (0 = aus). */
export const TIERS = [
  { name: 'high', pr: 1.5, shadow: 2048, post: true, ao: true },
  { name: 'medium', pr: 1.0, shadow: 1024, post: true, ao: false },
  { name: 'low', pr: 1.0, shadow: 1024, post: false, ao: false },
  { name: 'lowest', pr: 0.75, shadow: 0, post: false, ao: false },
];

const MIN_FPS = 30;
const WINDOW_S = 2;
const GRACE_S = 5; // nach Start und nach jedem Stufenwechsel (Shader-Kompilierung)

/**
 * GPU-Name aus WebGL (leer, wenn der Browser ihn verbirgt).
 * @param {import('three').WebGLRenderer} renderer
 */
export function gpuName(renderer) {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) ?? '');
  } catch {
    return '';
  }
}

/**
 * Startstufe: URL `?q=...` > GPU-Heuristik > "high".
 * @param {string} gpu
 * @param {string} search location.search
 * @returns {number} Index in TIERS
 */
export function initialTier(gpu, search = location.search) {
  const q = new URLSearchParams(search).get('q');
  const forced = TIERS.findIndex((t) => t.name === q);
  if (forced >= 0) return forced;
  if (/swiftshader|llvmpipe|software/i.test(gpu)) return 3;
  if (/intel/i.test(gpu)) return 1;
  return 0;
}

/**
 * Bildraten-Wächter: ruft onSlow(), wenn ein 2-s-Fenster unter MIN_FPS liegt.
 * Misst mit performance.now() (dt im Spiel ist auf 0,1 s gedeckelt).
 * @param {() => void} onSlow
 */
export function createFpsGuard(onSlow) {
  let grace = GRACE_S;
  let frames = 0;
  let windowStart = performance.now();
  let last = windowStart;
  return {
    /** Pro Frame aufrufen. */
    tick() {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      if (grace > 0) { grace -= dt; windowStart = now; frames = 0; return; }
      frames++;
      const span = (now - windowStart) / 1000;
      if (span >= WINDOW_S) {
        const fps = frames / span;
        frames = 0;
        windowStart = now;
        if (fps < MIN_FPS) { grace = GRACE_S; onSlow(fps); }
      }
    },
    /** Nach manuellem Wechsel neu einschwingen lassen. */
    reset() { grace = GRACE_S; },
  };
}
