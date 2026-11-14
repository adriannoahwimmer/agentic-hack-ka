/**
 * Panzer der Polizei (spawn_units mit unit_type "tank", 5 Sterne), Modell und Kennwerte.
 *
 * Zweck: liefert das Low-Poly-Mesh (Wanne = Streifenwagen-Box x1,6 in Dunkelgrün, Ketten,
 * Turm-Box, Rohr als dünne Box) und die Kennwerte; gefahren wird mit der bestehenden
 * Streifenwagen-Logik in features/police.js (Rapier-Character-Controller, größerer Collider).
 * Use-Cases:
 * - 5★-Eskalation: ein Panzer fährt mit 60 % Streifenwagen-Tempo direkt auf den Spieler zu
 *   und schiebt ihn bzw. sein Auto weg; er schießt nicht
 * - Der Turm dreht sich zum Spieler (`aimTurret`), rein optisch
 * - Kampfziel `police` mit vielen Trefferpunkten; zerstört wird er zum Wrack wie ein Streifenwagen
 * Performance (Intel HD 620): Geometrie und Materialien einmal pro Modul, keine Lichter, keine Schatten.
 */

export const TANK_SCALE = 1.6;
export const TANK_SPEED_FACTOR = 0.6;
export const TANK_HP = 15;
export const TANK_STOP_DIST = 1.5; // fährt bis an den Spieler heran (schieben)
/** Halbe Collider-Maße (Streifenwagen 0.9 x 0.6 x 2.0, x1,6 in der Fläche). */
export const TANK_HALF_EXTENTS = { x: 0.9 * TANK_SCALE, y: 0.6, z: 2.0 * TANK_SCALE };

/** @type {null | {box: object, hull: object, turret: object, track: object, barrel: object}} */
let shared = null;

/**
 * Geteilte Geometrie und Materialien (einmal pro Modul).
 * @param {typeof import('three')} THREE
 */
function sharedAssets(THREE) {
  if (shared) return shared;
  shared = {
    box: new THREE.BoxGeometry(1, 1, 1),
    hull: new THREE.MeshLambertMaterial({ color: 0x2f4a2a }),
    turret: new THREE.MeshLambertMaterial({ color: 0x3a5a33 }),
    track: new THREE.MeshLambertMaterial({ color: 0x1a1d18 }),
    barrel: new THREE.MeshLambertMaterial({ color: 0x223320 }),
  };
  return shared;
}

/**
 * Quader aus der geteilten Box-Geometrie.
 * @param {typeof import('three')} THREE
 * @param {[number, number, number]} size Breite, Höhe, Tiefe
 * @param {object} material
 * @param {[number, number, number]} pos Mittelpunkt
 */
function block(THREE, size, material, pos) {
  const m = new THREE.Mesh(sharedAssets(THREE).box, material);
  m.scale.set(...size);
  m.position.set(...pos);
  return m;
}

/**
 * Panzer-Mesh bauen. Ursprung am Boden, Vorderseite nach -z (wie models.car).
 * `userData.turret` ist die Turm-Gruppe (für aimTurret), `userData.size` die Maße.
 * @param {typeof import('three')} THREE
 * @returns {import('three').Group}
 */
export function createTankModel(THREE) {
  const S = sharedAssets(THREE);
  const w = 1.8 * TANK_SCALE;
  const l = 4.2 * TANK_SCALE;
  const g = new THREE.Group();
  g.name = 'police-tank';
  g.add(block(THREE, [w, 0.6 * TANK_SCALE, l], S.hull, [0, 0.85, 0])); // Wanne
  for (const x of [-w / 2 + 0.25, w / 2 - 0.25]) g.add(block(THREE, [0.6, 0.7, l + 0.2], S.track, [x, 0.35, 0])); // Ketten
  const turret = new THREE.Group();
  turret.position.set(0, 1.33, 0.4);
  turret.add(block(THREE, [1.9, 0.7, 2.6], S.turret, [0, 0.35, 0]));
  turret.add(block(THREE, [0.18, 0.18, 3.2], S.barrel, [0, 0.4, -2.9])); // Rohr ragt nach vorn
  g.add(turret);
  g.userData.turret = turret;
  g.userData.size = { w, h: 2.4, l };
  return g;
}

/**
 * Turm zum Ziel drehen (rein optisch, ohne Allokation).
 * @param {import('three').Object3D} tankObj Rückgabe von createTankModel
 * @param {number} dx Ziel-x minus Panzer-x
 * @param {number} dz Ziel-z minus Panzer-z
 */
export function aimTurret(tankObj, dx, dz) {
  const turret = tankObj.userData.turret;
  if (turret) turret.rotation.y = Math.atan2(-dx, -dz) - tankObj.rotation.y;
}
