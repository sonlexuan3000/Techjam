"""Compatibility exports for the production input preprocessor."""

from submission.src.shopping_copilot.preprocessing import (
    InputPreprocessor,
    canonicalize_punctuation,
    is_core_protocol_message,
)

__all__ = [
    "InputPreprocessor",
    "canonicalize_punctuation",
    "is_core_protocol_message",
]
