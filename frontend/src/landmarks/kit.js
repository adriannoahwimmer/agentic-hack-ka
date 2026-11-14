/**
 * Baukasten für handmodellierte Low-Poly-Landmarks (Feature Landmarks).
 *
 * Zweck: wenige Grundkörper (Quader, Prisma, Dach-Stumpf) mit Vertex-Farbe und flachen
 * Normalen sammeln und am Ende zu EINER BufferGeometry zusammenführen (1 Draw-Call).
 * Use-Cases: Schloss, Pyramide, Stadtkirche, Rathaus bauen sich daraus in lokalen Koordinaten
 * (u ≈ Ost = x, v ≈ Süd = z, y = oben, Ursprung = Mitte des Grundrisses auf dem Boden).
 */
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

/** Sammelt Teile eines Landmarks und führt sie zusammen. */
export class Kit {
  /** Leerer Baukasten. */
  constructor() {
    /** @type {THREE.BufferGeometry[]} */
    this.parts = [];
  }

  /**
   * Geometrie nicht-indiziert machen, platzieren, flach schattieren und einfärben.
   * @param {THREE.BufferGeometry} geo
   * @param {number} color Hex-Farbe
   * @param {number} x
   * @param {number} y
   * @param {number} z
   * @param {number} rotY Drehung um y (Radiant)
   */
  push(geo, color, x, y, z, rotY = 0) {
    const g = geo.index ? geo.toNonIndexed() : geo;
    if (g.getAttribute('uv')) g.deleteAttribute('uv');
    if (rotY) g.rotateY(rotY);
    g.translate(x, y, z);
    g.computeVertexNormals(); // nicht-indiziert = flache Normalen (Low-Poly)
    const c = new THREE.Color(color);
    const n = g.getAttribute('position').count;
    const col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b; }
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    this.parts.push(g);
    return this;
  }

  /** Quader w (u) × h × d (v), Unterkante bei y. */
  box(w, h, d, color, x = 0, y = 0, z = 0, rotY = 0) {
    return this.push(new THREE.BoxGeometry(w, h, d).translate(0, h / 2, 0), color, x, y, z, rotY);
  }

  /** Prisma/Kegelstumpf mit seg Seiten (8 = Achteck), Unterkante bei y. rTop = 0 ergibt eine Spitze. */
  prism(r, h, seg, color, x = 0, y = 0, z = 0, rTop = r) {
    const g = new THREE.CylinderGeometry(rTop, r, h, seg, 1, rTop === 0).translate(0, h / 2, 0);
    if (seg === 4) g.rotateY(Math.PI / 4); // Quadrat achsparallel
    return this.push(g, color, x, y, z);
  }

  /**
   * Rechteckiger Stumpf: unten wb × db, oben wt × dt, Höhe h. Deckt alle Dächer ab:
   * Walmdach (wt = wb − db, dt = 0), Satteldach/Giebel mit First entlang u (wt = wb, dt = 0),
   * Pyramide (wt = dt = 0), Mansarde (zwei Stümpfe übereinander). Ohne Bodenfläche.
   */
  roof(wb, db, wt, dt, h, color, x = 0, y = 0, z = 0, rotY = 0) {
    const b = [[-wb / 2, 0, -db / 2], [wb / 2, 0, -db / 2], [wb / 2, 0, db / 2], [-wb / 2, 0, db / 2]];
    const t = [[-wt / 2, h, -dt / 2], [wt / 2, h, -dt / 2], [wt / 2, h, dt / 2], [-wt / 2, h, dt / 2]];
    const tris = [];
    for (let i = 0; i < 4; i++) {
      const j = (i + 1) % 4;
      tris.push([b[i], b[j], t[j]], [b[i], t[j], t[i]]);
    }
    if (wt > 0 && dt > 0) tris.push([t[0], t[1], t[2]], [t[0], t[2], t[3]]);
    const pos = [];
    const inner = new THREE.Vector3(0, h * 0.3, 0);
    const va = new THREE.Vector3(); const vb = new THREE.Vector3(); const vc = new THREE.Vector3();
    const nrm = new THREE.Vector3(); const mid = new THREE.Vector3();
    for (const [a, p, q] of tris) {
      va.fromArray(a); vb.fromArray(p); vc.fromArray(q);
      nrm.subVectors(vb, va).cross(vc.clone().sub(va));
      if (nrm.lengthSq() < 1e-9) continue; // entartet (Giebel-/Spitzen-Ecken)
      mid.copy(va).add(vb).add(vc).divideScalar(3).sub(inner);
      // Windung nach außen drehen, damit Normale und Backface-Culling stimmen.
      if (nrm.dot(mid) < 0) pos.push(...a, ...q, ...p); else pos.push(...a, ...p, ...q);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    return this.push(g, color, x, y, z, rotY);
  }

  /** Alle Teile zu einer Geometrie zusammenführen (null, wenn leer). */
  build() {
    if (this.parts.length === 0) return null;
    const merged = mergeGeometries(this.parts, false);
    for (const p of this.parts) p.dispose();
    this.parts = [];
    return merged;
  }
}
