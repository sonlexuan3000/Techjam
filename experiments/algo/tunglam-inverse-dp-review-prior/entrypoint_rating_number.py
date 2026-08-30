"""Catalog-only rating-count ablation for the inverse-DP candidate."""

from __future__ import annotations

from pathlib import Path

from tunglam_inverse_dp.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the same candidate using only the supplied catalog popularity."""

    return Agent(
        catalog_path,
        prior_field="rating_number",
        prior_smoothing=0.0,
    )
