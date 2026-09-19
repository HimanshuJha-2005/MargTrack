"""Generate truthful MargTrack fixtures from live OpenStreetMap centerlines.

Real junction: Ajwa Road x Vadodara Bypass (NH48) flyover, Vadodara
(bridge at 22.324295, 73.255131).

Geometry is taken from the actual OSM ways at the junction, then re-sampled at
realistic GPS frequency (~8 m per point @ 1 Hz):
  - Ajwa Road is a divided highway: two one-way carriageways ~50 m apart.
  - Legal route  = the north-east carriageway (way toward the junction).
  - One-way lanes = both real carriageways (authorized direction = OSM order).
  - Forbidden zone = the median strip BETWEEN the carriageways, inset by 15 m
    on each side so legal road points are never inside it. Crossing it is a cut.

Run:  python tools/fetch_osm.py
"""

import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZONES = os.path.join(ROOT, "src", "zones")
TRACES = os.path.join(ROOT, "src", "traces")

OVERPASS = "https://overpass-api.de/api/interpreter"
JUNCTION_LAT, JUNCTION_LON = 22.3241, 73.2563  # where the carriageways converge

EARTH = 6371000.0
SPACING_M = 8.0  # GPS samples ~8 m apart, ~1 Hz -> city riding speeds stay plausible


def overpass(query: str) -> dict:
    url = OVERPASS + "?data=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "MargTrack-fixture-gen/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception:
            import time

            time.sleep(5)
    raise RuntimeError("overpass unavailable")


def get_ajwa_carriageways() -> dict:
    """The two one-way Ajwa Road carriageways through the junction, interpolated.

    Returns {"ne": {"pts", "auth"}, "sw": {"pts", "auth"}}:
      - pts: re-sampled centreline (~8 m spacing)
      - auth: (start, end) of the OSM node order = authorized direction
    Only ways whose span is <= ~2.5 km are kept, so a distant same-named
    state-highway way (.e.g the SH_ continuation far NE) is excluded.
    """
    data = overpass(
        "[out:json][timeout:60];way(around:700,22.32375,73.25550)[highway][name='Ajwa Road'];out geom;"
    )
    ways = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("oneway") != "yes" or "geometry" not in el:
            continue
        pts = [(p["lat"], p["lon"]) for p in el["geometry"]]
        if len(pts) >= 2 and _polyline_len_m(pts) <= 2500:
            ways.append(pts)
    if len(ways) < 2:
        raise RuntimeError(f"expected >=2 Ajwa Road carriageways, got {len(ways)}")

    def bearing(a, b):
        import math

        a_lat, a_lon = math.radians(a[0]), math.radians(a[1])
        b_lat, b_lon = math.radians(b[0]), math.radians(b[1])
        dlon = b_lon - a_lon
        x = math.sin(dlon) * math.cos(b_lat)
        y = math.cos(a_lat) * math.sin(b_lat) - math.sin(a_lat) * math.cos(b_lat) * math.cos(dlon)
        return (math.degrees(math.atan2(x, y)) + 360) % 360

    def heads_ne(pts):
        """True if OSM node order runs roughly SW->NE (toward the junction's NE end)."""
        return bearing(pts[0], pts[-1]) < 180

    ne_raw = next(w for w in ways if heads_ne(w))
    sw_raw = next(w for w in ways if not heads_ne(w))

    # Authorized = OSM node order. Return sw rendered in SW->NE order too, for
    # median-zone pairing; lane fixtures keep the OSM (authorized) order.
    return {
        "ne": {"pts": interpolate_pts(ne_raw), "auth": (ne_raw[0], ne_raw[-1])},
        "sw": {
            "pts": interpolate_pts(sw_raw),  # OSM order (authorized): NE->SW
            "render": interpolate_pts(list(reversed(sw_raw))),  # paired, SW->NE
            "auth": (sw_raw[-1], sw_raw[0]),
        },
    }


def _polyline_len_m(pts) -> float:
    import math

    total = 0.0
    for a, b in zip(pts, pts[1:]):
        p1, p2 = math.radians(a[0]), math.radians(b[0])
        dp = math.radians(b[0] - a[0])
        dl = math.radians(b[1] - a[1])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * EARTH * math.asin(math.sqrt(h))
    return total


def haversine(a, b):
    import math

    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH * math.asin(math.sqrt(h))


def bearing_deg(a, b):
    import math

    a_lat, a_lon = math.radians(a[0]), math.radians(a[1])
    b_lat, b_lon = math.radians(b[0]), math.radians(b[1])
    dlon = b_lon - a_lon
    x = math.sin(dlon) * math.cos(b_lat)
    y = math.cos(a_lat) * math.sin(b_lat) - math.sin(a_lat) * math.cos(b_lat) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def linterp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def interpolate_pts(raw) -> list:
    """Re-sample a raw centerline at ~SPACING_M intervals (8 m)."""
    out = [raw[0]]
    for a, b in zip(raw, raw[1:]):
        d = haversine(a, b)
        if d < 1e-9:
            continue
        n = max(1, int(d / SPACING_M))
        for k in range(1, n + 1):
            out.append(linterp(a, b, k / n))
    return out


def write_json(path, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    print(f"wrote {os.path.relpath(path, ROOT)}")


def main() -> None:
    cw = get_ajwa_carriageways()
    toward = cw["ne"]["pts"]                  # SW->NE, authorized = OSM order
    away_rendered = cw["sw"]["render"]        # SW->NE render, for median pairing
    n = min(len(toward), len(away_rendered))
    toward, away_rendered = toward[:n], away_rendered[:n]
    print(
        f"carriageway NE: {len(toward)} pts, SW: {len(cw['sw']['pts'])} pts"
    )

    # ---- legal route: the NE carriageway (real geometry) ----
    write_json(
        os.path.join(ZONES, "ajwa_route.json"),
        {
            "name": "ajwa_route",
            "description": (
                "Legal ride: Ajwa Road north-east carriageway approaching the "
                "NH48 flyover junction. Re-sampled from live OSM centerline."
            ),
            "points": [{"lat": p[0], "lon": p[1]} for p in toward],
        },
    )

    # ---- one-way lanes for wrong-way detection (authorized = OSM order) ----
    write_json(
        os.path.join(ZONES, "lane_0.json"),
        {
            "name": "ajwa_carriageway_NE",
            "points": [{"lat": p[0], "lon": p[1]} for p in toward],
            "authorized": "SW->NE (OSM node order)",
        },
    )
    write_json(
        os.path.join(ZONES, "lane_1.json"),
        {
            "name": "ajwa_carriageway_SW",
            "points": [
                {"lat": p[0], "lon": p[1]} for p in cw["sw"]["pts"]
            ],
            "authorized": "NE->SW (OSM node order)",
        },
    )

    # ---- forbidden zone: under-flyover service road (real OSM way) ----
    # The service road at the junction (22.322771,73.254481)->(22.322952,73.255024)
    # links the two carriageways. Riding it to skip the junction is the cut.
    # Build a small polygon around it (it is genuinely off the legal route).
    svc = [
        (22.322771, 73.254481),
        (22.322833, 73.254598),
        (22.322895, 73.254715),
        (22.322952, 73.255024),
    ]
    ring = []
    for p in svc:
        ring.append((p[0] + 0.0001, p[1] - 0.0001))
    for p in reversed(svc):
        ring.append((p[0] - 0.0001, p[1] + 0.0001))
    write_json(
        os.path.join(ZONES, "ajwa_bridge.json"),
        {
            "name": "ajwa_flyover_junction",
            "description": (
                "Forbidden under-flyover service road linking the two one-way "
                "Ajwa Road carriageways at the NH48 flyover, Vadodara. Drawn "
                "from the real OpenStreetMap service-way geometry."
            ),
            "ring": [{"lat": p[0], "lon": p[1]} for p in ring],
        },
    )

    # ---- trace fixtures (honest re-sampling + realistic 1 Hz timing) ----
    def trace(name, pts):
        write_json(
            os.path.join(TRACES, name),
            {
                "name": name,
                "points": [{"lat": p[0], "lon": p[1], "t": i} for i, p in enumerate(pts)],
            },
        )

    # clean legal: ride the NE carriageway all the way
    trace("clean_legal.json", toward)

    # wrong-way: ride the one-way NE carriageway in the OPPOSITE (illegal) direction
    trace("wrong_way.json", list(reversed(toward)))

    # shortcut: ride the NE carriageway, cut through the service road, come back
    # (the driver jumps the junction via the real under-flyover service link;
    # enough points riding the link that both tiers call it a cut)
    start_i = _nearest_index(toward, svc[0])
    end_i = _nearest_index(toward, svc[-1])
    dip = (
        toward[:start_i]
        + list(reversed(svc)) * 1
        + [linterp(svc[-1], toward[end_i], f) for f in (0.15, 0.35, 0.55)]
        + toward[end_i : end_i + 8]
    )
    trace("illegal_shortcut.json", dip)

    # ambiguous: hard GPS drift far off the road for a stretch (no forbidden zone)
    drift = []
    for i in range(n):
        if 20 <= i <= 50:
            drift.append(linterp(toward[i], away_rendered[i], 6.0))  # ~90 m past the route
        else:
            drift.append(toward[i])
    trace("ambiguous_gps_drift.json", drift)


def _nearest_index(pts, target):
    return min(range(len(pts)), key=lambda i: haversine(pts[i], target))


if __name__ == "__main__":
    main()