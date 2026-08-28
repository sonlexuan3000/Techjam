from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starter.agent import Agent


RAW_FEATURE = "High quality mesh for maximum breathability to keep you cool"
INTERNAL_SEMICOLON_FEATURE = "Water resistant; machine washable"
RAW_WITHOUT_FEATURE = "Easy to use and holds effectively without wiggling"
RAW_AVOID_FEATURE = "Please avoid soaking the fabric for extended periods"


class LightweightNLPTest(unittest.TestCase):
    """Behaviour contract for wrapper-tolerant, catalog-guided parsing.

    These tests intentionally exercise the public ``Agent`` API instead of a
    particular parser implementation.  A lightweight rules/phrase-matching
    parser, a future standalone parser module, or another deterministic
    implementation should all be able to satisfy the same contract.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        catalog_path = Path(self.temporary_directory.name) / "catalog.jsonl"
        rows = [
            {
                "parent_asin": "TARGET_SHIRT",
                "title": "Navy cotton performance shirt",
                "features": [
                    RAW_FEATURE,
                    INTERNAL_SEMICOLON_FEATURE,
                    RAW_WITHOUT_FEATURE,
                    RAW_AVOID_FEATURE,
                    "100% Cotton",
                ],
                "details": {"Color": "Deep Navy"},
                "description": [],
                "categories": ["Clothing", "Shirts"],
                "store": "Example",
            },
            {
                "parent_asin": "LEATHER_SHOE",
                "title": "Leather walking shoe",
                "features": ["Genuine Leather", "Cushioned footbed"],
                "details": {"Color": "Black"},
                "description": [],
                "categories": ["Clothing", "Footwear"],
                "store": "Example",
            },
            {
                "parent_asin": "CANVAS_SHOE",
                "title": "Canvas walking shoe",
                "features": ["Canvas", "Cushioned footbed"],
                "details": {"Color": "White"},
                "description": [],
                "categories": ["Clothing", "Footwear"],
                "store": "Example",
            },
        ]
        catalog_path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        self.agent = Agent(catalog_path)

    def _respond(self, session_id: str, message: str, turn: int = 1) -> dict:
        return self.agent.respond(
            session_id,
            message,
            turn=turn,
            top_k=10,
        )

    def _new_state(self, session_id: str, message: str) -> dict:
        self.agent.reset(session_id, {})
        self._respond(session_id, message)
        return self.agent.debug_state(session_id)

    @staticmethod
    def _texts(state: dict, collection: str = "history") -> list[str]:
        return [item["text"] for item in state[collection]]

    def test_official_buying_wrapper_preserves_raw_metadata_phrase(self) -> None:
        state = self._new_state(
            "official-buying",
            f"I'm looking for shirts. A key requirement is: {RAW_FEATURE}.",
        )

        self.assertEqual(state["category"].lower(), "shirts")
        self.assertEqual(self._texts(state), [RAW_FEATURE])
        self.assertEqual(state["history"][0]["source"], "initial_requirement")

    def test_paraphrased_buying_wrappers_keep_hard_requirement_source(self) -> None:
        messages = (
            f"I need shirts. One requirement I can't compromise on is: {RAW_FEATURE}.",
            f"Help me find shirts; it must satisfy: {RAW_FEATURE}.",
            f"I'm shopping for shirts, and this is essential: {RAW_FEATURE}.",
            f"For shirts, my main requirement is: {RAW_FEATURE}.",
        )

        for index, message in enumerate(messages):
            with self.subTest(message=message):
                state = self._new_state(f"paraphrased-buying-{index}", message)
                self.assertEqual(state["category"].lower(), "shirts")
                self.assertEqual(self._texts(state), [RAW_FEATURE])
                self.assertEqual(
                    state["history"][0]["source"],
                    "initial_requirement",
                )

    def test_disclosed_metadata_words_without_and_avoid_are_not_negations(self) -> None:
        cases = (
            (
                "raw-without",
                f"I'm looking for shirts. A key requirement is: {RAW_WITHOUT_FEATURE}.",
                RAW_WITHOUT_FEATURE,
                "initial_requirement",
            ),
            (
                "raw-avoid",
                f"For that, these points matter to me: {RAW_AVOID_FEATURE}.",
                RAW_AVOID_FEATURE,
                "revealed",
            ),
        )

        for session_id, message, expected, source in cases:
            with self.subTest(message=message):
                self.agent.reset(session_id, {})
                self._respond(session_id, message, turn=1 if source == "initial_requirement" else 2)
                state = self.agent.debug_state(session_id)
                self.assertEqual(self._texts(state, "retrieval_evidence"), [expected])
                self.assertEqual(state["negative_evidence"], [])
                self.assertEqual(state["history"][0]["source"], source)

    def test_unknown_wrappers_do_not_turn_metadata_words_into_negation(self) -> None:
        cases = (
            (
                "unknown-without",
                f"My absolute requirement is: {RAW_WITHOUT_FEATURE}.",
                "initial_requirement",
            ),
            (
                "unknown-avoid",
                f"Please find one with: {RAW_AVOID_FEATURE}.",
                "catalog_fallback",
            ),
        )

        for session_id, message, expected_source in cases:
            with self.subTest(message=message):
                self.agent.reset(session_id, {})
                self._respond(session_id, message)
                state = self.agent.debug_state(session_id)
                self.assertEqual(state["negative_evidence"], [])
                self.assertEqual(len(state["retrieval_evidence"]), 1)
                self.assertEqual(
                    state["retrieval_evidence"][0]["source"],
                    expected_source,
                )

    def test_bare_catalog_feature_starting_with_avoid_is_not_negation(self) -> None:
        state = self._new_state(
            "bare-avoid-feature",
            f"{RAW_AVOID_FEATURE}.",
        )

        self.assertEqual(state["negative_evidence"], [])
        self.assertEqual(self._texts(state, "retrieval_evidence"), [RAW_AVOID_FEATURE])
        self.assertEqual(state["history"][0]["source"], "catalog_fallback")

    def test_smart_punctuation_and_polite_suffix_do_not_change_raw_value(self) -> None:
        state = self._new_state(
            "smart-punctuation",
            f"I’m shopping for shirts, and this is essential: {RAW_FEATURE}, if possible.",
        )

        self.assertEqual(state["category"].lower(), "shirts")
        self.assertEqual(self._texts(state), [RAW_FEATURE])
        self.assertEqual(state["history"][0]["source"], "initial_requirement")

    def test_official_compound_reply_does_not_split_internal_metadata_semicolon(
        self,
    ) -> None:
        self.agent.reset("official-compound", {})
        self._respond(
            "official-compound",
            "I'm looking for shirts, but I'm still exploring.",
        )
        self._respond(
            "official-compound",
            (
                "For that, what matters is: "
                f"{INTERNAL_SEMICOLON_FEATURE}; 100% Cotton."
            ),
            turn=2,
        )

        state = self.agent.debug_state("official-compound")
        self.assertCountEqual(
            self._texts(state, "retrieval_evidence"),
            [INTERNAL_SEMICOLON_FEATURE, "100% Cotton"],
        )

    def test_compound_reply_can_use_and_instead_of_semicolon(self) -> None:
        self.agent.reset("compound-and", {})
        self._respond("compound-and", "I'm looking for shirts, but I'm still exploring.")
        self._respond(
            "compound-and",
            "What matters to me is: 100% Cotton and Color: Deep Navy.",
            turn=2,
        )

        state = self.agent.debug_state("compound-and")
        self.assertCountEqual(
            self._texts(state, "retrieval_evidence"),
            ["100% Cotton", "Color: Deep Navy"],
        )

    def test_paraphrased_compound_reply_recovers_two_exact_catalog_atoms(self) -> None:
        wrappers = (
            "For that, these points matter to me: {constraints}.",
            "Here is what I care about for that: {constraints}.",
            "My relevant requirements or preferences are: {constraints}.",
            "Please take these into account: {constraints}.",
        )
        payload = f"{INTERNAL_SEMICOLON_FEATURE}; 100% Cotton"

        for index, wrapper in enumerate(wrappers):
            with self.subTest(wrapper=wrapper):
                session_id = f"paraphrased-compound-{index}"
                self.agent.reset(session_id, {})
                self._respond(
                    session_id,
                    "I'd like to browse shirts. I don't have firm requirements yet.",
                )
                self._respond(session_id, wrapper.format(constraints=payload), turn=2)
                state = self.agent.debug_state(session_id)
                self.assertEqual(state["category"].lower(), "shirts")
                self.assertCountEqual(
                    self._texts(state, "retrieval_evidence"),
                    [INTERNAL_SEMICOLON_FEATURE, "100% Cotton"],
                )

    def test_free_style_compound_message_extracts_catalog_phrases_not_wrapper(self) -> None:
        state = self._new_state(
            "free-style-compound",
            (
                "I'm after shirts: material-wise I want 100% Cotton, "
                "while Color: Deep Navy would be ideal."
            ),
        )

        self.assertEqual(state["category"].lower(), "shirts")
        self.assertCountEqual(
            self._texts(state, "retrieval_evidence"),
            ["100% Cotton", "Color: Deep Navy"],
        )

    def test_intent_override_wrapper_variants_replace_same_slot_value(self) -> None:
        override_messages = (
            "Actually, set aside my earlier preference. What I need now is: Canvas.",
            (
                "I've changed my mind; please ignore the previous preference. "
                "My requirement is: Canvas."
            ),
            (
                "Correction: the earlier preference no longer matters. "
                "Please prioritize: Canvas."
            ),
            "Please replace my earlier preference with this requirement: Canvas.",
        )

        for index, override_message in enumerate(override_messages):
            with self.subTest(override_message=override_message):
                session_id = f"override-{index}"
                self.agent.reset(session_id, {})
                self._respond(
                    session_id,
                    (
                        "I'm shopping for footwear. "
                        "One thing I care about is: Genuine Leather."
                    ),
                )
                self._respond(session_id, override_message, turn=3)
                state = self.agent.debug_state(session_id)
                history = {item["text"].lower(): item for item in state["history"]}

                self.assertEqual(state["category"].lower(), "footwear")
                self.assertIn("genuine leather", history)
                self.assertIn("canvas", history)
                self.assertFalse(history["genuine leather"]["active"])
                self.assertFalse(history["genuine leather"]["searchable"])
                self.assertTrue(history["canvas"]["active"])
                self.assertEqual(history["canvas"]["source"], "override")

    def test_negation_wrapper_variants_remove_only_the_catalog_value(self) -> None:
        negation_messages = (
            "Actually, I don't want Genuine Leather anymore.",
            "Genuine Leather is no longer acceptable to me.",
            "Please exclude Genuine Leather from the options.",
            "Anything but Genuine Leather, please.",
            "Please avoid Genuine Leather.",
        )

        for index, negation_message in enumerate(negation_messages):
            with self.subTest(negation_message=negation_message):
                session_id = f"negation-{index}"
                self.agent.reset(session_id, {})
                self._respond(
                    session_id,
                    (
                        "I'm looking for footwear. "
                        "A key requirement is: Genuine Leather."
                    ),
                )
                self._respond(session_id, negation_message, turn=2)
                state = self.agent.debug_state(session_id)

                self.assertEqual(state["current_intent"], [])
                self.assertEqual(state["retrieval_evidence"], [])
                self.assertEqual(
                    [text.lower() for text in self._texts(state, "negative_evidence")],
                    ["genuine leather"],
                )

    def test_negation_discourse_prefix_is_not_part_of_value(self) -> None:
        self.agent.reset("negation-prefix", {})
        self._respond(
            "negation-prefix",
            "I'm looking for footwear. A key requirement is: Genuine Leather.",
        )
        self._respond(
            "negation-prefix",
            "Actually, Genuine Leather is no longer acceptable to me.",
            turn=2,
        )

        state = self.agent.debug_state("negation-prefix")
        self.assertEqual(state["retrieval_evidence"], [])
        self.assertEqual(self._texts(state, "negative_evidence"), ["Genuine Leather"])

    def test_explicit_requirement_beats_unrelated_no_preference_clause(self) -> None:
        state = self._new_state(
            "mixed-flexible-hard",
            (
                "I don't have a preference for color, but a key requirement is: "
                "100% Cotton."
            ),
        )

        self.assertEqual(self._texts(state, "retrieval_evidence"), ["100% Cotton"])

    def test_strong_unknown_hard_wrapper_accepts_singleton_constraint(self) -> None:
        state = self._new_state(
            "hard-singleton",
            "It absolutely must be Cotton.",
        )

        self.assertEqual(self._texts(state, "retrieval_evidence"), ["Cotton"])
        self.assertEqual(state["history"][0]["source"], "initial_requirement")

    def test_bare_singleton_reply_uses_exact_catalog_fallback(self) -> None:
        self.agent.reset("bare-singleton", {})
        self._respond(
            "bare-singleton",
            "I'm looking for footwear, but I'm still exploring.",
        )
        self._respond("bare-singleton", "Canvas.", turn=2)

        state = self.agent.debug_state("bare-singleton")
        self.assertEqual(self._texts(state, "retrieval_evidence"), ["Canvas"])
        self.assertEqual(state["history"][0]["source"], "catalog_fallback")

    def test_compact_turn_one_remainder_must_match_catalog_evidence(self) -> None:
        state = self._new_state(
            "arbitrary-remainder",
            "I'm looking for shirts. Can you show me some options?",
        )

        self.assertEqual(state["category"].lower(), "shirts")
        self.assertEqual(state["history"], [])

    def test_boundary_and_no_additional_preference_variants_add_no_evidence(
        self,
    ) -> None:
        browsing_messages = (
            "I'm considering shirts, but I haven't settled on the details.",
            "Help me explore shirts; my preferences are still open.",
            "I'd like to browse shirts. I don't have firm requirements yet.",
            "I'm shopping for shirts and could use help narrowing it down.",
        )
        no_preference_messages = (
            "I don't have a preference regarding material; use your best judgment.",
            "No preference on material; I'm flexible there.",
            "Material isn't something I care about, so you can decide.",
            "I'm open on material; please choose what makes sense.",
            "Nothing else comes to mind for other.",
            "I have no additional requirement about feature.",
        )

        for index, browsing_message in enumerate(browsing_messages):
            with self.subTest(browsing_message=browsing_message):
                session_id = f"boundary-{index}"
                self.agent.reset(session_id, {})
                self._respond(session_id, browsing_message)
                for turn, no_preference_message in enumerate(
                    no_preference_messages,
                    start=2,
                ):
                    self._respond(session_id, no_preference_message, turn=turn)

                state = self.agent.debug_state(session_id)
                self.assertEqual(state["category"].lower(), "shirts")
                self.assertEqual(state["history"], [])


if __name__ == "__main__":
    unittest.main()
