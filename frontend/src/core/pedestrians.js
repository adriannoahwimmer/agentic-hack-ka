/**
 * Fußgänger: Zivilisten, die auf Straßen und Plätzen laufen (Scheibe Welt, W3).
 *
 * Zweck: belebte Stadt und schießbare Ziele (`civilian`, hp 1) für die Fahndung.
 * Use-Cases: Spieler erschießt einen Zivilisten → core/combat sendet `npc_killed`
 * (npc_kind "civilian"); Schüsse in der Nähe (ctx.combat.onShot) lassen sie fliehen.
 * Sie laufen zwischen Stichproben-Punkten auf Straßen (world.roadPoints), ohne Physik;
 * weit entfernte Fußgänger werden in Spielernähe neu gesetzt. Tote werden ersetzt.
 */
import { animateWalk } from './models.js';

const COUNT = 18;
const WALK = 1.4;
const RUN = 5.5;
const FLEE_RADIUS = 45;
const FLEE_TIME = 5;
const RECYCLE_DIST = 260;
const STEP_RADIUS = 28;
const BODY_TTL = 10;

/**
 * Fußgänger anlegen.
 * @param {{scene: object, models: object, worldApi: object, combat: object, player: object}} deps
 */
export function createPedestrians({ scene, models, worldApi, combat, player }) {
  const points = worldApi.roadPoints;
  const peds = [];
  const bodies = [];
  let serial = 0;

  /** Zufälliger Straßenpunkt in [min, max] Metern um (x, z). */
  const pointNear = (x, z, min, max) => worldApi.randomRoadPoint({ x, z }, min, max);

  /** Nächstes Laufziel: Straßenpunkt im Umkreis, beim Fliehen möglichst weit weg von der Gefahr. */
  function nextTarget(ped) {
    const { x, z } = ped.obj.position;
    if (ped.flee > 0) {
      let best = null;
      let bestD = -1;
      for (const p of points) {
        if (Math.abs(p.x - x) > STEP_RADIUS || Math.abs(p.z - z) > STEP_RADIUS) continue;
        const d = Math.hypot(p.x - ped.danger.x, p.z - ped.danger.z);
        if (d > bestD) { bestD = d; best = p; }
      }
      if (best) return { x: best.x, z: best.z };
    }
    return pointNear(x, z, 6, STEP_RADIUS);
  }

  /** Neuen Fußgänger an Punkt p setzen und als Kampfziel registrieren. */
  function spawn(p) {
    const obj = models.person();
    obj.position.set(p.x, 0, p.z);
    scene.add(obj);
    const ped = { id: `ped-${++serial}`, obj, target: null, flee: 0, danger: { x: 0, z: 0 }, speed: 0 };
    ped.target = nextTarget(ped);
    combat.addTarget(obj, {
      id: ped.id,
      kind: 'civilian',
      hp: 1,
      onKilled: () => kill(ped),
    });
    peds.push(ped);
    return ped;
  }

  /** Tot: umfallen lassen, nach BODY_TTL entfernen, Ersatz weit weg spawnen. */
  function kill(ped) {
    peds.splice(peds.indexOf(ped), 1);
    ped.obj.rotation.x = -Math.PI / 2;
    ped.obj.position.y = 0.15;
    bodies.push({ obj: ped.obj, ttl: BODY_TTL });
    const pp = player.position();
    spawn(pointNear(pp.x, pp.z, 90, 200));
  }

  // Start: die Hälfte um den Spieler, der Rest an "crowded"-POIs.
  const start = player.position();
  const crowded = worldApi.pois.filter((p) => p.tags.includes('crowded'));
  for (let i = 0; i < COUNT; i++) {
    const anchor = i % 2 === 0 || crowded.length === 0 ? start : crowded[i % crowded.length];
    spawn(pointNear(anchor.x, anchor.z, 8, 70));
  }

  combat.onShot(({ x, z }) => {
    for (const ped of peds) {
      if (Math.hypot(ped.obj.position.x - x, ped.obj.position.z - z) < FLEE_RADIUS) {
        ped.flee = FLEE_TIME;
        ped.danger = { x, z };
        ped.target = nextTarget(ped);
      }
    }
  });

  /**
   * Pro Frame: laufen, fliehen, recyceln, Leichen aufräumen.
   * @param {number} dt
   */
  function update(dt) {
    const pp = player.position();
    for (const ped of peds) {
      const o = ped.obj;
      if (ped.flee > 0) ped.flee -= dt;
      if (Math.hypot(o.position.x - pp.x, o.position.z - pp.z) > RECYCLE_DIST) {
        const p = pointNear(pp.x, pp.z, 80, 180);
        o.position.set(p.x, 0, p.z);
        ped.target = nextTarget(ped);
      }
      const dx = ped.target.x - o.position.x;
      const dz = ped.target.z - o.position.z;
      const d = Math.hypot(dx, dz);
      if (d < 0.8) { ped.target = nextTarget(ped); continue; }
      const v = ped.flee > 0 ? RUN : WALK;
      const step = Math.min(d, v * dt);
      o.position.x += (dx / d) * step;
      o.position.z += (dz / d) * step;
      o.rotation.y = Math.atan2(-dx, -dz);
      ped.speed = v;
      animateWalk(o, v, dt);
    }
    for (let i = bodies.length - 1; i >= 0; i--) {
      bodies[i].ttl -= dt;
      if (bodies[i].ttl <= 0) { scene.remove(bodies[i].obj); bodies.splice(i, 1); }
    }
  }

  return { update, list: () => peds };
}
