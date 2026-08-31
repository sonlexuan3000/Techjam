from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
for path in (PROJECT_ROOT, CANDIDATE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from submission.src.shopping_copilot.parser import ParsedMessage
from tunglam_robust_dp.agent import Agent, ScenarioPosterior, semantic_terms


class RobustHypothesisAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        products = [
            {
                "parent_asin": "TARGET",
                "title": "Dry comfortable running shoe",
                "features": [
                    "Water resistant",
                    "Rubber sole",
                    "Cushioned comfort",
                    "Wide fit",
                ],
                "description": [],
                "price": None,
                "categories": ["Clothing", "Shoes"],
                "details": {},
                "average_rating": 4.5,
                "rating_number": 10,
                "store": "Target Store",
            },
            {
                "parent_asin": "POPULAR",
                "title": "Popular fashion shoe",
                "features": [
                    "Leather upper",
                    "Foam sole",
                    "Classic style",
                    "Standard fit",
                ],
                "description": [],
                "price": None,
                "categories": ["Clothing", "Shoes"],
                "details": {},
                "average_rating": 4.9,
                "rating_number": 1000,
                "store": "Popular Store",
            },
            {
                "parent_asin": "DISTRACTOR",
                "title": "Everyday walking shoe",
                "features": [
                    "Canvas upper",
                    "Flat sole",
                    "Casual design",
                    "Narrow fit",
                ],
                "description": [],
                "price": None,
                "categories": ["Clothing", "Shoes"],
                "details": {},
                "average_rating": 4.2,
                "rating_number": 100,
                "store": "Other Store",
            },
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        self.agent = Agent(
            self.catalog_path,
            prior_field="rating_number",
            prior_smoothing=0.0,
        )

    def test_initial_preference_does_not_confirm_future_override(self) -> None:
        self.agent.reset("uncertain", {})
        response = self.agent.respond(
            "uncertain",
            "I'm shopping for Shoes. My current preference is: Wide fit.",
            1,
            10,
        )

        posterior = self.agent.scenario_posteriors["uncertain"]
        state = self.agent.sessions["uncertain"]
        self.assertEqual(state.scenario, "unconfirmed")
        self.assertIsNone(posterior.confirmed)
        self.assertGreater(posterior.probabilities["intent_override"], 0.0)
        self.assertLess(posterior.probabilities["intent_override"], 1.0)
        self.assertTrue(response["recommendations"])
        self.assertTrue(state.last_recommendations_scored)

    def test_late_override_rolls_back_provisional_rejections(self) -> None:
        self.agent.reset("rollback", {})
        first = self.agent.respond(
            "rollback",
            "I'm looking for Shoes. Wide fit",
            1,
            10,
        )
        self.assertEqual(first["recommendations"], [{"parent_asin": "TARGET"}])

        self.agent.respond(
            "rollback",
            "For that, what matters is: Water resistant; Rubber sole.",
            2,
            10,
        )
        self.assertIn("TARGET", self.agent.sessions["rollback"].rejected)

        third = self.agent.respond(
            "rollback",
            (
                "Actually, ignore my earlier preference. "
                "What I need is: Water resistant."
            ),
            3,
            10,
        )

        self.assertNotIn("TARGET", self.agent.sessions["rollback"].rejected)
        self.assertEqual(third["recommendations"], [{"parent_asin": "TARGET"}])
        self.assertEqual(
            self.agent.scenario_posteriors["rollback"].confirmed,
            "intent_override",
        )

    def test_turn_four_without_override_closes_override_branch(self) -> None:
        posterior = ScenarioPosterior()
        posterior.observe(ParsedMessage(), 1)
        posterior.observe(ParsedMessage(action="add", payload="x"), 2)
        posterior.observe(ParsedMessage(action="add", payload="y"), 3)
        posterior.observe(ParsedMessage(action="ignore"), 4)

        self.assertEqual(posterior.probabilities["intent_override"], 0.0)
        self.assertNotEqual(posterior.confirmed, "intent_override")

    def test_agent_discards_rollback_history_after_turn_four(self) -> None:
        self.agent.reset("window", {})
        messages = (
            "I'm looking for Shoes, but I'm still exploring.",
            "I don't have a preference for other; please use your judgment.",
            "For that, what matters is: Leather upper; Foam sole.",
            "I don't have an additional preference for other.",
        )
        for turn, message in enumerate(messages, start=1):
            self.agent.respond("window", message, turn, 10)

        state = self.agent.sessions["window"]
        self.assertEqual(
            self.agent.scenario_posteriors["window"].probabilities[
                "intent_override"
            ],
            0.0,
        )
        self.assertEqual(state.pre_override_recommendations, set())

    def test_semantic_aliases_bridge_value_paraphrases(self) -> None:
        self.assertEqual(semantic_terms("not wet in rain"), {"waterproof"})
        self.assertEqual(semantic_terms("Water resistant"), {"waterproof"})
        self.assertEqual(semantic_terms("good traction"), {"traction"})
        self.assertEqual(semantic_terms("Rubber sole"), {"traction"})
        self.assertEqual(semantic_terms("mesh"), {"breathable"})

    def test_semantic_reply_promotes_target_without_exact_value(self) -> None:
        self.agent.reset("semantic", {})
        first = self.agent.respond(
            "semantic",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            10,
        )
        self.assertEqual(first["recommendations"][0]["parent_asin"], "POPULAR")

        second = self.agent.respond(
            "semantic",
            "For that, what matters is: not wet in rain; good traction.",
            2,
            10,
        )

        self.assertEqual(second["recommendations"][0]["parent_asin"], "TARGET")
        stats = self.agent.debug_algorithm_stats("semantic")
        self.assertTrue(stats["nlp_fallback"])
        self.assertEqual(stats["retrieval_mode"], "focus_tier")

    def test_unresolved_semantics_do_not_delete_recovery_universe(self) -> None:
        self.agent.reset("recovery", {})
        self.agent.respond(
            "recovery",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            10,
        )
        self.agent.respond(
            "recovery",
            "For that, what matters is: telepathic sparkle control.",
            2,
            10,
        )

        state = self.agent.sessions["recovery"]
        self.assertIn("TARGET", state.trusted_universe)
        self.assertTrue(state.nlp_fallback)


if __name__ == "__main__":
    unittest.main()
