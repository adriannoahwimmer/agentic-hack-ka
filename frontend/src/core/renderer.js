/**
 * Renderer, Szene, Kamera, Licht und Nebel (Scheibe Welt).
 *
 * Zweck: die Three.js-Grundlage für ctx.scene, ctx.camera und ctx.renderer.
 * Use-Cases: Stadt und Figuren rendern; Features hängen Objekte an ctx.scene.
 * Stil: Low-Poly mit Lambert-Materialien, Himmel als Hintergrundfarbe, Nebel
 * verdeckt den Rand des Bake-Bereichs.
 */
import * as THREE from 'three';

/** Himmelsfarbe, gleichzeitig Nebelfarbe. */
export const SKY_COLOR = 0xa9c8e8;

/**
 * Renderer an #app hängen, Szene mit Licht und Nebel, Perspektivkamera, Resize-Handler.
 * @param {HTMLElement} container
 * @returns {{renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera}}
 */
export function createRenderer(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.setSize(innerWidth, innerHeight);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(SKY_COLOR);
  scene.fog = new THREE.Fog(SKY_COLOR, 180, 850);

  const camera = new THREE.PerspectiveCamera(65, innerWidth / innerHeight, 0.1, 1200);
  camera.position.set(0, 30, 200);

  scene.add(new THREE.HemisphereLight(0xdfeeff, 0x6b6450, 1.6));
  const sun = new THREE.DirectionalLight(0xfff1d6, 1.6);
  sun.position.set(-300, 400, 200); // Sonne im Südwesten, Nachmittag
  scene.add(sun);

  addEventListener('resize', () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });
  return { renderer, scene, camera };
}
