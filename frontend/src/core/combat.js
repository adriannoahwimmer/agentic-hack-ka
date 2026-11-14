/**
 * Ballern, Ziele und Client-Events (Scheibe Welt).
 *
 * Zweck: ctx.combat (`addTarget`, `removeTarget`, additiv `onShot`) und alle Spieler-Events
 * an den Server: gebündeltes `shot_fired`, `npc_killed`, `zone_entered`, `player_position`.
 * Use-Cases: Linksklick schießt per Raycast aus der Kamera, Gebäude blockieren (Rapier-Raycast
 * gegen feste Collider), Treffer ziehen HP ab, bei 0 meldet core `npc_killed` und ruft
 * `onKilled` (das Feature entfernt sein Objekt). Fußgänger und Features hören `onShot`.
 */
import { POSITION_INTERVAL_MS, SHOT_BUNDLE_MS } from '../net.js';

const WEAPONS = {
  pistol: { label: 'Pistol', cooldown: 0.28, auto: false, spread: 0.004 },
  smg: { label: 'SMG', cooldown: 0.085, auto: true, spread: 0.022 },
};
const RANGE_M = 220;
const MAX_SHOTS_PER_EVENT = 50; // Vertrag: shot_fired.shots 1–50

/**
 * Kampf- und Event-System anlegen.
 * @param {{THREE: object, scene: object, camera: object, RAPIER: object, world: object, input: object, hud: object, net: object, player: object, worldApi: object}} deps
 */
export function createCombat({ THREE, scene, camera, RAPIER, world, input, hud, net, player, worldApi }) {
  /** @type {Map<string, {obj: object, kind: string, questId: string|null, hp: number, onKilled?: Function}>} */
  const targets = new Map();
  const shotListeners = new Set();
  const raycaster = new THREE.Raycaster();
  raycaster.far = RANGE_M;
  const rapierRay = new RAPIER.Ray({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 1 });
  let weapon = 'pistol';
  let cooldown = 0;
  let bundle = null; // {shots, weapon, timer}
  let lastZone = null;
  let lastNonNullZone = null;

  // --- Effekte ---------------------------------------------------------------
  const flash = new THREE.PointLight(0xffc46b, 0, 8);
  scene.add(flash);
  const flashMesh = new THREE.Mesh(new THREE.SphereGeometry(0.12, 6, 4), new THREE.MeshBasicMaterial({ color: 0xffe08a }));
  flashMesh.visible = false;
  scene.add(flashMesh);
  const tracerMat = new THREE.LineBasicMaterial({ color: 0xfff1a8, transparent: true, opacity: 0.9 });
  const sparkGeo = new THREE.SphereGeometry(0.08, 5, 4);
  const sparkMat = new THREE.MeshBasicMaterial({ color: 0xffd166 });
  const effects = []; // {obj, ttl}
  let flashTtl = 0;

  /** Kurzlebiges Effektobjekt anlegen. */
  function addEffect(obj, ttl) {
    scene.add(obj);
    effects.push({ obj, ttl });
  }

  const gunPos = new THREE.Vector3();
  const dir = new THREE.Vector3();
  const origin = new THREE.Vector3();
  const wp = new THREE.Vector3();

  /** Ziel-Id eines getroffenen Mesh (Elternkette hoch). */
  function targetIdOf(obj) {
    for (let o = obj; o; o = o.parent) {
      if (o.userData.combatId && targets.has(o.userData.combatId)) return o.userData.combatId;
    }
    return null;
  }

  /** Einen Schuss abgeben: Raycast, Treffer, Effekte, Bündelung fürs Event. */
  function fire() {
    const w = WEAPONS[weapon];
    cooldown = w.cooldown;
    player.setAiming(true);
    camera.getWorldDirection(dir);
    dir.x += (Math.random() - 0.5) * w.spread * 2;
    dir.y += (Math.random() - 0.5) * w.spread * 2;
    dir.z += (Math.random() - 0.5) * w.spread * 2;
    dir.normalize();
    origin.copy(camera.position);

    // Ziele zwischen Kamera und Spieler zählen nicht.
    const p = player.position();
    const minDist = Math.hypot(camera.position.x - p.x, camera.position.z - p.z) * 0.8;
    rapierRay.origin = { x: origin.x, y: origin.y, z: origin.z };
    rapierRay.dir = { x: dir.x, y: dir.y, z: dir.z };
    const wall = world.castRay(rapierRay, RANGE_M, true, RAPIER.QueryFilterFlags.ONLY_FIXED);
    const wallDist = wall ? wall.timeOfImpact : RANGE_M;

    raycaster.set(origin, dir);
    const objs = [...targets.values()].map((t) => t.obj);
    const hits = raycaster.intersectObjects(objs, true).filter((h) => h.distance > minDist && h.distance < wallDist);
    const impactDist = hits.length ? hits[0].distance : wallDist;
    const impact = origin.clone().addScaledVector(dir, impactDist);

    const gun = player.object3d.userData.gun;
    if (gun && player.object3d.visible) gun.getWorldPosition(gunPos); else gunPos.copy(origin);
    flash.position.copy(gunPos);
    flash.intensity = 6;
    flashMesh.position.copy(gunPos);
    flashMesh.visible = true;
    flashTtl = 0.05;
    const tracer = new THREE.Line(new THREE.BufferGeometry().setFromPoints([gunPos.clone(), impact]), tracerMat);
    addEffect(tracer, 0.05);
    if (impactDist < RANGE_M) {
      const spark = new THREE.Mesh(sparkGeo, sparkMat);
      spark.position.copy(impact);
      addEffect(spark, 0.12);
    }

    if (hits.length) {
      const id = targetIdOf(hits[0].object);
      if (id) damage(id, 1);
    }

    // Bündeln: ein shot_fired pro SHOT_BUNDLE_MS (Vertrag).
    if (!bundle) {
      bundle = { shots: 0, weapon, timer: setTimeout(flushShots, SHOT_BUNDLE_MS) };
    }
    bundle.shots += 1;
    bundle.weapon = weapon;
    const sp = player.position();
    for (const fn of shotListeners) {
      try { fn({ x: sp.x, z: sp.z, weapon }); } catch (err) { console.error('[combat] onShot', err); }
    }
  }

  /** Gebündelte Schüsse als ein shot_fired senden. */
  function flushShots() {
    if (!bundle) return;
    const p = player.position();
    net.send('shot_fired', {
      x: p.x, z: p.z,
      shots: Math.min(MAX_SHOTS_PER_EVENT, Math.max(1, bundle.shots)),
      weapon: bundle.weapon,
      zone_id: worldApi.zoneAt(p.x, p.z),
    });
    bundle = null;
  }

  /**
   * Schaden zufügen. Bei hp <= 0: npc_killed senden, Ziel austragen, onKilled aufrufen.
   * @param {string} id
   * @param {number} amount
   */
  function damage(id, amount) {
    const t = targets.get(id);
    if (!t) return;
    t.hp -= amount;
    hud.hitMarker();
    if (t.hp > 0) return;
    targets.delete(id);
    t.obj.getWorldPosition(wp);
    net.send('npc_killed', {
      npc_id: id.slice(0, 60),
      npc_kind: t.kind,
      x: wp.x, z: wp.z,
      zone_id: worldApi.zoneAt(wp.x, wp.z),
      quest_id: t.questId ?? null,
    });
    try { t.onKilled?.(); } catch (err) { console.error(`[combat] onKilled ${id}`, err); }
  }

  input.onKey('Digit1', () => { weapon = 'pistol'; hud.setWeapon(WEAPONS.pistol.label); });
  input.onKey('Digit2', () => { weapon = 'smg'; hud.setWeapon(WEAPONS.smg.label); });
  input.onMouseDown((button) => {
    if (button === 0 && cooldown <= 0 && !player.inVehicle()) fire();
  });

  let aimTimer = 0;

  /**
   * Pro Frame: Dauerfeuer, Effekte ausblenden, Zonenwechsel und Position melden.
   * @param {number} dt
   */
  function update(dt) {
    cooldown -= dt;
    const holding = input.locked() && input.isMouseDown(0) && !player.inVehicle();
    if (holding && WEAPONS[weapon].auto && cooldown <= 0) fire();
    if (holding || input.isMouseDown(2)) { aimTimer = 0.6; player.setAiming(true); }
    else if (aimTimer > 0) { aimTimer -= dt; if (aimTimer <= 0) player.setAiming(false); }

    if (flashTtl > 0) {
      flashTtl -= dt;
      if (flashTtl <= 0) { flash.intensity = 0; flashMesh.visible = false; }
    }
    for (let i = effects.length - 1; i >= 0; i--) {
      effects[i].ttl -= dt;
      if (effects[i].ttl <= 0) {
        scene.remove(effects[i].obj);
        if (effects[i].obj.isLine) effects[i].obj.geometry.dispose();
        effects.splice(i, 1);
      }
    }

    const p = player.position();
    const zone = worldApi.zoneAt(p.x, p.z);
    if (zone !== lastZone) {
      if (zone) net.send('zone_entered', { zone_id: zone, previous_zone_id: lastNonNullZone });
      if (zone) lastNonNullZone = zone;
      lastZone = zone;
    }
    net.sendThrottled('player_position', {
      x: p.x, z: p.z,
      heading: player.heading(),
      speed: Math.min(200, Math.max(0, player.speed())),
      in_vehicle: player.inVehicle(),
      zone_id: zone,
    }, POSITION_INTERVAL_MS);
  }

  return {
    update,
    /**
     * Schießbares Ziel registrieren. core macht Raycast und HP, sendet npc_killed, ruft onKilled.
     * @param {object} object3d
     * @param {import('../types.js').CombatTarget} t
     */
    addTarget(object3d, t) {
      object3d.userData.combatId = t.id;
      targets.set(t.id, { obj: object3d, kind: t.kind, questId: t.questId ?? null, hp: t.hp ?? 1, onKilled: t.onKilled });
    },
    /** Ziel austragen (ohne Event). */
    removeTarget(id) { targets.delete(id); },
    /** Lokaler Beobachter für jeden Schuss ({x, z, weapon}); gibt eine Abmeldefunktion zurück. */
    onShot(fn) {
      shotListeners.add(fn);
      return () => shotListeners.delete(fn);
    },
    /** Schaden von außen (z. B. Überfahren durch das Auto). */
    damage,
  };
}
