"""Local dashboard server for MargTrack.

Serves the MapLibre GL UI and the same JSON API contract the AWS deployment
will expose via API Gateway:

    GET  /                    -> dashboard/index.html
    GET  /vendor/<file>       -> locally-vendored MapLibre GL
    GET  /tiles/<z>/<x>/<y>.png -> proxied raster basemap tiles (same-origin)
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
import re
import sys
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(REPO, "src"))

from audit import Trace, TracePoint, audit_trace  # noqa: E402
from agent.review_agent import review_event  # noqa: E402
from audit import demerit  # noqa: E402
from audit.policy import evaluate as cedar_evaluate  # noqa: E402

TRACES = {
    "clean_legal": os.path.join(REPO, "src", "traces", "clean_legal.json"),
    "wrong_way": os.path.join(REPO, "src", "traces", "wrong_way.json"),
    "illegal_shortcut": os.path.join(REPO, "src", "traces", "illegal_shortcut.json"),
    "ambiguous_gps_drift": os.path.join(REPO, "src", "traces", "ambiguous_gps_drift.json"),
}
ZONES = {"ajwa_junction": os.path.join(REPO, "src", "zones", "ajwa_bridge.json")}
ROUTES = {
    "ajwa_route": os.path.join(REPO, "src", "zones", "ajwa_route.json"),
    "maps_fair_route": os.path.join(REPO, "src", "zones", "maps_fair_route.json"),
    "wrong_way_route": os.path.join(REPO, "src", "zones", "wrong_way_route.json"),
}
# The comparisons the demo cares about: which legal route (green line on the
# map) each trace is audited against. The SHORTCUT green line is the ~430m
# maps-fair loop; the WRONG_WAY green line is what the driver should have
# followed (straight north, then left).
TRACE_ROUTES = {
    "clean_legal": "ajwa_route",
    "wrong_way": "wrong_way_route",
    "illegal_shortcut": "maps_fair_route",
    "ambiguous_gps_drift": "ajwa_route",
}
LANES = {
    "ajwa_carriageway_NE": os.path.join(REPO, "src", "zones", "lane_0.json"),
    "ajwa_carriageway_SW": os.path.join(REPO, "src", "zones", "lane_1.json"),
}

LABELS = {
    "clean_legal": "Clean — legal ride",
    "wrong_way": "Wrong-way — drove on the one-way carriageway backwards",
    "illegal_shortcut": "NH48 Flyover Deck — Illegal Service Road Cut",
    "ambiguous_gps_drift": "Ambiguous — GPS drift off the corridor",
    "ajwa_junction": "Forbidden under-flyover wedge (Ajwa Rd at-grade crossing excluded)",
    "ajwa_route": "Legal route — west bypass carriageway (strict, S→N)",
    "maps_fair_route": "Legal route shown in the SHORTCUT scenario — ~430m loop on real roads (connectors + Ajwa Rd at-grade, no one-way violation)",
    "wrong_way_route": "Legal route shown in the WRONG_WAY scenario — what the driver should have followed (straight north, then left)",
}

TRACE_ORDER = ["clean_legal", "wrong_way", "illegal_shortcut", "ambiguous_gps_drift"]

HUMAN_REASONS = {
    ("VIOLATION", "ZONE_CUT"): "Unauthorized cut across the one-way median under the flyover deck. Head-on hazard.",
    ("VIOLATION", "WRONG_WAY"): "Rode against the one-way bypass carriageway direction. Head-on hazard.",
    ("AMBIGUOUS", ""): "Trace left the legal corridor - possible GPS drift, needs a human check.",
    ("CLEAN", ""): "Ride stayed on the legal corridor.",
}

TILE_RE = re.compile(r"^/tiles/(\d+)/(\d+)/(\d+)\.png$")

TILE_CACHE = OrderedDict()
TILE_CACHE_LIMIT = 600
TILE_UPSTREAMS = (
    "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
)
TILE_HEADERS = {"User-Agent": "MargTrackDashboard/1.0 (hackathon demo)"}


def proxy_tile(z, x, y):
    key = f"{z}/{x}/{y}"
    if key in TILE_CACHE:
        TILE_CACHE.move_to_end(key)
        return TILE_CACHE[key]
    if len(TILE_CACHE) >= TILE_CACHE_LIMIT:
        TILE_CACHE.popitem(last=False)
    body = None
    for upstream in TILE_UPSTREAMS:
        try:
            with urllib.request.urlopen(
                urllib.request.Request(upstream.format(z=z, x=x, y=y), headers=TILE_HEADERS),
                timeout=20,
            ) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    continue
                body = resp.read()
                break
        except Exception:
            continue
    if body is None:
        return None
    TILE_CACHE[key] = body
    return body


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
    trace = load_trace_input(body)
    zones = zone_data(body.get("zones", ["ajwa_junction"]))
    lanes = one_way_lanes(body.get("lanes"))
    rl, rn = [], []
    route = body.get("route") or TRACE_ROUTES.get(body.get("trace", "upload"))
    if route:
        rl, rn = route_latlons(route)
    if not rl and not rn:  # uploaded custom trace -> audit against the maps-fair loop
        rl, rn = route_latlons("maps_fair_route")

    event = audit_trace(trace, rl, rn, zones, one_way_lanes=lanes)
    cut = []
    if event.seg_start >= 0 and event.seg_end >= 0:
        cut = [{"lat": p.lat, "lon": p.lon} for p in trace.points[event.seg_start : event.seg_end + 1]]
    return build_audit_response(body, trace, event, rl, rn, cut)


SESSION = {"score": demerit.BASE_SCORE, "unresolved": 0, "history": []}


def reset_session() -> dict:
    """Clear the in-memory driver ledger back to a fresh one."""
    SESSION["score"] = demerit.BASE_SCORE
    SESSION["unresolved"] = 0
    SESSION["history"] = []
    return {"score": SESSION["score"], "unresolved_violations": SESSION["unresolved"]}


def session_snapshot() -> dict:
    return {"score": SESSION["score"], "unresolved_violations": SESSION["unresolved"]}


def load_trace_input(body: dict) -> Trace:
    """Fixture by name, or inline {lat, lon, t} points from a custom upload."""
    if body.get("points"):
        pts = [TracePoint(lat=p["lat"], lon=p["lon"], t=p.get("t", i))
               for i, p in enumerate(body["points"])]
        return Trace(points=pts)
    return load_trace(TRACES[body["trace"]])


def human_reason(event) -> str:
    """Plain-English description a fleet supervisor reads, not engine jargon."""
    return HUMAN_REASONS.get((event.verdict.value, event.violation_type or ""), event.reason)


def fmt_duration(mins: float) -> str:
    """Human duration: seconds under a minute, whole minutes above."""
    if mins < 1.0:
        return "~{} s".format(max(1, round(mins * 60)))
    return "~{} min".format(max(1, round(mins)))


def ops_metrics(trace, route_lats, route_lons, event, ride_ms: float = 8.3) -> list[dict]:
    """Human operations metrics: corridor length, ride distance, time cheat.

    Time-cheated is only reported for established violations (VIOLATION).
    Ambiguous/clean rides show "no cheat detected" - never imply guilt the
    audit did not prove.
    """
    import math as _math

    def dist_km(poly_lats, poly_lons):
        R = 6371.0
        ring = [(la, lo) for la, lo in zip(poly_lats, poly_lons) if la is not None and lo is not None]
        if len(ring) < 2:
            return 0.0
        total = 0.0
        for (la1, lo1), (la2, lo2) in zip(ring, ring[1:]):
            p, q, r, s = map(_math.radians, (la1, lo1, la2, lo2))
            h = _math.sin((p - r) / 2) ** 2 + _math.cos(p) * _math.cos(r) * _math.sin((q - s) / 2) ** 2
            total += 2 * R * _math.asin(_math.sqrt(min(1.0, h)))
        return total

    ride_pts = [(p.lat, p.lon) for p in trace.points]
    ride_km = dist_km([la for la, _ in ride_pts], [lo for _, lo in ride_pts])
    route_km = dist_km(route_lats, route_lons)
    ride_min = ride_km / (ride_ms * 60 / 1000) if ride_km else 0.0
    route_min = route_km / (ride_ms * 60 / 1000) if route_km else 0.0
    minutes_saved = max(0.0, route_min - ride_min) if event.verdict.value == "VIOLATION" else 0.0

    rows = [
        {"label": "Legal corridor", "value": f"{route_km:.1f} km ({fmt_duration(route_min)})"},
        {"label": "Ride taken", "value": f"{ride_km:.2f} km ({fmt_duration(ride_min)})"},
    ]
    if event.verdict.value == "VIOLATION" and minutes_saved:
        rows.append({"label": "Time cheated", "value": "~{} s saved".format(max(1, round(minutes_saved * 60)))})
    else:
        rows.append({"label": "Time cheated", "value": "no cheat detected"})
    return rows


def build_audit_response(body, trace, event, rl, rn, cut) -> dict:
    """Audit one ride against the driver's live session ledger."""
    score = demerit.apply_event(SESSION["score"], event)
    SESSION["score"], SESSION["unresolved"] = score["safety_score"], score["unresolved_violations"]
    SESSION["history"].append({"trace": body.get("trace", "upload"), "verdict": event.verdict.value})
    gate = cedar_evaluate(score["safety_score"], score["unresolved_violations"])
    status = ("ON HOLD" if gate["decision"] == "DENIED" else score["status"])
    return {
        "verdict": event.verdict.value,
        "reason": event.reason,
        "human_reason": human_reason(event),
        "state": event.state.value,
        "severity": event.severity,
        "violation_type": event.violation_type,
        "seg_start": event.seg_start,
        "seg_end": event.seg_end,
        "metrics": event.metrics,
        "ops_metrics": ops_metrics(trace, rl, rn, event),
        "safety": score,
        "trip_status": status,
        "dispatch": gate,
        "session": session_snapshot(),
        "points": [{"lat": p.lat, "lon": p.lon, "t": p.t} for p in trace.points],
        "cut": cut,
        "trace_name": body.get("trace", "upload"),
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
        if self.path.startswith("/vendor/"):
            return self._serve_file(os.path.join(ROOT, self.path.lstrip("/")), {
                ".js": "application/javascript",
                ".css": "text/css",
            }.get(os.path.splitext(self.path)[1], "application/octet-stream"))
        tile_match = TILE_RE.match(self.path)
        if tile_match:
            z, x, y = (int(g) for g in tile_match.groups())
            body = proxy_tile(z, x, y)
            if body is None:
                return self._send(502, {"error": "upstream tile unreachable"})
            return self._send(200, body, "image/png")
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
                "trace_routes": TRACE_ROUTES,
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
                trace = load_trace_input(body)
                zones = zone_data(body.get("zones", ["ajwa_junction"]))
                lanes = one_way_lanes(body.get("lanes"))
                rl, rn = [], []
                route = body.get("route") or TRACE_ROUTES.get(body.get("trace", "upload"))
                if route:
                    rl, rn = route_latlons(route)
                if not rl and not rn:
                    rl, rn = route_latlons("maps_fair_route")
                out = review_event(trace, rl, rn, zones, one_way_lanes=lanes, previous_score=SESSION["score"])
                if out.get("after_review"):
                    ar = out["after_review"]
                    SESSION["score"], SESSION["unresolved"] = ar["safety_score"], ar["unresolved_violations"]
                    out["after_dispatch"] = cedar_evaluate(ar["safety_score"], ar["unresolved_violations"])
                    out["session"] = session_snapshot()
                return self._send(200, out)
            if self.path == "/api/reset":
                return self._send(200, reset_session())
            self._send(404, {"error": "unknown endpoint"})
        except KeyError as exc:
            self._send(400, {"error": f"missing key: {exc}"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"MargTrack dashboard: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()