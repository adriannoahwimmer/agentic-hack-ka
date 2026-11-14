/**
 * PLATZHALTER-Kern bis die Scheibe Welt ihn ersetzt (Plan, Phase 1).
 *
 * Zweck: Das Skelett baut und läuft, bevor es eine Stadt gibt. Zeigt den
 * Verbindungsstatus und loggt jede eingehende Aktion in die Konsole, damit
 * /debug/action und der WebSocket ohne Spiel prüfbar sind.
 * Use-Cases: Smoke-Test von Schritt 0b, Startpunkt für core/ in Scheibe 1.
 * Liefert nur einen Teil von ctx (siehe types.js); Scheibe 1 liefert alles.
 */
import * as THREE from 'three';

/**
 * Minimalen Kern bauen.
 * @param {{net: import('../types.js').Net}} deps
 * @returns {Promise<Partial<import('../types.js').Ctx>>}
 */
export async function createCore({ net }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(innerWidth, innerHeight);
  document.getElementById('app').appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x10141c);
  const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.1, 2000);
  camera.position.set(0, 120, 160);
  camera.lookAt(0, 0, 0);
  scene.add(new THREE.GridHelper(400, 40, 0x3a4660, 0x222a3a));

  const label = document.createElement('div');
  label.style.cssText = 'position:fixed;left:16px;top:16px;font:14px system-ui;color:#e8ecf2';
  document.getElementById('hud').appendChild(label);
  const showStatus = (ok) => {
    label.textContent = `Fächerstadt Agents: world arrives in slice 1 · server ${ok ? 'connected' : 'offline'}`;
  };
  showStatus(false);
  net.onStatus((ok) => {
    showStatus(ok);
    console.info(`[net] ${ok ? 'connected' : 'disconnected'}`);
  });
  net.on('*', (payload, env) => console.info('[net] action', env.type, payload));

  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });

  const updates = new Set();
  return {
    three: THREE,
    scene,
    camera,
    renderer,
    net,
    onUpdate(fn) {
      updates.add(fn);
      return () => updates.delete(fn);
    },
    start() {
      let last = performance.now();
      renderer.setAnimationLoop((now) => {
        const dt = Math.min((now - last) / 1000, 0.1);
        last = now;
        for (const fn of updates) fn(dt, now / 1000);
        renderer.render(scene, camera);
      });
    },
  };
}
