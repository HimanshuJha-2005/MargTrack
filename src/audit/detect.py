"""Ride audit engine: compare a GPS trace against the legal route + forbidden zones."""

from .geometry import (
    angular_delta,
    haversine_m,
    initial_bearing_deg,
    nearest_route_index,
    path_length_m,
    point_in_polygon,
    point_segment_distance_m,
    polyline_subpath_m,
)
from .types import DetectedEvent, EventState, Trace, Verdict, ViolationType

MAX_PLAUSIBLE_SPEED_MS = 55.0  # ~200 km/h: above this a hop is GPS noise, not movement
WRONG_WAY_DELTA_DEG = 120.0  # bearings this far from legal direction => driving against one-way
MIN_ON_CORRIDOR_FRAC = 0.7  # share of trace points that must hug the route for a corridor verdict


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


def _auto_confirms(metrics: dict, violation_type) -> bool:
    """Tier-2 auto-confirm rule, per violation type.

    - ZONE_CUT: shortcut must be HUGE (x1.5) AND heading change severe (>=120 deg).
    - WRONG_WAY: bearing delta >=160 deg is unambiguously reversed travel.
    Everything else stays PENDING_REVIEW so the operator (or Tier-3 agent) decides.
    """
    if violation_type == ViolationType.WRONG_WAY:
        return metrics.get("bearing_delta_deg", 0) >= 160
    return metrics.get("shortcut_factor", 0) >= 1.5 and metrics.get("bearing_delta_deg", 0) >= 120


def _hops_are_plausible(points) -> bool:
    """True if no hop between consecutive trace points implies an impossible speed.

    A 200+ km/h jump means bad GPS fixes (teleporting blips), not real movement.
    Skips pairs without usable timestamps rather than blaming the rider.
    """
    for a, b in zip(points, points[1:]):
        dt = b.t - a.t
        if dt <= 0:
            continue
        dist = haversine_m(a.lat, a.lon, b.lat, b.lon)
        if dist / dt > MAX_PLAUSIBLE_SPEED_MS:
            return False
    return True


def _anchored_to_route(trace: Trace, run: list[int], route_lats, route_lons, anchor_m: float) -> tuple[bool, list[str]]:
    """A real shortcut leaves the legal route and REJOINS it: the neighbour
    points right before/after the in-zone run should sit on the corridor.

    A floating GPS dip (never near the route on either side) fails this and is
    treated as noise, not a cut. Returns (ok, problems).
    """
    seg_start, seg_end = run[0], run[-1]
    problems: list[str] = []
    if seg_start <= 0 or seg_end >= len(trace.points) - 1:
        return False, ["run reaches the trace edge: missing entry/exit anchor"]

    before = trace.points[seg_start - 1]
    after = trace.points[seg_end + 1]
    db = distance_to_route_m(before.lat, before.lon, route_lats, route_lons)
    da = distance_to_route_m(after.lat, after.lon, route_lats, route_lons)
    if db > anchor_m:
        problems.append(f"entry anchor {db:.0f}m off route")
    if da > anchor_m:
        problems.append(f"exit anchor {da:.0f}m off route")
    return not problems, problems


def audit_trace(
    trace: Trace,
    route_lats,
    route_lons,
    zones,
    off_route_m: float = 40.0,
    min_deep_points: int = 3,
    anchor_m: float = 60.0,
    one_way_lanes: list | None = None,
    lane_match_m: float = 15.0,
) -> DetectedEvent:
    """Verdict for one trace against the legal route and forbidden-zone polygons.

    one_way_lanes: list of dicts {"points":[{"lat","lon"}], "name": str}.
      Each is a legal carriageway whose authorized direction is its point order
      (first -> last). A trace hugging that lane but moving the other way is
      a WRONG_WAY violation regardless of the forbidden zones.

    lane_match_m: the radius used to decide a single trace point sits ON a
      one-way lane. Must stay below the gap between opposing carriageways
      (the bypass lanes here are ~37m apart). Default 15m.
    """
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

        # Guard 1: impossible hop speeds mean bad GPS fixes, not movement.
        if not _hops_are_plausible(trace.points[seg_start : seg_end + 1]):
            return DetectedEvent(
                verdict=Verdict.AMBIGUOUS,
                reason=f"points [{seg_start}..{seg_end}] in forbidden zone but hop speeds are "
                "physically impossible (>200km/h) - GPS noise suspected",
                seg_start=seg_start,
                seg_end=seg_end,
                severity="HIGH",
                state=EventState.PENDING_REVIEW,
                metrics={"_hops_are_plausible": False},
            )

        # Guard 2: a real shortcut leaves and REJOINS the legal route.
        anchored, anchor_problems = _anchored_to_route(trace, run, route_lats, route_lons, anchor_m)
        if route_lats and not anchored:
            return DetectedEvent(
                verdict=Verdict.AMBIGUOUS,
                reason=f"points [{seg_start}..{seg_end}] in forbidden zone but trace does not "
                "rejoin the legal route: " + ", ".join(anchor_problems),
                seg_start=seg_start,
                seg_end=seg_end,
                severity="HIGH",
                state=EventState.PENDING_REVIEW,
                metrics={"_anchored": False, "anchor_problems": anchor_problems},
            )

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
                EventState.CONFIRMED
                if _auto_confirms(metrics, ViolationType.ZONE_CUT)
                else EventState.PENDING_REVIEW
            ),
            metrics=metrics,
            violation_type=ViolationType.ZONE_CUT,
        )

    # Not deep in a zone: WRONG_WAY check against explicitly listed one-way lanes.
    if one_way_lanes:
        wrong = _wrong_way_via_lanes(trace, one_way_lanes, lane_match_m)
        if wrong:
            return wrong

    # Not deep in a zone, no one-way lanes: fall back to a single directional route.
    if route_lats and len(route_lats) > 1:
        route_bearing = initial_bearing_deg(
            route_lats[0], route_lons[0], route_lats[-1], route_lons[-1]
        )
        trace_bearing = initial_bearing_deg(
            trace.points[0].lat, trace.points[0].lon,
            trace.points[-1].lat, trace.points[-1].lon,
        )
        delta = angular_delta(route_bearing, trace_bearing)

        on_corridor = sum(
            1 for p in trace.points if distance_to_route_m(p.lat, p.lon, route_lats, route_lons) <= off_route_m
        ) / len(trace.points)

        if on_corridor >= MIN_ON_CORRIDOR_FRAC and delta >= WRONG_WAY_DELTA_DEG:
            return DetectedEvent(
                verdict=Verdict.VIOLATION,
                reason=(
                    f"driving the legal corridor in the wrong direction "
                    f"({delta:.0f}deg against one-way route, {on_corridor:.0%} of points on corridor)"
                ),
                severity="HIGH",
                state=(
                    EventState.CONFIRMED
                    if _auto_confirms({"bearing_delta_deg": delta}, ViolationType.WRONG_WAY)
                    else EventState.PENDING_REVIEW
                ),
                metrics={"route_bearing": round(route_bearing, 1), "trace_bearing": round(trace_bearing, 1), "bearing_delta_deg": round(delta, 1)},
                violation_type=ViolationType.WRONG_WAY,
            )

    # Not deep in a zone, but floating far off the legal path -> ambiguous, review it.
    if route_lats:
        off_count = 0
        for p in trace.points:
            near_any_lane = False
            if one_way_lanes:
                for ln in one_way_lanes:
                    lats = [q["lat"] for q in ln["points"]]
                    lons = [q["lon"] for q in ln["points"]]
                    if distance_to_route_m(p.lat, p.lon, lats, lons) <= off_route_m:
                        near_any_lane = True
                        break
            near_route = distance_to_route_m(p.lat, p.lon, route_lats, route_lons) <= off_route_m
            if not (near_route or near_any_lane):
                off_count += 1
        if off_count >= max(2, len(trace.points) // 5):
            return DetectedEvent(
                verdict=Verdict.AMBIGUOUS,
                reason=f"{off_count}/{len(trace.points)} points off legal route by >{off_route_m:.0f}m",
                state=EventState.PENDING_REVIEW,
                metrics={
                    "off_route_count": off_count,
                    "total_points": len(trace.points),
                    "off_route_frac": round(off_count / len(trace.points), 3),
                },
            )

    return DetectedEvent(
        verdict=Verdict.CLEAN,
        reason="trace follows legal corridor",
        state=EventState.CONFIRMED,
        metrics={
            "total_points": len(trace.points),
            "on_corridor": "all"
            if not route_lats
            else f"{100 * on_corridor:.0f}%",
            "off_route_tolerance": off_route_m,
        },
    )


def _wrong_way_via_lanes(trace: Trace, lanes, lane_match_m: float) -> DetectedEvent | None:
    """WRONG_WAY verdict if the trace hugs a one-way lane but moves against it.

    Each lane is {"points", "name"}: its authorized direction is first->last.
    Every trace point is matched to its nearest lane; if the trace is
    predominantly on one lane yet its overall bearing opposes the lane's
    authorized bearing by >=120 deg, that is driving the wrong way.

    lane_match_m is the tight radius used to decide a trace points sits ON a
    lane. It must be smaller than the gap between opposing carriageways so a
    rider legally on one lane is not confused with the opposite one-way lane.
    """
    if not lanes:
        return None
    all_lats = {id(ln): [p["lat"] for p in ln["points"]] for ln in lanes}
    all_lons = {id(ln): [p["lon"] for p in ln["points"]] for ln in lanes}
    lane_names = {id(ln): ln.get("name", "") for ln in lanes}

    best_lane, best_frac = None, 0.0
    for ln in lanes:
        lats = all_lats[id(ln)]
        lons = all_lons[id(ln)]
        on = sum(
            1 for p in trace.points
            if distance_to_route_m(p.lat, p.lon, lats, lons) <= lane_match_m
        ) / len(trace.points)
        if on > best_frac:
            best_frac, best_lane = on, ln
    if best_frac < MIN_ON_CORRIDOR_FRAC:
        return None

    lane_bearing = initial_bearing_deg(
        best_lane["points"][0]["lat"], best_lane["points"][0]["lon"],
        best_lane["points"][-1]["lat"], best_lane["points"][-1]["lon"],
    )
    trace_bearing = initial_bearing_deg(
        trace.points[0].lat, trace.points[0].lon,
        trace.points[-1].lat, trace.points[-1].lon,
    )
    delta = angular_delta(lane_bearing, trace_bearing)
    if delta < WRONG_WAY_DELTA_DEG:
        return None

    return DetectedEvent(
        verdict=Verdict.VIOLATION,
        reason=(
            f"driving lane '{lane_names[id(best_lane)]}' in the wrong direction "
            f"({delta:.0f}deg against one-way, {best_frac:.0%} of points on lane)"
        ),
        severity="HIGH",
        state=(
            EventState.CONFIRMED
            if _auto_confirms({"bearing_delta_deg": delta}, ViolationType.WRONG_WAY)
            else EventState.PENDING_REVIEW
        ),
        metrics={
            "lane": lane_names[id(best_lane)],
            "lane_bearing": round(lane_bearing, 1),
            "trace_bearing": round(trace_bearing, 1),
            "bearing_delta_deg": round(delta, 1),
        },
        violation_type=ViolationType.WRONG_WAY,
    )