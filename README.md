# MargTrack

GPS trace audit and dispatch compliance engine. It replays a ride against road geometry, flags wrong-way travel and illegal shortcuts, updates a demerit score, and asks an AWS Cedar policy whether the driver may accept another dispatch.

Built for the WeMakeDevs x AWS First Commit Hackathon (Bharat Builds Tour 2026, Build It track).

## Why

Ride and delivery platforms already collect GPS breadcrumbs. MargTrack turns that existing telemetry into a compliance signal without adding cameras or roadside hardware. The rules are deterministic and the evidence is inspectable: distance from the corridor, entry and exit points, bearing, and the polygon that was crossed.

The demo area is the Ajwa Road and NH48 flyover junction in Vadodara, Gujarat. The two carriageways are mapped as one-way OSM ways (219869674 and 219869675), and the median gap under the flyover is the forbidden shortcut.

## How an audit runs

1. **Geometry and noise filtering.** Haversine distance and segment projection place each point relative to the route and lanes. Ray casting tests forbidden polygons. A speed filter drops points implying more than 200 km/h, and entry/exit anchors reject traces that only touch the corridor.
2. **Heuristic verdicts.** A bearing delta of 160 degrees or more against an authorized lane is flagged as wrong-way. A shortcut factor of 1.5 or more with a 120 degree delta is flagged as a zone cut. Clear cases end here.
3. **Agent review for ambiguous cases.** The Strands agent receives the engine's evidence bundle and can call deterministic tools (`dist_to_route_m`, `in_any_zone`, `cut_profile`) that reuse the same geometry code. It recommends VIOLATION or NOISE; the result is a recommendation, not an automatic accusation.
4. **Demerit ledger.** Drivers start at 100. Wrong-way costs 30 points, a zone cut 15. Clean trips and dismissed noise recover 2 points.
5. **Cedar dispatch gate.** `Action::"DispatchRide"` is permitted only when the safety score is at least 70 and no violations are unresolved. Otherwise dispatch goes on hold.

The Cedar policy is in `policies/driver_policy.cedar` and is evaluated through `cedarpy`; a small Python fallback keeps the demo usable without the native module.

## Stack

- Python 3.12, no web framework for the engine
- AWS Cedar via `cedarpy`
- AWS Strands Agents with Ollama locally (`llama3.2:3b`) or Amazon Bedrock Nova Micro
- MapLibre GL dashboard with a local Python HTTP server

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Tests
python -m unittest discover -s tests -p "test_*.py"

# CLI audit
python main.py --trace src/traces/illegal_shortcut.json \
               --zone src/zones/ajwa_bridge.json \
               --route src/zones/maps_fair_route.json \
               --lanes src/zones/lane_0.json src/zones/lane_1.json

# Dashboard
python dashboard/server.py
```

The dashboard runs at http://localhost:8000. It supports trace replay, a compliance card, Cedar status, metrics, ambiguous-case review, and custom trace upload.

Agent review needs Ollama running with `llama3.2:3b` pulled. Set `USE_BEDROCK=1` to use Amazon Bedrock instead (`amazon.nova-micro-v1:0` by default, configurable with `BEDROCK_MODEL`). Model and host can be overridden with `OLLAMA_MODEL` and `OLLAMA_HOST`.

## Fixtures

| Fixture | Scenario | Verdict | Cedar |
|---|---|---|---|
| `clean_legal.json` | Follows the legal corridor | CLEAN | ALLOWED |
| `wrong_way.json` | Travels against the one-way carriageway | WRONG_WAY | DENIED |
| `illegal_shortcut.json` | Cuts through the forbidden median | ZONE_CUT | DENIED |
| `ambiguous_gps_drift.json` | Off-route drift, no forbidden zone | AMBIGUOUS | ON HOLD, then reviewed |

## Tests

24 tests in three files:

- `test_detect.py`: geometry, projection, polygon tests, and noise guards
- `test_ledger.py`: demerit scoring and the Cedar gate
- `test_parser.py`: strict parsing of agent recommendations

The suite runs in under a second and needs no network access.

## Layout

```
main.py                       CLI entry point
policies/driver_policy.cedar  dispatch authorization policy
src/audit/                    geometry, detection, demerits, policy, types
src/agent/review_agent.py     Strands agent and deterministic tools
src/traces/                   ride fixtures
src/zones/                    route, lane, and forbidden-zone polygons
dashboard/                    MapLibre UI and local API server
tests/                        unit tests
```

## Limitations

- The demo is calibrated to one junction. Supporting a city means ingesting OSM ways and polygons for each corridor.
- The agent recommends a verdict; a human still owns enforcement decisions.
- GPS drift, tunnels, and multi-level roads can produce ambiguous evidence, which is why those cases go to review instead of auto-decline.
- There is no persistent database; the dashboard keeps the session ledger in memory.

## Demo

Video: https://youtu.be/MEsncWw6f2o

## License

MIT. See [LICENSE](LICENSE).
