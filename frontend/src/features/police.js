/**
 * Polizei im Client: Fahndungssterne, Streifenwagen mit Blaulicht und Verfolgung (Scheibe Polizei).
 * Blaulicht: rote und blaue Dach-Segmente (MeshBasicMaterial, keine PointLights) blinken abwechselnd.
 *
 * Zweck: setzt die Server-Aktionen `set_wanted_level` und `spawn_units` (faction "police")
 * im Spiel um. Der Server (game_state, Dispatcher-Agent oder Fallback) entscheidet nur
 * die Parameter; hier wird gefahren.
 * Use-Cases:
 * - Level 0 → alle Einheiten verschwinden
 * - spawn_units → `count` Polizeiautos 120–200 m vom Spieler (oder am POI near_poi_id)
 * - Taktiken: chase (direkt auf den Spieler), roadblock (60 m vor dem Spieler halten),
 *   surround (4 Punkte um den Spieler); Tempo steigt mit dem Level
 * - Autos sind Kampfziele (`police`, hp 3); ein zerstörtes Auto bleibt kurz als Wrack liegen
 * Bewegung: Rapier-Kinematic-Character-Controller gegen Gebäude (ctx.physics), ohne Schwerkraft.
 * Steckt ein Auto fest oder ist es zu weit weg, wird es auf einen Straßenpunkt nahe am Spieler gesetzt.
 */

const MAX_UNITS = 8;
const SPAWN_MIN = 120;
const SPAWN_MAX = 200;
const NEAR_POI_MAX = 80;
const STOP_DIST = 7;
const ROADBLOCK_AHEAD = 60;
const ROADBLOCK_GIVEUP = 140;
const SURROUND_R = 12;
const LEASH = 420;
const STUCK_S = 3;
const WRECK_S = 8;
const HOVER_Y = 0.8;
const BLINK_HZ = 4;

/** Tempo in m/s je Fahndungsstufe. @param {number} level */
const speedFor = (level) => 9 + 3 * Math.max(1, level);

/** Kleinster Winkelunterschied a → b. */
function angleDiff(a, b) {
  let d = b - a;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  return d;
}

/**
 * Feature-Einstieg.
 * @param {import('../types.js').Ctx} ctx
 */
export function init(ctx) {
  const { scene, models, world, combat, hud, net, player } = ctx;
  const RAPIER = ctx.rapier;
  const physics = ctx.physics;
  /** @type {Map<string, object>} */
  const units = new Map();
  const wrecks = [];
  let level = 0;
  let serial = 0;
  let blink = 0;

  /** POI zur ID (ctx.world.poi, falls vorhanden). */
  const poiById = (id) => (id ? (world.poi?.(id) ?? world.pois.find((p) => p.id === id)) : null);

  /** Physik-Körper für ein Auto anlegen; ohne Physik läuft das Auto frei (Fallback). */
  function createBody(x, z) {
    try {
      const body = physics.createRigidBody(
        RAPIER.RigidBodyDesc.kinematicPositionBased().setTranslation(x, HOVER_Y, z),
      );
      const collider = physics.createCollider(RAPIER.ColliderDesc.cuboid(0.9, 0.6, 2.0), body);
      const cc = physics.createCharacterController(0.05);
      cc.setSlideEnabled(true);
      return { body, collider, cc };
    } catch (err) {
      console.warn('[police] Physik nicht verfügbar, fahre ohne Kollision', err);
      return null;
    }
  }

  /** Physik-Körper entfernen. */
  function destroyBody(u) {
    if (!u.phys) return;
    try {
      physics.removeCharacterController(u.phys.cc);
      physics.removeRigidBody(u.phys.body);
    } catch (err) {
      console.warn('[police] removeRigidBody', err);
    }
    u.phys = null;
  }

  /** Auto an (x, z) setzen (Spawn oder Rettung aus einer Sackgasse). */
  function place(u, p) {
    u.pos.x = p.x;
    u.pos.z = p.z;
    u.obj.position.set(p.x, 0, p.z);
    if (typeof p.heading === 'number') u.heading = p.heading;
    if (u.phys) {
      u.phys.body.setTranslation({ x: p.x, y: HOVER_Y, z: p.z }, true);
      u.phys.body.setNextKinematicTranslation({ x: p.x, y: HOVER_Y, z: p.z });
    }
    u.stuck = 0;
  }

  /** Ein Polizeiauto erzeugen. */
  function spawnUnit(spawnPoint, tactic, unitType) {
    const index = ++serial;
    const id = `cop-${index}`;
    const obj = models.car({ police: true });
    if (unitType === 'swat') obj.scale.set(1.15, 1.2, 1.1);
    scene.add(obj);
    const u = {
      id, obj, tactic, index, heading: 0, speed: 0, stuck: 0, holding: false,
      pos: { x: spawnPoint.x, z: spawnPoint.z }, phys: createBody(spawnPoint.x, spawnPoint.z),
      roadblock: null,
    };
    place(u, spawnPoint);
    combat.addTarget(obj, { id, kind: 'police', hp: 3, onKilled: () => wreck(u) });
    units.set(id, u);
    return u;
  }

  /** Auto entfernen (Level 0, Leine, Wrack abgelaufen). */
  function removeUnit(u) {
    units.delete(u.id);
    combat.removeTarget(u.id);
    destroyBody(u);
    scene.remove(u.obj);
  }

  /** Zerstört: Physik weg, dunkel kippen, nach WRECK_S entfernen. */
  function wreck(u) {
    units.delete(u.id);
    destroyBody(u);
    u.obj.rotation.z = 0.25;
    u.obj.traverse((o) => {
      if (!o.material?.color) return;
      o.material = o.material.clone(); // Materialien sind evtl. geteilt
      o.material.color.multiplyScalar(0.25);
    });
    for (const l of u.obj.userData.lightbar ?? []) l.visible = false;
    wrecks.push({ obj: u.obj, ttl: WRECK_S });
  }

  /** Alle Einheiten weg (Level 0). */
  function clearAll() {
    for (const u of [...units.values()]) removeUnit(u);
  }

  /** Ziel der Taktik für ein Auto: {x, z, hold} (hold = dort stehen bleiben). */
  function goal(u) {
    const p = player.position();
    if (u.tactic === 'surround') {
      const a = (u.index % 4) * (Math.PI / 2) + Math.PI / 4;
      return { x: p.x + Math.cos(a) * SURROUND_R, z: p.z + Math.sin(a) * SURROUND_R, hold: true };
    }
    if (u.tactic === 'roadblock') {
      if (!u.roadblock) {
        const h = player.heading();
        const ahead = { x: p.x - Math.sin(h) * ROADBLOCK_AHEAD, z: p.z - Math.cos(h) * ROADBLOCK_AHEAD };
        const r = world.randomRoadPoint(ahead, 0, 25);
        u.roadblock = { x: r.x + (u.index % 2) * 5, z: r.z, heading: (r.heading ?? 0) + Math.PI / 2 };
      }
      if (Math.hypot(p.x - u.roadblock.x, p.z - u.roadblock.z) > ROADBLOCK_GIVEUP) {
        u.tactic = 'chase'; // Spieler ist vorbei: Straßensperre aufgeben, verfolgen
        return { x: p.x, z: p.z, hold: false };
      }
      return { ...u.roadblock, hold: true };
    }
    return { x: p.x, z: p.z, hold: false };
  }

  /** Ein Auto einen Frame bewegen. */
  function drive(u, dt) {
    const p = player.position();
    const toPlayer = Math.hypot(p.x - u.pos.x, p.z - u.pos.z);
    if (toPlayer > LEASH) {
      place(u, world.randomRoadPoint(p, SPAWN_MIN, SPAWN_MAX));
      return;
    }
    const g = goal(u);
    const dx = g.x - u.pos.x;
    const dz = g.z - u.pos.z;
    const d = Math.hypot(dx, dz);
    const arrive = g.hold ? 2 : STOP_DIST;
    let want = 0;
    if (d > arrive && toPlayer > STOP_DIST * (g.hold ? 0.5 : 1)) {
      want = Math.min(speedFor(level), d * 1.5);
      u.heading += angleDiff(u.heading, Math.atan2(-dx, -dz)) * Math.min(1, 4 * dt);
    } else if (g.hold && typeof g.heading === 'number') {
      u.heading += angleDiff(u.heading, g.heading) * Math.min(1, 2 * dt);
    }
    u.speed += (want - u.speed) * Math.min(1, 2.5 * dt);
    const mx = -Math.sin(u.heading) * u.speed * dt;
    const mz = -Math.cos(u.heading) * u.speed * dt;
    let moved = Math.hypot(mx, mz);
    if (u.phys) {
      u.phys.cc.computeColliderMovement(u.phys.collider, { x: mx, y: 0, z: mz }, RAPIER.QueryFilterFlags.EXCLUDE_SENSORS);
      const m = u.phys.cc.computedMovement();
      u.pos.x += m.x;
      u.pos.z += m.z;
      moved = Math.hypot(m.x, m.z);
      u.phys.body.setNextKinematicTranslation({ x: u.pos.x, y: HOVER_Y, z: u.pos.z });
    } else {
      u.pos.x += mx;
      u.pos.z += mz;
    }
    // Festgefahren (Wand): nach STUCK_S auf eine Straße nahe am Spieler setzen.
    if (want > 2 && moved < want * dt * 0.2) u.stuck += dt; else u.stuck = Math.max(0, u.stuck - dt);
    if (u.stuck > STUCK_S) place(u, world.randomRoadPoint(p, 40, 90));
    u.obj.position.set(u.pos.x, 0, u.pos.z);
    u.obj.rotation.y = u.heading;
  }

  net.on('set_wanted_level', (payload) => {
    level = payload.level;
    hud.setWanted(level);
    if (level === 0) clearAll();
  });

  net.on('spawn_units', (payload) => {
    if (payload.faction !== 'police') return; // Gang-Boss gestrichen
    const free = Math.max(0, MAX_UNITS - units.size);
    const count = Math.min(payload.count, free);
    const poi = poiById(payload.near_poi_id);
    const p = player.position();
    for (let i = 0; i < count; i++) {
      const sp = poi ? world.randomRoadPoint(poi, 10, NEAR_POI_MAX) : world.randomRoadPoint(p, SPAWN_MIN, SPAWN_MAX);
      spawnUnit(sp, payload.tactic, payload.unit_type);
    }
    if (count > 0) {
      const where = poi ? ` near ${poi.name}` : '';
      hud.toast(`${count} police unit${count > 1 ? 's' : ''} dispatched${where} (${payload.tactic})`, 2500);
    }
  });

  ctx.onUpdate((dt) => {
    blink += dt;
    const on = Math.floor(blink * BLINK_HZ) % 2 === 0;
    for (const u of units.values()) {
      drive(u, dt);
      models.setLightbar(u.obj, u.index % 2 ? on : !on); // rot/blau im Wechsel, jedes zweite Auto gegenläufig
    }
    for (let i = wrecks.length - 1; i >= 0; i--) {
      wrecks[i].ttl -= dt;
      if (wrecks[i].ttl <= 0) { scene.remove(wrecks[i].obj); wrecks.splice(i, 1); }
    }
  });
}
