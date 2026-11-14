/**
 * OSM-Stadt aus den gebackenen Assets (Scheibe Welt).
 *
 * Zweck: lädt `city/{buildings,roads,areas}.json` (scripts/bake_osm.py) und baut daraus
 * wenige große Meshes plus einen statischen Rapier-Collider.
 * Use-Cases: Bühne fürs Spiel, Kollision für Spieler, Fahrzeuge und Schüsse (Raycast).
 *
 * Performance: Gebäude, Straßen und Flächen sind je ein zusammengeführtes Mesh mit
 * Vertex-Farben (insgesamt 4 Draw-Calls inkl. Boden). Gebäude werden selbst extrudiert
 * (Wände + Dach per ShapeUtils), das ist schlanker als 1000 ExtrudeGeometries.
 * Der Collider ist ein einziges Trimesh aus allen Wänden, dazu Boden und Randwände.
 */
import * as THREE from 'three';

const WALL_COLORS = [0xe8dcc4, 0xd9c7a7, 0xcbb89a, 0xe3d3b8, 0xbfae95, 0xd8cfc0, 0xc4b5a5, 0xeae2d2];
const ROOF_COLORS = [0x8c5a4a, 0x7a4e40, 0x6f6a66, 0x9a6b55, 0x5f5a57];
const LANDMARK = { wall: 0xf2ead8, roof: 0x4f6f78 }; // Schloss, Kirche, ... (POIs)

const DRIVABLE = new Set([
  'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified',
  'residential', 'living_street', 'service', 'track',
]);
const ROAD_COLOR = { drivable: 0x50545a, pedestrian: 0xb9ae9c, path: 0xcdbf9f };
// Ein Grün für alle Grünflächen: Überlappungen (Rasen im Park) flimmern dann nicht sichtbar.
const AREA_COLOR = { park: 0x7fa65a, garden: 0x7fa65a, grass: 0x7fa65a, parking: 0x6b6e73, plaza: 0xc6baa6 };
// Plätze unten, Grün darüber, Wege (roads, 0,04–0,06) obendrauf: So zeigt z. B. der Schlossplatz
// seine Rasenflächen und Wege statt einer einzigen Platzfläche.
const AREA_Y = { plaza: 0.012, parking: 0.018, park: 0.026, garden: 0.026, grass: 0.026 };
const GROUND_COLOR = 0x9b9a88;

/**
 * Punkt-in-Polygon (Strahlverfahren) für einen Ring [[x, z], ...].
 * @param {number} x
 * @param {number} z
 * @param {number[][]} ring
 */
export function pointInRing(x, z, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, zi] = ring[i];
    const [xj, zj] = ring[j];
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

/**
 * Kleine, stabile Hash-Funktion (für Farbwahl pro Gebäude-Id).
 * @param {string} s
 */
function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Wachsender Puffer für Position, Normale und Farbe (nicht indiziert). */
class GeoBuilder {
  constructor() { this.pos = []; this.nor = []; this.col = []; }

  /** Dreieck mit Normale und Farbe anhängen. */
  tri(a, b, c, n, color) {
    this.pos.push(...a, ...b, ...c);
    for (let i = 0; i < 3; i++) { this.nor.push(...n); this.col.push(color.r, color.g, color.b); }
  }

  /** BufferGeometry aus dem Puffer. */
  build() {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(this.nor, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(this.col, 3));
    g.computeBoundingSphere();
    return g;
  }
}

/**
 * Polygon (x, z) bei Höhe y als nach oben zeigende Fläche triangulieren.
 * @param {GeoBuilder} gb
 * @param {number[][]} pts Ring [[x, z], ...], offen
 * @param {number} y
 * @param {THREE.Color} color
 * @param {number[][][]} [holes] Löcher (Innenhöfe), Ringe wie pts
 */
function addFlat(gb, pts, y, color, holes = []) {
  const v2 = (ring) => ring.map(([x, z]) => new THREE.Vector2(x, z));
  const tris = THREE.ShapeUtils.triangulateShape(v2(pts), holes.map(v2));
  const all = pts.concat(...holes); // Indizes der Dreiecke zählen über Außenring + Löcher
  for (const [a, b, c] of tris) {
    const [ax, az] = all[a];
    const [bx, bz] = all[b];
    const [cx, cz] = all[c];
    // Windung so wählen, dass die Vorderseite nach oben zeigt (y-Komponente des Kreuzprodukts > 0).
    const up = (bz - az) * (cx - ax) - (bx - ax) * (cz - az) > 0;
    if (up) gb.tri([ax, y, az], [bx, y, bz], [cx, y, cz], [0, 1, 0], color);
    else gb.tri([ax, y, az], [cx, y, cz], [bx, y, bz], [0, 1, 0], color);
  }
}

/**
 * Gebäude-Mesh (Wände + Dächer) und Collider-Daten (nur Wände, indiziert).
 * Innenhöfe (`holes`) bekommen eigene Wände; deren Normalen zeigen in den Hof, weil der Bake
 * Löcher gegen den Uhrzeigersinn liefert. `ranges` merkt sich pro OSM-Id die Vertex-Bereiche
 * im zusammengeführten Mesh (zum Ausblenden einzelner Gebäude).
 * @param {{id: string, h: number, pts: number[][], holes?: number[][][]}[]} buildings
 * @param {Set<string>} landmarkIds osm_refs der POIs
 */
function buildBuildings(buildings, landmarkIds) {
  const gb = new GeoBuilder();
  const colVerts = [];
  const colIdx = [];
  /** @type {Map<string, {start: number, count: number}[]>} */
  const ranges = new Map();
  const wallC = new THREE.Color();
  const shade = new THREE.Color();
  const roofC = new THREE.Color();
  for (const b of buildings) {
    const hsh = hash(b.id);
    const landmark = landmarkIds.has(b.id.split('#')[0]);
    wallC.setHex(landmark ? LANDMARK.wall : WALL_COLORS[hsh % WALL_COLORS.length]);
    roofC.setHex(landmark ? LANDMARK.roof : ROOF_COLORS[(hsh >>> 8) % ROOF_COLORS.length]);
    const { h, pts } = b;
    const holes = b.holes ?? [];
    const start = gb.pos.length / 3;
    for (const ring of [pts, ...holes]) {
      const n = ring.length;
      for (let i = 0; i < n; i++) {
        const [ax, az] = ring[i];
        const [bx, bz] = ring[(i + 1) % n];
        const dx = bx - ax;
        const dz = bz - az;
        const len = Math.hypot(dx, dz) || 1;
        const nrm = [dz / len, 0, -dx / len]; // außen bei Ring im Uhrzeigersinn (Bake)
        // Leichte Schattierung je Himmelsrichtung, damit Kanten lesbar sind.
        shade.copy(wallC).multiplyScalar(0.82 + 0.18 * Math.abs(nrm[0]));
        const a0 = [ax, 0, az];
        const b0 = [bx, 0, bz];
        const b1 = [bx, h, bz];
        const a1 = [ax, h, az];
        gb.tri(a0, a1, b1, nrm, shade);
        gb.tri(a0, b1, b0, nrm, shade);
        const base = colVerts.length / 3;
        colVerts.push(ax, 0, az, bx, 0, bz, bx, h, bz, ax, h, az);
        colIdx.push(base, base + 1, base + 2, base, base + 2, base + 3);
      }
    }
    addFlat(gb, pts, h, roofC, holes);
    const baseId = b.id.split('#')[0];
    if (!ranges.has(baseId)) ranges.set(baseId, []);
    ranges.get(baseId).push({ start, count: gb.pos.length / 3 - start });
  }
  return { geometry: gb.build(), colVerts: new Float32Array(colVerts), colIdx: new Uint32Array(colIdx), ranges };
}

/**
 * Straßen als flache Bänder (Segment-Quads plus Füllpunkte an Knicken).
 * @param {{kind: string, w: number, pts: number[][]}[]} roads
 */
function buildRoads(roads) {
  const gb = new GeoBuilder();
  const color = new THREE.Color();
  const up = [0, 1, 0];
  for (const r of roads) {
    const cls = DRIVABLE.has(r.kind) ? 'drivable' : r.kind === 'pedestrian' || r.kind === 'living_street' ? 'pedestrian' : 'path';
    color.setHex(ROAD_COLOR[cls]);
    const y = cls === 'drivable' ? 0.06 : cls === 'pedestrian' ? 0.05 : 0.04;
    const hw = r.w / 2;
    for (let i = 0; i < r.pts.length - 1; i++) {
      const [ax, az] = r.pts[i];
      const [bx, bz] = r.pts[i + 1];
      const len = Math.hypot(bx - ax, bz - az) || 1;
      const ox = (-(bz - az) / len) * hw;
      const oz = ((bx - ax) / len) * hw;
      const p1 = [ax + ox, y, az + oz];
      const p2 = [bx + ox, y, bz + oz];
      const p3 = [bx - ox, y, bz - oz];
      const p4 = [ax - ox, y, az - oz];
      gb.tri(p1, p2, p3, up, color);
      gb.tri(p1, p3, p4, up, color);
      if (i > 0) { // Knick füllen (Achteck)
        for (let k = 0; k < 8; k++) {
          const t0 = (k / 8) * Math.PI * 2;
          const t1 = ((k + 1) / 8) * Math.PI * 2;
          gb.tri([ax, y, az], [ax + Math.cos(t1) * hw, y, az + Math.sin(t1) * hw], [ax + Math.cos(t0) * hw, y, az + Math.sin(t0) * hw], up, color);
        }
      }
    }
  }
  return gb.build();
}

/**
 * Grünflächen, Plätze und Parkplätze als flache Polygone.
 * @param {{kind: string, pts: number[][]}[]} areas
 */
function buildAreas(areas) {
  const gb = new GeoBuilder();
  const color = new THREE.Color();
  // Je Art eine eigene Höhe: Plätze liegen über Parkplätzen, beide über Grün.
  for (const a of areas) {
    color.setHex(AREA_COLOR[a.kind] ?? AREA_COLOR.grass);
    addFlat(gb, a.pts, AREA_Y[a.kind] ?? 0.02, color, a.holes ?? []);
  }
  return gb.build();
}

/**
 * Material für flache Ebenen, mit Polygon-Offset gegen Z-Fighting.
 * @param {number} offset je negativer, desto weiter vorn
 */
function flatMaterial(offset) {
  return new THREE.MeshLambertMaterial({
    vertexColors: true, polygonOffset: true, polygonOffsetFactor: offset, polygonOffsetUnits: offset,
  });
}

/**
 * City-Assets laden (relativ zur Vite-Base, also /play/city/... im Build).
 * @returns {Promise<{buildings: object[], roads: object[], areas: object[]}>}
 */
export async function loadCityData() {
  const base = import.meta.env.BASE_URL;
  const get = async (name) => {
    const res = await fetch(`${base}city/${name}.json`);
    if (!res.ok) throw new Error(`city/${name}.json: HTTP ${res.status}`);
    return res.json();
  };
  const [buildings, roads, areas] = await Promise.all([get('buildings'), get('roads'), get('areas')]);
  return { buildings, roads, areas };
}

/**
 * Stadt in die Szene setzen und statische Collider anlegen.
 * @param {{scene: THREE.Scene, RAPIER: object, world: object, data: {buildings: object[], roads: object[], areas: object[]}, pois: object[]}} deps
 * @returns {{bounds: {minX: number, maxX: number, minZ: number, maxZ: number}, meshes: THREE.Mesh[]}}
 */
export function buildCity({ scene, RAPIER, world, data, pois }) {
  const landmarkIds = new Set(pois.map((p) => p.osm_ref));
  const b = buildBuildings(data.buildings, landmarkIds);
  const buildingsMesh = new THREE.Mesh(b.geometry, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide }));
  buildingsMesh.name = 'city-buildings';
  const roadsMesh = new THREE.Mesh(buildRoads(data.roads), flatMaterial(-3));
  roadsMesh.name = 'city-roads';
  const areasMesh = new THREE.Mesh(buildAreas(data.areas), flatMaterial(-1));
  areasMesh.name = 'city-areas';

  // Ausdehnung aus den Straßen und Gebäuden, plus Rand.
  let minX = Infinity; let maxX = -Infinity; let minZ = Infinity; let maxZ = -Infinity;
  for (const item of [...data.buildings, ...data.roads]) {
    for (const [x, z] of item.pts) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z);
    }
  }
  const bounds = { minX, maxX, minZ, maxZ };
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(4000, 4000).rotateX(-Math.PI / 2),
    new THREE.MeshLambertMaterial({ color: GROUND_COLOR }),
  );
  ground.name = 'city-ground';
  ground.position.set(cx, 0, cz);
  scene.add(ground, areasMesh, roadsMesh, buildingsMesh);

  // Statische Collider: Boden, alle Gebäudewände als ein Trimesh, Randwände.
  const body = world.createRigidBody(RAPIER.RigidBodyDesc.fixed());
  world.createCollider(RAPIER.ColliderDesc.cuboid(2000, 0.5, 2000).setTranslation(cx, -0.5, cz), body);
  if (b.colIdx.length > 0) world.createCollider(RAPIER.ColliderDesc.trimesh(b.colVerts, b.colIdx), body);
  const hx = (maxX - minX) / 2 + 2;
  const hz = (maxZ - minZ) / 2 + 2;
  for (const [x, z, sx, sz] of [[cx, minZ - 2, hx, 1], [cx, maxZ + 2, hx, 1], [minX - 2, cz, 1, hz], [maxX + 2, cz, 1, hz]]) {
    world.createCollider(RAPIER.ColliderDesc.cuboid(sx, 20, sz).setTranslation(x, 20, z), body);
  }
  // Gebäude ausblenden (z. B. wenn ein Landmark-Modell an seiner Stelle steht). Der Collider bleibt.
  const posAttr = b.geometry.getAttribute('position');
  const saved = new Map(); // baseId -> [{start, data}]

  /**
   * Gebäude (alle Teile einer OSM-Id) unsichtbar machen: Vertices auf einen Punkt legen.
   * @param {string} osmRef z. B. 'way/316433983'
   * @returns {boolean} false, wenn die Id nicht in buildings.json steht
   */
  function hideBuilding(osmRef) {
    const id = String(osmRef).split('#')[0];
    const parts = b.ranges.get(id);
    if (!parts) return false;
    if (saved.has(id)) return true;
    saved.set(id, parts.map(({ start, count }) => ({ start, data: posAttr.array.slice(start * 3, (start + count) * 3) })));
    for (const { start, count } of parts) posAttr.array.fill(0, start * 3, (start + count) * 3);
    posAttr.needsUpdate = true;
    return true;
  }

  /** Ausgeblendetes Gebäude wieder zeigen. */
  function showBuilding(osmRef) {
    const id = String(osmRef).split('#')[0];
    const parts = saved.get(id);
    if (!parts) return false;
    for (const { start, data } of parts) posAttr.array.set(data, start * 3);
    saved.delete(id);
    posAttr.needsUpdate = true;
    return true;
  }

  /**
   * Alle Gebäude ausblenden, deren Grundriss (x, z) enthält.
   * @returns {string[]} ausgeblendete Ids
   */
  function hideBuildingsAt(x, z) {
    const hit = data.buildings.filter((bd) => pointInRing(x, z, bd.pts)).map((bd) => bd.id.split('#')[0]);
    const ids = [...new Set(hit)];
    ids.forEach(hideBuilding);
    return ids;
  }

  return { bounds, meshes: [buildingsMesh, roadsMesh, areasMesh, ground], hideBuilding, showBuilding, hideBuildingsAt };
}

export { DRIVABLE };
