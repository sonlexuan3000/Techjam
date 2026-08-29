"""Uniform-prior ablation for the inverse-DP candidate."""

from __future__ import annotations

from pathlib import Path

from src.agent import Agent


def build_agent(catalog_path: str | Path) -> Agent:
    """Build the same candidate with equal probability for every product."""

    return Agent(
        catalog_path,
        prior_field="uniform",
        prior_smoothing=0.0,
    )
