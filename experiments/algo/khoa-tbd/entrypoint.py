"""Entrypoint for Khoa's algorithm experiment candidate."""

from pathlib import Path

from src.agent import Agent


ADAPTIVE_K_MODEL = Path(__file__).with_name("adaptive_k_model.json")


def build_agent(catalog_path: str) -> Agent:
    """Build Khoa's candidate agent."""

    return Agent(
        catalog_path,
        adaptive_k_model_path=ADAPTIVE_K_MODEL if ADAPTIVE_K_MODEL.is_file() else None,
    )
