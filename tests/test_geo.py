"""Tests der Projektion (geo.py) und der Lage der POIs im Bake-Bereich."""

import math

import pytest

import geo
import protocol


def test_origin_is_zero():
    assert geo.to_local(geo.ORIGIN_LAT, geo.ORIGIN_LON) == (0.0, 0.0)


def test_north_is_negative_z():
    x, z = geo.to_local(geo.ORIGIN_LAT + 0.001, geo.ORIGIN_LON)
    assert x == 0.0
    assert z == pytest.approx(-111.195, abs=0.01)


def test_east_is_positive_x():
    x, z = geo.to_local(geo.ORIGIN_LAT, geo.ORIGIN_LON + 0.001)
    assert x == pytest.approx(72.93, abs=0.01)
    assert z == 0.0


@pytest.mark.parametrize(("lat", "lon"), [(49.0089, 8.4039), (49.0160, 8.3965)])
def test_roundtrip(lat, lon):
    back = geo.to_latlon(*geo.to_local(lat, lon))
    x1, z1 = geo.to_local(lat, lon)
    x2, z2 = geo.to_local(*back)
    assert math.hypot(x1 - x2, z1 - z2) < 0.01


def test_in_bbox():
    assert geo.in_bbox(geo.ORIGIN_LAT, geo.ORIGIN_LON)
    assert not geo.in_bbox(49.0, 8.4)


def test_pois_inside_bbox_and_projected_with_geo():
    for poi in protocol.load_pois().pois:
        assert geo.in_bbox(poi.lat, poi.lon), poi.id
        x, z = geo.to_local(poi.lat, poi.lon)
        assert math.hypot(poi.x - x, poi.z - z) < 0.5, poi.id


def test_market_square_lies_south_of_palace():
    pois = protocol.load_pois()
    schloss, markt = pois.get("schloss"), pois.get("marktplatz")
    assert 450 < markt.z - schloss.z < 560
    assert abs(markt.x - schloss.x) < 60


def test_poi_zones_do_not_overlap():
    pois = protocol.load_pois().pois
    for i, a in enumerate(pois):
        for b in pois[i + 1 :]:
            assert math.hypot(a.x - b.x, a.z - b.z) >= a.radius + b.radius, (a.id, b.id)
