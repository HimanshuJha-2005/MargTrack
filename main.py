"""CLI: audit one trace file against zones and an optional legal route.

Usage:
    python main.py --trace src/traces/illegal_under_bridge_cut.json \
        --zone src/zones/ajwa_bridge.json
    python main.py --trace src/traces/illegal_under_bridge_cut.json \
        --zone src/zones/ajwa_bridge.json \
        --route src/traces/clean_legal.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from audit import Trace, TracePoint, audit_trace  # noqa: E402


def load_trace(path: str) -> Trace:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pts = []
    for i, p in enumerate(data.get("points", [])):
        pts.append(TracePoint(lat=p["lat"], lon=p["lon"], t=p.get("t", i)))
    return Trace(points=pts)


def main() -> None:
    parser = argparse.ArgumentParser(description="GPS trace ride audit")
    parser.add_argument("--trace", required=True, help="path to trace JSON")
    parser.add_argument("--zone", nargs="*", default=[], help="zone JSON file(s)")
    parser.add_argument("--route", default=None, help="optional legal-route trace JSON")
    args = parser.parse_args()

    trace = load_trace(args.trace)

    zones = []
    for zpath in args.zone:
        with open(zpath, encoding="utf-8") as f:
            zones.append(json.load(f))

    route_lats, route_lons = [], []
    if args.route:
        route = load_trace(args.route)
        route_lats = [p.lat for p in route.points]
        route_lons = [p.lon for p in route.points]

    event = audit_trace(trace, route_lats, route_lons, zones)

    print(f"verdict:      {event.verdict.value}")
    print(f"reason:       {event.reason}")
    print(f"state:        {event.state.value}")
    print(f"severity:     {event.severity}")
    if event.seg_start >= 0 and event.seg_end >= 0:
        print(f"cut segment:  points [{event.seg_start}..{event.seg_end}] of {len(trace.points)}")
    if event.metrics:
        m = event.metrics
        print(
            f"evidence:     trace {m['trace_len_m']}m vs legal {m['route_len_m']}m | "
            f"shortcut x{m['shortcut_factor']} | bearing delta {m['bearing_delta_deg']}deg"
        )


if __name__ == "__main__":
    main()