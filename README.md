# MargTrack

GPS-trace ride audit: an embedded compliance layer that detects traffic-rule
violations (illegal cuts, wrong-side driving) from a ride's GPS trace, demerits
the driver, and surfaces the evidence to ride platforms.

Built for the WeMakeDevs x AWS "First Commit" hackathon (Bharat Builds Tour
2026). One codebase, two lanes: local AWS open-source stack (Build It) and a
deployable live stack (Ship It).

## Problem

Gig-ride drivers under time pressure routinely cut no-U-turn zones and drive
wrong-side to shave minutes. Existing tools audit *other* cars from a camera,
for police or fleet owners. Nobody hands the ride platform an independent,
auditable, GPS-derived check of each trip. That gap is MargTrack.

## Pipeline

    trace in -> audit engine (zone + route geometry) -> verdict
             -> agent readout (Strands/Bedrock) -> demerit -> score -> dashboard

## Quickstart (Build It, local)

Run the audit on a trace and print a verdict:

    python main.py --trace src/traces/illegal_shortcut.json --zone src/zones/ajwa_bridge.json

Launch the dashboard (serves map tiles, fixtures, `POST /api/audit`,
`POST /api/review`, and a custom-trace upload endpoint):

    python dashboard/server.py          # http://localhost:8000

Run checks (no deps beyond the standard library):

    python -m unittest discover -s tests -p "test_*.py"

Compliance extras (beyond stdlib):

- **AWS Cedar dispatch gate** — `pip install cedarpy`; audits then evaluate
  `Action::"DispatchRide"` against the driver's safety score. Without cedarpy
  the inline Python fallback in `src/audit/policy.py` applies the same rule.
- **Strands Tier-3 agent** — optional (heavy). Set `USE_BEDROCK=1` in
  `src/agent/review_agent.py` to run the model on Amazon Bedrock
  (`amazon.nova-micro-v1:0`) instead of a local Ollama server.

## Trace fixtures

- `clean_legal.json`            - follows the legal corridor -> CLEAN
- `wrong_way.json`              - rides the one-way carriageway backwards -> WRONG_WAY (confirmed)
- `illegal_shortcut.json`       - cuts across the one-way median under the flyover -> ZONE_CUT (pending review)
- `ambiguous_gps_drift.json`    - off-route, gentle GPS wander -> AMBIGUOUS (pending review)

Legal-route references used by the dashboard are kept in
`src/zones/*_route.json` (see `tools/rebuild_bypass_scenario.py`).

## Status

Working pipeline: geometry + zone and one-way-lane detection, legal-route
anchoring per scenario, verdicts with states, unit tests, permissioned
dispatch policy (Cedar), demerit ledger and safety score, Strands/Bedrock
review agent, and a dashboard with rider profile, safety score, Cedar gate,
ops metrics, and custom-trace upload. Next: OSRM legal-route fetch,
DynamoDB (LocalStack) audit log, live Bedrock deployment.