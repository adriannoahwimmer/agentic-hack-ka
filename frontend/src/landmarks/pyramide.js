/**
 * Landmark Pyramide auf dem Marktplatz (OSM way/90034221), Low-Poly von Hand.
 *
 * Zweck: Grabmal des Stadtgründers Karl Wilhelm aus rotem Sandstein (ca. 6,8 m). Der
 * extrudierte OSM-Block (7 m Quader) würde aus den Schrägen ragen und wird deshalb zur
 * Laufzeit ausgeblendet (`hideBlock`); sein Collider bleibt als Kollision der Pyramide.
 * Use-Cases: Wahrzeichen des Marktplatzes, Quest-Ziel „Pyramid Trouble“.
 * Ca. 20 Dreiecke.
 */

const SANDSTONE = 0x9c4b37; // roter Sandstein
const PLINTH = 0x7d6455;

export const pyramide = {
  name: 'Pyramide',
  ref: 'way/90034221',
  align: true,
  hideBlock: true,
  /**
   * @param {import('./kit.js').Kit} kit
   * @param {{w: number, d: number}} fp
   */
  build(kit, fp) {
    kit.box(fp.w + 0.8, 0.5, fp.d + 0.8, PLINTH); // Sockelstufe
    kit.roof(fp.w, fp.d, 0, 0, 6.4, SANDSTONE, 0, 0.5, 0);
  },
};
