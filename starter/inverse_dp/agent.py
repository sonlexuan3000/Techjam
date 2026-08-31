"""Compatibility exports for the selected inverse-DP core."""

from submission.src.shopping_copilot.core import (
    Agent,
    ProductIntent,
    SessionState,
    _coarse_category,
    _intent_card,
)

__all__ = [
    "Agent",
    "ProductIntent",
    "SessionState",
    "_coarse_category",
    "_intent_card",
]
