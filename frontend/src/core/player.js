/**
 * Spielfigur mit Rapier-Character-Controller und Third-Person-Kamera (Scheibe Welt).
 *
 * Zweck: ctx.player (`position()`, `heading()`, `inVehicle()`, `object3d`) und die Kamera.
 * Use-Cases: WASD laufen, Shift sprinten, Maus-Orbit im Pointer-Lock, nicht durch Gebäude
 * gehen; Fahrzeuge (core/vehicle.js) übernehmen über `setVehicle()` Position und Kamera.
 *
 * heading: Rotation um y (Three.js), Blickrichtung (−sin h, −cos h) in (x, z),
 * also h = 0 → Norden (−z), h = π/2 → Westen.
 */
import { animateWalk } from './models.js';

const WALK_SPEED = 4.5;
const SPRINT_SPEED = 8.5;
const ACCEL = 14;
const HOVER = 0.06; // Abstand Kapsel–Boden in m
const CAPSULE_HALF = 0.55;
const CAPSULE_RADIUS = 0.35;
const CENTER_Y = CAPSULE_HALF + CAPSULE_RADIUS; // Kapselmitte über dem Boden
const CAM_DIST = 4.6;
const CAM_SHOULDER = 0.6;
const CAM_HEIGHT = 1.6;
const MOUSE_YAW = 0.0024;
const MOUSE_PITCH = 0.002;

/**
 * Winkel a in Richtung b drehen, höchstens um maxStep (kürzester Weg).
 * @param {number} a
 * @param {number} b
 * @param {number} maxStep
 */
export function turnTowards(a, b, maxStep) {
  let d = ((b - a + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI;
  d = Math.max(-maxStep, Math.min(maxStep, d));
  return a + d;
}

/**
 * Spieler anlegen.
 * @param {{THREE: object, scene: object, camera: object, RAPIER: object, world: object, fixed: Function, input: object, models: object, spawn: {x: number, z: number}}} deps
 */
export function createPlayer({ THREE, scene, camera, RAPIER, world, fixed, input, models, spawn }) {
  const object3d = models.person({ color: 0x1d3557 });
  object3d.name = 'player';
  const gun = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.12, 0.42), new THREE.MeshLambertMaterial({ color: 0x111111 }));
  gun.position.set(0, -0.55, -0.2);
  object3d.userData.arms[1].add(gun);
  object3d.userData.gun = gun;
  scene.add(object3d);

  const body = world.createRigidBody(
    RAPIER.RigidBodyDesc.kinematicPositionBased().setTranslation(spawn.x, CENTER_Y + HOVER, spawn.z),
  );
  const collider = world.createCollider(RAPIER.ColliderDesc.capsule(CAPSULE_HALF, CAPSULE_RADIUS), body);
  // Die Stadt ist flach: Die Kapsel schwebt HOVER über dem Boden, der Controller rechnet nur
  // horizontal gegen Wände. Mit Schwerkraft sank die Kapsel in den Boden-Collider und blieb hängen.
  const cc = world.createCharacterController(0.02);
  cc.setApplyImpulsesToDynamicBodies(true);
  cc.setSlideEnabled(true);

  const pos = { x: spawn.x, y: CENTER_Y + HOVER, z: spawn.z };
  const vel = { x: 0, z: 0 };
  let heading = 0;
  let yaw = 0; // Kamerarichtung, gleiche Konvention wie heading
  let pitch = 0.25; // > 0: Kamera oberhalb, blickt nach unten
  let speed = 0;
  let aiming = false;
  /** Aktives Fahrzeug (core/vehicle.js) oder null. */
  let vehicle = null;

  fixed((dt) => {
    if (vehicle) return;
    const fx = -Math.sin(yaw);
    const fz = -Math.cos(yaw);
    let wx = 0;
    let wz = 0;
    if (input.isDown('KeyW')) { wx += fx; wz += fz; }
    if (input.isDown('KeyS')) { wx -= fx; wz -= fz; }
    if (input.isDown('KeyD')) { wx += -fz; wz += fx; }
    if (input.isDown('KeyA')) { wx -= -fz; wz -= fx; }
    const len = Math.hypot(wx, wz);
    const topSpeed = input.isDown('ShiftLeft') || input.isDown('ShiftRight') ? SPRINT_SPEED : WALK_SPEED;
    const tx = len > 0 ? (wx / len) * topSpeed : 0;
    const tz = len > 0 ? (wz / len) * topSpeed : 0;
    const k = Math.min(1, ACCEL * dt);
    vel.x += (tx - vel.x) * k;
    vel.z += (tz - vel.z) * k;

    cc.computeColliderMovement(collider, { x: vel.x * dt, y: 0, z: vel.z * dt }, RAPIER.QueryFilterFlags.EXCLUDE_SENSORS);
    const m = cc.computedMovement();
    pos.x += m.x;
    pos.z += m.z;
    pos.y = CENTER_Y + HOVER;
    body.setNextKinematicTranslation(pos);
    speed = Math.hypot(m.x, m.z) / dt;

    if (aiming) heading = turnTowards(heading, yaw, 18 * dt);
    else if (len > 0) heading = turnTowards(heading, Math.atan2(-vel.x, -vel.z), 10 * dt);
  });

  const target = new THREE.Vector3();
  const camPos = new THREE.Vector3();
  const ray = new RAPIER.Ray({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 1 });

  /**
   * Pro Frame: Maus auswerten, Figur animieren, Kamera setzen (mit Kollision gegen die Stadt).
   * @param {number} dt
   */
  function update(dt) {
    const { dx, dy } = input.takeMouseDelta();
    yaw -= dx * MOUSE_YAW;
    pitch = Math.max(-0.35, Math.min(1.1, pitch + dy * MOUSE_PITCH));
    if (vehicle) return; // Kamera macht das Fahrzeug

    object3d.position.set(pos.x, pos.y - CENTER_Y, pos.z);
    object3d.rotation.y = heading;
    animateWalk(object3d, speed, dt);
    const arm = object3d.userData.arms[1];
    if (aiming) { arm.rotation.x = -Math.PI / 2 + pitch * 0.6; }

    const rx = Math.cos(yaw);
    const rz = -Math.sin(yaw);
    target.set(pos.x + rx * CAM_SHOULDER, pos.y - CENTER_Y + CAM_HEIGHT, pos.z + rz * CAM_SHOULDER);
    const back = new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
    let dist = CAM_DIST;
    ray.origin = { x: target.x, y: target.y, z: target.z };
    ray.dir = { x: back.x, y: back.y, z: back.z };
    const hit = world.castRay(ray, CAM_DIST, true, RAPIER.QueryFilterFlags.ONLY_FIXED);
    if (hit) dist = Math.max(0.6, hit.timeOfImpact - 0.25);
    camPos.copy(target).addScaledVector(back, dist);
    camPos.y = Math.max(0.3, camPos.y);
    camera.position.copy(camPos);
    camera.lookAt(target);
  }

  return {
    object3d,
    body,
    collider,
    update,
    /** @returns {{x: number, z: number}} */
    position: () => (vehicle ? vehicle.position() : { x: pos.x, z: pos.z }),
    heading: () => (vehicle ? vehicle.heading() : heading),
    speed: () => (vehicle ? vehicle.speed() : speed),
    inVehicle: () => vehicle !== null,
    /** Kamerarichtung (Yaw, Konvention wie heading) und Neigung. */
    view: () => ({ yaw, pitch }),
    /** Beim Zielen/Schießen dreht sich die Figur zur Kamera und hebt den Arm. */
    setAiming(on) {
      aiming = on;
      if (!on) object3d.userData.arms[1].rotation.x = 0;
    },
    /**
     * Fahrzeug übernehmen (vehicle = {position, heading, speed}) oder mit null aussteigen
     * und an (x, z) absetzen.
     */
    setVehicle(v, exitAt = null) {
      vehicle = v;
      object3d.visible = !v;
      collider.setEnabled(!v);
      if (!v && exitAt) {
        Object.assign(pos, { x: exitAt.x, y: CENTER_Y + HOVER, z: exitAt.z });
        body.setTranslation(pos, true);
        vel.x = 0; vel.z = 0;
      }
    },
  };
}
