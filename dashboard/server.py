"""Local dashboard server for MargTrack.

Serves the Leaflet UI and the same JSON API contract the AWS deployment will
expose via API Gateway:

    GET  /                    -> dashboard/index.html
    GET  /api/fixtures        -> available demo traces / zones / legal route
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
    "clean_legal.json": os.path.join(REPO, "src", "traces", "clean_legal.json"),
    "illegal_under_bridge_cut.json": os.path.join(REPO, "src", "traces", "illegal_under_bridge_cut.json"),
    "ambiguous_gps_drift.json": os.path.join(REPO, "src", "traces", "ambiguous_gps_drift.json"),
    "zone_dip_unanchored.json": os.path.join(REPO, "src", "traces", "zone_dip_unanchored.json"),
    "zone_teleport.json": os.path.join(REPO, "src", "traces", "zone_teleport.json"),
}
ZONES = {"ajwa_bridge.json": os.path.join(REPO, "src", "zones", "ajwa_bridge.json")}
ROUTES = {"clean_legal.json": os.path.join(REPO, "src", "traces", "clean_legal.json")}


def load_trace(path: str) -> Trace:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pts = [TracePoint(lat=p["lat"], lon=p["lon"], t=p.get("t", i)) for i, p in enumerate(data["points"])]
    return Trace(points=pts)


def run_engine(body: dict) -> dict:
    trace = load_trace(TRACES[body["trace"]])
    zone_paths = [ZONES[z] for z in body.get("zones", ["ajwa_bridge.json"])]
    zones = [json.load(open(p, encoding="utf-8")) for p in zone_paths]
    rl = rn = []
    if body.get("route"):
        route = load_trace(ROUTES[body["route"]])
        rl = [p.lat for p in route.points]
        rn = [p.lon for p in route.points]

    event = audit_trace(trace, rl, rn, zones)
    return {
        "verdict": event.verdict.value,
        "reason": event.reason,
        "state": event.state.value,
        "severity": event.severity,
        "seg_start": event.seg_start,
        "seg_end": event.seg_end,
        "metrics": event.metrics,
        "points": [{"lat": p.lat, "lon": p.lon, "t": p.t} for p in trace.points],
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
            return self._send_trace(self.path.rsplit("/", 1)[1])
        if self.path.startswith("/api/zone/"):
            return self._send_zone(self.path.rsplit("/", 1)[1])
        if self.path == "/api/fixtures":
            return self._send(200, {"traces": list(TRACES), "zones": list(ZONES), "routes": list(ROUTES)})
        self._send(404, {"error": "not found"})

    def _send_trace(self, name):
        if name not in TRACES:
            return self._send(404, {"error": "unknown trace"})
        return self._send(200, json.load(open(TRACES[name], encoding="utf-8")))

    def _send_zone(self, name):
        if name not in ZONES:
            return self._send(404, {"error": "unknown zone"})
        return self._send(200, json.load(open(ZONES[name], encoding="utf-8")))

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
                zones = [json.load(open(ZONES[z], encoding="utf-8")) for z in body.get("zones", ["ajwa_bridge.json"])]
                rl = rn = []
                if body.get("route"):
                    route = load_trace(ROUTES[body["route"]])
                    rl = [p.lat for p in route.points]
                    rn = [p.lon for p in route.points]
                return self._send(200, review_event(trace, rl, rn, zones))
            self._send(404, {"error": "unknown endpoint"})
        except KeyError as exc:
            self._send(400, {"error": f"missing key: {exc}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"MargTrack dashboard: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()