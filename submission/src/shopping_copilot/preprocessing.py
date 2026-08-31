"""Paraphrase-tolerant input adapter for the production inverse-DP agent.

This module owns only natural-language wrapper normalization. It preserves the
constraint payload and converts recognized message families back to the public
evaluator's canonical wording, so retrieval, filtering, ranking, and DP remain
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .parser import parse_message


_SMART_PUNCTUATION = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)
_NO_ADDITIONAL_HINT = re.compile(
    r"\b(?:additional|extra|further|nothing\s+else)\b",
    re.IGNORECASE,
)


def canonicalize_punctuation(value: str) -> str:
    return str(value).translate(_SMART_PUNCTUATION)


def _clean_payload(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.\t\r\n")


def is_core_protocol_message(message: str, turn: int) -> bool:
    """Return whether ``message`` uses an organizer-released exact wrapper.

    Only these messages are safe to replay as exact inverse-simulator evidence.
    A parsed paraphrase can still be useful for ranking, but canonicalizing it
    must not silently upgrade an uncertain NLP interpretation into a hard
    protocol fact.
    """

    normalized = re.sub(r"\s+", " ", message).strip().lower()
    if turn == 1 and normalized.startswith("i'm looking for "):
        return True
    return normalized.startswith(
        (
            "for that, what matters is: ",
            "actually, ignore my earlier preference. what i need is: ",
            "i don't have a preference for ",
            "i don't have an additional preference for ",
        )
    )


@dataclass
class _InputState:
    category: str = ""
    last_ask_attribute: str = "other"


class InputPreprocessor:
    """Translate supported paraphrases into the core agent's input protocol."""

    def __init__(self) -> None:
        self.sessions: dict[str, _InputState] = {}

    def reset(self, session_id: str) -> None:
        self.sessions[session_id] = _InputState()

    def canonicalize(
        self,
        session_id: str,
        user_message: str,
        turn: int,
    ) -> str:
        state = self.sessions.setdefault(session_id, _InputState())
        raw_message = str(user_message or "")
        if is_core_protocol_message(raw_message, turn):
            return raw_message
        parsed = parse_message(raw_message, turn=turn)

        if parsed.category:
            state.category = _clean_payload(parsed.category)

        payload = _clean_payload(parsed.payload or "")
        category = state.category

        if turn == 1 and category:
            if parsed.action == "add" and payload:
                if parsed.source == "initial_requirement":
                    return (
                        f"I'm looking for {category}. "
                        f"A key requirement is: {payload}."
                    )
                if parsed.source in {
                    "initial_preference",
                    "compact_initial_preference",
                }:
                    return f"I'm looking for {category}. {payload}"

            # Browsing and Boundary use the same first-turn protocol. Unknown
            # prose around a recognized category is deliberately not evidence.
            return f"I'm looking for {category}, but I'm still exploring."

        if parsed.action == "override" and payload:
            return (
                "Actually, ignore my earlier preference. "
                f"What I need is: {payload}."
            )

        if parsed.action == "add" and payload:
            return f"For that, what matters is: {payload}."

        if parsed.action == "ignore":
            if _NO_ADDITIONAL_HINT.search(raw_message):
                return "I don't have an additional preference for other."
            attribute = state.last_ask_attribute or "other"
            return (
                f"I don't have a preference for {attribute}; "
                "please use your judgment."
            )

        # Keep unknown and explicitly negative messages intact. The core's
        # paraphrase-tolerant path treats them as non-destructive evidence.
        return raw_message

    def note_ask_attribute(
        self,
        session_id: str,
        ask_attribute: object,
    ) -> None:
        state = self.sessions.setdefault(session_id, _InputState())
        if isinstance(ask_attribute, str) and ask_attribute:
            state.last_ask_attribute = ask_attribute
