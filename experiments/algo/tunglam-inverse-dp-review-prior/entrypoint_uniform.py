"""Compatibility alias for the primary uniform inverse-DP candidate."""

from __future__ import annotations

from pathlib import Path

from tunglam_inverse_dp.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the data-safe primary candidate with equal product priors."""

    return Agent(
        catalog_path,
        prior_field="uniform",
        prior_smoothing=0.0,
    )
