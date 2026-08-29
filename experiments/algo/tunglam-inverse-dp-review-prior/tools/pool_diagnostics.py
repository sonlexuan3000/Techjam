#!/usr/bin/env python3
"""Summarize candidate-pool changes caused by each protocol evidence step."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[4]
CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, CANDIDATE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from entrypoint import build_agent  # noqa: E402
from evaluator.local_evaluator import (  # noqa: E402
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
)


def transition_name(message: str, turn: int, scenario: str, disclosure: int) -> str:
    normalized = message.lower()
    if turn == 1:
        if scenario == "buying":
            return "initial category + one hard constraint"
        if scenario == "intent_override":
            return "initial category + old soft preference"
        return "initial category"
    if normalized.startswith("for that, what matters is:"):
        return f"constraint disclosure {disclosure} (up to two values)"
    if normalized.startswith("actually, ignore my earlier preference"):
        return "intent override"
    return "no new constraint"


def summarize(values: list[tuple[int, int]]) -> dict:
    before = [item[0] for item in values]
    after = [item[1] for item in values]
    return {
        "transitions": len(values),
        "mean_before": round(statistics.fmean(before), 3),
        "mean_after": round(statistics.fmean(after), 3),
        "median_before": statistics.median(before),
        "median_after": statistics.median(after),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/unseen_eval/dev_set.jsonl")
    args = parser.parse_args()

    agent = build_agent(args.catalog)
    # Filtering is independent of Top-K choice. Bypass DP so this diagnostic
    # measures all protocol steps quickly and does not end a session on a hit.
    agent._recommendation_limit = lambda state, ranked, turn, top_k: 0

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    transitions: dict[str, list[tuple[int, int]]] = defaultdict(list)

    for sample in samples:
        session_id = f"pool_{uuid.uuid4().hex}"
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        intent_card, behavior = materialize_hidden_fields(sample, products)
        effective_sample = {**sample, "intent_card": intent_card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        user_message = initial_message(
            effective_sample,
            coarse_category(categories.get(target, [])),
            disclosed,
        )
        disclosure_number = 0

        for turn in range(1, MAX_TURNS + 1):
            before = (
                len(catalog_ids)
                if turn == 1
                else len(agent.sessions[session_id].current_candidates)
            )
            if user_message.lower().startswith("for that, what matters is:"):
                disclosure_number += 1
            label = transition_name(
                user_message,
                turn,
                str(sample["scenario_type"]),
                disclosure_number,
            )
            response = agent.respond(session_id, user_message, turn, TOP_K)
            after = len(agent.sessions[session_id].current_candidates)
            transitions[label].append((before, after))

            if turn == MAX_TURNS:
                break
            override = effective_sample.get("behavior", {}).get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message = str(override.get("message", ""))
            else:
                user_message, boundary_used = customer_reply(
                    effective_sample,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                )

    result = {
        name: summarize(values)
        for name, values in sorted(transitions.items())
        if name != "no new constraint"
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
