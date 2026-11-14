"""OSM-Bake für Fächerstadt Agents: Overpass-Rohdaten -> statische Stadt-Assets.

Zweck: Die Stadt kommt einmal aus OpenStreetMap und wird vorab in kleine JSON-Dateien
in Weltkoordinaten (geo.py: Meter, x = Ost, z = Süd) gebacken. Zur Laufzeit gibt es
keine OSM-Abfragen (Plan, "Was wir NICHT machen").

Use-Cases:
- `python scripts/bake_osm.py --fetch`: einmalige Overpass-Abfrage für den Bake-Bereich
  (geo.BAKE_BBOX) nach `data/osm/raw.json` (eingecheckt). Braucht Netz.
- `python scripts/bake_osm.py` bzw. `--bake` (Default, offline): liest `raw.json` und
  schreibt `frontend/public/city/{buildings,roads,areas}.json`. Deterministisch, d. h.
  ein erneuter Lauf erzeugt byte-gleiche Dateien.

Ausgabeformate (Design.md, "OSM-Stadt"):
- buildings.json: `[{id, h, pts: [[x, z], ...], holes?}]`, Ring offen (letzter != erster Punkt),
  im Uhrzeigersinn von oben (Karte mit Norden oben), d. h. Shoelace in (x, z) > 0.
- roads.json: `[{id, kind, w, pts}]`, Polylinie, `w` = Breite in Metern.
- areas.json: `[{id, kind, pts, holes?}]`, `kind` aus park, garden, grass, parking, plaza.
- `holes` (nur bei Multipolygon-Relationen mit Innenringen, z. B. Innenhöfe): Liste offener
  Ringe gegen den Uhrzeigersinn (Shoelace < 0).

Nur Standardbibliothek. Daten: © OpenStreetMap contributors (ODbL).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # Aufruf als `python scripts/bake_osm.py`
    sys.path.insert(0, str(ROOT))

import geo

RAW_PATH = ROOT / "data" / "osm" / "raw.json"
OUT_DIR = ROOT / "frontend" / "public" / "city"

# Overpass: overpass-api.de und kumi.systems waren von hier nicht erreichbar (0a).
OVERPASS_URL = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
USER_AGENT = "faecherstadt-bake/1.0 (hackathon OSM bake script)"
# Ausweichquelle, falls kein Overpass-Mirror antwortet (2026-11-14 ab 13:30: mail.ru 504).
OSM_API_URL = "https://api.openstreetmap.org/api/0.6/map.json"
FETCH_TIMEOUT_S = 180

# Größenbudget in Bytes (Plan, W1). Darüber bricht das Skript ab.
BUDGET = {
    "raw.json": 8_000_000,
    "buildings.json": 1_500_000,
    "roads.json": 500_000,
    "areas.json": 500_000,
}

SIMPLIFY_TOLERANCE_M = 0.5  # Douglas-Peucker
ROUND_DIGITS = 1  # 0,1 m
LEVEL_HEIGHT_M = 3.2
DEFAULT_BUILDING_HEIGHT_M = 12.0
MIN_BUILDING_HEIGHT_M = 2.5
MAX_BUILDING_HEIGHT_M = 120.0

# Straßenbreite in Metern je highway-Wert (ohne width-Tag).
ROAD_WIDTHS = {
    "motorway": 14.0,
    "trunk": 12.0,
    "primary": 12.0,
    "secondary": 10.0,
    "tertiary": 9.0,
    "unclassified": 7.0,
    "residential": 7.0,
    "living_street": 6.0,
    "service": 5.0,
    "pedestrian": 8.0,
    "track": 3.5,
    "footway": 3.0,
    "cycleway": 2.5,
    "path": 2.5,
    "bridleway": 2.5,
    "steps": 2.5,
}
DEFAULT_ROAD_WIDTH_M = 5.0
# Keine Straßen im Spiel (Baustellen, Planungen, Gehsteig-Details).
SKIP_HIGHWAYS = {
    "proposed",
    "construction",
    "abandoned",
    "razed",
    "platform",
    "elevator",
    "corridor",
}
SKIP_FOOTWAY = {"sidewalk", "crossing", "traffic_island"}


# Drei Teilabfragen: Eine einzige Abfrage lief am Mirror in einen 504 (Gateway-Timeout).
OVERPASS_PARTS = {
    "buildings": [
        'way["building"]',
        'relation["building"]["type"="multipolygon"]',
    ],
    "roads": [
        'way["highway"]["footway"!~"^(sidewalk|crossing|traffic_island)$"]',
    ],
    "areas": [
        'way["leisure"~"^(park|garden)$"]',
        'relation["leisure"~"^(park|garden)$"]',
        'way["landuse"~"^(grass|meadow|village_green)$"]',
        'way["amenity"="parking"]',
        'way["place"="square"]',
        'relation["place"="square"]',
    ],
}
FETCH_ATTEMPTS = 3
FETCH_RETRY_WAIT_S = 15
FETCH_RETRY_STATUS = {429, 502, 503, 504}


def overpass_query(
    selectors: list[str], bbox: tuple[float, float, float, float] = geo.BAKE_BBOX
) -> str:
    """Overpass-QL für die Selektoren im Bake-Bereich, Ausgabe mit Tags und Geometrie."""
    b = ",".join(f"{v:.4f}" for v in bbox)
    body = "\n".join(f"  {sel}({b});" for sel in selectors)
    return f"[out:json][timeout:90];\n(\n{body}\n);\nout body geom;\n"


# --- Geometrie ----------------------------------------------------------------


def project(geometry: list[dict]) -> list[tuple[float, float]]:
    """Overpass-Geometrie [{lat, lon}] -> [(x, z)] über geo.to_local (einzige Projektion)."""
    return [geo.to_local(p["lat"], p["lon"]) for p in geometry if p is not None]


def _point_segment_distance(p, a, b) -> float:
    """Abstand von Punkt p zur Strecke a-b in Metern."""
    ax, az = a
    bx, bz = b
    px, pz = p
    dx, dz = bx - ax, bz - az
    if dx == 0 and dz == 0:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / (dx * dx + dz * dz)))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def simplify(
    points: list[tuple[float, float]], tolerance: float
) -> list[tuple[float, float]]:
    """Douglas-Peucker (iterativ). Erster und letzter Punkt bleiben immer erhalten."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        best_i, best_d = -1, -1.0
        for i in range(start + 1, end):
            d = _point_segment_distance(points[i], points[start], points[end])
            if d > best_d:
                best_i, best_d = i, d
        if best_d > tolerance:
            keep[best_i] = True
            stack.append((start, best_i))
            stack.append((best_i, end))
    return [p for p, k in zip(points, keep) if k]


def _r(v: float) -> float:
    """Auf 0,1 m runden, -0.0 zu 0.0 normalisieren (byte-gleiche Ausgabe)."""
    return round(v, ROUND_DIGITS) + 0.0


def round_points(points: list[tuple[float, float]]) -> list[list[float]]:
    """Runden und direkt aufeinanderfolgende Duplikate entfernen."""
    out: list[list[float]] = []
    for x, z in points:
        p = [_r(x), _r(z)]
        if not out or out[-1] != p:
            out.append(p)
    return out


def signed_area(ring: list[list[float]]) -> float:
    """Shoelace in (x, z). > 0 heißt im Uhrzeigersinn von oben (z zeigt nach Süden)."""
    s = 0.0
    for i, (x1, z1) in enumerate(ring):
        x2, z2 = ring[(i + 1) % len(ring)]
        s += x1 * z2 - x2 * z1
    return s / 2.0


def clean_ring(
    points: list[tuple[float, float]], clockwise: bool = True
) -> list[list[float]] | None:
    """Ring vereinfachen, runden, offen; Außenring im, Loch gegen den Uhrzeigersinn.

    None, wenn degeneriert (weniger als 3 Punkte oder kleiner als 1 m²).
    """
    if len(points) < 3:
        return None
    if points[0] != points[-1]:
        points = [*points, points[0]]
    ring = round_points(simplify(points, SIMPLIFY_TOLERANCE_M))
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        return None
    area = signed_area(ring)
    if abs(area) < 1.0:  # kleiner als 1 m²
        return None
    if (area < 0) == clockwise:
        ring.reverse()
    return ring


def stitch_rings(ways: list[list[dict]]) -> list[list[dict]]:
    """Äußere Wege einer Multipolygon-Relation zu geschlossenen Ringen zusammensetzen."""
    pending = [list(w) for w in ways if w and len(w) >= 2]
    rings: list[list[dict]] = []

    def same(a: dict, b: dict) -> bool:
        return a["lat"] == b["lat"] and a["lon"] == b["lon"]

    while pending:
        ring = pending.pop(0)
        changed = True
        while not same(ring[0], ring[-1]) and changed:
            changed = False
            for i, w in enumerate(pending):
                if same(ring[-1], w[0]):
                    ring += w[1:]
                elif same(ring[-1], w[-1]):
                    ring += list(reversed(w))[1:]
                elif same(ring[0], w[-1]):
                    ring = w[:-1] + ring
                elif same(ring[0], w[0]):
                    ring = list(reversed(w))[:-1] + ring
                else:
                    continue
                pending.pop(i)
                changed = True
                break
        if len(ring) >= 4 and same(ring[0], ring[-1]):
            rings.append(ring)
    return rings


def outer_rings(element: dict) -> list[list[dict]]:
    """Geschlossene Außenringe (lat/lon) eines Wegs oder einer Multipolygon-Relation."""
    return [outer for outer, _ in polygons(element)]


def _contains(ring: list[dict], pt: dict) -> bool:
    """Punkt-in-Polygon (Strahlverfahren) in lat/lon, ausreichend für kleine Flächen."""
    inside = False
    x, y = pt["lon"], pt["lat"]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a["lat"] > y) != (b["lat"] > y):
            xc = a["lon"] + (y - a["lat"]) * (b["lon"] - a["lon"]) / (
                b["lat"] - a["lat"]
            )
            if x < xc:
                inside = not inside
    return inside


def polygons(element: dict) -> list[tuple[list[dict], list[list[dict]]]]:
    """Polygone (Außenring, [Innenringe]) in lat/lon.

    Wege haben keine Innenringe. Bei Multipolygon-Relationen werden äußere und innere Wege
    zu Ringen zusammengesetzt; jeder Innenring (Innenhof) gehört zu dem Außenring, der seinen
    ersten Punkt enthält. Innenringe ohne passenden Außenring entfallen.
    """
    if element["type"] == "way":
        geom = element.get("geometry") or []
        if len(geom) >= 4 and geom[0] == geom[-1]:
            return [(geom, [])]
        return []
    members = [m for m in element.get("members", []) if m.get("type") == "way"]
    outers = stitch_rings(
        [
            m.get("geometry") or []
            for m in members
            if m.get("role", "outer") in ("outer", "")
        ]
    )
    inners = stitch_rings(
        [m.get("geometry") or [] for m in members if m.get("role") == "inner"]
    )
    result: list[tuple[list[dict], list[list[dict]]]] = [(o, []) for o in outers]
    for inner in inners:
        for outer, holes in result:
            if _contains(outer, inner[0]):
                holes.append(inner)
                break
    return result


def baked_polygons(
    element: dict,
) -> list[tuple[list[list[float]], list[list[list[float]]]]]:
    """Polygone in Weltkoordinaten: (Außenring im Uhrzeigersinn, [Löcher dagegen])."""
    out = []
    for outer, inners in polygons(element):
        ring = clean_ring(project(outer))
        if not ring:
            continue
        holes = [
            h for h in (clean_ring(project(g), clockwise=False) for g in inners) if h
        ]
        out.append((ring, holes))
    return out


# --- Regeln -------------------------------------------------------------------


def _parse_number(value: str | None) -> float | None:
    """'12', '12.5 m', '12,5' -> float. Unlesbar -> None."""
    if not value:
        return None
    text = value.strip().lower().replace(",", ".").removesuffix("m").strip()
    try:
        number = float(text.split(";")[0])
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def building_height(tags: dict) -> float:
    """Höhe aus `height`, sonst `building:levels` x 3,2 m, sonst 12 m (geclampt, 0,1 m)."""
    h = _parse_number(tags.get("height"))
    if h is None:
        levels = _parse_number(tags.get("building:levels"))
        if levels is not None:
            h = levels * LEVEL_HEIGHT_M
    if h is None:
        h = DEFAULT_BUILDING_HEIGHT_M
    return _r(min(MAX_BUILDING_HEIGHT_M, max(MIN_BUILDING_HEIGHT_M, h)))


def road_width(tags: dict) -> float:
    """Breite aus `width`, sonst Tabelle je highway-Wert."""
    w = _parse_number(tags.get("width"))
    if w is None or w > 40:
        w = ROAD_WIDTHS.get(tags.get("highway", ""), DEFAULT_ROAD_WIDTH_M)
    return _r(w)


def area_kind(tags: dict) -> str | None:
    """Flächenart für areas.json oder None."""
    if tags.get("leisure") in ("park", "garden"):
        return tags["leisure"]
    if tags.get("landuse") in ("grass", "meadow", "village_green"):
        return "grass"
    if (
        tags.get("amenity") == "parking"
        and "building" not in tags
        and tags.get("parking") not in ("underground", "multi-storey", "rooftop")
    ):
        return "parking"
    if tags.get("place") == "square":
        return "plaza"
    if tags.get("highway") in ("pedestrian", "footway") and tags.get("area") == "yes":
        return "plaza"
    return None


def element_id(element: dict) -> str:
    """OSM-Referenz wie in pois.json (`way/123`, `relation/45`)."""
    return f"{element['type']}/{element['id']}"


def _sort_key(item: dict) -> tuple[str, int]:
    kind, _, num = item["id"].partition("/")
    return kind, int(num)


# --- Bake ---------------------------------------------------------------------


def bake(raw: dict) -> dict[str, list]:
    """Overpass-JSON -> {"buildings": [...], "roads": [...], "areas": [...]}, sortiert nach id."""
    buildings: list[dict] = []
    roads: list[dict] = []
    areas: list[dict] = []

    for el in raw.get("elements", []):
        tags = el.get("tags") or {}
        eid = element_id(el)

        if "building" in tags and tags["building"] != "no":
            h = building_height(tags)
            for i, (ring, holes) in enumerate(baked_polygons(el)):
                item = {"id": eid if i == 0 else f"{eid}#{i}", "h": h, "pts": ring}
                if holes:
                    item["holes"] = holes
                buildings.append(item)
            continue

        kind = area_kind(tags)
        if kind:
            for i, (ring, holes) in enumerate(baked_polygons(el)):
                item = {
                    "id": eid if i == 0 else f"{eid}#{i}",
                    "kind": kind,
                    "pts": ring,
                }
                if holes:
                    item["holes"] = holes
                areas.append(item)
            continue

        hw = tags.get("highway")
        if el["type"] == "way" and hw and hw not in SKIP_HIGHWAYS:
            if tags.get("footway") in SKIP_FOOTWAY or tags.get("area") == "yes":
                continue
            pts = round_points(
                simplify(project(el.get("geometry") or []), SIMPLIFY_TOLERANCE_M)
            )
            if len(pts) >= 2:
                roads.append({"id": eid, "kind": hw, "w": road_width(tags), "pts": pts})

    # Mehrteilige Ids ("way/1#1") nach dem Basis-Id sortieren, stabil.
    def key(item: dict) -> tuple[str, int, str]:
        base, _, part = item["id"].partition("#")
        kind, num = _sort_key({"id": base})
        return kind, num, part

    return {
        "buildings": sorted(buildings, key=key),
        "roads": sorted(roads, key=key),
        "areas": sorted(areas, key=key),
    }


def dumps(data) -> str:
    """Kompaktes, deterministisches JSON (byte-gleich bei gleichem Input)."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False, sort_keys=False)


class BudgetExceeded(SystemExit):
    """Eine Ausgabe ist größer als ihr Budget (Plan, W1). Beendet das Skript mit Meldung."""


def check_budget(name: str, size: int) -> None:
    """Wirft BudgetExceeded, wenn `size` über BUDGET[name] liegt."""
    limit = BUDGET[name]
    if size > limit:
        raise BudgetExceeded(
            f"{name}: {size / 1e6:.2f} MB > Budget {limit / 1e6:.2f} MB. "
            "Bake-Bereich verkleinern oder Filter in overpass_query() schärfen."
        )


def write_outputs(
    baked: dict[str, list], out_dir: Path | None = None
) -> dict[str, int]:
    """Budget prüfen (alle Dateien vor dem Schreiben), dann schreiben. Liefert Größen in Bytes."""
    texts = {f"{name}.json": dumps(items) for name, items in baked.items()}
    sizes = {name: len(text.encode("utf-8")) for name, text in texts.items()}
    for name, size in sizes.items():
        check_budget(name, size)
    out_dir = (
        out_dir or OUT_DIR
    )  # erst hier auflösen, damit Tests OUT_DIR patchen können
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return sizes


def _overpass(query: str) -> dict:
    """Eine Overpass-Abfrage mit bis zu FETCH_ATTEMPTS Versuchen bei 429/5xx."""
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        req = urllib.request.Request(
            OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in FETCH_RETRY_STATUS or attempt == FETCH_ATTEMPTS:
                raise
            print(
                f"Overpass HTTP {exc.code}, Versuch {attempt}, warte {FETCH_RETRY_WAIT_S} s"
            )
            time.sleep(FETCH_RETRY_WAIT_S)
    raise RuntimeError("unreachable")


def wanted(el: dict) -> bool:
    """Lokale Entsprechung von OVERPASS_PARTS (für die Quelle osmapi)."""
    tags = el.get("tags") or {}
    is_way, is_rel = el["type"] == "way", el["type"] == "relation"
    mp = is_rel and tags.get("type") == "multipolygon"
    if "building" in tags and (is_way or mp):
        return True
    if is_way and "highway" in tags and tags.get("footway") not in SKIP_FOOTWAY:
        return True
    if tags.get("leisure") in ("park", "garden") and (is_way or is_rel):
        return True
    if is_way and tags.get("landuse") in ("grass", "meadow", "village_green"):
        return True
    if is_way and tags.get("amenity") == "parking":
        return True
    return tags.get("place") == "square" and (is_way or is_rel)


def _get_json(url: str) -> dict:
    """GET mit User-Agent, JSON-Antwort."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_osmapi(
    bbox: tuple[float, float, float, float] = geo.BAKE_BBOX, tiles: int = 2
) -> list[dict]:
    """Ausweichquelle: OSM-API `map.json` in tiles x tiles Kacheln (Limit 50.000 Knoten pro Aufruf).

    Liefert Elemente im Overpass-Format (`out body geom`): Wege mit `geometry`,
    Relationen mit `members[].geometry`. Einmalig für den kleinen Bake-Bereich.
    """
    south, west, north, east = bbox
    nodes: dict[int, dict] = {}
    ways: dict[int, dict] = {}
    rels: dict[int, dict] = {}
    for i in range(tiles):
        for j in range(tiles):
            s = south + (north - south) * i / tiles
            n = south + (north - south) * (i + 1) / tiles
            w = west + (east - west) * j / tiles
            e = west + (east - west) * (j + 1) / tiles
            data = _get_json(f"{OSM_API_URL}?bbox={w:.5f},{s:.5f},{e:.5f},{n:.5f}")
            for el in data.get("elements", []):
                target = {"node": nodes, "way": ways, "relation": rels}[el["type"]]
                target[el["id"]] = el
            print(f"Kachel {i},{j}: {len(data.get('elements', []))} Elemente")

    def geometry(way: dict) -> list[dict] | None:
        pts = [nodes.get(ref) for ref in way.get("nodes", [])]
        if any(p is None for p in pts):
            return None
        return [{"lat": p["lat"], "lon": p["lon"]} for p in pts]

    out: list[dict] = []
    for way in ways.values():
        if wanted(way) and (g := geometry(way)):
            out.append(
                {"type": "way", "id": way["id"], "tags": way["tags"], "geometry": g}
            )
    for rel in rels.values():
        if not wanted(rel):
            continue
        members = []
        for m in rel.get("members", []):
            if (
                m["type"] == "way"
                and m["ref"] in ways
                and (g := geometry(ways[m["ref"]]))
            ):
                members.append(
                    {"type": "way", "ref": m["ref"], "role": m["role"], "geometry": g}
                )
        if members:
            out.append(
                {
                    "type": "relation",
                    "id": rel["id"],
                    "tags": rel["tags"],
                    "members": members,
                }
            )
    return out


def fetch_overpass() -> list[dict]:
    """Drei Overpass-Teilabfragen am Mirror, zusammengeführt."""
    elements: list[dict] = []
    for part, selectors in OVERPASS_PARTS.items():
        data = _overpass(overpass_query(selectors))
        if data.get("remark"):
            print(f"Overpass-Hinweis ({part}): {data['remark']}", file=sys.stderr)
        for el in data.get("elements", []):
            el.pop(
                "nodes", None
            )  # Knoten-Ids braucht der Bake nicht (Geometrie ist inline)
            el.pop("bounds", None)
            elements.append(el)
        print(f"{part}: {len(data.get('elements', []))} Elemente")
    return elements


def fetch(raw_path: Path | None = None, source: str = "auto") -> int:
    """Einmalige Abfrage -> raw.json (kompakt). Liefert die Größe in Bytes.

    source: "overpass" (Mirror), "osmapi" (OSM-API, Ausweichquelle) oder "auto"
    (erst Overpass, bei HTTP- oder Netzfehler die OSM-API).
    """
    raw_path = raw_path or RAW_PATH
    used = source
    if source in ("auto", "overpass"):
        try:
            found = fetch_overpass()
            used = "overpass"
        except (urllib.error.URLError, TimeoutError) as exc:
            if source == "overpass":
                raise
            print(f"Overpass nicht verfügbar ({exc}), weiter mit der OSM-API")
            used = "osmapi"
    if used == "osmapi":
        found = fetch_osmapi()
    elements = {(el["type"], el["id"]): el for el in found}
    # Ohne Zeitstempel, damit ein erneuter Fetch ohne OSM-Änderung byte-gleich ist.
    out = {
        "generator": f"scripts/bake_osm.py via {'Overpass API' if used == 'overpass' else 'OSM API 0.6'}",
        "copyright": "The data included in this document is from www.openstreetmap.org. "
        "The data is made available under ODbL.",
        "bbox": list(geo.BAKE_BBOX),
        "elements": [elements[k] for k in sorted(elements)],
    }
    text = dumps(out)
    size = len(text.encode("utf-8"))
    check_budget("raw.json", size)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(text, encoding="utf-8", newline="\n")
    return size


def main(argv: list[str] | None = None) -> int:
    """CLI: --fetch (Netz) und/oder --bake (Default, offline)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fetch", action="store_true", help="Overpass -> data/osm/raw.json"
    )
    parser.add_argument(
        "--bake", action="store_true", help="raw.json -> frontend/public/city"
    )
    parser.add_argument(
        "--source", choices=("auto", "overpass", "osmapi"), default="auto"
    )
    args = parser.parse_args(argv)
    if args.fetch:
        size = fetch(source=args.source)
        print(f"raw.json: {size / 1e6:.2f} MB")
    if args.bake or not args.fetch:
        raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        baked = bake(raw)
        sizes = write_outputs(baked)
        for name, items in baked.items():
            print(
                f"{name}.json: {len(items)} Einträge, {sizes[name + '.json'] / 1e3:.0f} KB"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
