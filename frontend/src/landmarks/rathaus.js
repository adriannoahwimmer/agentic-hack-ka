/**
 * Landmark Rathaus am Marktplatz (OSM relation/1333212), Low-Poly von Hand.
 *
 * Zweck: Weinbrenners Rathaus auf der Westseite des Marktplatzes, gegenüber der Stadtkirche:
 * Walmdach über dem Ostflügel, Mittelrisalit mit Giebel zum Platz und der Rathausturm.
 * Use-Cases: Orientierung am Marktplatz (Kirche und Rathaus rahmen die Pyramide).
 * Lokale Achsen: u ≈ Ost (Fassade zum Marktplatz bei +u), v ≈ Süd. Ca. 150 Dreiecke.
 */

const WALL = 0xdcc6a2; // heller Sandstein
const TRIM = 0xeee3cc;
const ROOF = 0x6d625c;

export const rathaus = {
  name: 'Rathaus',
  ref: 'relation/1333212',
  align: true,
  /**
   * @param {import('./kit.js').Kit} kit
   * @param {{w: number, d: number, h: number}} fp
   */
  build(kit, fp) {
    const h = fp.h;
    const east = fp.w / 2; // Fassade zum Marktplatz
    const wing = 15; // Flügeltiefe
    const len = fp.d * 0.62; // gerader Teil der Ostfassade (Süden ist abgeschrägt)
    const v0 = -fp.d / 2 + len / 2;
    kit.roof(wing, len, 0.5, len - wing, 5.5, ROOF, east - wing / 2 - 1, h, v0);
    // Mittelrisalit mit Dreiecksgiebel nach Osten.
    kit.box(2, h + 1.2, 16, TRIM, east - 0.2, 0, v0);
    kit.roof(2, 16, 2, 0, 3.6, TRIM, east - 0.2, h + 1.2, v0);
    // Rathausturm hinter dem Risalit.
    const tu = east - wing / 2 - 1;
    kit.box(7, 22, 7, WALL, tu, h, v0);
    kit.box(7.8, 0.8, 7.8, TRIM, tu, h + 22, v0);
    kit.box(6, 5, 6, TRIM, tu, h + 22.8, v0);
    kit.roof(6.6, 6.6, 0, 0, 5, ROOF, tu, h + 27.8, v0);
  },
};
