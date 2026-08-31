from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path


EXPERIMENT = Path(__file__).resolve().parents[1]
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

import agent as dynamic_agent_module  # noqa: E402
import k_policy as k_policy_module  # noqa: E402
from agent import ConservativeBellmanTopKAgent  # noqa: E402
from starter.agent import Agent  # noqa: E402


def product(index: int) -> dict:
    return {
        "parent_asin": f"P{index:02d}",
        "title": f"Synthetic shirt {index}",
        "features": ["cotton" if index < 6 else "polyester"],
        "description": [f"description {index}"],
        "price": 10 + index,
        "categories": ["Clothing", "Men", "Shirts"],
        "details": {"Color": "blue" if index % 2 else "red"},
        "average_rating": 4.0,
        "rating_number": 100 - index,
        "store": "Synthetic",
    }


class ConstantPolicy:
    def __init__(self, k: int):
        self.k = k
        self.fingerprint = "synthetic"

    def choose(self, _state, *, requested_top_k: int):
        return min(self.k, requested_top_k, 10), "accepted"


class DynamicKAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.catalog = root / "catalog.jsonl"
        self.catalog.write_text(
            "".join(json.dumps(product(index)) + "\n" for index in range(12)),
            encoding="utf-8",
        )
        self.policy = root / "policy.json"
        self.policy.write_text(
            json.dumps(
                {
                    "selected_variant": "baseline",
                    "minimum_state_samples": 8,
                    "global_gate": {"accepted": False},
                    "actions": {},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self) -> ConservativeBellmanTopKAgent:
        return ConservativeBellmanTopKAgent(self.catalog, policy_path=self.policy)

    def test_runtime_does_not_use_evaluation_labels(self) -> None:
        source = inspect.getsource(dynamic_agent_module) + inspect.getsource(k_policy_module)
        for forbidden in (
            '["ground_truth"]',
            '["target_asin"]',
            '["sample_id"]',
            '["intent_card"]',
            '["behavior"]',
        ):
            self.assertNotIn(forbidden, source)

    def test_ranking_is_exactly_inherited_baseline(self) -> None:
        baseline = Agent(self.catalog)
        dynamic = self.build()
        baseline.reset("b", {})
        dynamic.reset("d", {})
        message = "I'm looking for Men Shirts. A key requirement is: cotton."
        baseline._parse(baseline.sessions["b"], message, 1)
        dynamic._parse(dynamic.sessions["d"], message, 1)
        expected = baseline._rank(baseline.sessions["b"])
        self.assertEqual(dynamic._rank(dynamic.sessions["d"]), expected)
        self.assertIs(ConservativeBellmanTopKAgent._rank, Agent._rank)

    def test_only_emitted_count_changes(self) -> None:
        dynamic = self.build()
        dynamic.k_policy = ConstantPolicy(4)
        dynamic.reset("s", {})
        response = dynamic.respond(
            "s",
            "I'm looking for Men Shirts. A key requirement is: cotton.",
            1,
            10,
        )
        expected = Agent._rank(dynamic, dynamic.sessions["s"])
        actual = [item["parent_asin"] for item in response["recommendations"]]
        self.assertEqual(actual, expected[:4])

    def test_question_policy_override_and_fingerprint(self) -> None:
        dynamic = self.build()
        dynamic.reset("s", {})
        dynamic.sessions["s"].shown.add("SENTINEL")
        values = []
        for turn in range(1, 6):
            message = (
                "Actually, ignore my earlier preference. What I need is: polyester."
                if turn == 1
                else "No additional preference."
            )
            values.append(dynamic.respond("s", message, turn, 10)["ask_attribute"])
        self.assertNotIn("SENTINEL", dynamic.sessions["s"].shown)
        self.assertEqual(values, ["other", "other", "other", None, None])
        self.assertEqual(
            dynamic.decision_log["s"][0]["artifact_fingerprint"],
            dynamic.k_policy.fingerprint,
        )


if __name__ == "__main__":
    unittest.main()
