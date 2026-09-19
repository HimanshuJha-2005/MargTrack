"""Local dashboard server for MargTrack.

Serves the MapLibre GL UI and the same JSON API contract the AWS deployment
will expose via API Gateway:

    GET  /                    -> dashboard/index.html
    GET  /api/fixtures        -> available traces / zones / routes / lanes
    GET  /api/trace/<name>    -> raw trace fixture
    GET  /api/route/<name>    -> raw legal-route fixture
    GET  /api/lane/<name>     -> raw one-way lane fixture
    GET  /api/zone/<name>     -> raw forbidden-zone fixture
    POST /api/audit           -> run the engine, return the DetectedEvent
    POST /api/review          -> run the engine + Tier-3 Strands agent

Run:  python dashboard/server.py
Then: open http://localhost:8000
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(REPO, "src"))

from audit import Trace, TracePoint, audit_trace  # noqa: E402
from agent.review_agent import review_event  # noqa: E402

TRACES = {
    "clean_legal": os.path.join(REPO, "src", "traces", "clean_legal.json"),
    "wrong_way": os.path.join(REPO, "src", "traces", "wrong_way.json"),
    "illegal_shortcut": os.path.join(REPO, "src", "traces", "illegal_shortcut.json"),
    "ambiguous_gps_drift": os.path.join(REPO, "src", "traces", "ambiguous_gps_drift.json"),
}
ZONES = {"ajwa_junction": os.path.join(REPO, "src", "zones", "ajwa_bridge.json")}
ROUTES = {"ajwa_route": os.path.join(REPO, "src", "zones", "ajwa_route.json")}
LANES = {
    "ajwa_carriageway_NE": os.path.join(REPO, "src", "zones", "lane_0.json"),
    "ajwa_carriageway_SW": os.path.join(REPO, "src", "zones", "lane_1.json"),
}

LABELS = {
    "clean_legal": "Clean — legal ride (NE carriageway)",
    "wrong_way": "Wrong-way — riding the one-way NE carriageway backwards",
    "illegal_shortcut": "Shortcut — cutting through the under-flyover service road",
    "ambiguous_gps_drift": "Ambiguous — GPS drifts hard off the road",
    "ajwa_junction": "Forbidden under-flyover junction box (real OSM)",
    "ajwa_route": "Legal route — Ajwa Rd NE carriageway",
}

TRACE_ORDER = ["clean_legal", "wrong_way", "illegal_shortcut", "ambiguous_gps_drift"]


def load_trace(path: str) -> Trace:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pts = [TracePoint(lat=p["lat"], lon=p["lon"], t=p.get("t", i)) for i, p in enumerate(data["points"])]
    return Trace(points=pts)


def zone_data(names):
    paths = [ZONES[n] for n in names]
    return [json.load(open(p, encoding="utf-8")) for p in paths]


def route_latlons(name):
    with open(ROUTES[name], encoding="utf-8") as f:
        data = json.load(f)
    return [p["lat"] for p in data["points"]], [p["lon"] for p in data["points"]]


def one_way_lanes(names=None):
    names = names or ["ajwa_carriageway_NE", "ajwa_carriageway_SW"]
    return [json.load(open(LANES[n], encoding="utf-8")) for n in names if n in LANES]


def run_engine(body: dict) -> dict:
    trace = load_trace(TRACES[body["trace"]])
    zones = zone_data(body.get("zones", ["ajwa_junction"]))
    lanes = one_way_lanes(body.get("lanes"))
    rl, rn = [], []
    if body.get("route"):
        rl, rn = route_latlons(body["route"])

    event = audit_trace(trace, rl, rn, zones, one_way_lanes=lanes)
    cut = []
    if event.seg_start >= 0 and event.seg_end >= 0:
        cut = [{"lat": p.lat, "lon": p.lon} for p in trace.points[event.seg_start : event.seg_end + 1]]
    return {
        "verdict": event.verdict.value,
        "reason": event.reason,
        "state": event.state.value,
        "severity": event.severity,
        "violation_type": event.violation_type,
        "seg_start": event.seg_start,
        "seg_end": event.seg_end,
        "metrics": event.metrics,
        "points": [{"lat": p.lat, "lon": p.lon, "t": p.t} for p in trace.points],
        "cut": cut,
        "trace_name": body["trace"],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._serve_file(os.path.join(ROOT, "index.html"), "text/html")
        if self.path == "/app.js":
            return self._serve_file(os.path.join(ROOT, "app.js"), "application/javascript")
        if self.path == "/style.css":
            return self._serve_file(os.path.join(ROOT, "style.css"), "text/css")
        if self.path.startswith("/api/trace/"):
            return self._send_fixture(TRACES, self.path.rsplit("/", 1)[1])
        if self.path.startswith("/api/zone/"):
            return self._send_fixture(ZONES, self.path.rsplit("/", 1)[1])
        if self.path.startswith("/api/route/"):
            return self._send_fixture(ROUTES, self.path.rsplit("/", 1)[1])
        if self.path.startswith("/api/lane/"):
            return self._send_fixture(LANES, self.path.rsplit("/", 1)[1])
        if self.path == "/api/fixtures":
            return self._send(200, {
                "traces": TRACE_ORDER,
                "trace_labels": {k: LABELS.get(k, k) for k in TRACE_ORDER},
                "zones": list(ZONES),
                "routes": list(ROUTES),
                "lanes": list(LANES),
                "labels": LABELS,
            })
        self._send(404, {"error": "not found"})

    def _send_fixture(self, table, name):
        if name not in table:
            return self._send(404, {"error": f"unknown: {name}"})
        with open(table[name], encoding="utf-8") as f:
            return self._send(200, json.load(f))

    def _serve_file(self, path, ctype):
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        try:
            body = self._read_json()
            if self.path == "/api/audit":
                return self._send(200, run_engine(body))
            if self.path == "/api/review":
                trace = load_trace(TRACES[body["trace"]])
                zones = zone_data(body.get("zones", ["ajwa_junction"]))
                lanes = one_way_lanes(body.get("lanes"))
                rl, rn = [], []
                if body.get("route"):
                    rl, rn = route_latlons(body["route"])
                return self._send(200, review_event(trace, rl, rn, zones, one_way_lanes=lanes))
            self._send(404, {"error": "unknown endpoint"})
        except KeyError as exc:
            self._send(400, {"error": f"missing key: {exc}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"MargTrack dashboard: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()