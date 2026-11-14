/**
 * Frontend-Kern: baut ctx gemäß types.js und startet die Spielschleife (Scheibe Welt).
 *
 * Zweck: Einstieg für main.js (`createCore({net})`). Verdrahtet Renderer, Physik, Stadt,
 * Welt, Input, HUD, Spieler und Kampf; Features bekommen ctx in `init(ctx)`.
 * Use-Cases: Spiel starten, Feature-Scheiben (Polizei, Quest, Overlay) andocken.
 *
 * Reihenfolge pro Frame: Physik (fester Schritt, inkl. Spieler-Controller) → Spieler/Kamera
 * → Kampf und Events → Feature-Updates (`ctx.onUpdate`) → Rendern.
 */
import * as THREE from 'three';
import { addAttribution } from './attribution.js';
import { buildCity, loadCityData } from './city.js';
import { createCombat } from './combat.js';
import { createHud } from './hud.js';
import { createInput } from './input.js';
import * as models from './models.js';
import { createLook } from '../look/index.js';
import { createPedestrians } from './pedestrians.js';
import { createPhysics } from './physics.js';
import { createVehicles } from './vehicle.js';
import { createPlayer } from './player.js';
import { createRenderer } from './renderer.js';
import { createWorld } from './world.js';

const SPAWN_POI = 'schlossplatz';
/** Debug/Intro: `?view=top` zeigt die Stadt von oben (Kamera fest über dem Schloss). */
const overview = new URLSearchParams(location.search).get('view') === 'top';

/**
 * Kern bauen.
 * @param {{net: import('../types.js').Net}} deps
 * @returns {Promise<import('../types.js').Ctx>}
 */
export async function createCore({ net }) {
  const hudRoot = document.getElementById('hud');
  const { renderer, scene, camera } = createRenderer(document.getElementById('app'));
  const hud = createHud(hudRoot);
  addAttribution(hudRoot);
  hud.setConnected(net.connected);
  net.onStatus((ok) => {
    hud.setConnected(ok);
    console.info(`[net] ${ok ? 'connected' : 'disconnected'}`);
  });
  net.on('*', (payload, env) => console.debug('[net] action', env.type, payload));
  // Sterne zeigt schon der Kern (Phase-1-Kriterium); police.js darf zusätzlich reagieren.
  net.on('set_wanted_level', (p) => hud.setWanted(p.level));
  net.on('error', (p) => console.warn('[net] server error', p.code, p.message));

  const [physics, data] = await Promise.all([createPhysics(), loadCityData()]);
  const { RAPIER, world: physicsWorld } = physics;

  const worldApi = createWorld({ roads: data.roads, bounds: null });
  const city = buildCity({ scene, RAPIER, world: physicsWorld, data, pois: worldApi.pois });
  worldApi.bounds = city.bounds;

  const input = createInput(renderer.domElement);
  const spawnPoi = worldApi.poi(SPAWN_POI) ?? { x: 0, z: 150 };
  const player = createPlayer({
    THREE, scene, camera, RAPIER, world: physicsWorld, fixed: physics.fixed, input, models,
    spawn: { x: spawnPoi.x, z: spawnPoi.z + 20 },
  });
  const combat = createCombat({ THREE, scene, camera, RAPIER, world: physicsWorld, input, hud, net, player, worldApi });
  const pedestrians = createPedestrians({ scene, models, worldApi, combat, player });
  const vehicles = createVehicles({
    THREE, scene, camera, RAPIER, world: physicsWorld, fixed: physics.fixed, input, models, player, worldApi, net, hud, combat, pedestrians,
  });

  const look = await createLook({ renderer, scene, camera, input, hud, player, overview });

  // Start-Overlay bis zum Pointer-Lock; danach nur noch bei Esc.
  document.addEventListener('pointerlockchange', () => hud.setStartVisible(!input.locked()));

  const updates = new Set();
  if (overview || new URLSearchParams(location.search).get('start') === '0') hud.setStartVisible(false);
  if (overview) {
    scene.fog = null;
    camera.far = 4000;
    camera.updateProjectionMatrix();
  }

  /** @type {import('../types.js').Ctx} */
  const ctx = {
    three: THREE,
    scene,
    camera,
    renderer,
    rapier: RAPIER,
    physics: physicsWorld,
    net,
    onUpdate(fn) {
      updates.add(fn);
      return () => updates.delete(fn);
    },
    input: { isDown: input.isDown, onKey: input.onKey },
    player: {
      position: player.position,
      heading: player.heading,
      inVehicle: player.inVehicle,
      object3d: player.object3d,
    },
    world: worldApi,
    combat: { addTarget: combat.addTarget, removeTarget: combat.removeTarget, onShot: combat.onShot },
    models: { car: models.car, person: models.person },
    hud,
    start() {
      let last = performance.now();
      renderer.setAnimationLoop((now) => {
        const dt = Math.min((now - last) / 1000, 0.1);
        last = now;
        physics.step(dt);
        player.update(dt);
        combat.update(dt);
        pedestrians.update(dt);
        vehicles.update(dt);
        for (const fn of updates) {
          try { fn(dt, now / 1000); } catch (err) { console.error('[core] onUpdate', err); }
        }
        if (overview) {
          camera.position.set(0, 1100, 260);
          camera.lookAt(0, 0, 220);
        }
        look.update(dt);
        look.render();
      });
    },
  };
  // Interne Teile für weitere core-Module (Fahrzeuge, Fußgänger), nicht Teil des Vertrags.
  ctx._core = { physics, player, combat, input, city, pedestrians, vehicles, look };
  if (import.meta.env.DEV) window.__ctx = ctx; // nur im Vite-Dev-Server, für Konsole und Smoke-Tests
  return ctx;
}
