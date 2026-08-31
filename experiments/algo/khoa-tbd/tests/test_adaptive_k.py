from __future__ import annotations

import importlib.util
import inspect
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "adaptive_k.py"
SPEC = importlib.util.spec_from_file_location("khoa_tbd_adaptive_k", MODULE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import setup failure
    raise RuntimeError(f"cannot import adaptive-K module from {MODULE_PATH}")
adaptive_k = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adaptive_k
SPEC.loader.exec_module(adaptive_k)

# Load the candidate Agent by exact path. Its direct-file fallback imports the
# adaptive-K module under this short name, avoiding ambiguity with other
# experiment folders named ``src`` during repository-wide discovery.
sys.modules.setdefault("adaptive_k", adaptive_k)
AGENT_PATH = Path(__file__).resolve().parents[1] / "src" / "agent.py"
AGENT_SPEC = importlib.util.spec_from_file_location("khoa_tbd_agent", AGENT_PATH)
if AGENT_SPEC is None or AGENT_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import candidate Agent from {AGENT_PATH}")
agent_module = importlib.util.module_from_spec(AGENT_SPEC)
sys.modules[AGENT_SPEC.name] = agent_module
AGENT_SPEC.loader.exec_module(agent_module)


class AdaptiveKMathTest(unittest.TestCase):
    def test_technical_utility_matches_evaluator_contribution(self) -> None:
        self.assertAlmostEqual(adaptive_k.technical_utility(turn=1, rank=1), 1.0)
        self.assertAlmostEqual(adaptive_k.technical_utility(turn=1, rank=10), 0.73)
        self.assertAlmostEqual(adaptive_k.technical_utility(turn=10, rank=1), 0.82)
        self.assertAlmostEqual(adaptive_k.technical_utility(turn=10, rank=10), 0.55)

        self.assertGreater(
            adaptive_k.technical_utility(turn=1, rank=1),
            adaptive_k.technical_utility(turn=1, rank=3),
        )
        self.assertGreater(
            adaptive_k.technical_utility(turn=1, rank=3),
            adaptive_k.technical_utility(turn=2, rank=3),
        )

    def test_projected_cdf_is_bounded_and_monotone(self) -> None:
        projected = adaptive_k.project_monotone_cdf(
            {1: 0.60, 3: -0.20, 5: 1.20, 10: 0.80}
        )

        self.assertEqual(set(projected), {1, 3, 5, 10})
        values = [projected[k] for k in (1, 3, 5, 10)]
        self.assertTrue(all(math.isfinite(value) for value in values))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in values))
        self.assertEqual(values, sorted(values))

    def test_cdf_conversion_preserves_each_probability_band(self) -> None:
        cdf = {1: 0.20, 3: 0.50, 5: 0.70, 10: 0.90}
        masses, tail = adaptive_k.cdf_to_rank_masses(cdf)

        self.assertAlmostEqual(masses[1], 0.20)
        self.assertAlmostEqual(sum(masses[r] for r in (2, 3)), 0.30)
        self.assertAlmostEqual(sum(masses[r] for r in (4, 5)), 0.20)
        self.assertAlmostEqual(sum(masses[r] for r in range(6, 11)), 0.20)
        self.assertAlmostEqual(tail, 0.10)
        self.assertAlmostEqual(sum(masses.values()) + tail, 1.0)
        self.assertTrue(all(value >= 0.0 for value in masses.values()))

    def test_literal_spec_q_is_monotone_and_degenerates_to_ten(self) -> None:
        # Under the requested formula, increasing K moves probability mass from
        # a negative continuation term to a positive hit utility. Therefore
        # Q_spec cannot decrease when utility and V_next are non-negative.
        masses = {
            1: 0.20,
            2: 0.10,
            3: 0.10,
            4: 0.10,
            5: 0.10,
            6: 0.10,
            7: 0.05,
            8: 0.05,
            9: 0.05,
            10: 0.05,
        }
        q_spec, _ = adaptive_k.compute_q_values(
            masses,
            turn=1,
            continuation_values={k: 0.70 for k in (1, 3, 5, 10)},
        )

        ordered = [q_spec[k] for k in (1, 3, 5, 10)]
        self.assertEqual(ordered, sorted(ordered))
        self.assertEqual(max(q_spec, key=q_spec.get), 10)

    def test_bellman_continuation_can_prefer_a_short_list(self) -> None:
        # If the target is currently fourth but a next-turn hit is worth more,
        # K=1 or K=3 should continue instead of accepting rank four now.
        masses = {rank: 0.0 for rank in range(1, 11)}
        masses[4] = 1.0
        q_spec, q_bellman = adaptive_k.compute_q_values(
            masses,
            turn=1,
            continuation_values={k: 0.95 for k in (1, 3, 5, 10)},
        )

        self.assertEqual(max(q_spec, key=q_spec.get), 5)
        self.assertEqual(max(q_bellman, key=q_bellman.get), 1)
        self.assertAlmostEqual(q_bellman[1], 0.95)
        self.assertAlmostEqual(q_bellman[3], 0.95)
        self.assertAlmostEqual(
            q_bellman[5], adaptive_k.technical_utility(turn=1, rank=4)
        )


def _model_payload() -> dict:
    """Return a tiny deterministic, calibrated artifact for runtime tests."""

    feature_names = ["turn_norm"]
    return {
        "schema_version": 1,
        "feature_names": feature_names,
        "normalization": {"mean": [0.0], "scale": [1.0]},
        # Most current-rank probability is in the rank 4--5 band, with a
        # non-zero 6--10 band so the literal objective has a strict K=10 max.
        "rank_heads": {
            "1": {"bias": 0.0, "weights": [0.0], "link": "identity"},
            "3": {"bias": 0.0, "weights": [0.0], "link": "identity"},
            "5": {"bias": 0.9, "weights": [0.0], "link": "identity"},
            "10": {"bias": 1.0, "weights": [0.0], "link": "identity"},
        },
        "continuation_heads": {
            "default": {"bias": 0.95, "weights": [0.0], "link": "identity"}
        },
        "rank_priors": {str(rank): 1.0 for rank in range(1, 11)},
        "metadata": {"model_version": "unit-test"},
    }


class AdaptiveKRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = tuple(
            adaptive_k.RankedCandidate(
                parent_asin=f"P{index}",
                score=11.0 - index,
                rating=float(index),
                components={
                    "hard": 1.0 / index,
                    "semantic": 1.0 / index,
                    "lexical": 1.0 / index,
                    "soft": 0.0,
                    "current": 1.0 / index,
                    "exclusion": 0.0,
                },
            )
            for index in range(1, 11)
        )
        self.context = adaptive_k.RankingContext(
            turn=1,
            intent="B2_ATTRIBUTE_BUYING",
            mode="buying",
            active_constraint_count=2,
            hard_constraint_count=2,
            evidence_turns=1,
            query_term_count=4,
            unique_query_term_count=3,
        )

    def test_feature_schema_is_target_free_and_finite(self) -> None:
        signature = inspect.signature(adaptive_k.extract_rank_features)
        self.assertNotIn("target", " ".join(signature.parameters).lower())
        self.assertNotIn("target", " ".join(adaptive_k.FEATURE_NAMES).lower())
        self.assertNotIn("ground_truth", adaptive_k.FEATURE_NAMES)

        features = adaptive_k.extract_rank_features(self.candidates, self.context)
        self.assertEqual(tuple(features), adaptive_k.FEATURE_NAMES)
        self.assertTrue(all(math.isfinite(value) for value in features.values()))

        empty = adaptive_k.extract_rank_features((), self.context)
        self.assertEqual(tuple(empty), adaptive_k.FEATURE_NAMES)
        self.assertTrue(all(math.isfinite(value) for value in empty.values()))

    def test_model_rejects_a_target_label_as_an_inference_feature(self) -> None:
        payload = _model_payload()
        payload["feature_names"] = ["target_rank"]
        with self.assertRaisesRegex(ValueError, "unknown adaptive-K features"):
            adaptive_k.AdaptiveKModel.from_dict(payload)

    def test_json_model_round_trip_produces_a_complete_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adaptive_k_model.json"
            path.write_text(json.dumps(_model_payload()), encoding="utf-8")
            policy = adaptive_k.RankAwareAdaptiveKPolicy.from_json(path)

        decision = policy.choose(self.candidates, self.context, top_k=10)
        log = decision.as_log(include_features=True)

        self.assertEqual(decision.selected_k, 1)
        self.assertEqual(decision.objective, "bellman")
        self.assertEqual(policy.last_log(), decision.as_log())
        self.assertEqual(set(log["rank_cdf"]), {"1", "3", "5", "10"})
        self.assertEqual(set(log["rank_probabilities"]), {str(rank) for rank in range(1, 11)})
        self.assertEqual(set(log["v_next"]), {"1", "3", "5", "10"})
        self.assertEqual(set(log["q_spec"]), {"1", "3", "5", "10"})
        self.assertEqual(set(log["q_bellman"]), {"1", "3", "5", "10"})
        self.assertAlmostEqual(
            sum(log["rank_probabilities"].values()) + log["p_rank_gt_10"],
            1.0,
        )
        # Logging is intended for JSONL experiment traces and must never need a
        # custom encoder or carry hidden-label fields.
        encoded = json.dumps(log, sort_keys=True)
        self.assertNotIn("target_asin", encoded)
        self.assertNotIn("ground_truth", encoded)
        self.assertNotIn("true_target_rank", encoded)

    def test_literal_spec_objective_selects_ten(self) -> None:
        model = adaptive_k.AdaptiveKModel.from_dict(_model_payload())
        policy = adaptive_k.RankAwareAdaptiveKPolicy(model, objective="spec")

        decision = policy.select(self.candidates, self.context, top_k=10)

        self.assertEqual(decision.selected_k, 10)
        self.assertEqual(decision.objective, "spec")

    def test_override_guard_falls_back_to_ten_only_for_an_uncertain_q_margin(self) -> None:
        model = adaptive_k.AdaptiveKModel.from_dict(_model_payload())
        override_context = adaptive_k.RankingContext(
            **{
                **self.context.__dict__,
                "intent": "O1_OVERRIDE",
                "override_seen": True,
            }
        )

        base_decision = adaptive_k.RankAwareAdaptiveKPolicy(model).choose(
            self.candidates, override_context
        )
        self.assertEqual(base_decision.selected_k, 1)
        q_margin = (
            base_decision.q_bellman[base_decision.selected_k]
            - base_decision.q_bellman[10]
        )
        self.assertGreater(q_margin, 0.0)

        guarded_policy = adaptive_k.RankAwareAdaptiveKPolicy(
            model,
            override_k10_q_margin_threshold=q_margin + 1e-6,
        )
        decision = guarded_policy.choose(self.candidates, override_context)
        log = decision.as_log()

        self.assertEqual(decision.base_selected_k, 1)
        self.assertEqual(decision.selected_k, 10)
        self.assertTrue(decision.override_guard_applied)
        self.assertAlmostEqual(decision.override_q_margin_to_k10, q_margin)
        self.assertEqual(decision.selection_reason, "override_uncertainty_fallback")
        self.assertEqual(log["base_selected_k"], 1)
        self.assertEqual(log["selected_k"], 10)
        self.assertTrue(log["override_guard_applied"])
        self.assertAlmostEqual(log["override_q_margin_to_k10"], q_margin)
        self.assertAlmostEqual(log["override_q_margin_threshold"], q_margin + 1e-6)
        self.assertEqual(log["selection_reason"], "override_uncertainty_fallback")

    def test_override_guard_preserves_confident_and_non_override_selections(self) -> None:
        model = adaptive_k.AdaptiveKModel.from_dict(_model_payload())
        base_decision = adaptive_k.RankAwareAdaptiveKPolicy(model).choose(
            self.candidates, self.context
        )
        q_margin = (
            base_decision.q_bellman[base_decision.selected_k]
            - base_decision.q_bellman[10]
        )

        # A guard configured generously must still be completely inert before
        # an override has occurred.
        non_override = adaptive_k.RankAwareAdaptiveKPolicy(
            model,
            override_k10_q_margin_threshold=q_margin + 1.0,
        ).choose(self.candidates, self.context)
        self.assertEqual(non_override.selected_k, base_decision.selected_k)
        self.assertEqual(non_override.base_selected_k, base_decision.selected_k)
        self.assertFalse(non_override.override_guard_applied)
        self.assertEqual(non_override.selection_reason, "q_bellman")

        # On the override turn, a margin above the configured threshold is
        # sufficiently confident and therefore retains the learned action.
        override_context = adaptive_k.RankingContext(
            **{
                **self.context.__dict__,
                "intent": "O1_OVERRIDE",
                "override_seen": True,
            }
        )
        confident = adaptive_k.RankAwareAdaptiveKPolicy(
            model,
            override_k10_q_margin_threshold=max(0.0, q_margin - 1e-6),
        ).choose(self.candidates, override_context)
        self.assertEqual(confident.selected_k, base_decision.selected_k)
        self.assertEqual(confident.base_selected_k, base_decision.selected_k)
        self.assertFalse(confident.override_guard_applied)
        self.assertAlmostEqual(confident.override_q_margin_to_k10, q_margin)
        self.assertEqual(confident.selection_reason, "q_bellman")

        # The guard is temporary: a later turn remembers the override as a
        # model feature but is no longer forcibly widened to K=10.
        post_override_context = adaptive_k.RankingContext(
            **{
                **self.context.__dict__,
                "intent": "O2_NON_CONFLICTING_UPDATE",
                "override_seen": True,
            }
        )
        post_override = adaptive_k.RankAwareAdaptiveKPolicy(
            model,
            override_k10_q_margin_threshold=q_margin + 1.0,
        ).choose(self.candidates, post_override_context)
        self.assertEqual(post_override.selected_k, base_decision.selected_k)
        self.assertFalse(post_override.override_guard_applied)

    def test_terminal_turn_has_no_continuation_value(self) -> None:
        model = adaptive_k.AdaptiveKModel.from_dict(_model_payload())
        terminal_context = adaptive_k.RankingContext(
            **{**self.context.__dict__, "turn": 10}
        )

        prediction = model.predict(
            adaptive_k.extract_rank_features(self.candidates, terminal_context),
            turn=10,
        )

        self.assertEqual(prediction.continuation_values, {1: 0.0, 3: 0.0, 5: 0.0, 10: 0.0})

    def test_policy_does_not_reorder_or_mutate_reranker_candidates(self) -> None:
        model = adaptive_k.AdaptiveKModel.from_dict(_model_payload())
        policy = adaptive_k.RankAwareAdaptiveKPolicy(model)
        before = tuple(self.candidates)

        policy.choose(self.candidates, self.context)

        self.assertEqual(self.candidates, before)
        self.assertEqual(
            [candidate.parent_asin for candidate in self.candidates],
            [f"P{index}" for index in range(1, 11)],
        )

    def test_top_k_contract_caps_available_actions_without_inventing_k(self) -> None:
        model = adaptive_k.AdaptiveKModel.from_dict(_model_payload())
        policy = adaptive_k.RankAwareAdaptiveKPolicy(model)

        self.assertIn(policy.choose(self.candidates, self.context, top_k=4).selected_k, {1, 3})
        self.assertEqual(policy.choose(self.candidates, self.context, top_k=0).selected_k, 0)


class AdaptiveKAgentIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.catalog_path = root / "catalog.jsonl"
        rows = [
            {
                "parent_asin": f"ITEM_{index:02d}",
                "title": f"Cotton everyday shirt option {index}",
                "features": ["breathable cotton", "machine washable"],
                "details": {"department": "unisex"},
                "description": ["comfortable casual shirt"],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
                "average_rating": 4.0 + index / 100.0,
                "rating_number": 20 + index,
                "price": 20.0 + index,
            }
            for index in range(1, 13)
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        self.model_path = root / "adaptive_k_model.json"
        self.model_path.write_text(json.dumps(_model_payload()), encoding="utf-8")
        self.message = "I'm looking for shirts. A key requirement is: breathable cotton."

    def _first_turn(self, **agent_options: object) -> tuple[object, dict]:
        agent = agent_module.Agent(self.catalog_path, **agent_options)
        agent.reset("session", {"preference_tags": ["comfort"]})
        response = agent.respond("session", self.message, turn=1, top_k=10)
        return agent, response

    def test_fixed_k_and_adaptive_k_only_slice_the_existing_reranker_order(self) -> None:
        fixed_agents: dict[int, object] = {}
        fixed_responses: dict[int, dict] = {}
        for k in (1, 3, 5, 10):
            agent, response = self._first_turn(fixed_k=k)
            fixed_agents[k] = agent
            fixed_responses[k] = response

        reference_order = fixed_agents[10].last_rank_state["ranked_ids"]
        reference_components = fixed_agents[10].last_ranking_components
        self.assertGreaterEqual(len(reference_order), 10)
        for k in (1, 3, 5, 10):
            returned = [item["parent_asin"] for item in fixed_responses[k]["recommendations"]]
            self.assertEqual(returned, reference_order[:k])
            self.assertEqual(fixed_agents[k].last_rank_state["ranked_ids"], reference_order)
            self.assertEqual(fixed_agents[k].last_ranking_components, reference_components)

        adaptive_agent, adaptive_response = self._first_turn(
            adaptive_k_model_path=self.model_path,
            adaptive_k_objective="bellman",
        )
        adaptive_returned = [
            item["parent_asin"] for item in adaptive_response["recommendations"]
        ]
        selected_k = adaptive_agent.last_recommendation_policy["k"]
        self.assertIn(selected_k, {1, 3, 5, 10})
        self.assertEqual(adaptive_returned, reference_order[:selected_k])
        self.assertEqual(adaptive_agent.last_rank_state["ranked_ids"], reference_order)
        self.assertEqual(adaptive_agent.last_ranking_components, reference_components)

    def test_adaptive_agent_emits_complete_target_free_log_on_every_turn(self) -> None:
        agent, _ = self._first_turn(
            adaptive_k_model_path=self.model_path,
            adaptive_k_objective="bellman",
        )
        agent.respond(
            "session",
            "For that, what matters is: machine washable.",
            turn=2,
            top_k=10,
        )

        self.assertEqual(len(agent.adaptive_k_logs), 2)
        required = {
            "session_id",
            "turn",
            "policy",
            "objective",
            "rank_cdf",
            "rank_probabilities",
            "p_rank_gt_10",
            "v_next",
            "q_spec",
            "q_bellman",
            "selected_k",
        }
        for expected_turn, log in enumerate(agent.adaptive_k_logs, start=1):
            self.assertTrue(required.issubset(log))
            self.assertEqual(log["session_id"], "session")
            self.assertEqual(log["turn"], expected_turn)
            self.assertIn(log["selected_k"], {1, 3, 5, 10})
            json.dumps(log)

        inference_payload = {
            "features": agent.last_rank_state["features"],
            "policy_log": agent.last_adaptive_k_log,
        }
        encoded = json.dumps(inference_payload, sort_keys=True).lower()
        self.assertNotIn("target_asin", encoded)
        self.assertNotIn("ground_truth", encoded)
        self.assertNotIn("true_target_rank", encoded)
        self.assertNotIn("target_rank", encoded)

        respond_parameters = inspect.signature(agent.respond).parameters
        self.assertNotIn("target", " ".join(respond_parameters).lower())


if __name__ == "__main__":
    unittest.main()
