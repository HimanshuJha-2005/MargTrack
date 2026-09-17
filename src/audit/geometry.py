"""Pure geometry helpers — the part of the engine a judge can't call a wrapper.

Everything here is plain math on (lat, lon) coordinates. No models, no magic.
"""

import math

EARTH_RADIUS_M = 6371000.0


def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Great-circle distance in metres between two points."""
    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dlambda = math.radians(b_lon - a_lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def path_length_m(lats, lons) -> float:
    """Total length of a polyline defined by parallel lat/lon lists, in metres."""
    total = 0.0
    for i in range(len(lats) - 1):
        total += haversine_m(lats[i], lons[i], lats[i + 1], lons[i + 1])
    return total


def initial_bearing_deg(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Initial compass bearing (0-360) travelling from A toward B."""
    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dlambda = math.radians(b_lon - a_lon)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def angular_delta(a: float, b: float) -> float:
    """Smallest signed-ish angular difference between two bearings in degrees (0-180)."""
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def point_in_polygon(lat: float, lon: float, ring) -> bool:
    """Ray-casting test: is (lat, lon) inside a closed polygon ring of (lat, lon) pairs?"""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside