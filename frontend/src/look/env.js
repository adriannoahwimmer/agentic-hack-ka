/**
 * Umgebung aus einem HDRI: Himmel, bildbasiertes Licht, Sonnenrichtung, Nebelfarbe (Look-Pass).
 *
 * Zweck: `public/look/*.hdr` (Poly Haven, CC0) als `scene.background` und, über PMREM,
 * als `scene.environment` für die PBR-Materialien. Aus den HDR-Daten werden die Richtung des
 * hellsten Texels (Sonne → Richtung des Schattenlichts) und die mittlere Horizontfarbe
 * (→ Nebelfarbe) gelesen, damit Himmel, Schatten und Nebel zusammenpassen.
 * Use-Cases: Look beim Start laden; schlägt das HDRI fehl, bleibt der einfarbige Himmel.
 */
import * as THREE from 'three';
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js';

/** HDRI-Datei relativ zur Vite-Base (CC0, polyhaven.com/a/kloofendal_48d_partly_cloudy_puresky). */
export const HDRI_FILE = 'look/kloofendal_48d_partly_cloudy_puresky_1k.hdr';
const MIN_SUN_ELEVATION = (28 * Math.PI) / 180; // flachere Sonne: zu lange Schatten in den Gassen

/**
 * Richtung zu einem Texel einer equirektangulären Textur (three: equirectUv-Konvention).
 * @param {number} u 0..1
 * @param {number} v 0..1 (1 = oben)
 */
function dirFromUv(u, v) {
  const phi = (u - 0.5) * Math.PI * 2;
  const lat = (v - 0.5) * Math.PI;
  return new THREE.Vector3(Math.cos(phi) * Math.cos(lat), Math.sin(lat), Math.sin(phi) * Math.cos(lat));
}

/**
 * Sonne (hellster Texel) und Horizontfarbe aus den HDR-Rohdaten (Float32 RGBA, flipY).
 * @param {THREE.DataTexture} tex
 */
export function analyzeHdr(tex) {
  const { data, width, height } = tex.image;
  let best = -1;
  let bestI = 0;
  for (let i = 0; i < width * height; i++) {
    const l = data[i * 4] * 0.2126 + data[i * 4 + 1] * 0.7152 + data[i * 4 + 2] * 0.0722;
    if (l > best) { best = l; bestI = i; }
  }
  const row = Math.floor(bestI / width);
  const col = bestI % width;
  const sunDir = dirFromUv((col + 0.5) / width, 1 - (row + 0.5) / height); // Zeile 0 = oben (flipY)
  if (Math.asin(sunDir.y) < MIN_SUN_ELEVATION) {
    const h = Math.hypot(sunDir.x, sunDir.z) || 1;
    sunDir.set((sunDir.x / h) * Math.cos(MIN_SUN_ELEVATION), Math.sin(MIN_SUN_ELEVATION), (sunDir.z / h) * Math.cos(MIN_SUN_ELEVATION));
  }
  // Horizont: Mittel über ein schmales Band knapp über v = 0.5.
  const horizon = new THREE.Color(0, 0, 0);
  let n = 0;
  for (let r = Math.floor(height * 0.46); r < Math.floor(height * 0.49); r++) {
    for (let c = 0; c < width; c += 4) {
      const i = (r * width + c) * 4;
      horizon.r += data[i]; horizon.g += data[i + 1]; horizon.b += data[i + 2];
      n++;
    }
  }
  horizon.multiplyScalar(1 / Math.max(1, n));
  return { sunDir: sunDir.normalize(), horizon, peak: best };
}

/**
 * HDRI laden und als Himmel und Umgebungslicht setzen.
 * @param {{renderer: THREE.WebGLRenderer, scene: THREE.Scene}} deps
 * @returns {Promise<{sunDir: THREE.Vector3, horizon: THREE.Color, peak: number} | null>} null bei Fehler
 */
export async function loadEnvironment({ renderer, scene }) {
  try {
    const loader = new HDRLoader().setDataType(THREE.FloatType);
    const tex = await loader.loadAsync(`${import.meta.env.BASE_URL}${HDRI_FILE}`);
    const info = analyzeHdr(tex);
    tex.mapping = THREE.EquirectangularReflectionMapping;
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromEquirectangular(tex).texture;
    pmrem.dispose();
    scene.background = tex;
    scene.backgroundIntensity = 1.2;
    scene.environmentIntensity = 0.55;
    return info;
  } catch (err) {
    console.warn('[look] HDRI nicht geladen, einfarbiger Himmel bleibt', err);
    return null;
  }
}
