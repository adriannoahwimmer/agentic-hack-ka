/**
 * Minimap unten links: Stadt, Spieler, POIs und Quest-Ziel (Scheibe Welt, W4).
 *
 * Zweck: Orientierung in der echten Karlsruher Innenstadt (nach Norden ausgerichtet, damit der
 * Fächer erkennbar bleibt). Die Grundkarte (Gebäude, Straßen, Flächen) wird einmal offscreen
 * gezeichnet; pro Frame (gedrosselt auf 15 Hz) nur Ausschnitt, Marker und Spielerpfeil.
 * Use-Cases: zum Quest-Ziel finden (gelber Ring, am Rand ein Pfeil, wenn es außerhalb liegt),
 * POIs erkennen, Fahndung sehen (Rand blinkt rot/blau ab 1 Stern). M blendet die Karte aus.
 * Das Quest-Ziel kommt aus dem Vertrag (`quest_update` über ctx.net), nicht aus Quest-Dateien.
 */

const SIZE = 190; // CSS-Pixel
const VIEW_M = 320; // sichtbarer Durchmesser in Metern
const BASE_PX_PER_M = 1;
const REDRAW_S = 1 / 15;
const COLORS = {
  ground: '#b7b3a3', building: '#8d8274', drivable: '#585c63', pedestrian: '#d3c8b1', path: '#c9bc9c',
  green: '#6f9a4f', plaza: '#d8cdb7', parking: '#80838a',
};
const DRIVABLE = new Set(['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'living_street', 'service', 'track']);

/**
 * Grundkarte in ein Offscreen-Canvas zeichnen (1 px = 1 m).
 * @param {{buildings: object[], roads: object[], areas: object[]}} data
 * @param {{minX: number, maxX: number, minZ: number, maxZ: number}} b
 */
function drawBase(data, b) {
  const pad = 40;
  const ox = b.minX - pad;
  const oz = b.minZ - pad;
  const c = document.createElement('canvas');
  c.width = Math.ceil((b.maxX - b.minX + pad * 2) * BASE_PX_PER_M);
  c.height = Math.ceil((b.maxZ - b.minZ + pad * 2) * BASE_PX_PER_M);
  const g = c.getContext('2d');
  g.scale(BASE_PX_PER_M, BASE_PX_PER_M);
  g.translate(-ox, -oz);
  g.fillStyle = COLORS.ground;
  g.fillRect(ox, oz, c.width, c.height);
  const poly = (pts) => {
    g.beginPath();
    pts.forEach(([x, z], i) => (i ? g.lineTo(x, z) : g.moveTo(x, z)));
    g.closePath();
  };
  // Gleiche Reihenfolge wie in 3D (core/city.js): Plätze unten, Parkplätze, Grün oben.
  const order = { plaza: 0, parking: 1 };
  const areas = [...data.areas].sort((a, b) => (order[a.kind] ?? 2) - (order[b.kind] ?? 2));
  for (const a of areas) {
    g.fillStyle = a.kind === 'plaza' ? COLORS.plaza : a.kind === 'parking' ? COLORS.parking : COLORS.green;
    poly(a.pts);
    g.fill();
  }
  g.lineCap = 'round';
  g.lineJoin = 'round';
  for (const r of data.roads) {
    g.strokeStyle = DRIVABLE.has(r.kind) ? COLORS.drivable : r.kind === 'pedestrian' ? COLORS.pedestrian : COLORS.path;
    g.lineWidth = Math.max(1.5, r.w);
    g.beginPath();
    r.pts.forEach(([x, z], i) => (i ? g.lineTo(x, z) : g.moveTo(x, z)));
    g.stroke();
  }
  g.fillStyle = COLORS.building;
  for (const bd of data.buildings) {
    g.beginPath();
    for (const ring of [bd.pts, ...(bd.holes ?? [])]) {
      ring.forEach(([x, z], i) => (i ? g.lineTo(x, z) : g.moveTo(x, z)));
      g.closePath();
    }
    g.fill('evenodd'); // Innenhöfe bleiben frei
  }
  return { canvas: c, ox, oz };
}

/**
 * Minimap anlegen.
 * @param {{hudRoot: HTMLElement, data: object, worldApi: object, player: object, net: object, hud: object, input: object}} deps
 */
export function createMinimap({ hudRoot, data, worldApi, player, net, hud, input }) {
  const base = drawBase(data, worldApi.bounds);
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const canvas = document.createElement('canvas');
  canvas.width = SIZE * dpr;
  canvas.height = SIZE * dpr;
  canvas.style.cssText = `position:fixed;left:16px;bottom:34px;width:${SIZE}px;height:${SIZE}px;border-radius:50%;`
    + 'border:3px solid #ffffffcc;box-shadow:0 2px 10px #0008;background:#0004';
  hudRoot.appendChild(canvas);
  const g = canvas.getContext('2d');
  const scale = (SIZE / VIEW_M) * dpr; // Canvas-Pixel pro Meter
  let quest = null; // {x, z, radius, title}
  let timer = 0;
  let blink = 0;

  net.on('quest_update', (p) => {
    quest = p.status === 'completed' ? null : { ...p.target, title: p.title };
  });
  input.onKey('KeyM', () => { canvas.hidden = !canvas.hidden; });

  /** Kreis-Marker in Weltkoordinaten zeichnen. */
  function dot(x, z, r, fill, stroke) {
    g.beginPath();
    g.arc(x, z, r, 0, Math.PI * 2);
    g.fillStyle = fill;
    g.fill();
    if (stroke) { g.lineWidth = 2 / scale; g.strokeStyle = stroke; g.stroke(); }
  }

  /**
   * Pro Frame aufrufen; zeichnet höchstens mit 15 Hz.
   * @param {number} dt
   */
  function update(dt) {
    blink += dt;
    timer -= dt;
    if (timer > 0 || canvas.hidden) return;
    timer = REDRAW_S;
    const p = player.position();
    const W = canvas.width;
    const half = W / 2;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, W, W);
    g.save();
    g.beginPath();
    g.arc(half, half, half, 0, Math.PI * 2);
    g.clip();
    // Welt → Karte: Spieler in der Mitte, Norden oben (z nach unten).
    g.setTransform(scale, 0, 0, scale, half - p.x * scale, half - p.z * scale);
    g.drawImage(base.canvas, base.ox, base.oz, base.canvas.width / BASE_PX_PER_M, base.canvas.height / BASE_PX_PER_M);
    for (const poi of worldApi.pois) dot(poi.x, poi.z, 6 / (scale / dpr), '#ffffffdd', '#333');
    if (quest) {
      g.beginPath();
      g.arc(quest.x, quest.z, Math.max(quest.radius, 12), 0, Math.PI * 2);
      g.lineWidth = (3 + Math.sin(blink * 6)) / (scale / dpr);
      g.strokeStyle = '#ffd23f';
      g.stroke();
      dot(quest.x, quest.z, 4 / (scale / dpr), '#ffd23f');
    }
    g.restore();

    // Quest-Ziel außerhalb: Pfeil am Rand.
    if (quest) {
      const dx = quest.x - p.x;
      const dz = quest.z - p.z;
      const d = Math.hypot(dx, dz);
      if (d * scale > half - 8 * dpr) {
        const a = Math.atan2(dz, dx);
        const rr = half - 9 * dpr;
        g.setTransform(1, 0, 0, 1, half + Math.cos(a) * rr, half + Math.sin(a) * rr);
        g.rotate(a);
        g.beginPath();
        g.moveTo(8 * dpr, 0); g.lineTo(-6 * dpr, -6 * dpr); g.lineTo(-6 * dpr, 6 * dpr);
        g.closePath();
        g.fillStyle = '#ffd23f';
        g.fill();
        g.setTransform(1, 0, 0, 1, 0, 0);
      }
    }

    // Spielerpfeil (heading h: Blick (−sin h, −cos h) → Canvas-Rotation −h).
    g.setTransform(dpr, 0, 0, dpr, half, half);
    g.rotate(-player.heading());
    g.beginPath();
    g.moveTo(0, -9); g.lineTo(6.5, 7); g.lineTo(0, 3.5); g.lineTo(-6.5, 7);
    g.closePath();
    g.fillStyle = player.inVehicle() ? '#4cc9f0' : '#e63946';
    g.fill();
    g.lineWidth = 1.5;
    g.strokeStyle = '#fff';
    g.stroke();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = '#fff';
    g.font = `bold ${11 * dpr}px system-ui, sans-serif`;
    g.textAlign = 'center';
    g.fillText('N', half, 13 * dpr);

    const wanted = hud.wanted?.() ?? 0;
    canvas.style.borderColor = wanted > 0 ? (Math.floor(blink * 3) % 2 ? '#e63946' : '#3a86ff') : '#ffffffcc';
  }

  return { update, setQuestTarget(t) { quest = t; } };
}
