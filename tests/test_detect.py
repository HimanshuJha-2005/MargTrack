import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audit import Trace, TracePoint, audit_trace  # noqa: E402
from audit.geometry import point_in_polygon  # noqa: E402

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


def route() -> tuple:
    tr = load(os.path.join(TRACES, "clean_legal.json"))
    return ([p.lat for p in tr.points], [p.lon for p in tr.points])


def lanes() -> list:
    out = []
    for name in ("lane_0.json", "lane_1.json"):
        with open(os.path.join(ZONES, name), encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def in_zone_indices(trace: Trace) -> list:
    ring = [(pt["lat"], pt["lon"]) for pt in zones()[0]["ring"]]
    return [i for i, p in enumerate(trace.points) if point_in_polygon(p.lat, p.lon, ring)]


class DetectTests(unittest.TestCase):
    def test_clean_trace_is_clean(self):
        trace = load(os.path.join(TRACES, "clean_legal.json"))
        r_lats, r_lons = route()
        event = audit_trace(trace, r_lats, r_lons, zones(), one_way_lanes=lanes())
        self.assertEqual(event.verdict.value, "CLEAN")
        self.assertEqual(event.state.value, "CONFIRMED")

    def test_illegal_cut_is_flagged_as_zone_cut(self):
        r_lats, r_lons = route()
        trace = load(os.path.join(TRACES, "illegal_shortcut.json"))
        event = audit_trace(trace, r_lats, r_lons, zones(), one_way_lanes=lanes())
        self.assertEqual(event.verdict.value, "VIOLATION")
        self.assertEqual(event.violation_type.value, "ZONE_CUT")
        self.assertGreaterEqual(event.seg_end, event.seg_start)
        self.assertGreaterEqual(event.seg_start, 0)
        self.assertEqual(event.state.value, "PENDING_REVIEW")

    def test_wrong_way_is_flagged(self):
        r_lats, r_lons = route()
        trace = load(os.path.join(TRACES, "wrong_way.json"))
        event = audit_trace(trace, r_lats, r_lons, zones(), one_way_lanes=lanes())
        self.assertEqual(event.verdict.value, "VIOLATION")
        self.assertEqual(event.violation_type.value, "WRONG_WAY")
        self.assertEqual(event.state.value, "CONFIRMED")
        self.assertEqual(event.severity, "HIGH")
        self.assertGreaterEqual(event.metrics["bearing_delta_deg"], 160)

    def test_ambiguous_is_not_clean_or_violation(self):
        r_lats, r_lons = route()
        trace = load(os.path.join(TRACES, "ambiguous_gps_drift.json"))
        event = audit_trace(trace, r_lats, r_lons, zones(), one_way_lanes=lanes())
        self.assertEqual(event.verdict.value, "AMBIGUOUS")
        self.assertEqual(event.state.value, "PENDING_REVIEW")

    def test_zone_dip_without_route_anchors_is_ambiguous(self):
        # Only the in-zone points, no legal-road neighbours on either side:
        # a floating GPS path, so NOT auto-flagged as a rider's violation.
        r_lats, r_lons = route()
        cut = load(os.path.join(TRACES, "illegal_shortcut.json"))
        zidx = in_zone_indices(cut)
        lo, hi = min(zidx), max(zidx)
        dip = Trace(points=cut.points[lo:hi + 1])  # the service-road crossing alone
        event = audit_trace(dip, r_lats, r_lons, zones(), one_way_lanes=lanes())
        self.assertEqual(event.verdict.value, "AMBIGUOUS")
        self.assertEqual(event.state.value, "PENDING_REVIEW")

    def test_zone_teleport_speed_is_ambiguous(self):
        # Identical geometry to the real cut, but one hop is a GPS blip at
        # impossible speed: noise, not a rider.
        r_lats, r_lons = route()
        cut = load(os.path.join(TRACES, "illegal_shortcut.json"))
        pts = copy.deepcopy(cut.points)
        zidx = in_zone_indices(cut)
        mid_hot = zidx[len(zidx) // 2]
        pts[mid_hot].t = pts[mid_hot - 1].t + 0.05  # ~600 m/s hop
        event = audit_trace(Trace(points=pts), r_lats, r_lons, zones(), one_way_lanes=lanes())
        self.assertEqual(event.verdict.value, "AMBIGUOUS")
        self.assertEqual(event.state.value, "PENDING_REVIEW")


if __name__ == "__main__":
    unittest.main()