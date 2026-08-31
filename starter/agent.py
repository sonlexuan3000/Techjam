"""Official Track 4 backend entrypoint.

The selected backend is Tung Lam Nguyen's data-safe inverse-card agent with a
uniform product prior. Keeping this adapter small makes the competition-facing
``starter.agent.Agent`` contract stable while the implementation remains split
into testable internal modules.
"""

from __future__ import annotations

from submission.agent import Agent
from submission.src.shopping_copilot.intent_tracker import normalize


__all__ = ["Agent", "normalize"]
