from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starter.agent import Agent


class AgentStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        rows = [
            {
                "parent_asin": "BOTH",
                "title": "Breathable cotton shirt",
                "features": ["Breathable", "100% Cotton"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
            },
            {
                "parent_asin": "COTTON",
                "title": "Cotton shirt",
                "features": ["100% Cotton"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
            },
            {
                "parent_asin": "BREATHABLE",
                "title": "Breathable shirt",
                "features": ["Breathable"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
            },
            {
                "parent_asin": "ALL",
                "title": "Everyday cotton shirt",
                "features": ["Cotton", "Breathable", "Machine washable"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
            },
            {
                "parent_asin": "LEATHER",
                "title": "Leather shoes",
                "features": ["Leather"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Footwear"],
                "store": "Example",
            },
            {
                "parent_asin": "CANVAS",
                "title": "Canvas shoes",
                "features": ["Canvas"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Footwear"],
                "store": "Example",
            },
            {
                "parent_asin": "OLD_ONLY",
                "title": "Old clue accessory",
                "features": ["Rare old feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Accessories"],
                "store": "Example",
            },
            {
                "parent_asin": "NEW_ONLY",
                "title": "New clue accessory",
                "features": ["New active feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Accessories"],
                "store": "Example",
            },
            {
                "parent_asin": "INTERNAL_SEMICOLON",
                "title": "Easy care shirt",
                "features": ["Water resistant; machine washable"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
            },
            {
                "parent_asin": "POPULAR_TIE",
                "title": "Popular accessory",
                "features": ["Shared feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Accessories"],
                "store": "Example",
                "rating_number": 1000,
            },
            {
                "parent_asin": "UNPOPULAR_TIE",
                "title": "Less popular accessory",
                "features": ["Shared feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Accessories"],
                "store": "Example",
                "rating_number": 10,
            },
            {
                "parent_asin": "POPULAR_IRRELEVANT",
                "title": "Very popular but irrelevant accessory",
                "features": ["Different feature"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Accessories"],
                "store": "Example",
                "rating_number": 1000000,
            },
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        self.agent = Agent(catalog_path)

    def test_non_conflicting_override_keeps_old_target_evidence(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for shirts. Breathable.",
            turn=1,
            top_k=1,
        )
        self.agent.respond(
            "session",
            "Actually, ignore my earlier preference. What I need is: 100% Cotton.",
            turn=3,
            top_k=1,
        )

        debug = self.agent.debug_state("session")
        current = {item["text"] for item in debug["current_intent"]}
        searchable = {item["text"] for item in debug["retrieval_evidence"]}
        history = {item["text"]: item for item in debug["history"]}

        self.assertEqual(current, {"100% Cotton"})
        self.assertEqual(searchable, {"Breathable", "100% Cotton"})
        self.assertFalse(history["Breathable"]["active"])
        self.assertTrue(history["Breathable"]["searchable"])
        self.assertEqual(self.agent._rank(self.agent.sessions["session"])[0], "BOTH")

    def test_same_material_override_disables_old_search_evidence(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for footwear. Leather.",
            turn=1,
            top_k=1,
        )
        self.agent.respond(
            "session",
            "Actually, ignore my earlier preference. What I need is: Canvas.",
            turn=3,
            top_k=1,
        )

        debug = self.agent.debug_state("session")
        searchable = {item["text"] for item in debug["retrieval_evidence"]}
        history = {item["text"]: item for item in debug["history"]}

        self.assertEqual(searchable, {"Canvas"})
        self.assertFalse(history["Leather"]["active"])
        self.assertFalse(history["Leather"]["searchable"])
        self.assertEqual(history["Leather"]["slot"], "material")
        self.assertEqual(history["Canvas"]["slot"], "material")
        self.assertEqual(self.agent._rank(self.agent.sessions["session"])[0], "CANVAS")

    def test_explicit_negation_moves_clue_to_negative_evidence(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for footwear. A key requirement is: Leather.",
            turn=1,
            top_k=1,
        )
        self.agent.respond(
            "session",
            "Actually, I don't want leather anymore.",
            turn=2,
            top_k=1,
        )

        debug = self.agent.debug_state("session")
        self.assertEqual(debug["retrieval_evidence"], [])
        self.assertEqual(
            {item["text"].lower() for item in debug["negative_evidence"]},
            {"leather"},
        )
        self.assertEqual(self.agent._rank(self.agent.sessions["session"])[0], "CANVAS")

    def test_normal_replies_accumulate_and_deduplicate_evidence(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for shirts. A key requirement is: Cotton.",
            turn=1,
            top_k=1,
        )
        reply = "For that, what matters is: Breathable; Machine washable."
        self.agent.respond("session", reply, turn=2, top_k=1)
        self.agent.respond("session", reply, turn=3, top_k=1)

        debug = self.agent.debug_state("session")
        searchable = [item["text"] for item in debug["retrieval_evidence"]]
        self.assertCountEqual(searchable, ["Cotton", "Breathable", "Machine washable"])
        self.assertEqual(len(debug["history"]), 3)
        self.assertEqual(self.agent._rank(self.agent.sessions["session"])[0], "ALL")

    def test_active_override_anchors_ranking_when_old_evidence_is_incompatible(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for accessories. Rare old feature.",
            turn=1,
            top_k=1,
        )
        self.agent.respond(
            "session",
            "Actually, ignore my earlier preference. What I need is: New active feature.",
            turn=3,
            top_k=1,
        )

        debug = self.agent.debug_state("session")
        self.assertCountEqual(
            [item["text"] for item in debug["retrieval_evidence"]],
            ["Rare old feature", "New active feature"],
        )
        self.assertEqual(self.agent._rank(self.agent.sessions["session"])[0], "NEW_ONLY")

    def test_explicit_old_value_falls_back_to_semantic_slot_match(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for footwear. Leather.",
            turn=1,
            top_k=1,
        )
        self.agent.respond(
            "session",
            (
                "Actually, ignore my earlier preference. "
                "What I need is: Canvas instead of genuine leather."
            ),
            turn=3,
            top_k=1,
        )

        history = {
            item["text"]: item for item in self.agent.debug_state("session")["history"]
        }
        self.assertFalse(history["Leather"]["searchable"])
        self.assertTrue(history["Canvas"]["searchable"])

    def test_multi_slot_override_detects_color_conflict(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for footwear. Black leather.",
            turn=1,
            top_k=1,
        )
        self.agent.respond(
            "session",
            "Actually, ignore my earlier preference. What I need is: Brown leather.",
            turn=3,
            top_k=1,
        )

        history = {
            item["text"]: item for item in self.agent.debug_state("session")["history"]
        }
        self.assertFalse(history["Black leather"]["searchable"])

    def test_internal_semicolon_is_preserved_as_one_exact_atom(self) -> None:
        parts = self.agent._split_revealed_payload("Water resistant; machine washable.")
        self.assertEqual(parts, ["Water resistant; machine washable"])

    def test_rating_number_breaks_only_relevance_ties(self) -> None:
        self.agent.reset("session", {})
        self.agent.respond(
            "session",
            "I'm looking for accessories. A key requirement is: Shared feature.",
            turn=1,
            top_k=1,
        )

        ranked = self.agent._rank(self.agent.sessions["session"])
        self.assertEqual(ranked[:2], ["POPULAR_TIE", "UNPOPULAR_TIE"])
        self.assertGreater(
            ranked.index("POPULAR_IRRELEVANT"),
            ranked.index("UNPOPULAR_TIE"),
        )

    def test_early_turns_use_a_conservative_recommendation_schedule(self) -> None:
        self.agent.reset("session", {})
        first = self.agent.respond(
            "session",
            "I'm looking for accessories, but I'm still exploring.",
            turn=1,
            top_k=10,
        )
        second = self.agent.respond(
            "session",
            "I don't have an additional preference for other.",
            turn=2,
            top_k=10,
        )
        third = self.agent.respond(
            "session",
            "I don't have an additional preference for other.",
            turn=3,
            top_k=10,
        )

        self.assertEqual(len(first["recommendations"]), 1)
        self.assertEqual(len(second["recommendations"]), 2)
        self.assertEqual(len(third["recommendations"]), 10)
        self.assertEqual(
            self.agent._recommendation_limit(turn=2, requested_top_k=1),
            1,
        )


if __name__ == "__main__":
    unittest.main()
