"""CLI: audit one trace file against zones.

Usage:
    python main.py --trace src/traces/illegal_cut.json --zone src/zones/ajwa_bridge.json
"""

import argparse
import json
import sys
import os

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
    args = parser.parse_args()

    trace = load_trace(args.trace)

    zones = []
    for zpath in args.zone:
        with open(zpath, encoding="utf-8") as f:
            zones.append(json.load(f))

    # Without a legal route, the engine uses the zone-only check.
    event = audit_trace(trace, [], [], zones)

    print(f"verdict:      {event.verdict.value}")
    print(f"reason:       {event.reason}")
    print(f"state:        {event.state.value}")
    print(f"severity:     {event.severity}")
    if event.seg_start >= 0 and event.seg_end >= 0:
        print(f"cut segment:  points [{event.seg_start}..{event.seg_end}] of {len(trace.points)}")


if __name__ == "__main__":
    main()