"""Tests des OSM-Bakes (scripts/bake_osm.py) auf einem kleinen eingebetteten Overpass-Fixture.

Prüft Projektion über geo.py, Höhenregeln, Vereinfachung, Rundung, Uhrzeigersinn,
Multipolygon-Ringe, Budget-Prüfung und Determinismus. Das echte raw.json wird nie
neu geladen (kein Netz); wenn es eingecheckt ist, muss der Bake die eingecheckten
city/*.json byte-gleich reproduzieren.
"""

import json

import pytest

import geo
from scripts import bake_osm


def ll(x: float, z: float) -> dict:
    """Weltkoordinate (m) -> Overpass-Geometriepunkt."""
    lat, lon = geo.to_latlon(x, z)
    return {"lat": lat, "lon": lon}


def ring(*pts: tuple[float, float]) -> list[dict]:
    """Geschlossener Ring als Overpass-Geometrie."""
    return [ll(x, z) for x, z in (*pts, pts[0])]


def way(osm_id: int, tags: dict, geometry: list[dict]) -> dict:
    return {"type": "way", "id": osm_id, "tags": tags, "geometry": geometry}


SQUARE_CCW = ((10, 10), (10, 30), (30, 30), (30, 10))  # Shoelace < 0 in (x, z)

FIXTURE = {
    "elements": [
        way(3, {"building": "yes"}, ring((0, 0), (20, 0), (20, 20), (0, 20))),
        way(1, {"building": "yes", "height": "15 m"}, ring(*SQUARE_CCW)),
        way(
            2,
            {"building": "apartments", "building:levels": "4"},
            ring((50, 0), (60, 0), (60, 8)),
        ),
        way(4, {"building": "no"}, ring((0, 0), (5, 0), (5, 5))),
        # Mittelpunkt 0,3 m neben der Kante -> fällt bei 0,5 m Toleranz weg
        way(
            10,
            {"highway": "residential"},
            [ll(0, 100), ll(50.04, 100.3), ll(100, 100)],
        ),
        way(11, {"highway": "primary", "width": "16"}, [ll(0, 200), ll(0, 300)]),
        way(12, {"highway": "footway", "footway": "sidewalk"}, [ll(0, 0), ll(10, 0)]),
        way(
            13,
            {"highway": "pedestrian", "area": "yes"},
            ring((0, 400), (40, 400), (40, 440)),
        ),
        way(20, {"leisure": "park"}, ring((-100, -100), (-50, -100), (-50, -50))),
        {
            "type": "relation",
            "id": 30,
            "tags": {"type": "multipolygon", "leisure": "garden"},
            "members": [
                {"type": "way", "role": "outer", "geometry": [ll(200, 0), ll(260, 0)]},
                {"type": "way", "role": "outer", "geometry": [ll(200, 60), ll(200, 0)]},
                {
                    "type": "way",
                    "role": "outer",
                    "geometry": [ll(260, 0), ll(260, 60), ll(200, 60)],
                },
                {
                    "type": "way",
                    "role": "inner",
                    "geometry": ring((210, 10), (220, 10), (220, 20)),
                },
            ],
        },
    ]
}


@pytest.fixture(scope="module")
def baked():
    return bake_osm.bake(FIXTURE)


def by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def test_projection_uses_geo(baked):
    pts = by_id(baked["buildings"])["way/3"]["pts"]
    assert sorted(map(tuple, pts)) == [
        (0.0, 0.0),
        (0.0, 20.0),
        (20.0, 0.0),
        (20.0, 20.0),
    ]


def test_height_rules(baked):
    b = by_id(baked["buildings"])
    assert b["way/1"]["h"] == 15.0
    assert b["way/2"]["h"] == 12.8  # 4 x 3,2 m
    assert b["way/3"]["h"] == 12.0
    assert "way/4" not in b  # building=no


@pytest.mark.parametrize(
    ("tags", "height"),
    [({"height": "7,5"}, 7.5), ({"height": "abc"}, 12.0), ({"height": "999"}, 120.0)],
)
def test_height_parsing(tags, height):
    assert bake_osm.building_height(tags) == height


def test_rings_open_and_clockwise(baked):
    for b in baked["buildings"]:
        assert b["pts"][0] != b["pts"][-1], b["id"]
        assert bake_osm.signed_area(b["pts"]) > 0, b["id"]
    # way/1 war gegen den Uhrzeigersinn und wurde umgedreht
    assert by_id(baked["buildings"])["way/1"]["pts"][0] in ([10.0, 10.0], [30.0, 10.0])


def test_simplification_drops_near_collinear_point(baked):
    road = by_id(baked["roads"])["way/10"]
    assert road["pts"] == [[0.0, 100.0], [100.0, 100.0]]


def test_simplify_keeps_corners():
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert bake_osm.simplify(pts, 0.5) == pts


def test_rounding_to_decimeter():
    assert bake_osm.round_points([(1.234, -0.04), (1.236, -0.01)]) == [[1.2, 0.0]]
    assert str(bake_osm._r(-0.04)) == "0.0"  # kein "-0.0" im JSON


def test_roads_kind_width_and_filters(baked):
    roads = by_id(baked["roads"])
    assert roads["way/10"]["kind"] == "residential"
    assert roads["way/10"]["w"] == bake_osm.ROAD_WIDTHS["residential"]
    assert roads["way/11"]["w"] == 16.0
    assert "way/12" not in roads  # Gehsteig
    assert "way/13" not in roads  # Fußgängerfläche -> areas


def test_areas_include_plaza_park_and_multipolygon(baked):
    areas = by_id(baked["areas"])
    assert areas["way/13"]["kind"] == "plaza"
    assert areas["way/20"]["kind"] == "park"
    garden = areas["relation/30"]
    assert garden["kind"] == "garden"
    assert len(garden["pts"]) == 4  # vier Außenwege zu einem Ring, inner ignoriert
    assert bake_osm.signed_area(garden["pts"]) == pytest.approx(3600.0, abs=1)


def test_output_sorted_and_deterministic(baked):
    ids = [b["id"] for b in baked["buildings"]]
    assert ids == ["way/1", "way/2", "way/3"]
    assert bake_osm.dumps(bake_osm.bake(FIXTURE)) == bake_osm.dumps(baked)


def test_budget_check_aborts_before_writing(tmp_path, monkeypatch, baked):
    with pytest.raises(bake_osm.BudgetExceeded, match="roads.json"):
        bake_osm.check_budget("roads.json", 500_001)
    bake_osm.check_budget("roads.json", 500_000)

    monkeypatch.setitem(bake_osm.BUDGET, "buildings.json", 10)
    with pytest.raises(bake_osm.BudgetExceeded):
        bake_osm.write_outputs(baked, tmp_path / "city")
    assert not (tmp_path / "city").exists()


def test_cli_bake_is_offline(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("bake darf kein Netz nutzen")

    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(FIXTURE), encoding="utf-8")
    monkeypatch.setattr(bake_osm.urllib.request, "urlopen", no_network)
    monkeypatch.setattr(bake_osm, "RAW_PATH", raw)
    monkeypatch.setattr(bake_osm, "OUT_DIR", tmp_path / "city")
    assert bake_osm.main([]) == 0
    written = json.loads(
        (tmp_path / "city" / "buildings.json").read_text(encoding="utf-8")
    )
    assert [b["id"] for b in written] == ["way/1", "way/2", "way/3"]


@pytest.mark.skipif(not bake_osm.RAW_PATH.exists(), reason="raw.json noch nicht geholt")
def test_checked_in_city_is_reproducible():
    """Erfolgskriterium W1: der Offline-Bake reproduziert die eingecheckten Dateien byte-gleich."""
    raw = json.loads(bake_osm.RAW_PATH.read_text(encoding="utf-8"))
    for name, items in bake_osm.bake(raw).items():
        path = bake_osm.OUT_DIR / f"{name}.json"
        assert path.read_bytes() == bake_osm.dumps(items).encode("utf-8"), name


@pytest.mark.parametrize("parking", ["underground", "multi-storey", "rooftop"])
def test_hidden_parking_is_not_an_area(parking):
    assert bake_osm.area_kind({"amenity": "parking", "parking": parking}) is None
    assert bake_osm.area_kind({"amenity": "parking", "parking": "surface"}) == "parking"
