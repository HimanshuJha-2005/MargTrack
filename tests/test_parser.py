import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent.review_agent import parse_recommendation  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_anchored_verdict_is_kept(self):
        self.assertEqual(parse_recommendation("VIOLATION\ncut is real"), "VIOLATION")
        self.assertEqual(parse_recommendation("NOISE\ngps blip"), "NOISE")
        self.assertEqual(
            parse_recommendation("the drift is minor\nRecommendation: NOISE"), "NOISE"
        )
        self.assertEqual(parse_recommendation("verdict: VIOLATION"), "VIOLATION")

    def test_negated_word_is_not_a_verdict(self):
        # The old token-scan flipped on "violation" inside "does NOT look like a
        # VIOLATION". An anchored verdict never appears there.
        for text in (
            "This does not look like a VIOLATION\nkeep for humans",
            "clearly NOT a VIOLATION here",
            "the cut is noisier than a real violation",
        ):
            self.assertEqual(parse_recommendation(text), "REVIEW")

    def test_unknown_prose_defaults_to_review(self):
        for text in (
            "",
            "could not decide, low confidence",
            "Recommendation: wait for evidence",
        ):
            self.assertEqual(parse_recommendation(text), "REVIEW")

    def test_noise_negation_does_not_clear(self):
        text = "this is absolutely not NOISE\nstill suspicious, keep for human"
        self.assertEqual(parse_recommendation(text), "REVIEW")


if __name__ == "__main__":
    unittest.main()