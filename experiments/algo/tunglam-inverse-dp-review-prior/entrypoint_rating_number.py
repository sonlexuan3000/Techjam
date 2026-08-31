"""Compatibility entrypoint for the catalog rating-count ablation."""

from __future__ import annotations

from pathlib import Path

from tunglam_inverse_dp.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the integrated core with a global catalog popularity prior."""

    return Agent(
        catalog_path,
        prior_field="rating_number",
        prior_smoothing=0.0,
    )
