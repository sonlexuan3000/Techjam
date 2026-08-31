"""Compatibility entrypoint for the uniform-belief ablation."""

from __future__ import annotations

from pathlib import Path

from tunglam_inverse_dp.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the integrated core with equal inverse-DP belief priors."""

    return Agent(
        catalog_path,
        prior_field="uniform",
        prior_smoothing=0.0,
    )
