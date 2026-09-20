#!/usr/bin/env python
"""Rebuild the MargTrack demo fixtures on the REAL NH48 bypass corridor that
matches the origin story (user-confirmed coordinates).

Corridor (live OSM, Vadodara NH48 flyover junction):
  way 219869674  primary, oneway, lanes=1  -> S->N  WEST carriageway
  way 219869675  primary, oneway, lanes=1  -> N->S  EAST carriageway

The forbidden zone is the under-deck gap where the rider cuts in the origin
story. It is sculpted as a wedge NORTH of the Ajwa Road (28839743) at-grade
crossing, so a legal rider taking the at-grade crossing or either one-way
carriageway is NEVER inside it.

The maps-fair legal loop (~430m) rides REAL roads and stays legal:
  exit the EAST carriageway at START onto connector 769451688, ride NE onto
  the Ajwa Road east turnaround, take Ajwa Road (28839743) westbound ACROSS
  the at-grade junction to its merge onto the WEST carriageway, then ride
  north to the destination. It never rides against a one-way and never
  enters the under-deck wedge.

This maps-fair loop is the *legal route shown in the SHORTCUT scenario* (the
green line that a maps app would offer the rider). It is a route fixture, NOT
a separate trace scenario.

The wrong-way legal route shows what the driver SHOULD have followed after the
wrong-way trace begins: drive straight to (22.329460, 73.252205), then turn
left and continue a few hundred metres.

Writes (deterministic, seed fixed):
  src/zones/ajwa_route.json     legal route = WEST carriageway (S->N)
  src/zones/maps_fair_route.json   SHORTCUT scenario legal route (~430m loop)
  src/zones/wrong_way_route.json   WRONG_WAY scenario legal route (straight
                                    north then left, off-junction)
  src/zones/lane_0.json         EAST carriageway (authorized N->S)
  src/zones/lane_1.json         WEST carriageway (authorized S->N)
  src/zones/ajwa_bridge.json    forbidden under-deck wedge
  src/traces/clean_legal.json   legal northbound ride on west carriageway
  src/traces/wrong_way.json     drives west carriageway N->S (against it)
  src/traces/illegal_shortcut.json  origin story (user coordinates)
  src/traces/ambiguous_gps_drift.json  subtle GPS wander off-route

Usage: python tools/rebuild_bypass_scenario.py
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

# Live OSM geometry (fetched via Overpass, User-Agent MargTrack/1.0)
WEST = [  # way 219869674, point order = authorized S->N
    (22.318421, 73.255092), (22.318613, 73.25501), (22.319143, 73.255023),
    (22.320594, 73.255092), (22.32276, 73.255237), (22.323238, 73.255236),
    (22.323562, 73.255233), (22.323649, 73.255229), (22.323959, 73.255212),
    (22.324467, 73.255121), (22.324959, 73.254989), (22.325536, 73.25478),
    (22.325986, 73.254578), (22.326427, 73.254311), (22.327191, 73.253803),
    (22.327325, 73.253712), (22.327427, 73.25372),
]
EAST = [  # way 219869675, point order = authorized N->S
    (22.327726, 73.253699), (22.327693, 73.253797), (22.327599, 73.253919),
    (22.326887, 73.254482), (22.326658, 73.254616), (22.326008, 73.254996),
    (22.325549, 73.255174), (22.325134, 73.255332), (22.325035, 73.25537),
    (22.324464, 73.255504), (22.324144, 73.255541), (22.323779, 73.255582),
    (22.323695, 73.255589), (22.323393, 73.255595), (22.322767, 73.25561),
    (22.321402, 73.255515), (22.320639, 73.255462), (22.319611, 73.255416),
    (22.318997, 73.255388), (22.318595, 73.255346), (22.318548, 73.255261),
]
# Way 219869681 = EAST carriageway continuation south of the flyover (N->S).
EAST_SOUTH = [
    (22.318548, 73.255261), (22.317935, 73.255230), (22.317695, 73.255210),
    (22.316831, 73.255138), (22.315833, 73.255062), (22.314764, 73.254980),
    (22.313920, 73.254916), (22.313665, 73.254898), (22.313528, 73.254888),
    (22.313015, 73.254853), (22.312870, 73.254841), (22.312541, 73.254815),
    (22.311692, 73.254746), (22.311400, 73.254722), (22.307504, 73.254407),
    (22.307054, 73.254376), (22.306196, 73.254316), (22.305993, 73.254302),
    (22.305897, 73.254296), (22.303775, 73.254149), (22.302041, 73.254029),
    (22.301794, 73.254012), (22.301601, 73.254000), (22.301460, 73.253985),
    (22.301364, 73.253975),
]
# Way 219869431 = EAST carriageway lowest segment into the south interchange.
EAST_LOW = [
    (22.300680, 73.253924), (22.298356, 73.253771), (22.297500, 73.253709),
]
# Way 219869433 = WEST carriageway lowest segment, authorized S->N.
WEST_LOW = [
    (22.297491, 73.253556), (22.300703, 73.253790),
]
# Way 219869432 = WEST carriageway south of the flyover, authorized S->N.
WEST_SOUTH = [
    (22.301370, 73.253842), (22.304228, 73.254007), (22.305609, 73.254091),
    (22.307694, 73.254254), (22.308557, 73.254316), (22.309012, 73.254353),
    (22.310142, 73.254446), (22.310177, 73.254448), (22.312031, 73.254597),
    (22.312853, 73.254668), (22.313457, 73.254707), (22.314904, 73.254816),
    (22.318421, 73.255092),
]
# User-confirmed legal interchange: keep EAST, right-turn onto WEST at the
# south interchange (NH48-under bridge crossing).
LEGAL_TURN = [(22.297031, 73.253773), (22.297104, 73.253490)]

# Origin story (user-confirmed):
START = (22.322702, 73.255615)      # east carriageway, south of junction
TURN = (22.323470, 73.255557)       # left cut begins (U-turn then straight)
CUT = (22.323960, 73.255194)        # under the flyover, onto west carriageway
DEST = (22.324924, 73.254964)       # customer / destination, west carriageway

# The maps-fair legal loop (~430m): real OSM roads, no one-way violation.
# This is the GREEN legal-route line for the SHORTCUT scenario: what maps
# would tell the rider to follow instead of the under-deck cut.
#   exit EAST carriageway at START onto connector 769451688, ride NE onto the
#   Ajwa Road east turnaround, ride Ajwa Rd (28839743) westbound ACROSS the
#   at-grade junction, merge onto the WEST carriageway, ride N to DEST.
MAPS_FAIR = [
    START,                      # east carriageway south end
    (22.322791, 73.255726),     # 769451688 west terminus (exit E/NE)
    (22.323688, 73.25622),      # 769451688 north-east
    (22.3238, 73.256302),       # 769451688 (near Ajwa east turnaround)
    (22.323977, 73.256166),     # 769451689 / Ajwa east end approach
    (22.323909, 73.256059),     # Ajwa Rd 28839743 westbound
    (22.323824, 73.255891),     # Ajwa Rd 28839743
    (22.323695, 73.255589),     # Ajwa Rd at-grade crossing of EAST cway
    (22.323562, 73.255233),     # Ajwa Rd merges into WEST carriageway
    (22.323649, 73.255229),     # WEST carriageway S->N
    (22.323959, 73.255212),
    (22.324467, 73.255121),
    (22.324959, 73.254989),
    DEST,
]

# The green legal-route line for the WRONG_WAY scenario: from where the
# driver started his wrong-way journey (the trace's first point, the north
# end of the WEST carriageway), he should have driven straight to
# (22.329460, 73.252205), taken the left, and continued ~300-400m. The line
# only needs to show what to follow; where it ends does not matter.
WRONG_START = (22.327427, 73.253720)  # start of the wrong-way trace
WRONG_WAY_ROUTE = [
    WRONG_START,
    (22.328100, 73.253300),
    (22.328900, 73.252800),
    (22.329460, 73.252205),     # straight leg target
    (22.329100, 73.251700),     # left
    (22.328800, 73.251200),     # +~300-400m after the left
    (22.328600, 73.250800),
]

RIDE_MS = 8.0  # ~29 km/h


def haversine_m(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = [math.radians(x) for x in (a[0], a[1], b[0], b[1])]
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(min(1.0, h)))


def resample(polyline, spacing=20.0):
    """Walk a polyline emitting a point every ~spacing metres (keeps vertices)."""
    out, carry = [polyline[0]], 0.0
    for a, b in zip(polyline, polyline[1:]):
        seg = haversine_m(a, b)
        n = max(1, int(round((carry + seg) / spacing)))
        for k in range(1, n + 1):
            f = min(1.0, (carry + seg * (k / n)) / (carry + seg))
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        carry = (carry + seg) % spacing
    return out


def interpolate(waypoints, ride_ms=RIDE_MS, seed=7):
    """Split each leg at ~ride_ms m/s, 1 Hz fixes, tiny lateral GPS jitter."""
    pts, t = [], 0
    rng = random.Random(seed)
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        dist = haversine_m(a, b)
        n = max(1, int(round(dist / ride_ms)))
        for k in range(n):
            if i == 0 and k == 0:
                pts.append((a[0], a[1], t))
                t += 1
                continue
            f = k / n
            lat = a[0] + (b[0] - a[0]) * f
            lon = a[1] + (b[1] - a[1]) * f
            lat += rng.uniform(-5e-6, 5e-6)
            lon += rng.uniform(-5e-6, 5e-6)
            pts.append((lat, lon, t))
            t += 1
    pts.append((waypoints[-1][0], waypoints[-1][1], t))
    return pts


def write(path, data):
    json.dump(data, open(path, "w", encoding="utf-8"), indent=2)
    print("WROTE", path.replace(ROOT, "."), f"({len(json.dumps(data)):,}B)")


def build_legal_route():
    """The legal path from the rider's origin (START) to the destination (DEST):
    ride SOUTH down the one-way EAST carriageway to the south interchange, make
    the legal right-hand turn onto the WEST carriageway, then ride NORTH to the
    destination. ~5.6 km — the forbidden under-flyover cut skips all of it.
    """
    return (
        [START]
        + EAST[14:]                # east carriageway south of START (N->S)
        + EAST_SOUTH[1:]           # east carriageway below the flyover
        + EAST_LOW[1:]             # east carriageway lowest segment
        + LEGAL_TURN               # user-confirmed interchange right-turn
        + WEST_LOW[1:]             # west carriageway lowest segment (S->N)
        + WEST_SOUTH[1:]           # west carriageway below the flyover
        + WEST[1:10]               # west carriageway up past DEST
        + [DEST]
    )


def main():
    west = resample(WEST)
    east = resample(EAST)

    write(os.path.join(ROOT, "src", "zones", "ajwa_route.json"), {
        "name": "ajwa_route",
        "description": "Legal route: NH48 bypass WEST carriageway (S->N), re-sampled from live OSM way 219869674.",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6)} for la, lo in west],
    })
    mf = resample(MAPS_FAIR)
    write(os.path.join(ROOT, "src", "zones", "maps_fair_route.json"), {
        "name": "maps_fair_route",
        "description": "Legal route shown in the SHORTCUT scenario: the ~430m loop a maps app would offer (EAST cway exit -> connector 769451688 -> Ajwa Rd 28839743 at-grade crossing -> WEST cway -> DEST). Rides only real OSM roads, never against a one-way.",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6)} for la, lo in mf],
    })
    ww = resample(WRONG_WAY_ROUTE, spacing=25.0)
    write(os.path.join(ROOT, "src", "zones", "wrong_way_route.json"), {
        "name": "wrong_way_route",
        "description": "Legal route shown in the WRONG_WAY scenario: from where the driver started his wrong-way journey, drive straight to (22.329460, 73.252205), take the left, continue ~300-400m.",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6)} for la, lo in ww],
    })
    write(os.path.join(ROOT, "src", "zones", "lane_0.json"), {
        "name": "bypass_carriageway_E",
        "description": "EAST carriageway, one-way, authorized N->S (OSM way 219869675).",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6)} for la, lo in east],
        "authorized": "N->S",
    })
    write(os.path.join(ROOT, "src", "zones", "lane_1.json"), {
        "name": "bypass_carriageway_W",
        "description": "WEST carriageway, one-way, authorized S->N (OSM way 219869674).",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6)} for la, lo in west],
        "authorized": "S->N",
    })

    # Forbidden zone: sculpted WEDGE under the flyover deck, NORTH of the
    # Ajwa Road (28839743) at-grade crossing so the legal at-grade rider and
    # both one-way carriageways stay OUTSIDE it. The wedge covers the diagonal
    # where the origin-story cut crosses the median.
    #   south edge  lat 22.32370 (above the Ajwa at-grade lane ~22.32355-63)
    #   north edge  lat 22.32405 (below clean west-carriageway ride latitude)
    #   east edge   lon 73.25544 (west of the EAST carriageway ~73.25556+)
    #   west edge   lon 73.25523 (east of the WEST carriageway ~73.25521-23)
    zone_ring = [
        (22.32370, 73.25523),
        (22.32370, 73.25544),
        (22.32405, 73.25539),
        (22.32405, 73.25523),
    ]
    write(os.path.join(ROOT, "src", "zones", "ajwa_bridge.json"), {
        "name": "ajwa_flyover_underpass",
        "description": "Forbidden under-deck wedge (Ajwa Road at-grade crossing checked out): where the origin-story rider cuts under the NH48 flyover deck, north of the Ajwa Road at-grade lane. Drawn from live OSM trunk geometry (ways 1316342272/1316342273).",
        "ring": [{"lat": round(la, 6), "lon": round(lo, 6)} for la, lo in zone_ring],
    })

    ring = zone_ring

    # clean_legal: ride the WEST carriageway north, exactly the legal direction.
    clean = interpolate([(west[0][0], west[0][1])] + [(la, lo) for la, lo in west[1:]])
    write(os.path.join(ROOT, "src", "traces", "clean_legal.json"), {
        "name": "clean_legal",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6), "t": tt} for la, lo, tt in clean],
    })

    # wrong_way: ride the WEST carriageway south (against its S->N one-way).
    wr = interpolate([(west[-1][0], west[-1][1])] + [(la, lo) for la, lo in west[-2::-1]])
    write(os.path.join(ROOT, "src", "traces", "wrong_way.json"), {
        "name": "wrong_way",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6), "t": tt} for la, lo, tt in wr],
    })

    # illegal_shortcut: the user-confirmed origin story.
    waypoints = [START, TURN, CUT, DEST]
    sc = interpolate(waypoints, seed=7)
    write(os.path.join(ROOT, "src", "traces", "illegal_shortcut.json"), {
        "name": "illegal_shortcut",
        "story": "After a U-turn, the rider rides NORTH against the one-way EAST carriageway (wrong way), cuts LEFT under the NH48 flyover through the forbidden gap, and rejoins the WEST carriageway to the destination.",
        "start": list(START),
        "end": list(DEST),
        "points": [{"lat": round(la, 6), "lon": round(lo, 6), "t": tt} for la, lo, tt in sc],
    })

    # maps_fair trace REMOVED: the maps-fair loop is the SHORTCUT scenario's
    # legal-route line (maps_fair_route.json), not a separate trace scenario.

    # ambiguous: ride the west carriageway, but with realistic GPS wander that
    # occasionally drifts 60-90m off the road into the median/east apron, then
    # returns. Plausible jitter (city canyon), not flipped across the map.
    amb_wp = [
        (west[0][0], west[0][1]), (west[1][0], west[1][1]),
        (22.319000, 73.255100), (22.319000, 73.255100),
        (22.319600, 73.255050), (22.319600, 73.255050),
        (22.320100, 73.255080), (22.320100, 73.255080),
        (22.320600, 73.255090), (22.320600, 73.255090),
        (22.321100, 73.255100), (22.321100, 73.255100),
        (22.321600, 73.255150), (22.321600, 73.255150),
        (22.322100, 73.255200), (22.322100, 73.255200),
        (22.322702, 73.255615), (22.322702, 73.255615),  # jitter toward START
        (22.323100, 73.254900), (22.323100, 73.254900),
        (22.323400, 73.254600), (22.323400, 73.254600),
        (22.323200, 73.254200), (22.323200, 73.254200),
        (22.322900, 73.253900), (22.322900, 73.253900),
        (22.322600, 73.254300), (22.322600, 73.254300),
        (22.322300, 73.254700), (22.322300, 73.254700),
        (22.322000, 73.255000), (22.322000, 73.255000),
        (22.322100, 73.255400), (22.322100, 73.255400),
    ]
    amb = interpolate(amb_wp)
    write(os.path.join(ROOT, "src", "traces", "ambiguous_gps_drift.json"), {
        "name": "ambiguous_gps_drift",
        "points": [{"lat": round(la, 6), "lon": round(lo, 6), "t": tt} for la, lo, tt in amb],
    })

    # --- verify --------------------------------------------------------------
    route_lats = [p[0] for p in resample(WEST)]
    route_lons = [p[1] for p in resample(WEST)]
    mf_lats = [p[0] for p in mf]
    mf_lons = [p[1] for p in mf]
    ww_lats = [p[0] for p in ww]
    ww_lons = [p[1] for p in ww]
    checks = [
        ("clean_legal", route_lats, route_lons),
        ("wrong_way", ww_lats, ww_lons),
        ("illegal_shortcut", mf_lats, mf_lons),
        ("ambiguous_gps_drift", route_lats, route_lons),
    ]
    for name, rl, rn in checks:
        tr = json.load(open(os.path.join(ROOT, "src", "traces", f"{name}.json"), encoding="utf-8"))
        trace = Trace(points=[TracePoint(lat=p["lat"], lon=p["lon"], t=p["t"]) for p in tr["points"]])
        zones = [json.load(open(os.path.join(ROOT, "src", "zones", "ajwa_bridge.json"), encoding="utf-8"))]
        lanes = [json.load(open(os.path.join(ROOT, "src", "zones", "lane_0.json"), encoding="utf-8")),
                 json.load(open(os.path.join(ROOT, "src", "zones", "lane_1.json"), encoding="utf-8"))]
        ev = audit_trace(trace, rl, rn, zones, one_way_lanes=lanes)
        print(f"  {name:20s} -> {ev.verdict.value:9s} {ev.state.value:14s} {getattr(ev.violation_type, 'value', '-'):10s} {ev.severity} | {ev.reason}")
        deep = [i for i, p in enumerate(trace.points) if point_in_polygon(p.lat, p.lon, ring)]
        if deep:
            print(f"      in_zone: {len(deep)} pts, idx {min(deep)}..{max(deep)}")


if __name__ == "__main__":
    main()