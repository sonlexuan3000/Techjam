from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
if str(CANDIDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(CANDIDATE_ROOT))

from evaluator.local_evaluator import (
    coarse_category as evaluator_coarse_category,
    intent_card as evaluator_intent_card,
)
from tunglam_inverse_dp.agent import Agent, _coarse_category, _intent_card


class InverseSimulatorAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        products = [
            {
                "parent_asin": "TARGET",
                "title": "Target shoe",
                "features": [
                    "alpha feature",
                    "beta feature",
                    "gamma feature",
                    "delta feature",
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
                "parent_asin": "POPULAR_DISTRACTOR",
                "title": "Distractor shoe",
                "features": [
                    "one feature",
                    "two feature",
                    "three feature",
                    "four feature",
                ],
                "description": [],
                "price": None,
                "categories": ["Clothing", "Shoes"],
                "details": {},
                "average_rating": 4.9,
                "rating_number": 1000,
                "store": "Distractor Store",
            },
            {
                "parent_asin": "SECOND_DISTRACTOR",
                "title": "Second distractor shoe",
                "features": [
                    "wrong feature one",
                    "wrong feature two",
                    "wrong feature three",
                    "wrong feature four",
                ],
                "description": [],
                "price": None,
                "categories": ["Clothing", "Shoes"],
                "details": {},
                "average_rating": 4.7,
                "rating_number": 500,
                "store": "Second Store",
            },
        ]
        catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        self.catalog_path = catalog_path
        self.agent = Agent(
            catalog_path,
            prior_field="rating_number",
            prior_smoothing=0.0,
        )

    def test_other_reply_filters_exploration_candidates(self) -> None:
        self.agent.reset("session", {})
        first = self.agent.respond(
            "session", "I'm looking for Shoes, but I'm still exploring.", 1, 10
        )
        self.assertEqual(
            first["recommendations"][0]["parent_asin"], "POPULAR_DISTRACTOR"
        )
        self.assertEqual(len(first["recommendations"]), 1)

        second = self.agent.respond(
            "session",
            "For that, what matters is: alpha feature; beta feature.",
            2,
            10,
        )
        self.assertEqual(second["recommendations"], [{"parent_asin": "TARGET"}])

    def test_evaluator_card_and_category_parity(self) -> None:
        product = {
            "parent_asin": "PARITY",
            "title": "Blue cotton walking shoe",
            "features": ["Water resistant", "Machine Wash"],
            "details": {"Closure": "Lace-Up"},
            "description": ["Everyday outdoor shoe"],
            "categories": ["Clothing", "Shoes", "Walking"],
            "store": "Parity Store",
            "price": 49.99,
        }
        card = evaluator_intent_card(product)

        self.assertEqual(
            _intent_card(product),
            (
                tuple(card["hard_constraints"]),
                tuple(card["soft_preferences"]),
            ),
        )
        self.assertEqual(
            _coarse_category(product["categories"]),
            evaluator_coarse_category(product["categories"]),
        )

    def test_intent_override_is_replayed_against_product_card(self) -> None:
        self.agent.reset("override", {})
        self.agent.respond(
            "override", "I'm looking for Shoes. delta feature", 1, 10
        )
        self.agent.respond(
            "override",
            "For that, what matters is: alpha feature; beta feature.",
            2,
            10,
        )
        response = self.agent.respond(
            "override",
            "Actually, ignore my earlier preference. What I need is: alpha feature.",
            3,
            10,
        )
        self.assertEqual(response["recommendations"], [{"parent_asin": "TARGET"}])

    def test_belief_is_proportional_to_rating_number(self) -> None:
        hypotheses = (("POPULAR_DISTRACTOR", 0), ("TARGET", 0))
        weights, total = self.agent._belief_weights(hypotheses)

        self.assertEqual(weights, [1000.0, 10.0])
        self.assertEqual(total, 1010.0)

    def test_external_prior_requires_an_explicit_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "prior_path is required"):
            Agent(self.catalog_path, prior_field="verified_reviews_365d")

    def test_external_prior_is_loaded_with_smoothing(self) -> None:
        prior_path = Path(self.temporary_directory.name) / "review_prior.tsv"
        prior_path.write_text(
            "parent_asin\tverified_reviews_365d\n"
            "TARGET\t40\n"
            "POPULAR_DISTRACTOR\t2\n"
            "SECOND_DISTRACTOR\t0\n",
            encoding="utf-8",
        )
        agent = Agent(
            self.catalog_path,
            prior_field="verified_reviews_365d",
            prior_smoothing=1.0,
            prior_path=prior_path,
        )

        weights, total = agent._belief_weights(
            (("TARGET", 0), ("POPULAR_DISTRACTOR", 0), ("SECOND_DISTRACTOR", 0))
        )

        self.assertEqual(weights, [41.0, 3.0, 1.0])
        self.assertEqual(total, 45.0)
        self.assertEqual(
            sorted(agent.products, key=agent._rank_key),
            ["TARGET", "POPULAR_DISTRACTOR", "SECOND_DISTRACTOR"],
        )

    def test_missing_external_prior_rows_keep_products_possible(self) -> None:
        prior_path = Path(self.temporary_directory.name) / "sparse_prior.tsv"
        prior_path.write_text(
            "parent_asin\tverified_reviews_365d\nTARGET\t9\n",
            encoding="utf-8",
        )
        agent = Agent(
            self.catalog_path,
            prior_field="verified_reviews_365d",
            prior_smoothing=1.0,
            prior_path=prior_path,
        )

        weights, total = agent._belief_weights(
            (("TARGET", 0), ("POPULAR_DISTRACTOR", 0))
        )

        self.assertEqual(weights, [10.0, 1.0])
        self.assertEqual(total, 11.0)

    def test_external_prior_rejects_malformed_assets(self) -> None:
        prior_path = Path(self.temporary_directory.name) / "malformed_prior.tsv"
        malformed_payloads = (
            "parent_asin\twrong_field\nTARGET\t1\n",
            "parent_asin\tverified_reviews_365d\nTARGET\n",
            "parent_asin\tverified_reviews_365d\nTARGET\t1.5\n",
            "parent_asin\tverified_reviews_365d\nTARGET\t-1\n",
            "parent_asin\tverified_reviews_365d\nTARGET\t1\nTARGET\t2\n",
        )
        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                prior_path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    Agent(
                        self.catalog_path,
                        prior_field="verified_reviews_365d",
                        prior_smoothing=1.0,
                        prior_path=prior_path,
                    )

    def test_prior_path_is_rejected_for_catalog_or_uniform_modes(self) -> None:
        prior_path = Path(self.temporary_directory.name) / "unused.tsv"
        prior_path.write_text("unused\n", encoding="utf-8")
        for prior_field in ("uniform", "rating_number"):
            with self.subTest(prior_field=prior_field):
                with self.assertRaisesRegex(ValueError, "only valid"):
                    Agent(
                        self.catalog_path,
                        prior_field=prior_field,
                        prior_path=prior_path,
                    )
        for smoothing in (-1.0, float("nan"), float("inf")):
            with self.subTest(smoothing=smoothing):
                with self.assertRaisesRegex(ValueError, "prior_smoothing"):
                    Agent(
                        self.catalog_path,
                        prior_field="uniform",
                        prior_smoothing=smoothing,
                    )

    def test_external_prior_never_reintroduces_a_hard_mismatch(self) -> None:
        prior_path = Path(self.temporary_directory.name) / "adversarial_prior.tsv"
        prior_path.write_text(
            "parent_asin\tverified_reviews_365d\n"
            "TARGET\t0\n"
            "POPULAR_DISTRACTOR\t1000000\n"
            "SECOND_DISTRACTOR\t500000\n",
            encoding="utf-8",
        )
        agent = Agent(
            self.catalog_path,
            prior_field="verified_reviews_365d",
            prior_smoothing=1.0,
            prior_path=prior_path,
        )
        agent.reset("hard-filter", {})
        agent.respond(
            "hard-filter",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            10,
        )

        response = agent.respond(
            "hard-filter",
            "For that, what matters is: alpha feature; beta feature.",
            2,
            10,
        )

        self.assertEqual(response["recommendations"], [{"parent_asin": "TARGET"}])

    def test_uniform_prior_removes_all_catalog_popularity_bias(self) -> None:
        agent = Agent(
            self.catalog_path,
            prior_field="uniform",
            prior_smoothing=999.0,
        )
        hypotheses = (("POPULAR_DISTRACTOR", 0), ("TARGET", 0))

        weights, total = agent._belief_weights(hypotheses)

        self.assertEqual(weights, [1.0, 1.0])
        self.assertEqual(total, 2.0)
        self.assertEqual(
            sorted(agent.products, key=agent._rank_key),
            ["POPULAR_DISTRACTOR", "SECOND_DISTRACTOR", "TARGET"],
        )

    def test_dp_can_choose_an_intermediate_cutoff(self) -> None:
        products = {}
        for index in range(5):
            parent_asin = f"PRODUCT_{index}"
            template = self.agent.products["TARGET"]
            products[parent_asin] = type(template)(
                parent_asin=parent_asin,
                category=template.category,
                hard=template.hard,
                soft=template.soft,
                rating_number=1,
                average_rating=template.average_rating,
                text=template.text,
                prior_weight=1.0,
            )

        original_products = self.agent.products
        self.agent.products = products
        self.addCleanup(setattr, self.agent, "products", original_products)
        hypotheses = tuple(
            (parent_asin, (1 << len(product.constraints)) - 1)
            for parent_asin, product in products.items()
        )
        self.agent._dp_cache.clear()

        _, optimal_k = self.agent._dp_value(9, hypotheses, False, 10)

        self.assertEqual(optimal_k, 3)

    def test_empty_soft_filter_falls_back_to_hard_matches(self) -> None:
        catalog_path = Path(self.temporary_directory.name) / "fallback.jsonl"
        products = [
            {
                "parent_asin": f"PRODUCT_{index}",
                "title": f"Fallback shoe {index}",
                "features": [
                    "shared hard one",
                    "shared hard two",
                    f"soft preference {index}a",
                    f"soft preference {index}b",
                ],
                "description": [],
                "price": None,
                "categories": ["Clothing", "Shoes"],
                "details": {},
                "average_rating": 4.0,
                "rating_number": 100 - index,
                "store": "Fallback Store",
            }
            for index in range(4)
        ]
        catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        agent = Agent(
            catalog_path,
            prior_field="rating_number",
            prior_smoothing=0.0,
        )
        agent.reset("fallback", {})
        agent.respond(
            "fallback",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            1,
        )
        agent.respond(
            "fallback",
            "For that, what matters is: shared hard one; shared hard two.",
            2,
            1,
        )
        response = agent.respond(
            "fallback",
            "For that, what matters is: unavailable soft one; unavailable soft two.",
            3,
            1,
        )

        state = agent.sessions["fallback"]
        surviving = [
            parent_asin
            for parent_asin in state.trusted_universe
            if parent_asin not in state.rejected
        ]
        self.assertTrue(surviving)
        self.assertTrue(
            all(
                agent.products[parent_asin].hard
                == ("shared hard one", "shared hard two")
                for parent_asin in surviving
            )
        )
        self.assertTrue(state.nlp_fallback)
        self.assertEqual(len(response["recommendations"]), 1)

    def test_explicit_grounded_hard_requirement_is_hard_filtered(self) -> None:
        self.agent.reset("grounded-hard", {})
        response = self.agent.respond(
            "grounded-hard",
            "I need Shoes. My main requirement is: alpha feature.",
            1,
            10,
        )

        self.assertEqual(
            self.agent.sessions["grounded-hard"].focus_candidates,
            ["TARGET"],
        )
        self.assertIn(
            "POPULAR_DISTRACTOR",
            self.agent.sessions["grounded-hard"].trusted_universe,
        )
        self.assertEqual(response["recommendations"], [{"parent_asin": "TARGET"}])

    def test_ungrounded_paraphrase_cannot_delete_the_target(self) -> None:
        self.agent.reset("uncertain", {})
        self.agent.respond(
            "uncertain",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            1,
        )
        self.agent.respond(
            "uncertain",
            "What matters to me is: stays dry through a storm.",
            2,
            2,
        )

        state = self.agent.sessions["uncertain"]
        self.assertTrue(state.nlp_fallback)
        self.assertIn("TARGET", state.trusted_universe)
        self.assertNotIn("TARGET", state.rejected)

    def test_wrong_grounded_paraphrase_is_focus_only(self) -> None:
        self.agent.reset("wrong-focus", {})
        self.agent.respond(
            "wrong-focus",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            1,
        )
        response = self.agent.respond(
            "wrong-focus",
            "My priorities are: wrong feature one; wrong feature two.",
            2,
            2,
        )

        state = self.agent.sessions["wrong-focus"]
        self.assertEqual(state.focus_candidates, ["SECOND_DISTRACTOR"])
        self.assertIn("TARGET", state.trusted_universe)
        self.assertNotIn("TARGET", state.rejected)
        self.assertEqual(
            response["recommendations"],
            [{"parent_asin": "SECOND_DISTRACTOR"}],
        )

    def test_protocol_trust_does_not_restart_after_a_paraphrase(self) -> None:
        self.agent.reset("broken-chain", {})
        self.agent.respond(
            "broken-chain",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            1,
        )
        self.agent.respond(
            "broken-chain",
            "My priorities are: wrong feature one; wrong feature two.",
            2,
            1,
        )
        self.agent.respond(
            "broken-chain",
            "For that, what matters is: alpha feature; beta feature.",
            3,
            10,
        )

        state = self.agent.sessions["broken-chain"]
        self.assertTrue(state.nlp_fallback)
        self.assertIn("TARGET", state.trusted_universe)
        self.assertNotIn("TARGET", state.rejected)

    def test_late_override_repairs_pre_override_rejections_only_once(self) -> None:
        self.agent.reset("late-override", {})
        first = self.agent.respond(
            "late-override",
            "Show me Shoes with delta feature.",
            1,
            1,
        )
        first_asin = first["recommendations"][0]["parent_asin"]
        self.agent.respond("late-override", "Give me a moment.", 2, 1)
        self.assertIn(first_asin, self.agent.sessions["late-override"].rejected)

        self.agent.respond(
            "late-override",
            "Actually, my new requirement is: alpha feature.",
            3,
            1,
        )
        state = self.agent.sessions["late-override"]
        self.assertNotIn(first_asin, state.rejected)

        scored = state.last_recommendations[0]
        self.agent.respond(
            "late-override",
            "Actually, my new requirement is: beta feature.",
            4,
            1,
        )
        self.assertIn(scored, state.rejected)

    def test_fallback_dp_mask_keeps_constraints_already_asked(self) -> None:
        product = self.agent.products["TARGET"]
        messages = [
            "I'm looking for Shoes. a different soft preference",
            "For that, what matters is: alpha feature; beta feature.",
            "Actually, ignore my earlier preference. What I need is: alpha feature.",
            "For that, what matters is: unavailable soft one; unavailable soft two.",
        ]

        self.assertTrue(self.agent._matches_hard_conversation(product, messages))
        self.assertEqual(
            self.agent._disclosed_mask(product, messages),
            (1 << len(product.constraints)) - 1,
        )

    def test_paraphrased_wrappers_are_canonicalized_before_filtering(self) -> None:
        self.agent.reset("paraphrase", {})
        self.agent.respond(
            "paraphrase",
            "Help me explore Shoes; my preferences are still open.",
            1,
            10,
        )
        response = self.agent.respond(
            "paraphrase",
            (
                "My relevant requirements or preferences are: "
                "alpha feature; beta feature."
            ),
            2,
            10,
        )

        self.assertEqual(response["recommendations"], [{"parent_asin": "TARGET"}])
        self.assertEqual(
            self.agent.sessions["paraphrase"].messages,
            [
                "I'm looking for Shoes, but I'm still exploring.",
                "For that, what matters is: alpha feature; beta feature.",
            ],
        )

    def test_paraphrased_override_reaches_the_existing_core_path(self) -> None:
        self.agent.reset("paraphrased-override", {})
        self.agent.respond(
            "paraphrased-override",
            "I'm shopping for Shoes. One thing I care about is: delta feature.",
            1,
            10,
        )
        self.agent.respond(
            "paraphrased-override",
            "For that, these points matter to me: alpha feature; beta feature.",
            2,
            10,
        )
        response = self.agent.respond(
            "paraphrased-override",
            (
                "Actually, set aside my earlier preference. "
                "What I need now is: alpha feature."
            ),
            3,
            10,
        )

        self.assertEqual(response["recommendations"], [{"parent_asin": "TARGET"}])


if __name__ == "__main__":
    unittest.main()
