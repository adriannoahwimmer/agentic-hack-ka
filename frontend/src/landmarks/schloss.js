/**
 * Landmark Karlsruher Schloss (OSM way/316433983), Low-Poly von Hand.
 *
 * Zweck: Der extrudierte OSM-Block (11,2 m) bekommt das, was das Schloss erkennbar macht:
 * den achteckigen Schlossturm im Norden (Mittelpunkt des Straßenfächers, ca. 51 m),
 * ein graublaues Mansarddach auf dem Corps de Logis und den Mittelgiebel zum Schlossplatz.
 * Use-Cases: Orientierung im Spiel (Turm von überall sichtbar), Intro-Kamera, Quest-Ziel.
 * Proportionen und Farben nach Google-Earth-Referenzen (cremegelbe Fassade, Schieferdach).
 * Ca. 300 Dreiecke.
 */

const WALL = 0xe9d9a8; // cremegelb
const TRIM = 0xf3ecd8; // helle Gliederung
const SLATE = 0x56616b; // Schieferdach
const DOME = 0x3d464e; // Turmhaube
const GOLD = 0xc9a54a;

export const schloss = {
  name: 'Schloss',
  ref: 'way/316433983',
  align: false, // Achse steht exakt Nord-Süd (Fächer), der längste Rand ist ein Schrägflügel
  /**
   * @param {import('./kit.js').Kit} kit
   * @param {{h: number, pts: number[][], toLocal: (x: number, z: number) => number[]}} fp
   */
  build(kit, fp) {
    // Turm: Mittel der nördlichsten Grundrisspunkte (achteckiger Turmsockel im OSM-Umriss).
    const minV = Math.min(...fp.pts.map((p) => p[1]));
    const north = fp.pts.filter((p) => p[1] < minV + 14);
    const tu = north.reduce((s, p) => s + p[0], 0) / north.length;
    const tv = north.reduce((s, p) => s + p[1], 0) / north.length;
    kit.prism(5.4, 26, 8, WALL, tu, 0, tv);
    kit.prism(5.8, 1.2, 8, TRIM, tu, 26, tv); // Gesims
    kit.prism(4.6, 9, 8, TRIM, tu, 27.2, tv); // Glockengeschoss
    kit.prism(4.9, 6, 8, DOME, tu, 36.2, tv, 1.4); // Haube
    kit.prism(1.4, 3, 8, TRIM, tu, 42.2, tv); // Laterne
    kit.prism(1.6, 2.2, 8, DOME, tu, 45.2, tv, 0.3);
    kit.prism(0.35, 3.5, 4, GOLD, tu, 47.4, tv, 0); // Spitze

    // Corps de Logis: Mansarddach über dem Mittelbau (Weltlage x −27…23, z −14…6, ~4° gedreht).
    const [cu, cv] = fp.toLocal(-2.2, -3.6);
    const rot = -0.075;
    const y0 = fp.h;
    kit.roof(50, 19, 46, 13, 4.2, SLATE, cu, y0, cv, rot);
    kit.roof(46, 13, 38, 0.1, 2.6, SLATE, cu, y0 + 4.2, cv, rot);
    // Seitenflügel-Dächer (Ost/West des Corps, x ≈ ±39, z −24…−8).
    for (const [x, z] of [[-39.5, -15.5], [38.5, -13.5]]) {
      const [u, v] = fp.toLocal(x, z);
      kit.roof(15, 15, 9, 9, 3.6, SLATE, u, y0, v, rot);
      kit.roof(9, 9, 0.1, 0.1, 2.2, SLATE, u, y0 + 3.6, v, rot);
    }
    // Mittelrisalit mit Dreiecksgiebel zum Schlossplatz (Süden, +z).
    const [ru, rv] = fp.toLocal(-2.8, 5.4);
    kit.box(18, 2.2, 3, TRIM, ru, y0 - 1, rv, rot);
    kit.roof(3, 18, 3, 0.1, 3.8, TRIM, ru, y0 + 1.2, rv, rot + Math.PI / 2);
    // Mittelpavillon-Kuppel über dem Risalit.
    const [pu, pv] = fp.toLocal(-2.6, -2);
    kit.prism(5.2, 2.5, 8, TRIM, pu, y0 + 6.8, pv);
    kit.prism(5.2, 4.5, 8, SLATE, pu, y0 + 9.3, pv, 1.2);
  },
};
