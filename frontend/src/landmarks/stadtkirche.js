/**
 * Landmark Evangelische Stadtkirche am Marktplatz (OSM way/90180591), Low-Poly von Hand.
 *
 * Zweck: Weinbrenners klassizistische Kirche erkennbar machen: Portikus mit sechs Säulen und
 * Dreiecksgiebel nach Westen zum Marktplatz, Satteldach über dem Schiff, weißer Turm
 * mit Spitze direkt hinter dem Portikus (ca. 62 m).
 * Use-Cases: Orientierung am Marktplatz, Quest-Ziel.
 * Lokale Achsen: u ≈ Ost (Schiff in Längsrichtung), v ≈ Süd. Ca. 400 Dreiecke.
 */

const STONE = 0xefe9dc; // heller Putz/Sandstein
const COLUMN = 0xf6f2e8;
const ROOF = 0x7b8289;
const SPIRE = 0x59626a;

export const stadtkirche = {
  name: 'Stadtkirche',
  ref: 'way/90180591',
  align: true,
  /**
   * @param {import('./kit.js').Kit} kit
   * @param {{w: number, d: number, h: number, pts: number[][]}} fp
   */
  build(kit, fp) {
    const h = fp.h;
    const west = -fp.w / 2; // Westfassade (Marktplatz)
    // Schiff: Grundriss ohne den östlichen Querbau (ca. 50 × 23 m).
    const naveLen = fp.w - 10;
    const naveMid = west + naveLen / 2;
    const naveD = 23;
    const naveV = -fp.d / 2 + 0.6 + naveD / 2;
    kit.roof(naveLen, naveD, naveLen, 0, 6.5, ROOF, naveMid, h, naveV);
    // Querbau im Osten mit Walmdach.
    kit.roof(10.5, fp.d, 0.5, fp.d - 10, 5, ROOF, fp.w / 2 - 5.25, h, 0);

    // Portikus: Stufe, 6 Säulen, Gebälk, Giebel (First entlang u, Dreieck zeigt nach Westen).
    const pu = west - 3.5;
    kit.box(8, 0.8, 19, STONE, pu + 0.5, 0, naveV);
    for (let i = 0; i < 6; i++) {
      const v = naveV - 7.5 + i * 3;
      kit.prism(0.65, h - 2.2, 8, COLUMN, pu - 1.5, 0.8, v, 0.55);
    }
    kit.box(7.5, 1.6, 18.2, STONE, pu + 0.25, h - 1.4, naveV);
    kit.roof(7.5, 18.2, 7.5, 0, 4.2, STONE, pu + 0.25, h + 0.2, naveV);

    // Turm hinter dem Giebel: zwei Geschosse, Glockengeschoss, Spitze.
    const tu = west + 5;
    kit.box(7, 30, 7, STONE, tu, h, naveV);
    kit.box(7.6, 1, 7.6, COLUMN, tu, h + 30, naveV);
    kit.prism(3.4, 8, 8, STONE, tu, h + 31, naveV);
    kit.prism(3.6, 0.8, 8, COLUMN, tu, h + 39, naveV);
    kit.prism(3.4, 9, 8, SPIRE, tu, h + 39.8, naveV, 0);
  },
};
