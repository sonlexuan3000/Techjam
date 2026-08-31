"""Submission entrypoint for the best validated vinh-greedy candidate."""

from agent import ConservativeBellmanTopKAgent


def build_agent(catalog_path: str):
    return ConservativeBellmanTopKAgent(catalog_path)
