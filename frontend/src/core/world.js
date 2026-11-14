/**
 * Weltwissen für Features: POIs, Zonen und Straßenpunkte (Scheibe Welt).
 *
 * Zweck: ctx.world mit `pois`, `zoneAt(x, z)` und `randomRoadPoint(near, minDist, maxDist)`.
 * Use-Cases: Polizei spawnt 120–200 m entfernt auf einer Straße, Quest zeigt POI-Ziele,
 * core/combat meldet zone_entered. POIs kommen aus data/pois.json (eine Quelle mit Python).
 */
import poiFile from '../../../data/pois.json';
import { DRIVABLE } from './city.js';

/** Abstand zwischen Stichproben-Punkten auf Straßen in Metern. */
const ROAD_SAMPLE_M = 10;
/** Straßen, auf denen Autos und Einheiten auftauchen dürfen (Kaiserstraße ist Fußgängerzone). */
const SPAWN_KINDS = new Set([...DRIVABLE, 'pedestrian']);

/**
 * Punkte im Abstand ROAD_SAMPLE_M entlang aller befahrbaren Straßen.
 * @param {{kind: string, pts: number[][]}[]} roads
 * @returns {{x: number, z: number, heading: number}[]} heading = Straßenrichtung (Radiant)
 */
export function sampleRoadPoints(roads) {
  const out = [];
  for (const r of roads) {
    if (!SPAWN_KINDS.has(r.kind)) continue;
    for (let i = 0; i < r.pts.length - 1; i++) {
      const [ax, az] = r.pts[i];
      const [bx, bz] = r.pts[i + 1];
      const len = Math.hypot(bx - ax, bz - az);
      const heading = Math.atan2(-(bx - ax), -(bz - az));
      for (let d = 0; d < len; d += ROAD_SAMPLE_M) {
        const t = d / len;
        out.push({ x: ax + (bx - ax) * t, z: az + (bz - az) * t, heading });
      }
    }
  }
  return out;
}

/**
 * ctx.world bauen.
 * @param {{roads: object[], bounds: object}} city
 */
export function createWorld({ roads, bounds }) {
  const pois = poiFile.pois;
  const roadPoints = sampleRoadPoints(roads);

  /**
   * Id des POI, in dessen Radius (x, z) liegt, sonst null. Zonen überlappen nicht (Test).
   * @param {number} x
   * @param {number} z
   */
  function zoneAt(x, z) {
    for (const p of pois) {
      if (Math.hypot(p.x - x, p.z - z) <= p.radius) return p.id;
    }
    return null;
  }

  /**
   * Zufälliger Straßenpunkt im Abstand [minDist, maxDist] von near. Gibt es keinen,
   * dann der Straßenpunkt mit dem Abstand, der dem Intervall am nächsten liegt.
   * @param {{x: number, z: number}} near
   * @param {number} minDist
   * @param {number} maxDist
   * @returns {{x: number, z: number, heading: number}}
   */
  function randomRoadPoint(near, minDist = 0, maxDist = Infinity) {
    const candidates = [];
    let best = null;
    let bestErr = Infinity;
    for (const p of roadPoints) {
      const d = Math.hypot(p.x - near.x, p.z - near.z);
      if (d >= minDist && d <= maxDist) candidates.push(p);
      else {
        const err = d < minDist ? minDist - d : d - maxDist;
        if (err < bestErr) { bestErr = err; best = p; }
      }
    }
    const pick = candidates.length ? candidates[Math.floor(Math.random() * candidates.length)] : best;
    return pick ? { ...pick } : { x: near.x, z: near.z, heading: 0 };
  }

  /** @param {string} id */
  const poi = (id) => pois.find((p) => p.id === id) ?? null;

  return { pois, zoneAt, randomRoadPoint, poi, roadPoints, bounds };
}
