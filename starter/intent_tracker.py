"""Compatibility exports for the production intent tracker."""

from submission.src.shopping_copilot.intent_tracker import (
    Agent,
    SPECIAL_WORDS,
    WORD_RE,
    normalize,
)

__all__ = ["Agent", "SPECIAL_WORDS", "WORD_RE", "normalize"]
