from __future__ import annotations

import unittest
from types import SimpleNamespace

from frontend.server import (
    DEFAULT_CANDIDATE_NAME,
    DEFAULT_ENTRYPOINT,
    SimulationService,
    UnknownSessionError,
    picker_session,
    product_view,
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


class TraceableAgent(ScriptedAgent):
    def __init__(
        self,
        responses: dict[int, dict],
        *,
        nlp_fallback: bool = False,
        pre_override: bool = False,
    ) -> None:
        super().__init__(responses)
        self.nlp_fallback = nlp_fallback
        self.pre_override = pre_override
        self.prior_field = "verified_reviews_365d"
        self.prior_smoothing = 1.0
        self.products = {
            "B_TARGET": SimpleNamespace(prior_weight=7.0),
            "B_OTHER": SimpleNamespace(prior_weight=1.0),
        }
        self.sessions: dict[str, SimpleNamespace] = {}

    def reset(self, session_id: str, user_profile: dict) -> None:
        super().reset(session_id, user_profile)
        focus = [] if self.nlp_fallback else ["B_TARGET", "B_OTHER"]
        self.sessions[session_id] = SimpleNamespace(
            initial_candidates=[] if self.nlp_fallback else ["B_TARGET", "B_OTHER"],
            current_candidates=focus,
            focus_candidates=focus,
            trusted_universe=("B_TARGET", "B_OTHER"),
            rejected=set(),
            scenario=(
                "intent_override"
                if self.pre_override
                else "exploring" if self.nlp_fallback else "buying"
            ),
            nlp_fallback=self.nlp_fallback,
            override_seen=False,
            override_applied=not self.pre_override,
        )

    def debug_state(self, session_id: str) -> dict:
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return {
            "current_intent": [
                {
                    "text": "cotton",
                    "slot": "material",
                    "active": True,
                }
            ],
            "negative_evidence": [],
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

    def test_picker_payload_never_exposes_ground_truth_or_hidden_intent(self) -> None:
        payload = picker_session(sample())

        self.assertNotIn("ground_truth", payload)
        self.assertNotIn("intent_card", payload)
        self.assertNotIn("behavior", payload)
        self.assertEqual(payload["sample_id"], "test_buying")
        self.assertEqual(payload["user_profile"]["preference_tags"], ["comfort", "fit"])

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

    def test_production_style_trace_is_target_free_and_explains_ranking(self) -> None:
        agent = TraceableAgent(
            {
                1: {
                    "message": "This is the strongest current match.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                }
            }
        )
        service = service_for(sample(), agent)

        result = service.simulate("test_buying")
        turn = result["transcript"][0]
        trace = turn["assistant"]["trace"]

        self.assertEqual(trace["route"], "exact-inverse")
        self.assertEqual(trace["policy"], "finite-horizon DP")
        self.assertEqual(trace["active_candidates"], 2)
        self.assertEqual(trace["k"], 1)
        self.assertEqual(trace["prior"], "verified reviews (365d) + 1")
        self.assertEqual(trace["evidence"][0]["text"], "cotton")
        self.assertEqual(
            turn["assistant"]["recommendations"][0]["ranking_signal"],
            {
                "label": "Verified reviews · 365d",
                "value": 6,
                "weight": 7.0,
            },
        )

        forbidden = {"target", "ground_truth", "target_rank", "is_target", "hit"}

        def assert_no_forbidden_keys(value: object) -> None:
            if isinstance(value, dict):
                self.assertTrue(forbidden.isdisjoint(value))
                for child in value.values():
                    assert_no_forbidden_keys(child)
            elif isinstance(value, list):
                for child in value:
                    assert_no_forbidden_keys(child)

        assert_no_forbidden_keys(trace)
        self.assertNotIn("B_TARGET", repr(trace))
        self.assertNotIn("B_TARGET", repr(agent.respond_calls[0]))

        # The same target-free trace must identify the production pre-override
        # K=1 guard accurately instead of presenting it as a DP decision.
        agent = TraceableAgent(
            {
                1: {
                    "message": "One provisional option while your intent can still change.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                }
            },
            pre_override=True,
        )
        service = service_for(sample(), agent)

        result = service.simulate("test_buying")
        trace = result["transcript"][0]["assistant"]["trace"]

        self.assertEqual(trace["scenario"], "intent_override")
        self.assertEqual(trace["policy"], "pre-override guard")
        self.assertEqual(trace["k"], 1)
        self.assertFalse(trace["override_applied"])
        self.assertIn("not scoreable", trace["explanation"])

    def test_recovery_trace_keeps_the_trusted_universe_visible(self) -> None:
        agent = TraceableAgent(
            {
                1: {
                    "message": "I need one more detail.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_OTHER"}],
                },
                2: {
                    "message": "Now I can rank the match.",
                    "ask_attribute": "other",
                    "recommendations": [{"parent_asin": "B_TARGET"}],
                },
            },
            nlp_fallback=True,
        )
        service = service_for(sample(), agent)

        result = service.simulate("test_buying")
        trace = result["transcript"][0]["assistant"]["trace"]

        self.assertEqual(trace["route"], "nlp-recovery")
        self.assertEqual(trace["policy"], "conservative recovery")
        self.assertEqual(trace["trusted_candidates"], 2)
        self.assertEqual(trace["active_candidates"], 2)

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
