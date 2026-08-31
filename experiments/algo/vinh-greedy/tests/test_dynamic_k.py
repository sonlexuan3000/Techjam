from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from k_policy import (  # noqa: E402
    ACTIONS,
    ConservativeKPolicy,
    PolicyState,
    baseline_action,
)


def state(turn: int = 1, *, override: str = "0", shown: str = "0") -> PolicyState:
    return PolicyState(
        turn=turn,
        remaining_other="2+" if turn <= 2 else "0",
        pool="11-30",
        useful="1",
        exact="1",
        tie="2",
        gain="1",
        override=override,
        no_information="0",
        shown=shown,
    )


def accepted_artifact(policy_state: PolicyState, k: int, samples: int = 50) -> dict:
    return {
        "selected_variant": "safe_bellman",
        "minimum_state_samples": 8,
        "global_gate": {"accepted": True},
        "actions": {
            policy_state.encode(): {
                "k": k,
                "samples": samples,
                "se": 0.01,
                "reason": "selected",
            }
        },
    }


class DynamicKPolicyTest(unittest.TestCase):
    def test_k_is_bounded_by_requested_cap_and_ten(self) -> None:
        policy_state = state()
        policy = ConservativeKPolicy(accepted_artifact(policy_state, 10))
        for cap in range(1, 15):
            choice, reason = policy.choose(policy_state, requested_top_k=cap)
            self.assertIn(choice, ACTIONS)
            self.assertLessEqual(choice, min(cap, 10))
            self.assertEqual(reason, "accepted_exact")

    def test_unseen_state_falls_back_to_baseline_schedule(self) -> None:
        policy = ConservativeKPolicy(
            {
                "minimum_state_samples": 8,
                "global_gate": {"accepted": True},
                "actions": {},
            }
        )
        for turn, expected in ((1, 1), (2, 2), (3, 10), (8, 10)):
            choice, reason = policy.choose(state(turn), requested_top_k=10)
            self.assertEqual(choice, expected)
            self.assertEqual(reason, "unseen_state")

    def test_sparse_state_falls_back(self) -> None:
        policy_state = state(turn=2)
        policy = ConservativeKPolicy(accepted_artifact(policy_state, 7, samples=7))
        choice, reason = policy.choose(policy_state, requested_top_k=10)
        self.assertEqual(choice, baseline_action(2))
        self.assertEqual(reason, "sparse_state")

    def test_global_safety_gate_falls_back_even_with_loaded_action(self) -> None:
        policy_state = state(turn=1)
        artifact = accepted_artifact(policy_state, 5)
        artifact["global_gate"]["accepted"] = False
        policy = ConservativeKPolicy(artifact)
        choice, reason = policy.choose(policy_state, requested_top_k=10)
        self.assertEqual(choice, 1)
        self.assertEqual(reason, "safety_gate")
        self.assertTrue(policy.actions)

    def test_override_state_can_choose_smaller_k_than_previous_turn(self) -> None:
        before = state(turn=3, override="0", shown="3-10")
        after = state(turn=4, override="1", shown="0")
        artifact = accepted_artifact(before, 8)
        artifact["actions"][after.encode()] = {
            "k": 1,
            "samples": 60,
            "se": 0.01,
            "reason": "selected",
        }
        policy = ConservativeKPolicy(artifact)
        first, _ = policy.choose(before, requested_top_k=10)
        second, _ = policy.choose(after, requested_top_k=10)
        self.assertEqual((first, second), (8, 1))

    def test_loading_and_fingerprint_are_deterministic(self) -> None:
        policy_state = state(turn=5)
        artifact = accepted_artifact(policy_state, 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            first = ConservativeKPolicy.load(path)
            second = ConservativeKPolicy.load(path)
            self.assertEqual(first.artifact, second.artifact)
            self.assertEqual(first.fingerprint, second.fingerprint)
            self.assertEqual(
                first.choose(policy_state, requested_top_k=10),
                second.choose(policy_state, requested_top_k=10),
            )


if __name__ == "__main__":
    unittest.main()
