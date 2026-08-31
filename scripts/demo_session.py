#!/usr/bin/env python3
"""Show one reproducible end-to-end conversation against the real catalog."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from starter.agent import Agent  # noqa: E402


def choose_target(agent: Agent, requested: str | None) -> str:
    if requested:
        if requested not in agent.products:
            raise ValueError(f"unknown parent_asin: {requested}")
        return requested

    # Pick a product late in the stable uniform ordering from a non-trivial
    # category so the demo normally shows clarification before a hit.
    category_sizes = Counter(product.category for product in agent.products.values())
    for parent_asin in reversed(agent.all_product_ids):
        product = agent.products[parent_asin]
        if len(product.constraints) >= 2 and category_sizes[product.category] >= 20:
            return parent_asin
    return agent.all_product_ids[-1]


def print_turn(turn: int, user_message: str, response: dict) -> None:
    print(f"\nTurn {turn}")
    print(f"User:  {user_message}")
    print(f"Agent: {response['message']}")
    print(f"Ask:   {response['ask_attribute']}")
    print(
        "Top:   "
        + json.dumps(
            [item["parent_asin"] for item in response["recommendations"]],
            ensure_ascii=False,
        )
    )


def run_demo(catalog_path: str, target_asin: str | None) -> int:
    agent = Agent(catalog_path)
    target_asin = choose_target(agent, target_asin)
    target = agent.products[target_asin]
    session_id = "local-demo"
    profile = {
        "purchase_frequency": "occasional",
        "average_prior_rating": 4.2,
        "rating_style": "balanced",
        "preference_tags": [],
        "summary": "Demo profile; ranking currently uses conversation evidence only.",
    }
    agent.reset(session_id, profile)

    print(f"Hidden demo target: {target_asin}")
    print(f"Category: {target.category}")
    disclosed: set[str] = set()
    user_message = f"I'm looking for {target.category}, but I'm still exploring."

    for turn in range(1, 11):
        response = agent.respond(session_id, user_message, turn, 10)
        print_turn(turn, user_message, response)
        recommendations = {
            item["parent_asin"] for item in response["recommendations"]
        }
        if target_asin in recommendations:
            rank = next(
                index
                for index, item in enumerate(response["recommendations"], start=1)
                if item["parent_asin"] == target_asin
            )
            print(f"\nFound target on turn {turn} at rank {rank}.")
            return 0

        remaining = [
            value for value in target.constraints if value not in disclosed
        ]
        if remaining:
            revealed = remaining[:2]
            disclosed.update(revealed)
            user_message = (
                "For that, what matters is: " + "; ".join(revealed) + "."
            )
        else:
            user_message = "I don't have an additional preference for other."

    print("\nTarget was not found within 10 turns.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--target-asin")
    args = parser.parse_args()
    raise SystemExit(run_demo(args.catalog, args.target_asin))


if __name__ == "__main__":
    main()
