"""Compatibility entrypoint for the selected offline review-prior backend."""

from __future__ import annotations

from pathlib import Path

from tunglam_inverse_dp.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the integrated winner with its selected review-count prior."""

    project_root = Path(__file__).resolve().parents[3]
    return Agent(
        catalog_path,
        prior_field="verified_reviews_365d",
        prior_smoothing=1.0,
        prior_path=project_root / "submission" / "data" / "review_prior.tsv",
    )
