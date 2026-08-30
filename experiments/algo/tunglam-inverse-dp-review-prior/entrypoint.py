"""Primary, data-safe entrypoint for the inverse-card + DP candidate."""

from __future__ import annotations

from pathlib import Path

from tunglam_inverse_dp.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the candidate without modifying the shared starter agent."""

    return Agent(
        catalog_path,
        prior_field="uniform",
        prior_smoothing=0.0,
    )
