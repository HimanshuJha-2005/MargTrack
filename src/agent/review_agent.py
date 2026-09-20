"""Tier-3 review agent: investigates PENDING_REVIEW events and drafts a verdict.

It does not guess. Every number it reasons about comes either from the engine's
evidence bundle or from tools that recompute it with our real geometry functions.
A human rubber-stamps the final decision.

Usage (local, needs Ollama running):
    python src/agent/review_agent.py --trace src/traces/ambiguous_gps_drift.json \
        --zone src/zones/ajwa_bridge.json --route src/traces/clean_legal.json
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from audit.detect import audit_trace
from audit.geometry import point_in_polygon
from audit.types import Trace, TracePoint, Verdict
from strands import Agent, tool
from strands.models.ollama import OllamaModel

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "amazon.nova-micro-v1:0")


def make_model():
    """Model-agnostic Strands backend: local Ollama (zero-cost default) or
    Amazon Bedrock when USE_BEDROCK=1 and credentials are configured."""
    if os.environ.get("USE_BEDROCK") == "1":
        from strands.models.bedrock import BedrockModel

        return BedrockModel(model_id=BEDROCK_MODEL, temperature=0.1, max_tokens=512)
    return OllamaModel(OLLAMA_HOST, model_id=OLLAMA_MODEL, temperature=0.1, max_tokens=512)


def build_review_agent(evidence: dict):
    """Create the Strands agent for one evidence bundle.

    Tools close over the real geometry data so the model computes, not imagines.
    """

    route_lats = evidence["route_lats"]
    route_lons = evidence["route_lons"]
    rings = evidence["zone_rings"]
    # from the engine: the violating run (used to build a point-by-point profile)
    points = evidence["points"]
    seg_start, seg_end = evidence.get("seg_start", -1), evidence.get("seg_end", -1)

    @tool(description="Min distance (metres) from (lat, lon) to the legal route polyline.")
    def dist_to_route_m(lat: float, lon: float) -> float:
        """Min distance (metres) from (lat, lon) to the legal route polyline."""
        best = float("inf")
        from audit.geometry import point_segment_distance_m

        for i in range(len(route_lats) - 1):
            d = point_segment_distance_m(
                lat, lon, route_lats[i], route_lons[i], route_lats[i + 1], route_lons[i + 1]
            )
            if d < best:
                best = d
        return round(best, 1)

    @tool(description="'IN_ZONE' if (lat, lon) is inside a forbidden zone, else 'OUTSIDE'.")
    def in_any_zone(lat: float, lon: float) -> str:
        """'IN_ZONE' if (lat, lon) is inside a forbidden zone, else 'OUTSIDE'."""
        for ring in rings:
            if point_in_polygon(lat, lon, ring):
                return "IN_ZONE"
        return "OUTSIDE"

    @tool(description="Verified point-by-point report of the flagged run: each point's distance to the legal route and its forbidden-zone membership.")
    def cut_profile() -> str:
        """Verified point-by-point report of the flagged run: each point's
        distance to the legal route and its forbidden-zone membership."""
        if seg_start < 0 or seg_end < 0 or seg_end - seg_start < 1:
            return "no cut segment flagged"
        lines = []
        for i in range(seg_start, seg_end + 1):
            p = points[i]
            lines.append(
                f"[{i}] lat={p.lat:.6f} lon={p.lon:.6f} "
                f"dist_to_route={dist_to_route_m(p.lat, p.lon)}m {in_any_zone(p.lat, p.lon)}"
            )
        return "\n".join(lines)

    agent = Agent(
        model=make_model(),
        tools=[dist_to_route_m, in_any_zone, cut_profile],
        system_prompt=(
            "You are a strict but fair GPS ride auditor. A human rideshare supervisor will "
            "rubber-stamp your recommendation, so be precise, never moralize, and never "
            "invent numbers. Use the provided tools to VERIFY the evidence: call cut_profile() "
            "to inspect the flagged run, dist_to_route_m() to confirm how far a point is from "
            "the legal route, and in_any_zone() to confirm forbidden-zone membership. "
            "You must call at least one tool before giving a verdict.\n\n"
            "Rules:\n"
            "- A real cut needs MULTIPLE consecutive points deep inside a forbidden zone\n"
            "  AND far off the legal route. A single GPS blip is NOT a violation.\n"
            "- Assess intent-free: is the PHYSICAL path clearly wrong, or could it be GPS noise?\n"
            "- Verdict vocabulary: 'VIOLATION' (deliberate cut through a forbidden zone), "
            "'NOISE' (bad GPS, dismissable), 'REVIEW' (needs a human decision).\n"
            "Reply with the recommendation word on its own line, then your reasoning."
        ),
    )
    return agent, dist_to_route_m, in_any_zone, cut_profile


def review_event(trace: Trace, route_lats, route_lons, zones, one_way_lanes=None) -> dict:
    """Run the engine, then the Tier-3 agent on a PENDING_REVIEW event.

    Routed through one_way_lanes so wrong-way rides are seen by the engine.
    Returns a dict ready to print: engine verdict + agent recommendation, plus
    the post-review safety-ledger snapshot when the agent reached a verdict.
    """
    from audit import demerit

    event = audit_trace(trace, route_lats, route_lons, zones, one_way_lanes=one_way_lanes)

    if event.state.value != "PENDING_REVIEW":
        return {
            "engine_verdict": event.verdict.value,
            "engine_state": event.state.value,
            "engine_reason": event.reason,
            "agent_recommendation": "SKIPPED (engine verdict is decisive, no Tier-3 review needed)",
        }

    evidence = {
        "points": trace.points,
        "route_lats": route_lats,
        "route_lons": route_lons,
        "zone_rings": [[(pt["lat"], pt["lon"]) for pt in z.get("ring", [])] for z in zones],
        "seg_start": event.seg_start,
        "seg_end": event.seg_end,
        "metrics": event.metrics,
    }

    agent, dist_to_route_m, in_any_zone, cut_profile = build_review_agent(evidence)

    prompt = (
        "Evidence bundle.\n"
        f"- engine verdict: {event.verdict.value} | severity: {event.severity}\n"
        f"- trace points: {len(trace.points)}\n"
        f"- engine metrics: {event.metrics or 'none'}\n"
        f"- flagged run points index range: [{event.seg_start}..{event.seg_end}]\n\n"
        "Verify the evidence with your tools, then recommend VIOLATION, NOISE, or REVIEW."
    )

    try:
        result = agent(prompt)
        blocks = getattr(result, "message", {}).get("content", [])
        text = "\n".join(
            b.get("text", "") for b in blocks if isinstance(b, dict) and "text" in b
        ) or getattr(result, "message", {}).get("content", "") or repr(result)
    except Exception as exc:  # model refused / connection lost -> stay pending
        return {
            "engine_verdict": event.verdict.value,
            "engine_state": event.state.value,
            "engine_reason": event.reason,
            "agent_recommendation": "REVIEW (agent unavailable, keep for human)",
            "agent_error": str(exc),
            "after_review": demerit.resolve_review(demerit.BASE_SCORE, event, "REVIEW"),
        }

    recommendation = "REVIEW"
    for token in text.split():
        up = token.strip(",.!()'\"").upper()
        if up in ("VIOLATION", "NOISE"):
            recommendation = up
            break

    return {
        "engine_verdict": event.verdict.value,
        "engine_state": event.state.value,
        "engine_reason": event.reason,
        "agent_recommendation": recommendation,
        "agent_text": text.strip(),
        "after_review": demerit.resolve_review(demerit.BASE_SCORE, event, recommendation),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Tier-3 review of one trace")
    parser.add_argument("--trace", required=True, help="trace JSON file")
    parser.add_argument("--zone", nargs="*", default=[], help="zone JSON file(s)")
    parser.add_argument("--route", default=None, help="legal-route trace JSON file")
    args = parser.parse_args()

    def load_points(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [TracePoint(lat=p["lat"], lon=p["lon"], t=p.get("t", i)) for i, p in enumerate(data["points"])]

    trace = Trace(points=load_points(args.trace))
    zones = [json.load(open(zp, encoding="utf-8")) for zp in args.zone]
    rl = rs = []
    if args.route:
        rl = [p.lat for p in load_points(args.route)]
        rs = [p.lon for p in load_points(args.route)]

    outcome = review_event(trace, rl, rs, zones)
    for k, v in outcome.items():
        print(f"{k.replace('_', ' '):22s}: {v}")