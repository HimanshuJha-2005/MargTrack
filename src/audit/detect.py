"""Ride audit engine: compare a GPS trace against the legal route + forbidden zones."""

from .geometry import (
    angular_delta,
    initial_bearing_deg,
    nearest_route_index,
    path_length_m,
    point_in_polygon,
    point_segment_distance_m,
    polyline_subpath_m,
)
from .types import DetectedEvent, EventState, Trace, Verdict


def distance_to_route_m(lat, lon, route_lats, route_lons) -> float:
    """Minimum distance from a point to the legal-route polyline, in metres."""
    best = float("inf")
    for i in range(len(route_lats) - 1):
        d = point_segment_distance_m(
            lat, lon, route_lats[i], route_lons[i], route_lats[i + 1], route_lons[i + 1]
        )
        if d < best:
            best = d
    return best


def _contiguous_runs(indices: list[int]) -> list[list[int]]:
    """Group sorted trace indices into runs of consecutive points."""
    runs: list[list[int]] = []
    for i in indices:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def _run_metrics(trace: Trace, run: list[int], route_lats, route_lons) -> dict:
    """Evidence for the violating run: lengths, shortcut factor, bearing delta."""
    seg_start, seg_end = run[0], run[-1]
    if seg_end - seg_start < 1 or not route_lats:
        return {}

    entry = trace.points[seg_start]
    exit_ = trace.points[seg_end]

    e_idx = nearest_route_index(entry.lat, entry.lon, route_lats, route_lons)
    x_idx = nearest_route_index(exit_.lat, exit_.lon, route_lats, route_lons)

    route_len = polyline_subpath_m(route_lats, route_lons, e_idx, x_idx)
    cut_lats = [p.lat for p in trace.points[seg_start : seg_end + 1]]
    cut_lons = [p.lon for p in trace.points[seg_start : seg_end + 1]]
    trace_len = path_length_m(cut_lats, cut_lons)

    if e_idx != x_idx:
        route_bearing = initial_bearing_deg(
            route_lats[e_idx], route_lons[e_idx], route_lats[x_idx], route_lons[x_idx]
        )
    else:
        nxt = min(x_idx + 1, len(route_lats) - 1)
        route_bearing = initial_bearing_deg(
            route_lats[e_idx], route_lons[e_idx], route_lats[nxt], route_lons[nxt]
        )
    trace_bearing = initial_bearing_deg(entry.lat, entry.lon, exit_.lat, exit_.lon)

    shortcut = route_len / max(trace_len, 1e-9)
    return {
        "trace_len_m": round(trace_len, 1),
        "route_len_m": round(route_len, 1),
        "shortcut_factor": round(shortcut, 2),
        "bearing_delta_deg": round(angular_delta(route_bearing, trace_bearing), 1),
    }


def _severity(metrics: dict) -> str:
    if metrics.get("bearing_delta_deg", 0) >= 120 or metrics.get("shortcut_factor", 0) >= 1.5:
        return "HIGH"
    return "MEDIUM"


def _auto_confirms(metrics: dict) -> bool:
    """Tier-2 auto-confirm: BOTH strongly provable (shortcut >= 1.5 AND wrong-way >= 120deg)."""
    return metrics.get("shortcut_factor", 0) >= 1.5 and metrics.get("bearing_delta_deg", 0) >= 120


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

    # A violation needs a real contiguous stay inside the zone, not GPS blips.
    if len(deep_points) >= min_deep_points:
        run = max(_contiguous_runs(deep_points), key=len)
        seg_start, seg_end = run[0], run[-1]
        metrics = _run_metrics(trace, run, route_lats, route_lons)
        reason = f"cut through forbidden zone over points [{seg_start}..{seg_end}]"
        if metrics:
            reason += (
                f" (trace {metrics['trace_len_m']}m vs legal {metrics['route_len_m']}m, "
                f"shortcut x{metrics['shortcut_factor']}, "
                f"bearing delta {metrics['bearing_delta_deg']}deg)"
            )
        return DetectedEvent(
            verdict=Verdict.VIOLATION,
            reason=reason,
            seg_start=seg_start,
            seg_end=seg_end,
            severity=_severity(metrics),
            state=(
                EventState.CONFIRMED if _auto_confirms(metrics) else EventState.PENDING_REVIEW
            ),
            metrics=metrics,
        )

    # Not deep in a zone, but floating far off the legal path -> ambiguous, review it.
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

    return DetectedEvent(
        verdict=Verdict.CLEAN,
        reason="trace follows legal corridor",
        state=EventState.CONFIRMED,
    )