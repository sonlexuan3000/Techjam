from __future__ import annotations

from collections import Counter
import unittest

from frontend.server import (
    DEFAULT_CANDIDATE_NAME,
    DEFAULT_ENTRYPOINT,
    DEFAULT_GENERATED_DATASET,
    DEFAULT_GENERATED_SESSION_LIMIT,
    SimulationService,
    UnknownSessionError,
    label_sessions,
    picker_session,
    product_view,
    select_generated_sessions,
)


def sample(*, scenario: str = "buying", behavior: dict | None = None) -> dict:
    return {
        "category_bucket": "clothing",
        "difficulty_bucket": "easy",
        "ground_truth": {"parent_asin": "B_TARGET"},
        "sample_id": f"test_{scenario}",
        "scenario_type": scenario,
        "user_profile": {
            "average_prior_rating": 4.5,
            "preference_tags": ["comfort", "fit"],
            "purchase_frequency": "3-4 prior purchases",
            "rating_style": "usually positive",
            "summary": "Prior purchases emphasize comfort and fit.",
        },
        "intent_card": {
            "target_category": "Target shirt",
            "hard_constraints": ["cotton", "color: blue"],
            "soft_preferences": ["machine washable", "relaxed fit"],
        },
        "behavior": behavior or {"scenario_type": scenario},
    }


class ScriptedAgent:
    def __init__(self, responses: dict[int, dict]) -> None:
        self.responses = responses
        self.reset_calls: list[tuple[str, dict]] = []
        self.respond_calls: list[tuple[str, str, int, int]] = []
        self.last_rank_state = {}
        self.last_recommendation_policy = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.reset_calls.append((session_id, user_profile))

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        self.respond_calls.append((session_id, user_message, turn, top_k))
        self.last_rank_state = {"intent": f"intent_{turn}", "mode": "buying"}
        self.last_recommendation_policy = {"policy": "test_policy", "k": 3}
        return self.responses.get(
            turn,
            {
                "message": "What else matters?",
                "ask_attribute": "other",
                "recommendations": [],
            },
        )

    def debug_algorithm_stats(self, session_id: str) -> dict:
        turn = self.respond_calls[-1][2]
        return {
            "hypothesis_count": 40 - turn,
            "focus_count": 40 - turn,
            "recovery_count": 0,
            "evidence_count": turn,
            "rejected_count": max(0, turn - 1),
            "dp_state_count": 20 + turn,
            "selected_k": 3,
            "retrieval_mode": "exact_protocol",
            "policy_mode": "finite_horizon_dp",
            "prior_mode": "uniform",
            "nlp_fallback": False,
        }


def service_for(test_sample: dict, agent: ScriptedAgent) -> SimulationService:
    target_product = {
        "parent_asin": "B_TARGET",
        "title": "Target cotton shirt",
        "features": ["cotton"],
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Shirts"],
        "price": 29.99,
        "average_rating": 4.7,
        "rating_number": 120,
        "store": "Target Store",
    }
    other_product = {
        "parent_asin": "B_OTHER",
        "title": "Another shirt",
        "features": ["polyester"],
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Shirts"],
        "price": 19.0,
        "average_rating": 4.1,
        "rating_number": 50,
        "store": "Other Store",
    }
    return SimulationService(
        agent=agent,
        samples=[test_sample],
        catalog_ids={"B_TARGET", "B_OTHER"},
        target_categories={"B_TARGET": target_product["categories"]},
        target_products={"B_TARGET": target_product},
        product_views={
            "B_TARGET": product_view(target_product),
            "B_OTHER": product_view(other_product),
        },
        candidate_name="test-candidate",
    )


class FrontendSimulationTests(unittest.TestCase):
    def test_frontend_defaults_to_selected_production_agent(self) -> None:
        self.assertEqual(DEFAULT_ENTRYPOINT.parent.name, "tunglam-inverse-dp-review-prior")
        self.assertEqual(DEFAULT_ENTRYPOINT.name, "entrypoint.py")
        self.assertEqual(
            DEFAULT_CANDIDATE_NAME,
            "Offline review-prior inverse-DP · production",
        )
        self.assertEqual(DEFAULT_GENERATED_DATASET.name, "dev_set.jsonl")
        self.assertEqual(DEFAULT_GENERATED_SESSION_LIMIT, 20)

    def test_picker_payload_never_exposes_ground_truth_or_hidden_intent(self) -> None:
        payload = picker_session(label_sessions([sample()], "public")[0])

        self.assertNotIn("ground_truth", payload)
        self.assertNotIn("intent_card", payload)
        self.assertNotIn("behavior", payload)
        self.assertNotIn("_frontend_dataset_source", payload)
        self.assertEqual(payload["sample_id"], "test_buying")
        self.assertEqual(payload["dataset_source"], "public")
        self.assertEqual(payload["user_profile"]["preference_tags"], ["comfort", "fit"])

    def test_generated_picker_fields_are_derived_without_target_data(self) -> None:
        generated = sample(scenario="boundary")
        generated.pop("difficulty_bucket")
        generated.pop("category_bucket")
        generated = label_sessions([generated], "generated_dev")[0]

        payload = picker_session(generated)

        self.assertEqual(payload["dataset_source"], "generated_dev")
        self.assertEqual(payload["difficulty_bucket"], "medium")
        self.assertEqual(payload["category_bucket"], "clothing")
        self.assertNotIn("ground_truth", payload)

    def test_generated_preview_is_deterministic_and_scenario_proportional(self) -> None:
        scenario_counts = {
            "buying": 40,
            "browsing": 40,
            "intent_override": 15,
            "boundary": 5,
        }
        generated = [
            {"sample_id": f"generated_{scenario}_{index:03d}", "scenario_type": scenario}
            for scenario, count in scenario_counts.items()
            for index in range(count)
        ]

        selected = select_generated_sessions(generated, 20)
        selected_again = select_generated_sessions(list(reversed(generated)), 20)

        self.assertEqual(
            Counter(item["scenario_type"] for item in selected),
            Counter({"buying": 8, "browsing": 8, "intent_override": 3, "boundary": 1}),
        )
        self.assertEqual(
            [item["sample_id"] for item in selected],
            [item["sample_id"] for item in selected_again],
        )

    def test_simulation_hydrates_ranked_products_and_stops_on_hit(self) -> None:
        agent = ScriptedAgent(
            {
                1: {
                    "message": "Here are two options.",
                    "ask_attribute": "other",
                    "recommendations": [
                        {"parent_asin": "NOT_IN_CATALOG"},
                        {"parent_asin": "B_OTHER"},
                        {"parent_asin": "B_TARGET"},
                        {"parent_asin": "B_TARGET"},
                    ],
                }
            }
        )
        service = service_for(sample(), agent)

        result = service.simulate("test_buying")

        self.assertTrue(result["outcome"]["hit"])
        self.assertEqual(result["outcome"]["first_hit_turn"], 1)
        self.assertEqual(result["outcome"]["best_rank"], 2)
        self.assertEqual(len(result["transcript"]), 1)
        recommendations = result["transcript"][0]["assistant"]["recommendations"]
        self.assertEqual([item["parent_asin"] for item in recommendations], ["B_OTHER", "B_TARGET"])
        self.assertTrue(recommendations[1]["is_target"])
        self.assertEqual(recommendations[1]["title"], "Target cotton shirt")
        self.assertEqual(agent.respond_calls[0][3], 10)
        calculation = result["transcript"][0]["assistant"]["calculation"]
        self.assertEqual(
            {
                "catalog_products": calculation["catalog_products"],
                "shortlist_size": calculation["shortlist_size"],
                "new_products": calculation["new_products"],
                "products_shown": calculation["products_shown"],
                "turn": calculation["turn"],
            },
            {
                "catalog_products": 2,
                "shortlist_size": 2,
                "new_products": 2,
                "products_shown": 2,
                "turn": 1,
            },
        )
        self.assertGreaterEqual(calculation["elapsed_ms"], 0)
        self.assertEqual(calculation["hypothesis_count"], 39)
        self.assertEqual(calculation["evidence_count"], 1)
        self.assertEqual(calculation["dp_state_count"], 21)
        self.assertEqual(calculation["selected_k"], 3)
        self.assertEqual(calculation["retrieval_mode"], "exact_protocol")
        self.assertEqual(calculation["policy_mode"], "finite_horizon_dp")
        self.assertEqual(calculation["prior_mode"], "uniform")
        self.assertNotIn("target", calculation)
        self.assertNotIn("target_rank", calculation)

    def test_session_listing_reports_dataset_source_counts(self) -> None:
        generated_sample = label_sessions([sample()], "generated_dev")[0]
        service = service_for(generated_sample, ScriptedAgent({}))

        payload = service.list_sessions()

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["source_counts"], {"generated_dev": 1})
        self.assertEqual(payload["sessions"][0]["dataset_source"], "generated_dev")

    def test_override_target_is_not_scored_until_override_is_applied(self) -> None:
        override_behavior = {
            "scenario_type": "intent_override",
            "override": {
                "turn": 2,
                "old_value": "color: red",
                "new_value": "color: blue",
                "message": "Actually, ignore red. What I need is: color: blue.",
            },
        }
        agent = ScriptedAgent(
            {
                1: {
                    "message": "An early guess.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                },
                2: {
                    "message": "Updated options.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                },
            }
        )
        test_sample = sample(scenario="intent_override", behavior=override_behavior)
        service = service_for(test_sample, agent)

        result = service.simulate("test_intent_override")

        self.assertEqual(result["outcome"]["first_hit_turn"], 2)
        self.assertEqual(len(result["transcript"]), 2)
        self.assertFalse(result["transcript"][0]["assistant"]["recommendations"][0]["is_target"])
        self.assertEqual(
            result["transcript"][1]["user"]["message"],
            "Actually, ignore red. What I need is: color: blue.",
        )
        self.assertTrue(result["transcript"][1]["assistant"]["recommendations"][0]["is_target"])
        first_calculation = result["transcript"][0]["assistant"]["calculation"]
        second_calculation = result["transcript"][1]["assistant"]["calculation"]
        self.assertEqual(first_calculation["new_products"], 1)
        self.assertEqual(first_calculation["products_shown"], 1)
        self.assertEqual(second_calculation["new_products"], 0)
        self.assertEqual(second_calculation["products_shown"], 1)

    def test_replays_reuse_one_candidate_session_slot(self) -> None:
        agent = ScriptedAgent(
            {
                1: {
                    "message": "Found it.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                }
            }
        )
        service = service_for(sample(), agent)

        first = service.simulate("test_buying")
        second = service.simulate("test_buying")

        self.assertNotEqual(first["simulation_id"], second["simulation_id"])
        self.assertEqual([call[0] for call in agent.reset_calls], ["frontend_preview", "frontend_preview"])

    def test_unknown_session_has_a_dedicated_lookup_error(self) -> None:
        service = service_for(sample(), ScriptedAgent({}))

        with self.assertRaisesRegex(UnknownSessionError, "unknown session"):
            service.simulate("missing")

    def test_public_style_session_materializes_hidden_dialogue_fields(self) -> None:
        public_style_sample = sample()
        public_style_sample.pop("intent_card")
        public_style_sample.pop("behavior")
        agent = ScriptedAgent(
            {
                2: {
                    "message": "This one matches.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                }
            }
        )
        service = service_for(public_style_sample, agent)

        result = service.simulate("test_buying")

        self.assertEqual(result["outcome"]["first_hit_turn"], 2)
        self.assertIn(
            "I'm looking for Women Shirts",
            result["transcript"][0]["user"]["message"],
        )
        self.assertTrue(
            result["transcript"][1]["user"]["message"].startswith(
                "For that, what matters is:"
            )
        )


if __name__ == "__main__":
    unittest.main()
