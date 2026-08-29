from __future__ import annotations

from types import SimpleNamespace
import unittest

from scripts.evaluate_independent_paraphrases import (
    category_state_matches,
    evaluate_case,
    match_facts,
)


class _DiagnosticCandidate:
    def __init__(self, clue: str, candidates: set[str]) -> None:
        self.clue = clue
        self.candidates = candidates

    def reset(self, session_id: str, user_profile: dict) -> None:
        pass

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        return {"message": "", "ask_attribute": None, "recommendations": []}

    def debug_state(self, session_id: str) -> dict:
        active = {
            "text": self.clue,
            "active": True,
            "negated": False,
        }
        return {
            "category": "Boots",
            "current_intent": [active],
            "negative_evidence": [],
            "history": [active],
        }

    def debug_clue_candidates(
        self,
        clue: str,
        *,
        category: str | None = None,
    ) -> set[str]:
        return self.candidates


class IndependentParaphraseScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.target = "ASIN00000"
        self.catalog = {f"ASIN{index:05d}" for index in range(50_000)}
        self.oracle = SimpleNamespace(
            asins=sorted(self.catalog),
            atom_to_asins={"rubber sole": {self.target}},
        )
        self.case = {
            "id": "hp_test",
            "kind": "semantic_value_paraphrase",
            "scenario": "buying",
            "messages": [{"turn": 1, "text": "Boots with a grippy rubber bottom."}],
            "expected": {
                "category": "Shoes Boots",
                "positive_values": ["grippy rubber bottom"],
                "negative_values": [],
                "inactive_values": [],
            },
            "target_asin": self.target,
            "target_atoms": ["Rubber sole"],
        }

    def test_category_accepts_clean_leaf_but_rejects_polluted_span(self) -> None:
        self.assertTrue(category_state_matches("Shoes Boots", "Boots"))
        self.assertFalse(
            category_state_matches("Shoes Boots", "Boots with leather lining")
        )
        self.assertFalse(category_state_matches("Shoes Boots", None))

    def test_fact_matching_checks_content_not_only_count(self) -> None:
        self.assertIsNotNone(
            match_facts(
                ["does not feel heavy"],
                ["won't feel heavy"],
                threshold=0.55,
            )
        )
        self.assertIsNone(
            match_facts(
                ["does not feel heavy"],
                ["bright red"],
                threshold=0.55,
            )
        )
        self.assertIsNotNone(
            match_facts(
                ["Rubber sole", "Mesh upper"],
                ["Rubber sole and Mesh upper"],
                threshold=0.78,
            )
        )

    def test_returning_the_entire_catalog_fails_grounding_selectivity(self) -> None:
        result = evaluate_case(
            _DiagnosticCandidate("grippy rubber bottom", self.catalog),
            self.oracle,
            self.case,
        )

        self.assertFalse(result["grounding_pass"])
        self.assertFalse(result["benchmark_pass"])
        self.assertTrue(any("unselective" in item for item in result["failures"]))

    def test_returning_all_visible_fixture_targets_fails_reference_precision(self) -> None:
        visible_targets = {self.target} | {
            f"ASIN{index:05d}" for index in range(1, 100)
        }
        result = evaluate_case(
            _DiagnosticCandidate("grippy rubber bottom", visible_targets),
            self.oracle,
            self.case,
        )

        self.assertFalse(result["grounding_pass"])
        self.assertFalse(result["benchmark_pass"])
        self.assertTrue(
            any("low reference precision" in item for item in result["failures"])
        )

    def test_split_composite_fact_is_equivalent_to_merged_fact(self) -> None:
        self.assertIsNotNone(
            match_facts(
                ["mid rise, stretchy, and water repellent"],
                ["mid rise", "stretchy", "water repellent"],
                threshold=0.78,
            )
        )

    def test_wrong_deactivation_channel_does_not_pass_end_to_end(self) -> None:
        active = {"text": "grippy rubber bottom", "active": True, "negated": False}
        wrongly_negated = {
            "text": "fixed straps",
            "active": False,
            "negated": True,
        }
        candidate = _DiagnosticCandidate("grippy rubber bottom", {self.target})
        candidate.debug_state = lambda _session_id: {
            "category": "Boots",
            "current_intent": [active],
            "negative_evidence": [wrongly_negated],
            "history": [active, wrongly_negated],
        }
        case = {
            **self.case,
            "scenario": "intent_override",
            "expected": {
                **self.case["expected"],
                "inactive_values": ["fixed straps"],
            },
        }

        result = evaluate_case(candidate, self.oracle, case)

        self.assertTrue(result["deactivation_fact_pass"])
        self.assertFalse(result["polarity_fact_pass"])
        self.assertFalse(result["fact_state_pass"])
        self.assertFalse(result["benchmark_pass"])

    def test_focused_grounding_and_correct_state_pass(self) -> None:
        result = evaluate_case(
            _DiagnosticCandidate("grippy rubber bottom", {self.target}),
            self.oracle,
            self.case,
        )

        self.assertTrue(result["fact_state_pass"])
        self.assertTrue(result["grounding_pass"])
        self.assertTrue(result["benchmark_pass"])


if __name__ == "__main__":
    unittest.main()
