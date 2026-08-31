from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_candidate import load_candidate
from starter.agent import Agent


ALLOWED_ATTRIBUTES = {
    "category",
    "material",
    "color",
    "size",
    "style",
    "brand",
    "budget",
    "feature",
    "use_case",
    "other",
    None,
}
VALID_PROFILE = {
    "purchase_frequency": "occasional",
    "average_prior_rating": 4.2,
    "rating_style": "balanced",
    "preference_tags": ["practical"],
    "summary": "Prefers practical products.",
}


class IntegratedAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        self.rows = [
            {
                "parent_asin": "A_DISTRACTOR",
                "title": "Distractor shoe",
                "features": ["one feature", "two feature", "three feature", "four feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shoes"],
                "store": "Example",
                "average_rating": 4.9,
                "rating_number": 1000,
                "price": None,
            },
            {
                "parent_asin": "B_TARGET",
                "title": "Target shoe",
                "features": ["alpha feature", "beta feature", "gamma feature", "delta feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shoes"],
                "store": "Example",
                "average_rating": 4.1,
                "rating_number": 1,
                "price": None,
            },
            {
                "parent_asin": "C_OTHER",
                "title": "Other shoe",
                "features": ["red feature", "blue feature", "green feature", "black feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shoes"],
                "store": "Example",
                "average_rating": 4.5,
                "rating_number": 20,
                "price": None,
            },
        ]
        self.catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in self.rows),
            encoding="utf-8",
        )

    def test_official_adapter_uses_uniform_prior_and_finds_exact_target(self) -> None:
        agent = Agent(self.catalog_path)
        self.assertEqual(agent.prior_field, "uniform")
        agent.reset("session", VALID_PROFILE)

        first = agent.respond(
            "session",
            "I'm looking for Shoes, but I'm still exploring.",
            turn=1,
            top_k=10,
        )
        second = agent.respond(
            "session",
            "For that, what matters is: alpha feature; beta feature.",
            turn=2,
            top_k=10,
        )

        self.assertEqual(len(first["recommendations"]), 1)
        self.assertEqual(second["recommendations"], [{"parent_asin": "B_TARGET"}])

    def test_response_contract_and_session_lifecycle(self) -> None:
        agent = Agent(self.catalog_path)
        with self.assertRaisesRegex(RuntimeError, "reset"):
            agent.respond("missing", "hello", turn=1, top_k=10)

        profile = dict(VALID_PROFILE)
        agent.reset("session", profile)
        response = agent.respond(
            "session",
            "I'm looking for Shoes, but I'm still exploring.",
            turn=1,
            top_k=10,
        )

        self.assertIsInstance(response["message"], str)
        self.assertIn(response["ask_attribute"], ALLOWED_ATTRIBUTES)
        self.assertLessEqual(len(response["recommendations"]), 10)
        identifiers = [item["parent_asin"] for item in response["recommendations"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(set(identifiers) <= {row["parent_asin"] for row in self.rows})
        self.assertEqual(response["usage"], {"prompt_tokens": 0, "completion_tokens": 0})
        self.assertEqual(agent.sessions["session"].user_profile, profile)

        # Resetting the same identifier must discard its transcript and misses.
        new_profile = {**VALID_PROFILE, "summary": "New profile."}
        agent.reset("session", new_profile)
        self.assertEqual(agent.sessions["session"].messages, [])
        self.assertEqual(agent.sessions["session"].rejected, set())

    def test_historical_entrypoint_alias_matches_production(self) -> None:
        root = Path(__file__).resolve().parents[1]
        entrypoint = (
            root
            / "experiments"
            / "algo"
            / "tunglam-inverse-dp-review-prior"
            / "entrypoint.py"
        )
        experiment, _ = load_candidate(entrypoint, str(self.catalog_path))
        production = Agent(self.catalog_path)
        transcript = (
            "I'm looking for Shoes, but I'm still exploring.",
            "For that, what matters is: alpha feature; beta feature.",
        )

        for candidate in (experiment, production):
            candidate.reset("parity", VALID_PROFILE)
        for turn, message in enumerate(transcript, start=1):
            self.assertEqual(
                production.respond("parity", message, turn, 10),
                experiment.respond("parity", message, turn, 10),
            )

    def test_submission_entry_file_can_be_loaded_directly(self) -> None:
        entrypoint = Path(__file__).resolve().parents[1] / "submission" / "agent.py"
        spec = importlib.util.spec_from_file_location("submitted_agent", entrypoint)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)

        agent = module.Agent(self.catalog_path)
        agent.reset("direct", VALID_PROFILE)
        response = agent.respond(
            "direct",
            "I'm looking for Shoes, but I'm still exploring.",
            turn=1,
            top_k=10,
        )
        self.assertEqual(response["ask_attribute"], "other")

    def test_out_of_contract_top_k_is_defensively_clamped(self) -> None:
        catalog_path = Path(self.temporary_directory.name) / "large-catalog.jsonl"
        rows = [
            {
                "parent_asin": f"PRODUCT_{index:02d}",
                "title": f"Shared shoe {index}",
                "features": ["shared one", "shared two", "shared three", "shared four"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shoes"],
                "store": "Example",
                "average_rating": 4.0,
                "rating_number": 1,
                "price": None,
            }
            for index in range(50)
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        agent = Agent(catalog_path)
        agent.reset("clamped", VALID_PROFILE)
        response = agent.respond(
            "clamped",
            "I'm looking for Shoes, but I'm still exploring.",
            turn=1,
            top_k=100,
        )

        self.assertLessEqual(len(response["recommendations"]), 10)

        agent.reset("zero", VALID_PROFILE)
        response = agent.respond(
            "zero",
            "I'm looking for Shoes, but I'm still exploring.",
            turn=1,
            top_k=0,
        )
        self.assertEqual(response["recommendations"], [])


if __name__ == "__main__":
    unittest.main()
