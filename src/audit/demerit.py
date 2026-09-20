"""Demerit & safety-score model for MargTrack.

Closes the loop promised in the README pipeline:
    trace -> audit engine -> verdict -> agent readout -> demerit -> safety
    score -> dispatch policy (AWS Cedar) -> dashboard

The score is a simple, auditable points ledger (no ML, no black box):

    base                    100
    WRONG_WAY               -30   (head-on hazard on a one-way carriageway)
    ZONE_CUT                -15   (deliberate shortcut through a forbidden zone)
    Tier-3 Strands confirm  -10   (agent verified a violation from evidence)
    clean trip              +2    recovery, capped at the base of 100

Scores below 70 fail the Cedar DispatchRide gate (see policies/*.cedar), so a
fleet platform stops dispatching to the driver until the ledger recovers.
"""

from typing import Optional

from .types import DetectedEvent, EventState, Verdict, ViolationType

BASE_SCORE = 100
DISPATCH_GATE = 70  # must match policies/driver_policy.cedar

PENALTY_WRONG_WAY = -30
PENALTY_ZONE_CUT = -15
PENALTY_AGENT_CONFIRM = -10
RECOVERY_CLEAN = +2


def penalty_for(event: DetectedEvent, agent_confirmed_violation: bool = False) -> int:
    """The demerit points for one audit event, before applying to a ledger."""
    if event.verdict == Verdict.CLEAN:
        return RECOVERY_CLEAN
    if event.verdict != Verdict.VIOLATION:
        return 0  # AMBIGUOUS / noise: no penalty yet, still counts unresolved

    penalty = 0
    if event.violation_type == ViolationType.WRONG_WAY:
        penalty += PENALTY_WRONG_WAY
    elif event.violation_type == ViolationType.ZONE_CUT:
        penalty += PENALTY_ZONE_CUT
    if agent_confirmed_violation:
        penalty += PENALTY_AGENT_CONFIRM
    return penalty


def apply_event(
    previous_score: int,
    event: DetectedEvent,
    agent_confirmed_violation: bool = False,
) -> dict:
    """Apply one audit event to a driver's safety ledger.

    Returns an immutable snapshot the dashboard renders:
      {safety_score, penalty, status, unresolved_violations, reason}
    """
    penalty = penalty_for(event, agent_confirmed_violation)
    score = max(0, min(BASE_SCORE, previous_score + penalty))

    unresolved = 1 if event.verdict != Verdict.CLEAN else 0
    status = (
        "ACTIVE" if score >= DISPATCH_GATE
        else "SUSPENDED" if score >= DISPATCH_GATE // 2
        else "BLOCKED"
    )

    reason = "clean trip: +{n} recovery".format(n=RECOVERY_CLEAN) if penalty == RECOVERY_CLEAN else (
        "no change" if not penalty else f"penalty {penalty:+d}"
    )
    return {
        "safety_score": score,
        "penalty": penalty,
        "status": status,
        "unresolved_violations": unresolved,
        "dispatch_gate": DISPATCH_GATE,
        "reason": reason,
    }


def demo_ledger(event: DetectedEvent, agent_confirmed_violation: bool = False) -> dict:
    """Score for the single-event dashboard demo, starting from a full ledger."""
    return apply_event(BASE_SCORE, event, agent_confirmed_violation)