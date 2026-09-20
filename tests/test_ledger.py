import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audit import demerit  # noqa: E402
from audit.policy import evaluate  # noqa: E402
from audit.types import DetectedEvent, EventState, Verdict, ViolationType  # noqa: E402


def event(verdict=Verdict.VIOLATION, vtype="", state=EventState.PENDING_REVIEW, severity="LOW"):
    if vtype == "WRONG_WAY" or vtype == ViolationType.WRONG_WAY:
        pass
    elif vtype == "ZONE_CUT" or vtype == ViolationType.ZONE_CUT:
        pass
    elif vtype is not None and vtype != "":
        vtype = ViolationType(vtype)
    vtype_str = vtype.value if isinstance(vtype, ViolationType) else (str(vtype) if vtype else "")
    return DetectedEvent(verdict=verdict, state=state, severity=severity, violation_type=vtype_str)


class DemeritTests(unittest.TestCase):
    def test_clean_trip_recovers_two_points(self):
        clean = event(Verdict.CLEAN)
        ledger = demerit.apply_event(94, clean)
        self.assertEqual(ledger["safety_score"], 96)
        self.assertEqual(ledger["penalty"], demerit.RECOVERY_CLEAN)
        self.assertTrue(ledger["unresolved_violations"] == 0)

    def test_clean_trip_caps_at_base(self):
        ledger = demerit.apply_event(100, event(Verdict.CLEAN))
        self.assertEqual(ledger["safety_score"], demerit.BASE_SCORE)

    def test_zone_cut_penalty(self):
        cut = event(Verdict.VIOLATION, "ZONE_CUT")
        ledger = demerit.apply_event(100, cut)
        self.assertEqual(ledger["safety_score"], 85)
        self.assertEqual(ledger["penalty"], demerit.PENALTY_ZONE_CUT)
        self.assertEqual(ledger["unresolved_violations"], 1)

    def test_wrong_way_penalty(self):
        ww = event(Verdict.VIOLATION, "WRONG_WAY", EventState.CONFIRMED, "HIGH")
        ledger = demerit.apply_event(100, ww)
        self.assertEqual(ledger["safety_score"], 70)
        self.assertEqual(ledger["penalty"], demerit.PENALTY_WRONG_WAY)

    def test_dispatch_fails_on_penalty(self):
        ww = event(Verdict.VIOLATION, "WRONG_WAY", EventState.CONFIRMED, "HIGH")
        ledger = demerit.apply_event(100, ww)
        self.assertEqual(evaluate(ledger["safety_score"], ledger["unresolved_violations"])["decision"], "DENIED")


class ResolveReviewTests(unittest.TestCase):
    def setUp(self):
        self.ambiguous = event(Verdict.AMBIGUOUS, "", EventState.PENDING_REVIEW)

    def test_noise_clears_unresolved_and_reopens_dispatch(self):
        ledger = demerit.resolve_review(demerit.BASE_SCORE, self.ambiguous, "NOISE")
        self.assertEqual(ledger["unresolved_violations"], 0)
        self.assertEqual(ledger["status"], "ACTIVE")
        self.assertEqual(evaluate(ledger["safety_score"], ledger["unresolved_violations"])["decision"], "ALLOWED")

    def test_noise_recovers_two_points_only_up_to_base(self):
        self.assertEqual(demerit.resolve_review(90, self.ambiguous, "NOISE")["safety_score"], 92)
        self.assertEqual(demerit.resolve_review(100, self.ambiguous, "NOISE")["safety_score"], 100)

    def test_violation_confirm_applies_agent_penalty_and_stays_blocked(self):
        # AMBIGUOUS -> agent says VIOLATION: the confirmed demerit is the
        # Strands-confirm penalty (-10); unresolved stays 1 so dispatch holds.
        ledger = demerit.resolve_review(demerit.BASE_SCORE, self.ambiguous, "VIOLATION")
        self.assertEqual(ledger["penalty"], demerit.PENALTY_AGENT_CONFIRM)
        self.assertEqual(ledger["safety_score"], 90)
        # unresolved stays 1: a confirmed violation is never auto-cleared
        self.assertEqual(ledger["unresolved_violations"], 1)
        self.assertEqual(evaluate(ledger["safety_score"], ledger["unresolved_violations"])["decision"], "DENIED")

    def test_zone_cut_confirm_adds_confirm_penalty(self):
        # A real ZONE_CUT the agent then confirms: -15 base + -10 confirm.
        cut = event(Verdict.VIOLATION, "ZONE_CUT", EventState.PENDING_REVIEW)
        ledger = demerit.resolve_review(demerit.BASE_SCORE, cut, "VIOLATION")
        self.assertEqual(ledger["penalty"], demerit.PENALTY_ZONE_CUT + demerit.PENALTY_AGENT_CONFIRM)
        self.assertEqual(ledger["safety_score"], 75)
        self.assertEqual(ledger["unresolved_violations"], 1)
        self.assertEqual(evaluate(ledger["safety_score"], ledger["unresolved_violations"])["decision"], "DENIED")

    def test_review_keeps_driver_on_hold(self):
        ledger = demerit.resolve_review(demerit.BASE_SCORE, self.ambiguous, "REVIEW")
        self.assertEqual(ledger["unresolved_violations"], 1)
        self.assertEqual(evaluate(ledger["safety_score"], ledger["unresolved_violations"])["decision"], "DENIED")


class PolicyTests(unittest.TestCase):
    def test_allowed_at_or_above_gate_clean_slate(self):
        self.assertEqual(evaluate(100, 0)["decision"], "ALLOWED")
        self.assertEqual(evaluate(70, 0)["decision"], "ALLOWED")

    def test_denied_below_gate(self):
        self.assertEqual(evaluate(69, 0)["decision"], "DENIED")

    def test_denied_with_unresolved_violations(self):
        self.assertEqual(evaluate(100, 1)["decision"], "DENIED")

    def test_backend_field_present(self):
        self.assertIn(evaluate(100, 0)["backend"], ("cedarpy", "python-fallback"))


if __name__ == "__main__":
    unittest.main()