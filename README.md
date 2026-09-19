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

    python main.py --trace src/traces/illegal_under_bridge_cut.json --zone src/zones/ajwa_bridge.json

Run checks (no deps beyond the standard library):

    python -m unittest discover -s tests -p "test_*.py"

## Trace fixtures

- `clean_legal.json`            - follows the legal corridor -> CLEAN
- `illegal_under_bridge_cut.json` - cuts under the bridge -> VIOLATION
- `ambiguous_gps_drift.json`    - off-route but no zone entry -> AMBIGUOUS (review)

## Status

Day 1 skeleton: geometry, zone-based cut detection, verdicts, tests, CLI.
Next: strand real Ajwa Road Bridge coordinates, legal-route fetch (OSRM),
Strands agent readout, demerit engine, DynamoDB (LocalStack), dashboard.