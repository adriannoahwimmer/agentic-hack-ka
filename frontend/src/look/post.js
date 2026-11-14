/**
 * Post-Processing: Render-Pass mit MSAA, GTAO (Umgebungsverdeckung), Bloom, Output (Look-Pass).
 *
 * Zweck: Kanten und Ecken der Low-Poly-Stadt durch Ambient Occlusion lesbar machen, helle
 * Lichter (Sonne, Mündungsfeuer, Blaulicht) leuchten lassen. Der Output-Pass macht das
 * ACES-Tonemapping und die sRGB-Ausgabe (renderer.toneMapping).
 * Use-Cases: `render()` statt `renderer.render`, AO separat schaltbar, Größe bei Resize.
 */
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

/**
 * Composer aufbauen.
 * @param {{renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera}} deps
 */
export function createPost({ renderer, scene, camera }) {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const target = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 4 });
  const composer = new EffectComposer(renderer, target);
  composer.setPixelRatio(renderer.getPixelRatio());
  composer.setSize(innerWidth, innerHeight);

  composer.addPass(new RenderPass(scene, camera));
  const ao = new GTAOPass(scene, camera, innerWidth, innerHeight);
  ao.updateGtaoMaterial({ radius: 2.2, distanceExponent: 1.4, thickness: 2.5, scale: 1.1, samples: 12 });
  ao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12 });
  ao.blendIntensity = 0.9;
  composer.addPass(ao);
  const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.45, 0.55, 3.0);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  addEventListener('resize', () => composer.setSize(innerWidth, innerHeight));

  return {
    /** Ein Bild mit allen Effekten rendern. */
    render: () => composer.render(),
    /** AO an/aus (Bloom und Tonemapping bleiben). */
    setAo(on) { ao.enabled = on; },
    aoEnabled: () => ao.enabled,
    /** Pixel-Ratio der Render-Targets (Qualitätsstufe). */
    setPixelRatio(pr) {
      composer.setPixelRatio(pr);
      composer.setSize(innerWidth, innerHeight);
    },
    /** Bloom-Schwelle setzen (HDR-Luminanz vor dem Tonemapping). */
    setBloomThreshold(t) { bloom.threshold = t; },
  };
}
