"""Ride audit engine: compare a GPS trace against the legal route + forbidden zones."""

from .geometry import (
    haversine_m,
    path_length_m,
    point_in_polygon,
)
from .types import DetectedEvent, EventState, Trace, TracePoint, Verdict


def _point_segment_m(px, py, ax, ay, bx, by) -> float:
    """Distance from point P to segment AB, using an equirectangular local plane.

    Good enough at the few-hundred-metre scale of a single bridge zone.
    Roughly: 1 deg lat ~ 111320 m, 1 deg lon ~ 111320 * cos(lat) m.
    """
    lat0 = (py + ay + by) / 3.0
    cos_lat = __import__("math").cos(__import__("math").radians(lat0))
    mx = cos_lat * 111320.0
    my = 111320.0
    px2, py2 = px * mx, py * my
    ax2, ay2 = ax * mx, ay * my
    bx2, by2 = bx * mx, by * my

    dx = bx2 - ax2
    dy = by2 - ay2
    if dx == 0 and dy == 0:
        return haversine_m(py, px, ay, ax)
    t = ((px2 - ax2) * dx + (py2 - ay2) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax2 + t * dx, ay2 + t * dy
    return haversine_m(py, px, cy / my, cx / mx)


def distance_to_route_m(lat, lon, route_lats, route_lons) -> float:
    """Minimum distance from a point to the legal-route polyline, in metres."""
    best = float("inf")
    for i in range(len(route_lats) - 1):
        d = _point_segment_m(lon, lat, route_lons[i], route_lats[i], route_lons[i + 1], route_lats[i + 1])
        if d < best:
            best = d
    return best


def audit_trace(
    trace: Trace,
    route_lats,
    route_lons,
    zones,
    off_route_m: float = 40.0,
    min_deep_points: int = 3,
) -> DetectedEvent:
    """Verdict for one trace against the legal route and forbidden-zone polygons."""
    if len(trace.points) < 2:
        return DetectedEvent(verdict=Verdict.CLEAN, reason="trace too short")

    deep_points: list[int] = []  # indices where the trace enters a forbidden zone

    for i, p in enumerate(trace.points):
        for zone in zones:
            ring = [(pt["lat"], pt["lon"]) for pt in zone.get("ring", [])]
            if not ring:
                continue
            if point_in_polygon(p.lat, p.lon, ring):
                deep_points.append(i)
                break

    # A violation needs a real stay inside the zone, not a GPS blip.
    if len(deep_points) >= min_deep_points:
        return DetectedEvent(
            verdict=Verdict.VIOLATION,
            reason=(
                f"trace entered {len(deep_points)} points inside forbidden zone "
                f"(zone present; {min_deep_points}+ required to confirm)"
            ),
            seg_start=deep_points[0],
            seg_end=deep_points[-1],
            severity="HIGH",
            state=EventState.PENDING_REVIEW,
        )

    # Not deep in a zone, but floating far off the legal path -> ambiguous, review it.
    # Only meaningful when a legal route is supplied.
    if route_lats:
        off_count = 0
        for p in trace.points:
            if distance_to_route_m(p.lat, p.lon, route_lats, route_lons) > off_route_m:
                off_count += 1
        if off_count >= max(2, len(trace.points) // 5):
            return DetectedEvent(
                verdict=Verdict.AMBIGUOUS,
                reason=f"{off_count}/{len(trace.points)} points off legal route by >{off_route_m:.0f}m",
                state=EventState.PENDING_REVIEW,
            )

    return DetectedEvent(verdict=Verdict.CLEAN, reason="trace follows legal corridor")