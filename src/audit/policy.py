"""AWS Cedar dispatch gate: the provable, deterministic access decision.

Evaluates the policy in policies/driver_policy.cedar against a driver's
current ledger snapshot (safety score + unresolved violations) and answers one
question: may the fleet platform send this rider the next DispatchRide action?

Uses aws-cloudtrail/cedarpy when installed. Falls back to a comment-for-
comment equivalent of the same rule so the demo never hard-fails offline
(the returned `backend` field tells the caller which one ran).

Usage:
    python -c "from audit.policy import evaluate; print(evaluate(65, 1))"
"""

import json
import os

try:
    import cedarpy  # type: ignore
    _HAS_CEDAR = True
except Exception:
    cedarpy = None
    _HAS_CEDAR = False

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POLICY_PATH = os.path.join(ROOT, "policies", "driver_policy.cedar")
DISPATCH_GATE = 70  # must match the .cedar `when` clause

_DRIVER_ID = "GJ-06-AX-1029"


def _read_policy() -> str:
    with open(POLICY_PATH, encoding="utf-8") as f:
        return f.read()


def _python_fallback(safety_score: int, unresolved_violations: int) -> dict:
    """Mirror of policies/driver_policy.cedar, no dependencies."""
    allowed = safety_score >= DISPATCH_GATE and unresolved_violations == 0
    return _outcome(allowed, safety_score, unresolved_violations, backend="python-fallback")


def _cedar_eval(safety_score: int, unresolved_violations: int) -> dict:
    request = {
        "principal": {"type": "Driver", "id": _DRIVER_ID},
        "action": {"type": "Action", "id": "DispatchRide"},
        "resource": {"type": "Driver", "id": _DRIVER_ID},
    }
    entities = [
        {
            "uid": {"type": "Driver", "id": _DRIVER_ID},
            "attrs": {
                "safety_score": safety_score,
                "unresolved_violations": unresolved_violations,
            },
            "parents": [],
        }
    ]
    result = cedarpy.is_authorized(request, _read_policy(), json.dumps(entities))
    return _outcome(bool(result.allowed), safety_score, unresolved_violations, backend="cedarpy")


def _outcome(allowed: bool, safety_score: int, unresolved_violations: int, backend: str) -> dict:
    decision = "ALLOWED" if allowed else "DENIED"
    if allowed:
        reason = "dispatch permitted: driver passes the safety + clean-slate gate"
    elif safety_score < DISPATCH_GATE and unresolved_violations > 0:
        reason = (
            f"dispatch blocked: safety score {safety_score} < {DISPATCH_GATE} "
            f"and {unresolved_violations} unresolved violation(s)"
        )
    elif safety_score < DISPATCH_GATE:
        reason = f"dispatch blocked: safety score {safety_score} < {DISPATCH_GATE}"
    else:
        reason = f"dispatch blocked: {unresolved_violations} unresolved violation(s)"
    return {
        "decision": decision,
        "reason": reason,
        "safety_score": safety_score,
        "unresolved_violations": unresolved_violations,
        "dispatch_gate": DISPATCH_GATE,
        "backend": backend,
    }


def evaluate(safety_score: int, unresolved_violations: int) -> dict:
    """Gate a DispatchRide for a driver ledger snapshot. Never raises."""
    if _HAS_CEDAR:
        try:
            return _cedar_eval(safety_score, unresolved_violations)
        except Exception:
            pass  # fall through to the dependency-free mirror
    return _python_fallback(safety_score, unresolved_violations)


if __name__ == "__main__":
    import sys

    score = int(sys.argv[1]) if len(sys.argv) > 1 else 65
    un = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    print(evaluate(score, un))