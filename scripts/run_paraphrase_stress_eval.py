#!/usr/bin/env python3
"""Run a deterministic, development-only paraphrase stress evaluation.

This evaluator preserves the official local evaluator's catalog, hidden intent
cards, scenario behavior, disclosure order, turn timing, recommendation
normalization, and metrics.  It changes only the natural-language wrappers
around facts that the simulator would have revealed anyway.

The resulting score is not an official competition score and must not be
reported as one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluator.local_evaluator import (  # noqa: E402
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
from starter.agent import Agent  # noqa: E402
from scripts.evaluate_candidate import load_candidate  # noqa: E402


STRESS_TEST_NOTE = (
    "Development-only deterministic paraphrase stress test. Only message "
    "wrappers change; this is not the official evaluator score and does not "
    "claim to predict private-set wording."
)

BUYING_INITIAL_TEMPLATES = (
    "I need {category}. One requirement I can't compromise on is: {constraint}.",
    "Help me find {category}; it must satisfy: {constraint}.",
    "I'm shopping for {category}, and this is essential: {constraint}.",
    "For {category}, my main requirement is: {constraint}.",
)

BROWSING_INITIAL_TEMPLATES = (
    "I'm considering {category}, but I haven't settled on the details.",
    "Help me explore {category}; my preferences are still open.",
    "I'd like to browse {category}. I don't have firm requirements yet.",
    "I'm shopping for {category} and could use help narrowing it down.",
)

OVERRIDE_INITIAL_TEMPLATES = (
    "I'm shopping for {category}. One thing I care about is: {old_value}.",
    "I need {category}. My current preference is: {old_value}.",
    "Please help me find {category}; for now, I prefer: {old_value}.",
    "I'm considering {category}. I'd like this if possible: {old_value}.",
)

OVERRIDE_TEMPLATES = (
    "Actually, set aside my earlier preference. What I need now is: {new_value}.",
    "I've changed my mind; please ignore the previous preference. My requirement is: {new_value}.",
    "Correction: the earlier preference no longer matters. Please prioritize: {new_value}.",
    "Please replace my earlier preference with this requirement: {new_value}.",
)

BOUNDARY_TEMPLATES = (
    "I don't have a preference regarding {attribute}; use your best judgment.",
    "No preference on {attribute}; I'm flexible there.",
    "{attribute} isn't something I care about, so you can decide.",
    "I'm open on {attribute}; please choose what makes sense.",
)

NO_ATTRIBUTE_TEMPLATES = (
    "Those aren't quite right. Please ask me about a specific attribute.",
    "I'm not ready to choose from those; ask one focused attribute question.",
    "Let's narrow it down first; ask about one concrete attribute.",
    "Please ask about a particular attribute before suggesting more.",
)

NO_ADDITIONAL_PREFERENCE_TEMPLATES = (
    "I don't have any further preference for {attribute}.",
    "Nothing else comes to mind for {attribute}.",
    "I have no additional requirement about {attribute}.",
    "No extra preference on {attribute}.",
)

CONSTRAINT_REPLY_TEMPLATES = (
    "For that, these points matter to me: {constraints}.",
    "Here is what I care about for that: {constraints}.",
    "My relevant requirements or preferences are: {constraints}.",
    "Please take these into account: {constraints}.",
)

TEMPLATE_FAMILIES: dict[str, tuple[str, ...]] = {
    "initial_buying": BUYING_INITIAL_TEMPLATES,
    "initial_browsing": BROWSING_INITIAL_TEMPLATES,
    "initial_override": OVERRIDE_INITIAL_TEMPLATES,
    "intent_override": OVERRIDE_TEMPLATES,
    "boundary_no_preference": BOUNDARY_TEMPLATES,
    "missing_ask_attribute": NO_ATTRIBUTE_TEMPLATES,
    "no_additional_preference": NO_ADDITIONAL_PREFERENCE_TEMPLATES,
    "constraint_reply": CONSTRAINT_REPLY_TEMPLATES,
}


def _variant_index(sample_id: str, turn: int, message_kind: str, count: int) -> int:
    """Choose a stable template from only sample ID, delivered turn, and kind."""

    seed = f"{sample_id}\0{turn}\0{message_kind}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(seed).digest()[:8], "big") % count


def _render_variant(
    sample_id: str,
    turn: int,
    message_kind: str,
    usage: dict[str, Counter[int]],
    **values: str,
) -> str:
    templates = TEMPLATE_FAMILIES[message_kind]
    index = _variant_index(sample_id, turn, message_kind, len(templates))
    usage[message_kind][index] += 1
    return templates[index].format(**values)


def paraphrased_initial_message(
    sample: dict,
    category: str,
    disclosed: set[str],
    usage: dict[str, Counter[int]],
) -> str:
    """Mirror initial_message while changing only its natural-language wrapper."""

    sample_id = str(sample["sample_id"])
    scenario = str(sample["scenario_type"])
    if scenario == "buying" and sample["intent_card"].get("hard_constraints"):
        constraint = str(sample["intent_card"]["hard_constraints"][0])
        disclosed.add(constraint)
        return _render_variant(
            sample_id,
            1,
            "initial_buying",
            usage,
            category=category,
            constraint=constraint,
        )
    if scenario == "intent_override":
        old_value = str(sample["behavior"]["override"]["old_value"])
        return _render_variant(
            sample_id,
            1,
            "initial_override",
            usage,
            category=category,
            old_value=old_value,
        )
    return _render_variant(
        sample_id,
        1,
        "initial_browsing",
        usage,
        category=category,
    )


def paraphrased_override_message(
    sample_id: str,
    delivered_turn: int,
    new_value: str,
    usage: dict[str, Counter[int]],
) -> str:
    return _render_variant(
        sample_id,
        delivered_turn,
        "intent_override",
        usage,
        new_value=new_value,
    )


def paraphrased_customer_reply(
    sample: dict,
    ask_attribute: object,
    disclosed: set[str],
    boundary_used: bool,
    delivered_turn: int,
    usage: dict[str, Counter[int]],
) -> tuple[str, bool]:
    """Mirror customer_reply exactly, except for deterministic prose wrappers."""

    sample_id = str(sample["sample_id"])
    attribute = ask_attribute if isinstance(ask_attribute, str) else None
    if sample["scenario_type"] == "boundary" and not boundary_used and attribute:
        return (
            _render_variant(
                sample_id,
                delivered_turn,
                "boundary_no_preference",
                usage,
                attribute=attribute,
            ),
            True,
        )
    if not attribute:
        return (
            _render_variant(
                sample_id,
                delivered_turn,
                "missing_ask_attribute",
                usage,
            ),
            boundary_used,
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
                delivered_turn,
                "no_additional_preference",
                usage,
                attribute=attribute,
            ),
            boundary_used,
        )

    disclosed.update(matches)
    return (
        _render_variant(
            sample_id,
            delivered_turn,
            "constraint_reply",
            usage,
            constraints="; ".join(matches),
        ),
        boundary_used,
    )


def _metric_payload(sessions: list[dict]) -> dict:
    overall = metric_summary(sessions)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = (
        0.50 * overall["hit_rate_at_10"]
        + 0.30 * overall["mrr"]
        + 0.20 * efficiency
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[session["scenario_type"]].append(session)
    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        "scenario_metrics": {
            name: metric_summary(grouped[name]) for name in sorted(grouped)
        },
    }


def evaluate_stress(
    agent: Agent,
    samples: list[dict],
    catalog_ids: set[str],
    categories: dict[str, list[str]],
    products: dict[str, dict],
) -> dict:
    if not samples:
        raise ValueError("The stress dataset must contain at least one session")

    sessions: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    variant_usage: dict[str, Counter[int]] = defaultdict(Counter)

    for sample_index, sample in enumerate(samples, start=1):
        sample_id = str(sample["sample_id"])
        session_id = f"stress_{sample_index:06d}_{sample_id}"
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        effective_intent_card, effective_behavior = materialize_hidden_fields(sample, products)
        effective_sample = {
            **sample,
            "intent_card": effective_intent_card,
            "behavior": effective_behavior,
        }
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        user_message = paraphrased_initial_message(
            effective_sample,
            coarse_category(categories.get(target, [])),
            disclosed,
            variant_usage,
        )
        hit_turn: int | None = None
        best_rank: int | None = None

        for turn in range(1, MAX_TURNS + 1):
            try:
                response = agent.respond(session_id, user_message, turn, TOP_K)
            except Exception:
                response = {"message": "", "ask_attribute": None, "recommendations": []}
            if not isinstance(response, dict) or not isinstance(response.get("message"), str):
                response = {"message": "", "ask_attribute": None, "recommendations": []}

            usage = response.get("usage")
            if isinstance(usage, dict):
                if isinstance(usage.get("prompt_tokens"), int) and usage["prompt_tokens"] >= 0:
                    total_prompt_tokens += usage["prompt_tokens"]
                if (
                    isinstance(usage.get("completion_tokens"), int)
                    and usage["completion_tokens"] >= 0
                ):
                    total_completion_tokens += usage["completion_tokens"]

            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            if override_applied and target in ranked:
                best_rank = ranked.index(target) + 1
                hit_turn = turn
                break
            if turn == MAX_TURNS:
                break

            delivered_turn = turn + 1
            override = effective_sample.get("behavior", {}).get("override") or {}
            if not override_applied and delivered_turn == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message = paraphrased_override_message(
                    sample_id,
                    delivered_turn,
                    new_value,
                    variant_usage,
                )
            else:
                user_message, boundary_used = paraphrased_customer_reply(
                    effective_sample,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                    delivered_turn,
                    variant_usage,
                )

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

    metrics = _metric_payload(sessions)
    return {
        "stress_test_note": STRESS_TEST_NOTE,
        "variant_policy": {
            "deterministic": True,
            "selection": (
                "SHA-256(sample_id + NUL + delivered_turn + NUL + message_kind), "
                "then modulo the number of templates in that family"
            ),
            "changed": "Natural-language wrappers only",
            "preserved": [
                "exact hidden constraint strings and their order",
                "intent-card construction and scenario behavior",
                "disclosure state and at-most-two reply limit",
                "override and boundary timing",
                "target ASIN, maximum turns, Top-10 normalization, and metrics",
            ],
            "external_models_or_apis": False,
            "template_counts": {
                name: len(templates) for name, templates in TEMPLATE_FAMILIES.items()
            },
        },
        **metrics,
        "reported_token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
        "variant_usage": {
            family: {
                str(index): variant_usage[family][index]
                for index in range(len(TEMPLATE_FAMILIES[family]))
            }
            for family in TEMPLATE_FAMILIES
        },
        "sessions": sessions,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/unseen_eval/dev_set.jsonl")
    parser.add_argument(
        "--output",
        default="data/unseen_eval/dev_paraphrase_stress_results.json",
    )
    parser.add_argument(
        "--entrypoint",
        help="optional experiment entrypoint.py exposing build_agent(catalog_path)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = load_jsonl(args.dataset)
    catalog_ids, categories, products = catalog_index(args.catalog)
    if args.entrypoint:
        agent, entrypoint_path = load_candidate(args.entrypoint, args.catalog)
        candidate_name = str(entrypoint_path)
    else:
        agent = Agent(args.catalog)
        candidate_name = "starter.agent:Agent"
    result = evaluate_stress(
        agent,
        samples,
        catalog_ids,
        categories,
        products,
    )
    result = {"candidate": candidate_name, "dataset": args.dataset, **result}
    Path(args.output).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "sessions"},
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
