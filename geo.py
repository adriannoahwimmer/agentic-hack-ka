"""Einzige Projektion lat/lon <-> lokale Meter für Fächerstadt Agents.

Zweck: Bake-Skript (scripts/bake_osm.py), POI-Datei und Server rechnen mit genau
derselben Projektion (Regel 5 im Plan). Use-Cases: OSM-Rohdaten in Weltkoordinaten
backen, POI-Koordinaten erzeugen und prüfen, Punkte für Overpass zurückrechnen.

Koordinaten (Vertrag, Design.md): Meter, Ursprung Schloss Karlsruhe,
x = Ost, y = oben, z = Süd (z = -Nord, Three.js-Konvention).
Äquirektangulär um den Ursprung: Fehler unter 0,1 m im Umkreis von 1 km.
"""

from math import cos, degrees, radians

ORIGIN_LAT = 49.0135
ORIGIN_LON = 8.4044
EARTH_RADIUS_M = 6_371_008.8  # mittlerer Erdradius (IUGG)

# Bake-Bereich als (Süd, West, Nord, Ost), Reihenfolge wie bei Overpass.
# Schloss, Schlossplatz, Marktplatz, Kaiserstraße; ca. 0,95 x 1,17 km.
BAKE_BBOX = (49.0075, 8.3965, 49.0160, 8.4125)

_COS_ORIGIN = cos(radians(ORIGIN_LAT))


def to_local(lat: float, lon: float) -> tuple[float, float]:
    """lat/lon in Grad -> (x, z) in Metern relativ zum Schloss (x Ost, z Süd)."""
    x = EARTH_RADIUS_M * radians(lon - ORIGIN_LON) * _COS_ORIGIN
    z = -EARTH_RADIUS_M * radians(lat - ORIGIN_LAT)
    return x, z


def to_latlon(x: float, z: float) -> tuple[float, float]:
    """(x, z) in Metern -> (lat, lon) in Grad. Umkehrung von to_local."""
    lat = ORIGIN_LAT - degrees(z / EARTH_RADIUS_M)
    lon = ORIGIN_LON + degrees(x / (EARTH_RADIUS_M * _COS_ORIGIN))
    return lat, lon


def in_bbox(
    lat: float, lon: float, bbox: tuple[float, float, float, float] = BAKE_BBOX
) -> bool:
    """True, wenn der Punkt im Bake-Bereich (Süd, West, Nord, Ost) liegt."""
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east
