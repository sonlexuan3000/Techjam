from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
if str(CANDIDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(CANDIDATE_ROOT))

from src.agent import Agent


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

    def test_review_prior_is_loaded_with_smoothing(self) -> None:
        prior_path = Path(self.temporary_directory.name) / "review_prior.tsv"
        prior_path.write_text(
            "parent_asin\tverified_reviews_365d\n"
            "TARGET\t7\n"
            "POPULAR_DISTRACTOR\t2\n",
            encoding="utf-8",
        )
        agent = Agent(self.catalog_path, review_features_path=prior_path)

        self.assertEqual(agent.products["TARGET"].prior_weight, 8.0)
        self.assertEqual(
            agent.products["POPULAR_DISTRACTOR"].prior_weight, 3.0
        )

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
            ["POPULAR_DISTRACTOR", "TARGET"],
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

        surviving = agent.sessions["fallback"].current_candidates
        self.assertTrue(surviving)
        self.assertTrue(
            all(
                agent.products[parent_asin].hard
                == ("shared hard one", "shared hard two")
                for parent_asin in surviving
            )
        )
        self.assertEqual(len(response["recommendations"]), 1)

    def test_soft_fallback_never_restores_a_hard_mismatch(self) -> None:
        self.agent.reset("hard-mismatch", {})
        self.agent.respond(
            "hard-mismatch",
            "I'm looking for Shoes, but I'm still exploring.",
            1,
            1,
        )
        response = self.agent.respond(
            "hard-mismatch",
            "For that, what matters is: nonexistent hard; impossible hard.",
            2,
            1,
        )

        self.assertEqual(
            self.agent.sessions["hard-mismatch"].current_candidates, []
        )
        self.assertEqual(response["recommendations"], [])

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
