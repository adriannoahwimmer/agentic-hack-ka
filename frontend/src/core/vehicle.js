/**
 * Fahrzeuge: geparkte Zivilautos zum Klauen und Fahren (Scheibe Welt, W3).
 *
 * Zweck: Rapier-`DynamicRayCastVehicleController` (4 Räder, Federung, Lenkung) mit
 * Ein- und Aussteigen per F, Verfolgerkamera und dem Event `vehicle_stolen`.
 * Use-Cases: Spieler klaut ein Auto (erstes Einsteigen → `vehicle_stolen`), fährt zum
 * Quest-Ziel, flieht vor der Polizei; Überfahren tötet Fußgänger (`npc_killed`).
 * `ctx.player.inVehicle()` ist true, solange der Spieler fährt.
 *
 * Steuerung: W Gas, S Bremse/Rückwärts, A/D lenken, Leertaste Handbremse, R aufrichten.
 * Konvention wie überall: Autos schauen nach −z, heading = Rotation um y.
 */

const PARKED_COUNT = 8;
const ENTER_RADIUS = 4;
const ENGINE_FORCE = 3400;
const REVERSE_FORCE = 1400;
const BRAKE_FORCE = 60;
const HANDBRAKE_FORCE = 120;
const MAX_STEER = 0.55;
const STEER_SPEED = 3.2;
const MAX_SPEED = 26; // m/s, darüber kein Gas mehr
const RUN_OVER_SPEED = 4; // m/s
const CHASE_DIST = 8;
const CHASE_HEIGHT = 3.2;

// Fahrwerk, lokal zum Body-Ursprung (= Unterkante des Modells).
const WHEEL_Y = 0.62;
const REST_LENGTH = 0.3;
const WHEEL_RADIUS = 0.36;
const WHEELS = [[-0.85, -1.35], [0.85, -1.35], [-0.85, 1.35], [0.85, 1.35]]; // vorne zuerst (−z)
const CHASSIS = { hx: 0.9, hy: 0.45, hz: 2.1, y: 0.8 };

/**
 * Fahrzeug-System anlegen und geparkte Autos verteilen.
 * @param {{THREE: object, scene: object, camera: object, RAPIER: object, world: object, fixed: Function, input: object, models: object, player: object, worldApi: object, net: object, hud: object, combat: object, pedestrians: object}} deps
 */
export function createVehicles(deps) {
  const { THREE, scene, camera, RAPIER, world, fixed, input, models, player, worldApi, net, hud, combat, pedestrians } = deps;
  /** @type {{id: string, kind: string, obj: object, body: object, vc: object, stolen: boolean, steer: number, flipTime: number}[]} */
  const cars = [];
  let driving = null;
  let serial = 0;

  /**
   * Auto mit Physik an Punkt p (Straßenrichtung p.heading) erzeugen.
   * @param {{x: number, z: number, heading?: number}} p
   * @param {{police?: boolean, color?: number}} [opts]
   */
  function spawnCar(p, opts = {}) {
    const obj = models.car(opts);
    scene.add(obj);
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), p.heading ?? 0);
    const body = world.createRigidBody(
      RAPIER.RigidBodyDesc.dynamic()
        .setTranslation(p.x, 0.15, p.z)
        .setRotation({ x: q.x, y: q.y, z: q.z, w: q.w })
        .setLinearDamping(0.15)
        .setAngularDamping(0.6)
        .setCcdEnabled(true),
    );
    world.createCollider(
      RAPIER.ColliderDesc.cuboid(CHASSIS.hx, CHASSIS.hy, CHASSIS.hz)
        .setTranslation(0, CHASSIS.y, 0)
        .setDensity(170) // ca. 1100 kg
        .setFriction(0.4),
      body,
    );
    const vc = world.createVehicleController(body);
    vc.indexUpAxis = 1;
    vc.setIndexForwardAxis = 2;
    for (const [x, z] of WHEELS) {
      vc.addWheel({ x, y: WHEEL_Y, z }, { x: 0, y: -1, z: 0 }, { x: -1, y: 0, z: 0 }, REST_LENGTH, WHEEL_RADIUS);
    }
    for (let i = 0; i < WHEELS.length; i++) {
      vc.setWheelSuspensionStiffness(i, 28);
      vc.setWheelSuspensionCompression(i, 2.4);
      vc.setWheelSuspensionRelaxation(i, 3.0);
      vc.setWheelMaxSuspensionTravel(i, 0.25);
      vc.setWheelFrictionSlip(i, 2.2);
      vc.setWheelSideFrictionStiffness(i, 1.0);
    }
    const car = { id: `car-${++serial}`, kind: opts.police ? 'police' : 'civilian', obj, body, vc, stolen: false, steer: 0, flipTime: 0 };
    cars.push(car);
    return car;
  }

  /** Prüft, ob an p eine Auto-Box frei von Gebäuden ist. */
  function spotIsFree(p) {
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), p.heading ?? 0);
    const shape = new RAPIER.Cuboid(1.1, 0.6, 2.4);
    const hit = world.intersectionWithShape({ x: p.x, y: 1.0, z: p.z }, { x: q.x, y: q.y, z: q.z, w: q.w }, shape,
      RAPIER.QueryFilterFlags.ONLY_FIXED);
    return !hit;
  }

  // Geparkte Autos: das erste nah am Spieler (Demo), der Rest verteilt.
  const start = player.position();
  for (let i = 0, tries = 0; cars.length < PARKED_COUNT && tries < 200; tries++) {
    const p = i === 0 ? worldApi.randomRoadPoint(start, 12, 40) : worldApi.randomRoadPoint(start, 40, 320);
    if (!spotIsFree(p)) continue;
    if (cars.some((c) => Math.hypot(c.body.translation().x - p.x, c.body.translation().z - p.z) < 12)) continue;
    spawnCar(p);
    i++;
  }

  /** Yaw (heading) eines Bodys aus seiner Rotation. */
  const tmpQ = new THREE.Quaternion();
  const tmpE = new THREE.Euler();
  function headingOf(body) {
    const r = body.rotation();
    tmpQ.set(r.x, r.y, r.z, r.w);
    tmpE.setFromQuaternion(tmpQ, 'YXZ');
    return tmpE.y;
  }

  /** Einsteigen (F nahe einem Auto) oder Aussteigen (F im Auto). */
  function toggleEnter() {
    if (driving) return exit();
    const p = player.position();
    let best = null;
    let bestD = ENTER_RADIUS;
    for (const c of cars) {
      const t = c.body.translation();
      const d = Math.hypot(t.x - p.x, t.z - p.z);
      if (d < bestD) { bestD = d; best = c; }
    }
    if (!best) return;
    driving = best;
    driving.body.wakeUp();
    player.setVehicle({
      position: () => { const t = best.body.translation(); return { x: t.x, z: t.z }; },
      heading: () => headingOf(best.body),
      speed: () => Math.abs(best.vc.currentVehicleSpeed()),
    });
    if (!best.stolen) {
      best.stolen = true;
      const t = best.body.translation();
      net.send('vehicle_stolen', {
        vehicle_id: best.id, vehicle_kind: best.kind, x: t.x, z: t.z, zone_id: worldApi.zoneAt(t.x, t.z),
      });
      hud.toast('Vehicle stolen');
    }
  }

  /** Aussteigen links (sonst rechts, sonst hinten) neben dem Auto, nicht in einer Wand. */
  function exit() {
    const c = driving;
    const t = c.body.translation();
    const h = headingOf(c.body);
    const rx = Math.cos(h);
    const rz = -Math.sin(h);
    const candidates = [[-rx * 2, -rz * 2], [rx * 2, rz * 2], [Math.sin(h) * 3.5, Math.cos(h) * 3.5]];
    let at = { x: t.x - rx * 2, z: t.z - rz * 2 };
    for (const [dx, dz] of candidates) {
      const hit = world.intersectionWithShape({ x: t.x + dx, y: 0.95, z: t.z + dz }, { x: 0, y: 0, z: 0, w: 1 },
        new RAPIER.Capsule(0.55, 0.35), RAPIER.QueryFilterFlags.ONLY_FIXED);
      if (!hit) { at = { x: t.x + dx, z: t.z + dz }; break; }
    }
    for (let i = 0; i < 4; i++) { c.vc.setWheelEngineForce(i, 0); c.vc.setWheelBrake(i, BRAKE_FORCE * 0.5); }
    driving = null;
    player.setVehicle(null, at);
  }

  /** Auto aufrichten (R oder nach 2 s auf dem Dach). */
  function rightUp(c) {
    const t = c.body.translation();
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), headingOf(c.body));
    c.body.setTranslation({ x: t.x, y: 1.0, z: t.z }, true);
    c.body.setRotation({ x: q.x, y: q.y, z: q.z, w: q.w }, true);
    c.body.setLinvel({ x: 0, y: 0, z: 0 }, true);
    c.body.setAngvel({ x: 0, y: 0, z: 0 }, true);
  }

  input.onKey('KeyF', toggleEnter);
  input.onKey('KeyR', () => { if (driving) rightUp(driving); });

  // Fester Schritt: Fahrphysik aller Autos (Kräfte nur für das gefahrene).
  fixed((dt) => {
    for (const c of cars) {
      if (c === driving) {
        const speed = c.vc.currentVehicleSpeed(); // < 0 vorwärts (−z), > 0 rückwärts (Probe 15:00)
        const gas = input.isDown('KeyW');
        const back = input.isDown('KeyS');
        let engine = 0;
        let brake = 0;
        if (gas && speed > -MAX_SPEED) engine = -ENGINE_FORCE;
        if (back) {
          if (speed < -1) brake = BRAKE_FORCE; else engine = REVERSE_FORCE;
        }
        const steerInput = (input.isDown('KeyA') ? 1 : 0) - (input.isDown('KeyD') ? 1 : 0);
        const steerMax = MAX_STEER * (1 - Math.min(0.6, Math.abs(speed) / 40));
        c.steer += Math.max(-STEER_SPEED * dt, Math.min(STEER_SPEED * dt, steerInput * steerMax - c.steer));
        const hand = input.isDown('Space');
        for (let i = 0; i < 4; i++) {
          const front = i < 2;
          c.vc.setWheelSteering(i, front ? c.steer : 0);
          c.vc.setWheelEngineForce(i, front ? 0 : engine);
          c.vc.setWheelBrake(i, !front && hand ? HANDBRAKE_FORCE : brake);
        }
      } else {
        for (let i = 0; i < 4; i++) { c.vc.setWheelEngineForce(i, 0); c.vc.setWheelBrake(i, BRAKE_FORCE * 0.3); }
      }
      c.vc.updateVehicle(dt);
    }
  });

  const camTarget = new THREE.Vector3();
  const camPos = new THREE.Vector3();
  const camVel = new THREE.Vector3();
  const ray = new RAPIER.Ray({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 1 });
  let camYaw = null;

  /**
   * Pro Frame: Modelle an die Physik hängen, Räder animieren, Kamera beim Fahren,
   * Überfahren, Aufrichten.
   * @param {number} dt
   */
  function update(dt) {
    for (const c of cars) {
      const t = c.body.translation();
      const r = c.body.rotation();
      c.obj.position.set(t.x, t.y, t.z);
      c.obj.quaternion.set(r.x, r.y, r.z, r.w);
      const wheels = c.obj.userData.wheels;
      for (let i = 0; i < 4; i++) {
        const len = c.vc.wheelSuspensionLength(i) ?? REST_LENGTH;
        wheels[i].position.y = WHEEL_Y - len;
        wheels[i].rotation.set(c.vc.wheelRotation(i) ?? 0, i < 2 ? c.steer : 0, 0, 'YXZ');
      }
    }
    if (!driving) { camYaw = null; return; }

    const c = driving;
    const t = c.body.translation();
    const speed = Math.abs(c.vc.currentVehicleSpeed());
    // Auf dem Dach? Nach 2 s aufrichten.
    const r = c.body.rotation();
    const upY = 1 - 2 * (r.x * r.x + r.z * r.z);
    c.flipTime = upY < 0.3 ? c.flipTime + dt : 0;
    if (c.flipTime > 2) { rightUp(c); c.flipTime = 0; }

    // Überfahren: Fußgänger vor/unter dem Auto bei Tempo.
    if (speed > RUN_OVER_SPEED) {
      for (const ped of [...pedestrians.list()]) {
        if (Math.hypot(ped.obj.position.x - t.x, ped.obj.position.z - t.z) < 2.0) combat.damage(ped.id, 99);
      }
    }

    // Verfolgerkamera: folgt der Fahrtrichtung, weich gedämpft, weicht Wänden aus.
    const h = headingOf(c.body);
    if (camYaw === null) camYaw = h;
    let d = h - camYaw;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    camYaw += d * Math.min(1, dt * 3);
    const { pitch } = player.view();
    const back = new THREE.Vector3(Math.sin(camYaw), 0.25 + Math.max(0, pitch) * 0.6, Math.cos(camYaw)).normalize();
    camTarget.set(t.x, t.y + 1.4, t.z);
    const dist = CHASE_DIST + speed * 0.12;
    ray.origin = { x: camTarget.x, y: camTarget.y, z: camTarget.z };
    ray.dir = { x: back.x, y: back.y, z: back.z };
    const hit = world.castRay(ray, dist, true, RAPIER.QueryFilterFlags.ONLY_FIXED);
    const useDist = hit ? Math.max(2, hit.timeOfImpact - 0.3) : dist;
    camPos.copy(camTarget).addScaledVector(back, useDist);
    camPos.y = Math.max(camPos.y, t.y + CHASE_HEIGHT * 0.6);
    camVel.subVectors(camPos, camera.position);
    camera.position.addScaledVector(camVel, Math.min(1, dt * 10));
    camera.lookAt(camTarget);
  }

  return { update, cars: () => cars, driving: () => driving, spawnCar };
}
