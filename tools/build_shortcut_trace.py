#!/usr/bin/env python
"""Rebuild illegal_shortcut.json as the origin story:
a rider appears at (22.322702, 73.255615), rides back the wrong way,
cuts under the flyover through the forbidden zone, and exits at
(22.324924, 73.254964).

Exact endpoints are preserved; intermediate points follow the real OSM
carriageway geometry refetched into ajwa_route.json, with modest GPS jitter.

Usage: python tools/build_shortcut_trace.py
"""
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from audit import Trace, TracePoint, audit_trace  # noqa: E402
from audit.geometry import point_in_polygon  # noqa: E402

START = (22.322702, 73.255615)
END = (22.324924, 73.254964)
RIDE_MS = 8.0  # ~29 km/h: a moped threading the wrong way

def haversine_m(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = [math.radians(x) for x in (a[0], a[1], b[0], b[1])]
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(min(1.0, h)))


def interpolate(waypoints, ride_ms=RIDE_MS):
    """Split each leg at ~ride_ms m/s, 1 Hz fixes, tiny lateral GPS jitter."""
    pts, t = [], 0
    rng = random.Random(7)
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        dist = haversine_m(a, b)
        n = max(1, int(round(dist / ride_ms)))
        for k in range(n):
            if i == 0 and k == 0:
                pts.append((START[0], START[1], t))
                t += 1
                continue
            f = k / n
            lat = a[0] + (b[0] - a[0]) * f
            lon = a[1] + (b[1] - a[1]) * f
            lat += rng.uniform(-6e-6, 6e-6)
            lon += rng.uniform(-6e-6, 6e-6)
            pts.append((lat, lon, t))
            t += 1
    pts.append((END[0], END[1], t))
    return pts


def main():
    route = json.load(open(os.path.join(ROOT, "src", "zones", "ajwa_route.json"), encoding="utf-8"))
    zone = json.load(open(os.path.join(ROOT, "src", "zones", "ajwa_bridge.json"), encoding="utf-8"))
    lanes = [json.load(open(os.path.join(ROOT, "src", "zones", "lane_0.json"), encoding="utf-8")),
             json.load(open(os.path.join(ROOT, "src", "zones", "lane_1.json"), encoding="utf-8"))]
    r_lats = [p["lat"] for p in route["points"]]
    r_lons = [p["lon"] for p in route["points"]]
    ring = [(p["lat"], p["lon"]) for p in zone["ring"]]

    # The trip, in order. START is fixed; the first leg weaves back (wrong way)
    # toward the carriageway corridor, the middle legs cut the forbidden box
    # under the flyover, the last leg exits north to END.
    waypoints = [
        START,
        (22.322550, 73.255430),
        (22.322380, 73.254800),
        (22.322530, 73.254250),
        (22.322920, 73.254520),
        (22.322980, 73.254700),
        (22.323000, 73.254880),
        (22.323150, 73.254990),
        (22.323550, 73.254980),
        (22.324100, 73.254980),
        (22.324600, 73.254970),
        END,
    ]

    pts = interpolate(waypoints)
    trace = Trace(points=[TracePoint(lat=la, lon=lo, t=tt) for la, lo, tt in pts])

    # Estimator pass so we can see what falls inside the box before writing.
    deep = [i for i, p in enumerate(trace.points) if point_in_polygon(p.lat, p.lon, ring)]
    import audit
    from audit.detect import _contiguous_runs, _anchored_to_route, distance_to_route_m
    runs = _contiguous_runs(deep)
    print(f"points={len(trace.points)} in_zone={len(deep)} runs={[len(r) for r in runs]}")
    if runs:
        run = max(runs, key=len)
        ok, probs = _anchored_to_route(trace, run, r_lats, r_lons, 60.0)
        before = trace.points[run[0] - 1]
        after = trace.points[run[-1] + 1]
        print(f"max run=[{run[0]}..{run[-1]}] len={len(run)} "
              f"db={distance_to_route_m(before.lat, before.lon, r_lats, r_lons):.0f}m "
              f"da={distance_to_route_m(after.lat, after.lon, r_lats, r_lons):.0f}m "
              f"anchored={ok} {probs}")
    for i, p in enumerate(trace.points):
        if point_in_polygon(p.lat, p.lon, ring):
            print("  deep", i, f"{p.lat:.6f} {p.lon:.6f}")

    event = audit_trace(trace, r_lats, r_lons, [zone], one_way_lanes=lanes)
    print("VERDICT:", event.verdict.value, event.violation_type,
          event.state.value, event.severity, event.reason)
    print("METRICS:", event.metrics)

    if event.verdict.value == "VIOLATION":
        out = {"name": "illegal_shortcut",
               "story": "wrong-way ride cut under the flyover service road",
               "start": list(START), "end": list(END),
               "points": [{"lat": round(la, 6), "lon": round(lo, 6), "t": tt} for la, lo, tt in pts]}
        path = os.path.join(ROOT, "src", "traces", "illegal_shortcut.json")
        json.dump(out, open(path, "w", encoding="utf-8"), indent=2)
        print("WROTE", path, len(out["points"]), "points")


if __name__ == "__main__":
    main()