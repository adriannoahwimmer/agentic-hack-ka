/**
 * Fußstreife der Polizei (spawn_units mit unit_type "foot"), Dispatch aus features/police.js.
 *
 * Zweck: Low-Poly-Beamte (ctx.models.person in Uniformblau, mit Mütze) laufen per Luftlinie
 * zum Spieler, bleiben in 12 m stehen, drehen sich zu ihm und schießen alle 1,5 s.
 * Use-Cases:
 * - Spawn 35–50 m vom Spieler auf einer Straße oder an der Tür eines Streifenwagens,
 *   der weniger als 20 m vom Spieler steht (police.js übergibt dann `door`)
 * - Hitscan mit Streuung (~35 % Trefferchance, ohne Raycast gegen Gebäude), Mündungsfeuer als
 *   wiederverwendetes MeshBasicMaterial-Quad (80 ms), Treffer: `ctx.player.damage(n)` falls es
 *   den Hook gibt, immer ein roter Bildschirmrand (eigenes DOM-Element, einmal erzeugt)
 * - Abschießbar als combat-Ziel (`police`, 2 Treffer): erster Treffer → `police_hit`,
 *   Tod → `police_killed`, die Figur fällt um und verschwindet nach ein paar Sekunden
 * - Höchstens 3 lebende Beamte; Level 0 räumt alles ab (`clear`); Spieler im Auto wird trotzdem verfolgt
 * Performance (Intel HD 620): Geometrie/Material einmal pro Modul, keine Lichter, keine Schatten,
 * keine Allokationen pro Frame.
 */
import { animateWalk } from '../core/models.js';

const MAX_FOOT = 3;
const SPAWN_MIN = 35;
const SPAWN_MAX = 50;
const STOP_DIST = 12;
const SHOOT_RANGE = 18;
const RUN_SPEED = 4.5;
const FIRE_INTERVAL = 1.5;
const HIT_CHANCE = 0.35;
const FLASH_S = 0.08;
const HP = 2;
const BODY_S = 5;
const FALL_S = 0.4;
const LEASH = 140;
const PLAYER_DMG = 8;
const HURT_FLASH_S = 0.12;
const PLAYER_SHOT_RANGE = 220; // wie core/combat.js RANGE_M
const UNIFORM = 0x1f3a93;
const DOOR_SIDE = 1.4;

/** @type {null | {flashGeo: object, flashMat: object, capGeo: object, capMat: object}} */
let shared = null;
/** @type {HTMLElement|null} */
let hurtEl = null;

/**
 * Geteilte Geometrien und Materialien (einmal pro Modul angelegt).
 * @param {typeof import('three')} THREE
 */
function sharedAssets(THREE) {
  if (shared) return shared;
  shared = {
    flashGeo: new THREE.PlaneGeometry(0.4, 0.4),
    // HDR-hell (Farbe x6), damit der Bloom-Pass das Mündungsfeuer aufgreift.
    flashMat: new THREE.MeshBasicMaterial({
      color: new THREE.Color(0xffe08a).multiplyScalar(6),
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
    capGeo: new THREE.BoxGeometry(0.36, 0.1, 0.4),
    capMat: new THREE.MeshLambertMaterial({ color: 0x14215c }),
  };
  return shared;
}

/**
 * Roter Treffer-Rand am Bildschirm (ein DOM-Element, einmal erzeugt).
 * @returns {HTMLElement}
 */
function hurtOverlay() {
  if (hurtEl) return hurtEl;
  hurtEl = document.createElement('div');
  hurtEl.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:40;opacity:0;'
    + 'box-shadow:inset 0 0 140px 50px rgba(220,0,0,0.75);';
  document.body.appendChild(hurtEl);
  return hurtEl;
}

/**
 * Fußstreife anlegen. Wird einmal in features/police.js init aufgerufen.
 * @param {import('../types.js').Ctx} ctx
 * @returns {{spawn: (count: number, door?: {x: number, z: number, heading: number}|null) => number, clear: () => void, update: (dt: number) => void, count: () => number}}
 */
export function createFootCops(ctx) {
  const THREE = ctx.three;
  const { scene, models, world, combat, net, player, camera } = ctx;
  const S = sharedAssets(THREE);
  /** @type {Map<string, {id: string, obj: object, flash: object, flashT: number, fireT: number, hit: boolean}>} */
  const cops = new Map();
  const copObjs = []; // lebende Figuren für den Treffer-Raycast (nur bei Spawn/Tod neu gefüllt)
  const bodies = []; // {obj, ttl, fall}
  const ray = new THREE.Raycaster();
  ray.far = PLAYER_SHOT_RANGE;
  const dir = new THREE.Vector3();
  let serial = 0;
  let hurtT = 0;
  let hitHook = false; // true, sobald core combat `onHit` aufruft (dann keine eigene Treffer-Schätzung)

  /** copObjs aus den lebenden Beamten neu füllen. */
  function rebuildObjs() {
    copObjs.length = 0;
    for (const c of cops.values()) copObjs.push(c.obj);
  }

  /**
   * Ersten Treffer an den Server melden (einmal pro Beamten).
   * @param {{id: string, hit: boolean}} c
   */
  function reportHit(c) {
    if (c.hit) return;
    c.hit = true;
    net.send('police_hit', { unit_id: c.id });
  }

  /**
   * Tod (von core combat über onKilled): melden, umfallen lassen, später entfernen.
   * @param {{id: string, obj: object, flash: object, hit: boolean}} c
   */
  function kill(c) {
    if (!cops.has(c.id)) return;
    reportHit(c); // Tod setzt einen Treffer voraus, falls die Schätzung ihn verpasst hat
    cops.delete(c.id);
    rebuildObjs();
    c.flash.visible = false;
    net.send('police_killed', { unit_id: c.id });
    bodies.push({ obj: c.obj, ttl: BODY_S, fall: 0 });
  }

  /**
   * Einen Beamten an (x, z) erzeugen und als combat-Ziel eintragen.
   * @param {number} x
   * @param {number} z
   */
  function spawnOne(x, z) {
    const id = `foot-${++serial}`;
    const obj = models.person({ color: UNIFORM }); // mat()-Cache: alle Beamten teilen ein Uniform-Material
    obj.name = 'police-foot';
    const cap = new THREE.Mesh(S.capGeo, S.capMat);
    cap.position.set(0, 1.86, 0);
    obj.add(cap);
    const flash = new THREE.Mesh(S.flashGeo, S.flashMat);
    flash.position.set(0.33, 1.5, -0.85); // vor der Hand des erhobenen rechten Arms
    flash.visible = false;
    obj.add(flash);
    obj.position.set(x, 0, z);
    scene.add(obj);
    const c = { id, obj, flash, flashT: 0, fireT: 0.6 + Math.random() * FIRE_INTERVAL, hit: false };
    combat.addTarget(obj, {
      id,
      kind: 'police',
      hp: HP,
      // Optionaler Core-Hook (siehe Bericht): wird pro Treffer gerufen, wenn core ihn unterstützt.
      onHit: () => { hitHook = true; reportHit(c); },
      onKilled: () => kill(c),
    });
    cops.set(id, c);
    rebuildObjs();
  }

  /**
   * Beamte spawnen (gedeckelt auf MAX_FOOT lebende).
   * @param {number} count gewünschte Anzahl
   * @param {{x: number, z: number, heading: number}|null} [door] Streifenwagen nahe am Spieler: Spawn an dessen Türen
   * @returns {number} tatsächlich gespawnt
   */
  function spawn(count, door) {
    const n = Math.max(0, Math.min(count, MAX_FOOT - cops.size));
    const p = player.position();
    for (let i = 0; i < n; i++) {
      if (door) {
        const h = door.heading;
        const side = i % 2 ? -DOOR_SIDE : DOOR_SIDE;
        const back = Math.floor(i / 2) * 0.9;
        spawnOne(door.x + Math.cos(h) * side + Math.sin(h) * back, door.z - Math.sin(h) * side + Math.cos(h) * back);
      } else {
        const r = world.randomRoadPoint(p, SPAWN_MIN, SPAWN_MAX);
        spawnOne(r.x, r.z);
      }
    }
    return n;
  }

  /** Alle Beamten und liegenden Körper entfernen (Level 0). */
  function clear() {
    for (const c of cops.values()) {
      combat.removeTarget(c.id);
      scene.remove(c.obj);
    }
    cops.clear();
    copObjs.length = 0;
    for (const b of bodies) scene.remove(b.obj);
    bodies.length = 0;
  }

  /** Spieler getroffen: optionaler HP-Hook, immer roter Bildschirmrand. */
  function hurtPlayer() {
    const hook = /** @type {any} */ (player).damage;
    if (typeof hook === 'function') {
      try { hook(PLAYER_DMG); } catch (err) { console.warn('[footCop] player.damage', err); }
    }
    const el = hurtOverlay();
    el.style.transition = 'none';
    el.style.opacity = '1';
    hurtT = HURT_FLASH_S;
  }

  /**
   * Beamten zu einem getroffenen Mesh finden (Elternkette hoch).
   * @param {object} obj
   */
  function copOf(obj) {
    for (let o = obj; o; o = o.parent) {
      const c = o.userData?.combatId ? cops.get(o.userData.combatId) : null;
      if (c) return c;
    }
    return null;
  }

  // Ohne core-Hook `onHit`: ersten Treffer per eigenem Kamera-Raycast schätzen (ohne Streuung,
  // läuft nach dem Schaden in combat.fire(); Ziele zwischen Kamera und Spieler zählen nicht).
  combat.onShot?.(() => {
    if (hitHook || !copObjs.length) return;
    camera.getWorldDirection(dir);
    ray.set(camera.position, dir);
    const p = player.position();
    const minDist = Math.hypot(camera.position.x - p.x, camera.position.z - p.z) * 0.8;
    const hits = ray.intersectObjects(copObjs, true);
    for (const h of hits) {
      if (h.distance <= minDist) continue;
      const c = copOf(h.object);
      if (c) reportHit(c);
      break;
    }
  });

  /**
   * Pro Frame: laufen, zielen, schießen, Körper umfallen lassen, Treffer-Rand ausblenden.
   * @param {number} dt
   */
  function update(dt) {
    const p = player.position();
    for (const c of cops.values()) {
      const o = c.obj;
      const dx = p.x - o.position.x;
      const dz = p.z - o.position.z;
      const d = Math.hypot(dx, dz);
      if (d > LEASH) {
        const r = world.randomRoadPoint(p, SPAWN_MIN, SPAWN_MAX);
        o.position.set(r.x, 0, r.z);
        continue;
      }
      o.rotation.y = Math.atan2(-dx, -dz);
      let v = 0;
      if (d > STOP_DIST) {
        v = RUN_SPEED;
        const step = Math.min(d - STOP_DIST, v * dt);
        o.position.x += (dx / d) * step;
        o.position.z += (dz / d) * step;
      }
      animateWalk(o, v, dt);
      if (d < SHOOT_RANGE) {
        const arm = o.userData.arms?.[1];
        if (arm) arm.rotation.x = Math.PI / 2; // rechter Arm zielt nach vorn (-z)
        c.fireT -= dt;
        if (c.fireT <= 0) {
          c.fireT = FIRE_INTERVAL;
          c.flash.visible = true;
          c.flashT = FLASH_S;
          if (Math.random() < HIT_CHANCE) hurtPlayer();
        }
      }
      if (c.flashT > 0) {
        c.flashT -= dt;
        if (c.flashT <= 0) c.flash.visible = false;
      }
    }
    for (let i = bodies.length - 1; i >= 0; i--) {
      const b = bodies[i];
      b.ttl -= dt;
      if (b.fall < 1) {
        b.fall = Math.min(1, b.fall + dt / FALL_S);
        b.obj.rotation.x = -b.fall * Math.PI / 2;
        b.obj.position.y = 0.15 * b.fall;
      }
      if (b.ttl <= 0) {
        scene.remove(b.obj);
        bodies.splice(i, 1);
      }
    }
    if (hurtT > 0) {
      hurtT -= dt;
      if (hurtT <= 0 && hurtEl) {
        hurtEl.style.transition = 'opacity 0.35s ease-out';
        hurtEl.style.opacity = '0';
      }
    }
  }

  return { spawn, clear, update, count: () => cops.size };
}
