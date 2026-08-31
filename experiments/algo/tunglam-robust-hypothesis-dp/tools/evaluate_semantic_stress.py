#!/usr/bin/env python3
"""Development-only stress test that paraphrases selected constraint values."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluator.local_evaluator import (
    ALLOWED_ATTRIBUTES,
    MAX_TURNS,
    TOP_K,
    catalog_index,
    classify_constraint,
    coarse_category,
    load_jsonl,
    materialize_hidden_fields,
    metric_summary,
    normalize_recommendations,
)
from scripts.evaluate_candidate import load_candidate
from scripts.run_paraphrase_stress_eval import (
    _metric_payload,
    _render_variant,
)
from starter.agent import Agent as BaselineAgent


VALUE_PARAPHRASES = (
    ("water resistant", "not wet in rain"),
    ("waterproof", "not wet in rain"),
    ("rubber outsole", "good traction"),
    ("rubber sole", "good traction"),
    ("amplifoam", "comfortable"),
    ("cushion", "comfortable"),
    ("breathable", "good airflow"),
    ("mesh", "good airflow"),
    ("lightweight", "not heavy"),
    ("machine wash", "easy to clean"),
    ("moisture", "dry"),
    ("wide fit", "extra room"),
    ("durable", "sturdy"),
)


def semanticize(value: str) -> tuple[str, bool]:
    lowered = value.lower()
    for needle, paraphrase in VALUE_PARAPHRASES:
        if needle in lowered:
            return paraphrase, True
    return value, False


def sample_has_transform(sample: dict, products: dict[str, dict]) -> bool:
    card, behavior = materialize_hidden_fields(sample, products)
    values = [
        *[str(value) for value in card.get("hard_constraints", [])],
        *[str(value) for value in card.get("soft_preferences", [])],
    ]
    override = behavior.get("override") or {}
    values.extend(
        str(override.get(name, ""))
        for name in ("old_value", "new_value")
    )
    return any(semanticize(value)[1] for value in values)


def initial_message(
    sample: dict,
    category: str,
    disclosed: set[str],
    usage: dict[str, Counter[int]],
) -> tuple[str, bool]:
    sample_id = str(sample["sample_id"])
    scenario = str(sample["scenario_type"])
    if scenario == "buying" and sample["intent_card"].get("hard_constraints"):
        original = str(sample["intent_card"]["hard_constraints"][0])
        disclosed.add(original)
        value, changed = semanticize(original)
        return (
            _render_variant(
                sample_id,
                1,
                "initial_buying",
                usage,
                category=category,
                constraint=value,
            ),
            changed,
        )
    if scenario == "intent_override":
        original = str(sample["behavior"]["override"]["old_value"])
        value, changed = semanticize(original)
        return (
            _render_variant(
                sample_id,
                1,
                "initial_override",
                usage,
                category=category,
                old_value=value,
            ),
            changed,
        )
    return (
        _render_variant(
            sample_id,
            1,
            "initial_browsing",
            usage,
            category=category,
        ),
        False,
    )


def override_message(
    sample_id: str,
    turn: int,
    value: str,
    usage: dict[str, Counter[int]],
) -> tuple[str, bool]:
    paraphrase, changed = semanticize(value)
    return (
        _render_variant(
            sample_id,
            turn,
            "intent_override",
            usage,
            new_value=paraphrase,
        ),
        changed,
    )


def customer_reply(
    sample: dict,
    ask_attribute: object,
    disclosed: set[str],
    boundary_used: bool,
    turn: int,
    usage: dict[str, Counter[int]],
) -> tuple[str, bool, bool]:
    sample_id = str(sample["sample_id"])
    attribute = ask_attribute if isinstance(ask_attribute, str) else None
    if sample["scenario_type"] == "boundary" and not boundary_used and attribute:
        return (
            _render_variant(
                sample_id,
                turn,
                "boundary_no_preference",
                usage,
                attribute=attribute,
            ),
            True,
            False,
        )
    if not attribute:
        return (
            _render_variant(
                sample_id,
                turn,
                "missing_ask_attribute",
                usage,
            ),
            boundary_used,
            False,
        )
    if attribute not in ALLOWED_ATTRIBUTES:
        attribute = "other"

    constraints = [
        *[str(value) for value in sample["intent_card"].get("hard_constraints", [])],
        *[str(value) for value in sample["intent_card"].get("soft_preferences", [])],
    ]
    matches = [
        value
        for value in constraints
        if value not in disclosed
        and (attribute == "other" or classify_constraint(value) == attribute)
    ][:2]
    if not matches:
        return (
            _render_variant(
                sample_id,
                turn,
                "no_additional_preference",
                usage,
                attribute=attribute,
            ),
            boundary_used,
            False,
        )

    disclosed.update(matches)
    rendered: list[str] = []
    changed = False
    for value in matches:
        paraphrase, value_changed = semanticize(value)
        rendered.append(paraphrase)
        changed = changed or value_changed
    return (
        _render_variant(
            sample_id,
            turn,
            "constraint_reply",
            usage,
            constraints="; ".join(rendered),
        ),
        boundary_used,
        changed,
    )


def evaluate(agent, samples, catalog_ids, categories, products) -> dict:
    sessions: list[dict] = []
    usage: dict[str, Counter[int]] = defaultdict(Counter)
    transformed_sessions: set[str] = set()

    for index, sample in enumerate(samples, start=1):
        sample_id = str(sample["sample_id"])
        session_id = f"semantic_{index:06d}_{sample_id}"
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        effective = {**sample, "intent_card": card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        user_message, changed = initial_message(
            effective,
            coarse_category(categories.get(target, [])),
            disclosed,
            usage,
        )
        if changed:
            transformed_sessions.add(sample_id)

        hit_turn = None
        best_rank = None
        for turn in range(1, MAX_TURNS + 1):
            response = agent.respond(session_id, user_message, turn, TOP_K)
            ranked = normalize_recommendations(
                response.get("recommendations"),
                catalog_ids,
            )
            if override_applied and target in ranked:
                hit_turn = turn
                best_rank = ranked.index(target) + 1
                break
            if turn == MAX_TURNS:
                break

            delivered_turn = turn + 1
            override = effective.get("behavior", {}).get("override") or {}
            if not override_applied and delivered_turn == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message, changed = override_message(
                    sample_id,
                    delivered_turn,
                    new_value,
                    usage,
                )
            else:
                user_message, boundary_used, changed = customer_reply(
                    effective,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                    delivered_turn,
                    usage,
                )
            if changed:
                transformed_sessions.add(sample_id)

        sessions.append(
            {
                "sample_id": sample_id,
                "scenario_type": sample["scenario_type"],
                "hit": hit_turn is not None,
                "first_hit_turn": hit_turn,
                "best_rank": best_rank,
                "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
            }
        )

    affected = [
        session
        for session in sessions
        if session["sample_id"] in transformed_sessions
    ]
    return {
        "note": (
            "Development-only stress test. Selected catalog values are replaced "
            "with deterministic semantic paraphrases; this is not official data."
        ),
        "transformed_session_count": len(transformed_sessions),
        **_metric_payload(sessions),
        "transformed_session_metrics": metric_summary(affected),
        "sessions": sessions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/unseen_eval/dev_set.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--entrypoint")
    parser.add_argument(
        "--affected-only",
        action="store_true",
        help="evaluate only sessions whose intent card contains a mapped value",
    )
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    if args.affected_only:
        samples = [
            sample
            for sample in samples
            if sample_has_transform(sample, products)
        ]
    if args.entrypoint:
        agent, path = load_candidate(args.entrypoint, args.catalog)
        candidate = str(path)
    else:
        agent = BaselineAgent(args.catalog)
        candidate = "starter.agent:Agent"
    result = {
        "candidate": candidate,
        "dataset": args.dataset,
        **evaluate(agent, samples, catalog_ids, categories, products),
    }
    Path(args.output).write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "sessions"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
