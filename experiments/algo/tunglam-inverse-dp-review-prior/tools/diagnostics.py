#!/usr/bin/env python3
"""Measure candidate latency and filter survival on generated sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource
import sys
import time
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
    normalize_recommendations,
)


def rss_mib() -> float:
    """Return process peak RSS in MiB on macOS or Linux."""

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return value / divisor


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/unseen_eval/dev_set.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rss_before = rss_mib()
    started = time.perf_counter()
    agent = build_agent(args.catalog)
    startup_seconds = time.perf_counter() - started
    startup_rss_mib = max(0.0, rss_mib() - rss_before)

    samples = load_jsonl(args.dataset)
    if args.limit > 0:
        samples = samples[: args.limit]
    catalog_ids, categories, products = catalog_index(args.catalog)

    turn_latencies_ms: list[float] = []
    survived_sessions = 0
    false_elimination_sessions = 0

    for sample in samples:
        session_id = f"diagnostic_{uuid.uuid4().hex}"
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
        survived = True

        for turn in range(1, MAX_TURNS + 1):
            turn_started = time.perf_counter()
            response = agent.respond(session_id, user_message, turn, TOP_K)
            turn_latencies_ms.append((time.perf_counter() - turn_started) * 1000)

            state = agent.sessions[session_id]
            if target not in state.current_candidates:
                survived = False

            ranked = normalize_recommendations(
                response.get("recommendations"), catalog_ids
            )
            if override_applied and target in ranked:
                break
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

        if survived:
            survived_sessions += 1
        else:
            false_elimination_sessions += 1

    result = {
        "sample_count": len(samples),
        "turn_count": len(turn_latencies_ms),
        "target_survival_rate": survived_sessions / len(samples),
        "false_elimination_rate": false_elimination_sessions / len(samples),
        "mean_turn_latency_ms": sum(turn_latencies_ms) / len(turn_latencies_ms),
        "p95_turn_latency_ms": percentile_95(turn_latencies_ms),
        "startup_seconds": startup_seconds,
        "startup_peak_rss_increment_mib": startup_rss_mib,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
