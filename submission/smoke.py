#!/usr/bin/env python3
"""Run a one-turn contract smoke test using only the submission bundle."""

from __future__ import annotations

import argparse
import json

from agent import Agent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    args = parser.parse_args()

    agent = Agent(args.catalog)
    example_product = next(iter(agent.products.values()))
    session_id = "submission-smoke"
    agent.reset(
        session_id,
        {
            "purchase_frequency": "occasional",
            "average_prior_rating": 4.2,
            "rating_style": "balanced",
            "preference_tags": ["practical"],
            "summary": "Submission smoke-test profile.",
        },
    )
    response = agent.respond(
        session_id,
        f"I'm looking for {example_product.category}, but I'm still exploring.",
        turn=1,
        top_k=10,
    )

    assert isinstance(response.get("message"), str)
    assert response.get("ask_attribute") == "other"
    recommendations = response.get("recommendations")
    assert isinstance(recommendations, list) and len(recommendations) <= 10
    assert all(
        isinstance(item, dict) and item.get("parent_asin") in agent.products
        for item in recommendations
    )
    assert response.get("usage") == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
