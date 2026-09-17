import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audit import Trace, TracePoint, audit_trace  # noqa: E402

TRACES = os.path.join(os.path.dirname(__file__), "..", "src", "traces")
ZONES = os.path.join(os.path.dirname(__file__), "..", "src", "zones")


def load(path: str) -> Trace:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pts = [TracePoint(lat=p["lat"], lon=p["lon"], t=p.get("t", i)) for i, p in enumerate(data["points"])]
    return Trace(points=pts)


def zones() -> list:
    with open(os.path.join(ZONES, "ajwa_bridge.json"), encoding="utf-8") as f:
        return [json.load(f)]


class DetectTests(unittest.TestCase):
    def test_clean_trace_is_clean(self):
        trace = load(os.path.join(TRACES, "clean_legal.json"))
        event = audit_trace(trace, [], [], zones())
        self.assertEqual(event.verdict.value, "CLEAN")

    def test_illegal_cut_is_flagged(self):
        trace = load(os.path.join(TRACES, "illegal_under_bridge_cut.json"))
        event = audit_trace(trace, [], [], zones())
        self.assertEqual(event.verdict.value, "VIOLATION")
        self.assertGreaterEqual(event.seg_end, event.seg_start)
        self.assertGreaterEqual(event.seg_start, 0)

    def test_ambiguous_is_not_clean_or_violation(self):
        # The ambiguous fixture drifts off the legal corridor without entering a zone.
        legal = load(os.path.join(TRACES, "clean_legal.json"))
        route_lats = [p.lat for p in legal.points]
        route_lons = [p.lon for p in legal.points]
        trace = load(os.path.join(TRACES, "ambiguous_gps_drift.json"))
        event = audit_trace(trace, route_lats, route_lons, zones())
        self.assertEqual(event.verdict.value, "AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()