# MargTrack

**GPS-Trace Ride Audit & Dispatch Compliance Engine**  
*Built for the WeMakeDevs × AWS "First Commit" Hackathon (Bharat Builds Tour 2026) — **Build It Track**.*

[![Tests](https://img.shields.io/badge/tests-24%20passing-success.svg)](#test-suite)
[![AWS Stack](https://img.shields.io/badge/AWS%20Open--Source-Strands%20%2B%20Cedar-orange.svg)](#aws-open-source-stack)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](#quickstart)

---

## 📹 Demo Video

> **[▶ Watch the 3-Minute YouTube Demo Video](https://youtu.be/YOUR_VIDEO_ID_HERE)**  
> *(Shows live violation detection, AWS Cedar dispatch suspension, and the AWS Strands edge-case resolution loop.)*

---

## The Problem

Gig delivery and bike-taxi riders face immense delivery pressure. To shave 3–5 minutes off trips, riders routinely cut through no-turn underpasses and drive the wrong way down one-way carriageways, endangering themselves and oncoming traffic.

Existing traffic-compliance solutions rely on expensive CCTV cameras that suffer from blind spots, or traffic police on the ground. However, platforms like Uber, Swiggy, and Rapido **already collect raw GPS breadcrumbs from every single trip**.

**MargTrack** is a lightweight, backend compliance layer that audits GPS traces against real road corridors, calculates driver demerits, evaluates **AWS Cedar** dispatch authorization, and invokes an **AWS Strands Agent** for autonomous forensic review.

---

## Architecture & Pipeline

```
  [Raw GPS Trace]
        │
        ▼
┌────────────────────────────────────────────────────────┐
│ Tier 1: Pure-Math Deterministic Geometry Engine        │
│  • Haversine & equirectangular segment projection      │
│  • Ray-casting point-in-polygon checks                 │
│  • Physical speed filter (< 200 km/h noise cutoff)     │
│  • Route entry/exit anchor validation                  │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ Tier 2: Heuristic Auto-Confirmation                    │
│  • High-severity wrong-way (bearing delta ≥ 160°)      │
│  • Clear cuts (shortcut factor ≥ 1.5 & delta ≥ 120°)   │
└───────────────────────┬────────────────────────────────┘
                        │
       ┌────────────────┴────────────────┐
       ▼                                 ▼
 [Decisive Verdict]             [Ambiguous Edge Case]
       │                                 │
       │                                 ▼
       │                ┌────────────────────────────────┐
       │                │ Tier 3: AWS Strands AI Agent   │
       │                │  • Tool-calling verification   │
       │                │    (dist_to_route_m, in_zone)  │
       │                │  • Recommends VIOLATION/NOISE  │
       │                └────────────────┬───────────────┘
       │                                 │
       └────────────────┬────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ Driver Demerit & Safety Ledger                         │
│  • Base score: 100                                     │
│  • WRONG_WAY: -30 pts | ZONE_CUT: -15 pts              │
│  • Clean trip / Noise dismissal: +2 pts recovery       │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ AWS Cedar Compliance Policy Gate                       │
│  • Evaluates Action::"DispatchRide"                    │
│  • ALLOWED: Score ≥ 70 & 0 unresolved violations       │
│  • DENIED: Automatically locks dispatch (ON HOLD)      │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ Interactive Operations Console (MapLibre GL)           │
│  • Driver card, Cedar chip, ops metrics, upload trace  │
└────────────────────────────────────────────────────────┘
```

---

## AWS Open-Source Stack

MargTrack leverages key open-source AWS technologies for local, auditable compliance:

1. **AWS Cedar (`policies/driver_policy.cedar` & `src/audit/policy.py`)**:
   Enforces provable dispatch authorization policies using Cedar's declarative policy language via `cedarpy` (with a zero-dependency Python fallback for offline execution):
   ```cedar
   permit(
       principal,
       action == Action::"DispatchRide",
       resource
   )
   when {
       resource.safety_score >= 70 &&
       resource.unresolved_violations == 0
   };
   ```

2. **AWS Strands Agents (`src/agent/review_agent.py`)**:
   Provides autonomous edge-case investigation. Rather than allowing LLMs to hallucinate geospatial numbers, the Strands agent is equipped with deterministic Python tools (`dist_to_route_m`, `in_any_zone`, `cut_profile`) that close over the exact geometric engine.

3. **Cloud-Ready Hybrid Switch (`USE_BEDROCK=1`)**:
   Operates on local **Ollama** (`llama3.2:3b`) by default for zero-cost developer testing, and seamlessly switches to **Amazon Bedrock** (`amazon.nova-micro-v1:0`) when `USE_BEDROCK=1` is set.

---

## Grounded in Real Geometry

MargTrack is calibrated on real-world OpenStreetMap telemetry at the notorious **Ajwa Road × NH48 Flyover Junction** in Vadodara, Gujarat:
* **West Carriageway (OSM Way 219869674):** Authorized One-Way South $\rightarrow$ North.
* **East Carriageway (OSM Way 219869675):** Authorized One-Way North $\rightarrow$ South.
* **Forbidden Zone:** The narrow median gap under the flyover deck where riders cut across head-on traffic to avoid the legal interchange loop.

---

## Trace Fixtures

| Fixture | Scenario Description | Expected Verdict | Cedar Gate |
| :--- | :--- | :---: | :---: |
| `clean_legal.json` | Follows the legal bypass corridor correctly | **CLEAN** | **ALLOWED** |
| `wrong_way.json` | Rides against one-way traffic on the bypass carriageway | **WRONG_WAY** | **DENIED** |
| `illegal_shortcut.json` | Cuts under the flyover deck through the forbidden median | **ZONE_CUT** | **DENIED** |
| `ambiguous_gps_drift.json` | Off-route wander without entering forbidden zones (GPS drift) | **AMBIGUOUS** | **ON HOLD** $\rightarrow$ **ALLOWED** *(via Strands)* |

---

## Quickstart (Local "Build It" Setup)

### 1. Environment Setup

```bash
# Clone repository
git clone https://github.com/HimanshuJha-2005/MargTrack.git
cd MargTrack

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Linux/macOS
.\.venv\Scripts\activate        # On Windows

# Install dependencies
pip install -r requirements.txt
pip install cedarpy             # Optional: for native Rust Cedar bindings
```

### 2. Run the Test Suite

MargTrack includes 24 comprehensive unit tests covering geometry, noise guards, demerit ledgers, Cedar policy gates, and verdict parsers:

```bash
python -m unittest discover -s tests -p "test_*.py"
```
*(All 24 tests run in under 0.2 seconds).*

### 3. CLI Audit

Run an instant audit from the command line:

```bash
python main.py --trace src/traces/illegal_shortcut.json \
               --zone src/zones/ajwa_bridge.json \
               --route src/zones/maps_fair_route.json \
               --lanes src/zones/lane_0.json src/zones/lane_1.json
```

### 4. Launch the Interactive Dashboard

```bash
python dashboard/server.py
```
Open **`http://localhost:8000`** in your browser to explore:
* **MapLibre GL Visualizer:** Replay GPS traces with animated heading markers.
* **Driver Compliance Card:** Real-time safety score and live AWS Cedar gate status.
* **High-Signal Operations Metrics:** Distance taken vs legal corridor, time saved/cheated.
* **Investigate Edge Case (AWS Strands):** Resolves ambiguous traces and updates the Cedar dispatch chip dynamically.
* **Custom Trace Upload:** Upload any `.json` or GeoJSON LineString file to test any custom route on the fly.

---

## Project Structure

```
margtrack/
├── dashboard/                 # MapLibre GL UI & local HTTP API server
│   ├── index.html             # High-signal compliance dashboard
│   ├── app.js                 # MapLibre rendering & Strands resolution handling
│   ├── server.py              # Tile proxy, audit API & session ledger
│   └── style.css              # Clean, dark/slate typography (no AI slop)
├── policies/
│   └── driver_policy.cedar    # AWS Cedar dispatch authorization rules
├── src/
│   ├── agent/
│   │   └── review_agent.py    # AWS Strands agent with deterministic math tools
│   ├── audit/
│   │   ├── demerit.py         # Demerit points ledger & score calculation
│   │   ├── detect.py          # Multi-tier audit engine & noise guards
│   │   ├── geometry.py        # Pure-math spherical geometry & ray-casting
│   │   ├── policy.py          # AWS Cedar evaluation & offline fallback
│   │   └── types.py           # Data models & verdict types
│   ├── traces/                # Real-world test scenarios
│   └── zones/                 # Road corridors & forbidden polygons
├── tests/
│   ├── test_detect.py         # Geometry engine & noise filter tests
│   ├── test_ledger.py         # Demerit ledger & Cedar gate tests
│   └── test_parser.py         # Robust Strands verdict parsing tests
├── tools/                     # OSM data fetchers & scenario generators
├── main.py                    # Standalone CLI entrypoint
└── requirements.txt           # strands-agents, ollama
```

---

## License

MIT License. Built for the WeMakeDevs × AWS BharatBuilds Tour 2026.