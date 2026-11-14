/**
 * Low-Poly-Modelle aus Primitiven (Scheibe Welt).
 *
 * Zweck: `ctx.models.car()` und `ctx.models.person()` für Spieler, Fußgänger,
 * geparkte Autos und die Einheiten der Feature-Scheiben (Polizei, Gang, Quest).
 * Use-Cases: Polizeiwagen mit Blaulicht spawnen, Quest-Gegner und NPCs darstellen.
 *
 * Konvention: Ursprung am Boden (y = 0), Vorderseite zeigt nach -z
 * (heading 0 = Norden, siehe Design.md "Frontend-Kern"). Geometrien und
 * Materialien werden geteilt; Farben pro Instanz über eigene Materialien aus einem Cache.
 */
import * as THREE from 'three';

const geo = {
  box: new THREE.BoxGeometry(1, 1, 1),
  wheel: new THREE.CylinderGeometry(0.36, 0.36, 0.28, 10).rotateZ(Math.PI / 2),
  head: new THREE.SphereGeometry(0.16, 8, 6),
};
const materialCache = new Map();

/**
 * Lambert-Material pro Farbe (gecacht, damit gleiche Farben dasselbe Material teilen).
 * @param {number} color
 * @param {number} [emissive]
 */
export function mat(color, emissive = 0x000000) {
  const key = `${color}:${emissive}`;
  if (!materialCache.has(key)) {
    materialCache.set(key, new THREE.MeshLambertMaterial({ color, emissive }));
  }
  return materialCache.get(key);
}

/**
 * Quader als Mesh mit Größe und Position.
 * @param {number} w Breite (x)
 * @param {number} h Höhe (y)
 * @param {number} d Tiefe (z)
 * @param {THREE.Material} material
 * @param {[number, number, number]} pos Mittelpunkt
 */
function block(w, h, d, material, pos) {
  const m = new THREE.Mesh(geo.box, material);
  m.scale.set(w, h, d);
  m.position.set(...pos);
  return m;
}

const CAR_COLORS = [0xc0392b, 0x2e86de, 0xf1c40f, 0x27ae60, 0x8e44ad, 0xecf0f1, 0x34495e, 0xe67e22];

/**
 * Low-Poly-Auto, ca. 4,2 x 1,8 x 1,5 m. Polizei: weiß-blau mit Lichtbalken.
 * `userData.lightbar` = [rot, blau] für das Blaulicht-Blinken (Feature-Scheibe),
 * `userData.wheels` = die vier Räder (Vorderräder zuerst) für die Lenkanimation.
 * @param {{police?: boolean, color?: number}} [opts]
 * @returns {THREE.Group}
 */
export function car(opts = {}) {
  const police = Boolean(opts.police);
  const color = opts.color ?? (police ? 0xf4f6f8 : CAR_COLORS[Math.floor(Math.random() * CAR_COLORS.length)]);
  const g = new THREE.Group();
  g.name = police ? 'police-car' : 'car';
  const body = mat(color);
  g.add(block(1.8, 0.6, 4.2, body, [0, 0.65, 0]));
  g.add(block(1.6, 0.55, 2.2, police ? mat(0x1f3a93) : mat(0x22303c), [0, 1.22, 0.2]));
  if (police) {
    g.add(block(1.82, 0.22, 4.22, mat(0x1f3a93), [0, 0.62, 0])); // Streifen
    const red = block(0.5, 0.14, 0.3, mat(0x550000, 0x000000), [-0.3, 1.57, 0.2]);
    const blue = block(0.5, 0.14, 0.3, mat(0x000055, 0x000000), [0.3, 1.57, 0.2]);
    red.material = red.material.clone();
    blue.material = blue.material.clone();
    g.add(red, blue);
    g.userData.lightbar = [red, blue];
  }
  g.add(block(0.4, 0.15, 0.05, mat(0xfff6c8, 0x806a30), [-0.6, 0.7, -2.11]));
  g.add(block(0.4, 0.15, 0.05, mat(0xfff6c8, 0x806a30), [0.6, 0.7, -2.11]));
  g.add(block(0.4, 0.15, 0.05, mat(0x8b0000, 0x400000), [-0.6, 0.75, 2.11]));
  g.add(block(0.4, 0.15, 0.05, mat(0x8b0000, 0x400000), [0.6, 0.75, 2.11]));
  const wheels = [];
  for (const [x, z] of [[-0.85, -1.35], [0.85, -1.35], [-0.85, 1.35], [0.85, 1.35]]) {
    const w = new THREE.Mesh(geo.wheel, mat(0x151515));
    w.position.set(x, 0.36, z);
    g.add(w);
    wheels.push(w);
  }
  g.userData.wheels = wheels;
  g.userData.size = { w: 1.8, h: 1.5, l: 4.2 };
  return g;
}

const SHIRT_COLORS = [0x3d5a80, 0xee6c4d, 0x98c1d9, 0x6a994e, 0xbc4749, 0xf2cc8f, 0x81b29a, 0x5e548e];
const SKIN = [0xf1c27d, 0xe0ac69, 0xc68642, 0x8d5524, 0xffdbac];

/**
 * Low-Poly-Person, ca. 1,8 m. `color` färbt das Oberteil.
 * `userData.legs` = [links, rechts] und `userData.arms` für eine einfache Laufanimation
 * (siehe animateWalk).
 * @param {{color?: number}} [opts]
 * @returns {THREE.Group}
 */
export function person(opts = {}) {
  const shirt = opts.color ?? SHIRT_COLORS[Math.floor(Math.random() * SHIRT_COLORS.length)];
  const skin = SKIN[Math.floor(Math.random() * SKIN.length)];
  const g = new THREE.Group();
  g.name = 'person';
  const legMat = mat(0x2b2d42);
  const legs = [-0.12, 0.12].map((x) => {
    const pivot = new THREE.Group();
    pivot.position.set(x, 0.9, 0);
    pivot.add(block(0.18, 0.9, 0.2, legMat, [0, -0.45, 0]));
    g.add(pivot);
    return pivot;
  });
  g.add(block(0.5, 0.62, 0.28, mat(shirt), [0, 1.22, 0]));
  const arms = [-0.33, 0.33].map((x) => {
    const pivot = new THREE.Group();
    pivot.position.set(x, 1.5, 0);
    pivot.add(block(0.14, 0.6, 0.16, mat(shirt), [0, -0.3, 0]));
    g.add(pivot);
    return pivot;
  });
  const head = new THREE.Mesh(geo.head, mat(skin));
  head.position.set(0, 1.68, 0);
  head.scale.set(1, 1.15, 1);
  g.add(head);
  g.userData.legs = legs;
  g.userData.arms = arms;
  g.userData.walkPhase = Math.random() * Math.PI * 2;
  return g;
}

/**
 * Lauf-Animation: Beine und Arme pendeln abhängig von der Geschwindigkeit.
 * @param {THREE.Object3D} personObj Rückgabe von person()
 * @param {number} speed m/s
 * @param {number} dt s
 */
export function animateWalk(personObj, speed, dt) {
  const ud = personObj.userData;
  if (!ud.legs) return;
  ud.walkPhase += dt * speed * 3.2;
  const swing = Math.min(1, speed / 3) * 0.7 * Math.sin(ud.walkPhase);
  ud.legs[0].rotation.x = swing;
  ud.legs[1].rotation.x = -swing;
  ud.arms[0].rotation.x = -swing * 0.8;
  ud.arms[1].rotation.x = swing * 0.8;
}
