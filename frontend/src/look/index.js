/**
 * Look-Pass: HDRI-Himmel, Sonne mit Schatten, ACES, Nebel, PBR-Materialien, SSAO, Bloom.
 *
 * Zweck: das Low-Poly-Karlsruhe ansehnlich machen, ohne core/ umzubauen. core/index.js ruft
 * `createLook()` einmal auf und pro Frame `update(dt)` und `render()`.
 * Use-Cases:
 * - P schaltet alle Post-Effekte (GTAO, Bloom) aus/an, O nur die Umgebungsverdeckung.
 * - `?fx=0` startet ohne Post-Effekte (schwache Laptops); die Wahl merkt sich der Browser.
 * - Qualitätsstufen (look/quality.js): Intel-GPUs starten auf "medium", unter 30 fps geht es eine
 *   Stufe runter (Pixel-Ratio, Schatten, AO, Post-FX); Q schaltet die Stufe reihum, `?q=` erzwingt sie.
 * Materialien: Alle MeshLambertMaterials in der Szene (auch später hinzugefügte, z. B. von
 * Feature-Scheiben) werden durch MeshStandardMaterials mit gleicher Farbe ersetzt, damit das
 * HDRI-Licht wirkt; Meshes bekommen Schatten (Stadt-Flächen nur empfangend).
 */
import * as THREE from 'three';
import { loadEnvironment } from './env.js';
import { facadeMaterial } from './facade.js';
import { createPost } from './post.js';
import { createFpsGuard, gpuName, initialTier, TIERS } from './quality.js';

const SHADOW_EXTENT = 90; // halbe Kantenlänge des Schattenbereichs um den Spieler (m)
const SHADOW_MAP = 2048;
const SUN_DIST = 300;
const SCAN_INTERVAL_S = 0.5;
const STORE_KEY = 'faecherstadt.postfx';

/** Gespeicherte Post-FX-Wahl lesen (localStorage kann fehlen oder werfen). */
function loadPref() {
  try { return localStorage.getItem(STORE_KEY); } catch { return null; }
}

/** Post-FX-Wahl speichern (Fehler ignorieren). */
function savePref(on) {
  try { localStorage.setItem(STORE_KEY, on ? '1' : '0'); } catch { /* privat/blockiert */ }
}

/**
 * Lambert → Standard mit gleichen Grundeigenschaften (gecacht pro Ausgangsmaterial).
 * @param {WeakMap<THREE.Material, THREE.Material>} cache
 * @param {THREE.MeshLambertMaterial} m
 */
function upgrade(cache, m) {
  if (!cache.has(m)) {
    const s = new THREE.MeshStandardMaterial({
      color: m.color, vertexColors: m.vertexColors, emissive: m.emissive, emissiveIntensity: m.emissiveIntensity,
      side: m.side, transparent: m.transparent, opacity: m.opacity, fog: m.fog,
      polygonOffset: m.polygonOffset, polygonOffsetFactor: m.polygonOffsetFactor, polygonOffsetUnits: m.polygonOffsetUnits,
      roughness: 0.85, metalness: 0.0,
    });
    s.name = m.name;
    // Farbe/Emissive bleiben gekoppelt: Wer später das Lambert-Material ändert (z. B. Blaulicht),
    // ändert dieselben Color-Objekte.
    s.color = m.color;
    s.emissive = m.emissive;
    cache.set(m, s);
  }
  return cache.get(m);
}

/**
 * Look aufsetzen.
 * @param {{renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, input: object, hud: object, player: object, overview?: boolean}} deps
 */
export async function createLook({ renderer, scene, camera, input, hud, player, overview = false }) {
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.62;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap; // PCFSoft gibt es in r187 nicht mehr

  const env = await loadEnvironment({ renderer, scene });
  const sunDir = env?.sunDir ?? new THREE.Vector3(-0.55, 0.65, 0.5).normalize();

  // Sonne: Richtung aus dem HDRI, Schatten folgen dem Spieler.
  const sun = scene.getObjectByName('sun') ?? new THREE.DirectionalLight(0xffffff, 1);
  if (!sun.parent) scene.add(sun);
  sun.color.set(0xfff0dc);
  sun.intensity = 2.4;
  sun.shadow.radius = 3;
  sun.castShadow = true;
  sun.shadow.mapSize.set(SHADOW_MAP, SHADOW_MAP);
  Object.assign(sun.shadow.camera, {
    left: -SHADOW_EXTENT, right: SHADOW_EXTENT, top: SHADOW_EXTENT, bottom: -SHADOW_EXTENT, near: 1, far: SUN_DIST * 2,
  });
  sun.shadow.camera.updateProjectionMatrix();
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.04;
  scene.add(sun.target);
  const hemi = scene.getObjectByName('hemi');
  if (hemi && env) hemi.intensity = 0.35; // Umgebungslicht kommt jetzt vom HDRI

  // Nebel in Horizontfarbe (lineare HDR-Werte, wie der Himmel tonemapped).
  const fogColor = env ? env.horizon.clone() : new THREE.Color(0xa9c8e8);
  scene.fog = overview ? null : new THREE.FogExp2(fogColor, 0.0016);

  const post = createPost({ renderer, scene, camera });
  if (env) post.setBloomThreshold(Math.min(6, Math.max(2.5, env.peak * 0.02)));
  const urlFx = new URLSearchParams(location.search).get('fx');
  let prefFx = urlFx !== null ? urlFx !== '0' : loadPref() !== '0'; // P-Wahl: Post-FX überhaupt erlaubt?
  let postOn = prefFx;

  // Qualitätsstufe anwenden: Pixel-Ratio deckeln, Schattenkarte, AO und Post-FX.
  const gpu = gpuName(renderer);
  let tier = initialTier(gpu);
  function applyTier(i, reason) {
    tier = Math.max(0, Math.min(TIERS.length - 1, i));
    const t = TIERS[tier];
    const pr = Math.min(devicePixelRatio || 1, t.pr);
    renderer.setPixelRatio(pr);
    renderer.setSize(innerWidth, innerHeight);
    post.setPixelRatio(pr);
    sun.castShadow = t.shadow > 0;
    if (t.shadow > 0 && sun.shadow.mapSize.x !== t.shadow) {
      sun.shadow.mapSize.set(t.shadow, t.shadow);
      sun.shadow.map?.dispose();
      sun.shadow.map = null; // wird in der neuen Größe neu angelegt
    }
    post.setAo(t.ao);
    postOn = t.post && prefFx;
    console.info(`[look] quality ${t.name} (${reason}), pixelRatio ${pr}, GPU: ${gpu || 'unbekannt'}`);
    if (reason !== 'start') hud.toast(`Graphics: ${t.name}${reason === 'auto' ? ' (low fps)' : ''}`, 2000);
  }
  applyTier(tier, 'start');
  const guard = createFpsGuard(() => { if (tier < TIERS.length - 1) applyTier(tier + 1, 'auto'); });
  input.onKey('KeyQ', () => { applyTier((tier + 1) % TIERS.length, 'manual'); guard.reset(); });

  input.onKey('KeyP', () => {
    postOn = !postOn;
    prefFx = postOn; // gilt auch für spätere Stufenwechsel
    savePref(postOn);
    hud.toast(`Post-FX ${postOn ? 'on' : 'off'} (P)`, 1500);
  });
  input.onKey('KeyO', () => {
    post.setAo(!post.aoEnabled());
    hud.toast(`Ambient occlusion ${post.aoEnabled() ? 'on' : 'off'} (O)`, 1500);
  });

  const cache = new WeakMap();
  const seen = new WeakSet();
  let scanTimer = 0;

  /** Neue Meshes: Material auf PBR heben, Schatten setzen. */
  function scan() {
    scene.traverse((o) => {
      if (!o.isMesh) return;
      if (o.name === 'city-buildings' && o.material?.name !== 'facade') o.material = facadeMaterial(o.material);
      if (Array.isArray(o.material)) o.material = o.material.map((m) => (m.isMeshLambertMaterial ? upgrade(cache, m) : m));
      else if (o.material?.isMeshLambertMaterial) o.material = upgrade(cache, o.material);
      if (seen.has(o)) return;
      seen.add(o);
      if (o.name === 'city-buildings') { o.castShadow = true; o.receiveShadow = true; }
      else if (o.name.startsWith('city-')) { o.receiveShadow = true; }
      else if (!o.material?.isMeshBasicMaterial) { o.castShadow = true; o.receiveShadow = true; }
    });
  }
  scan();


  /**
   * Pro Frame: Schattenbereich zum Spieler schieben (auf 2-m-Raster, gegen Flimmern),
   * neue Meshes aufwerten, Bildrate überwachen (adaptive Qualität).
   * @param {number} dt
   */
  function update(dt) {
    const p = player.position();
    const sx = Math.round(p.x / 2) * 2;
    const sz = Math.round(p.z / 2) * 2;
    sun.target.position.set(sx, 0, sz);
    sun.position.set(sx + sunDir.x * SUN_DIST, sunDir.y * SUN_DIST, sz + sunDir.z * SUN_DIST);
    scanTimer -= dt;
    if (scanTimer <= 0) { scanTimer = SCAN_INTERVAL_S; scan(); }
    if (!overview) guard.tick();
  }

  /** Bild ausgeben: mit oder ohne Post-FX. */
  function render() {
    if (postOn) post.render();
    else renderer.render(scene, camera);
  }

  return { update, render, sunDir, postFx: () => postOn, quality: () => TIERS[tier].name, gpu };
}
