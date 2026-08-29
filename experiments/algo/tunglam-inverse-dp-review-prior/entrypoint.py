"""Isolated entrypoint for the inverse-DP review-prior candidate."""

from __future__ import annotations

from pathlib import Path

from src.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the candidate without modifying the shared starter agent."""

    candidate_root = Path(__file__).resolve().parent
    return Agent(
        catalog_path,
        review_features_path=candidate_root / "data" / "review_prior.tsv",
    )
