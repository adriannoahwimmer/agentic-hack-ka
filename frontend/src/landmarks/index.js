/**
 * Landmarks: handmodellierte Low-Poly-Wahrzeichen auf den OSM-Grundrissen (Feature Landmarks).
 *
 * Zweck: Schloss, Pyramide, Stadtkirche und Rathaus erkennbar machen. Jedes Landmark sucht
 * seinen Grundriss per `osm_ref` in den gebackenen `data.buildings` (Weltkoordinaten über
 * geo.py) und setzt sein Modell darauf, ausgerichtet an der längsten Kante des Umrisses.
 * Use-Cases: Orientierung im Spiel, Quest-Ziele, Demo-Video.
 * Einhängepunkt: core/index.js ruft `addLandmarks({scene, data})` einmal nach `buildCity` auf.
 *
 * Robustheit: Fehlt eine osm_ref oder ist sie mehrteilig (`way/1#0`, `#1`, ...), wird nur
 * dieses Landmark mit console.warn übersprungen. Ebenso das Ausblenden des Pyramiden-Blocks.
 * Performance (Ziel `?q=medium`, Intel HD 620): alle Landmarks sind EIN Mesh mit einem
 * Lambert-Material und Vertex-Farben (+1 Draw-Call), keine Texturen, kein Code pro Frame.
 * Kollision bleibt beim Wand-Trimesh der Stadt (city.js); es kommen keine Collider dazu.
 */
import * as THREE from 'three';
import { Kit } from './kit.js';
import { pyramide } from './pyramide.js';
import { rathaus } from './rathaus.js';
import { schloss } from './schloss.js';
import { stadtkirche } from './stadtkirche.js';

/** Reihenfolge = Priorität (Schloss zuerst). */
const LANDMARKS = [schloss, pyramide, stadtkirche, rathaus];

/**
 * Den einen Grundriss zu einer osm_ref finden (null bei fehlend oder mehrteilig).
 * @param {{id: string, h: number, pts: number[][]}[]} buildings
 * @param {string} ref
 */
export function findFootprint(buildings, ref) {
  const parts = buildings.filter((b) => b.id.split('#')[0] === ref);
  if (parts.length !== 1) return null;
  return parts[0];
}

/**
 * Lokales Gerüst eines Grundrisses: Drehung a (längste Kante, auf ±45° normiert, oder 0),
 * Mittelpunkt der Bounding-Box im gedrehten System, Punkte und Umrechnung in lokal.
 * @param {{h: number, pts: number[][]}} b
 * @param {boolean} align an der längsten Kante ausrichten
 */
export function frameOf(b, align) {
  const n = b.pts.length;
  let a = 0;
  if (align) {
    let best = -1;
    for (let i = 0; i < n; i++) {
      const [ax, az] = b.pts[i];
      const [bx, bz] = b.pts[(i + 1) % n];
      const len = Math.hypot(bx - ax, bz - az);
      if (len > best) { best = len; a = Math.atan2(bz - az, bx - ax); }
    }
    a = Math.atan2(Math.sin(4 * a), Math.cos(4 * a)) / 4; // modulo 90° nach (−45°, 45°]
  }
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  const rel = (x, z) => [x * cos + z * sin, -x * sin + z * cos];
  const loc = b.pts.map(([x, z]) => rel(x, z));
  const us = loc.map((p) => p[0]);
  const vs = loc.map((p) => p[1]);
  const uc = (Math.min(...us) + Math.max(...us)) / 2;
  const vc = (Math.min(...vs) + Math.max(...vs)) / 2;
  const toLocal = (x, z) => { const [u, v] = rel(x, z); return [u - uc, v - vc]; };
  return {
    a,
    h: b.h,
    w: Math.max(...us) - Math.min(...us),
    d: Math.max(...vs) - Math.min(...vs),
    pts: loc.map(([u, v]) => [u - uc, v - vc]),
    toLocal,
    center: [uc * cos - vc * sin, uc * sin + vc * cos],
  };
}

/**
 * Block eines Gebäudes im zusammengeführten Stadt-Mesh unsichtbar machen: alle Dreiecke,
 * deren drei Ecken im Grundriss-Rechteck liegen, werden auf einen Punkt unter dem Boden
 * gelegt. Der Collider (Trimesh) bleibt. Gibt die Zahl der ausgeblendeten Dreiecke zurück.
 * @param {THREE.Scene} scene
 * @param {{pts: number[][]}} b
 */
export function hideCityBlock(scene, b) {
  const mesh = scene.getObjectByName('city-buildings');
  const pos = mesh?.geometry?.getAttribute('position');
  if (!pos) return 0;
  const m = 0.25;
  const xs = b.pts.map((p) => p[0]);
  const zs = b.pts.map((p) => p[1]);
  const [x0, x1, z0, z1] = [Math.min(...xs) - m, Math.max(...xs) + m, Math.min(...zs) - m, Math.max(...zs) + m];
  const inside = (i) => {
    const x = pos.getX(i);
    const z = pos.getZ(i);
    return x >= x0 && x <= x1 && z >= z0 && z <= z1;
  };
  let hidden = 0;
  for (let i = 0; i + 2 < pos.count; i += 3) {
    if (inside(i) && inside(i + 1) && inside(i + 2)) {
      for (let k = 0; k < 3; k++) pos.setXYZ(i + k, x0, -5, z0);
      hidden++;
    }
  }
  if (hidden > 0) pos.needsUpdate = true;
  return hidden;
}

/**
 * Alle Landmarks bauen und als ein Mesh in die Szene setzen.
 * @param {{scene: THREE.Scene, data: {buildings: {id: string, h: number, pts: number[][]}[]}}} deps
 * @returns {THREE.Mesh | null}
 */
export function addLandmarks({ scene, data }) {
  const geos = [];
  for (const lm of LANDMARKS) {
    try {
      const b = findFootprint(data?.buildings ?? [], lm.ref);
      if (!b) {
        console.warn(`[landmarks] ${lm.name}: ${lm.ref} fehlt oder ist mehrteilig, übersprungen`);
        continue;
      }
      const fp = frameOf(b, lm.align);
      if (lm.hideBlock) {
        const n = hideCityBlock(scene, b);
        if (n === 0) console.warn(`[landmarks] ${lm.name}: Block im Stadt-Mesh nicht gefunden, bleibt sichtbar`);
      }
      const kit = new Kit();
      lm.build(kit, fp);
      const g = kit.build();
      if (!g) continue;
      g.rotateY(-fp.a);
      g.translate(fp.center[0], 0, fp.center[1]);
      geos.push(g);
    } catch (err) {
      console.warn(`[landmarks] ${lm.name}: Bau fehlgeschlagen, übersprungen`, err);
    }
  }
  if (geos.length === 0) return null;
  const kit = new Kit();
  kit.parts = geos;
  const merged = kit.build();
  if (!merged) {
    console.warn('[landmarks] Zusammenführen fehlgeschlagen, keine Landmarks');
    return null;
  }
  const mesh = new THREE.Mesh(merged, new THREE.MeshLambertMaterial({ vertexColors: true }));
  mesh.name = 'landmarks';
  mesh.geometry.computeBoundingSphere();
  scene.add(mesh);
  console.info(`[landmarks] ${geos.length}/${LANDMARKS.length} gebaut, ${mesh.geometry.getAttribute('position').count / 3} Dreiecke`);
  return mesh;
}
