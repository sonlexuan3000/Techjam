#!/usr/bin/env python3
"""Evaluate the frozen independent human-style paraphrase fixture.

This is a diagnostic benchmark, not an organizer score.  It separates:

1. strict and content-aware conversation-state extraction,
2. polarity/deactivation handling,
3. selective catalog grounding to a concrete generated-dev target,
4. end-to-end success across state and grounding.

The fixture is intentionally generated without reading the participant parser.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from starter.agent import Agent, normalize  # noqa: E402


EXPECTED_KINDS = {"wrapper_exact_value", "semantic_value_paraphrase"}
EXPECTED_SCENARIOS = {
    "buying",
    "browsing",
    "intent_override",
    "boundary",
    "negation",
    "compound",
}
FACT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "brand",
    "color",
    "do",
    "does",
    "for",
    "feature",
    "finish",
    "from",
    "has",
    "have",
    "i",
    "in",
    "is",
    "it",
    "made",
    "material",
    "me",
    "my",
    "of",
    "on",
    "please",
    "rather",
    "really",
    "should",
    "size",
    "style",
    "that",
    "the",
    "this",
    "to",
    "too",
    "value",
    "want",
    "will",
    "with",
    "would",
}
CATEGORY_IGNORED_TOKENS = {
    "a",
    "an",
    "and",
    "boys",
    "for",
    "girls",
    "items",
    "kids",
    "men",
    "of",
    "the",
    "unisex",
    "women",
}
MAX_GROUNDING_CATALOG_FRACTION = 0.25
MIN_GROUNDING_REFERENCE_PRECISION = 0.25


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on fixture line {line_number}: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"fixture line {line_number} must be a JSON object")
            cases.append(value)
    return cases


def load_excluded_targets(path: str | Path) -> set[str]:
    targets: set[str] = set()
    for sample in load_jsonl(path):
        ground_truth = sample.get("ground_truth")
        if isinstance(ground_truth, dict) and ground_truth.get("parent_asin"):
            targets.add(str(ground_truth["parent_asin"]))
    return targets


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "sses", "xes", "zes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 3 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _canonical_tokens(value: object, *, category: bool = False) -> set[str]:
    text = str(value).lower().replace("’", "'")
    text = re.sub(r"\bwon't\b", "will not", text)
    text = re.sub(r"\bcan't\b", "can not", text)
    text = re.sub(r"\bt[ -]?shirts?\b", "tshirt", text)
    text = re.sub(r"\btees?\b", "tshirt", text)
    ignored = CATEGORY_IGNORED_TOKENS if category else FACT_STOPWORDS
    return {_stem(token) for token in normalize(text).split() if token not in ignored}


def category_state_matches(expected: str | None, actual: object) -> bool:
    actual_text = "" if actual is None else str(actual).strip()
    if expected is None:
        return not actual_text
    actual_tokens = _canonical_tokens(actual_text, category=True)
    expected_tokens = _canonical_tokens(expected, category=True)
    return bool(actual_tokens) and actual_tokens <= expected_tokens


def fact_similarity(left: str, right: str) -> float:
    left_tokens = _canonical_tokens(left)
    right_tokens = _canonical_tokens(right)
    if not left_tokens or not right_tokens:
        return float(normalize(left) == normalize(right))
    return 2.0 * len(left_tokens & right_tokens) / (
        len(left_tokens) + len(right_tokens)
    )


def match_facts(
    expected: list[str],
    actual: list[str],
    *,
    threshold: float,
) -> dict[int, int] | None:
    if not expected:
        return {} if not actual else None
    if not actual:
        return None

    expected_tokens = [_canonical_tokens(value) for value in expected]
    actual_tokens = [_canonical_tokens(value) for value in actual]
    if any(not tokens for tokens in expected_tokens + actual_tokens):
        return None

    expected_union = set().union(*expected_tokens)
    actual_union = set().union(*actual_tokens)
    expected_coverage = len(expected_union & actual_union) / len(expected_union)
    actual_coverage = len(actual_union & expected_union) / len(actual_union)
    if expected_coverage < threshold or actual_coverage < threshold:
        return None

    # The concrete mapping is diagnostic-only. Fact content may legitimately be
    # split or merged by a parser, so union coverage decides equivalence.
    return {
        expected_index: max(
            range(len(actual_tokens)),
            key=lambda actual_index: len(tokens & actual_tokens[actual_index]),
        )
        for expected_index, tokens in enumerate(expected_tokens)
    }


def _string_list(value: object, *, field: str, case_id: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{case_id}: {field} must be a list of strings")
    return value


def load_candidate(catalog_path: str, entrypoint: str) -> tuple[Any, str]:
    entrypoint_path = Path(entrypoint).resolve()
    if not entrypoint_path.is_file():
        raise ValueError(f"candidate entrypoint does not exist: {entrypoint_path}")
    module_suffix = hashlib.sha256(str(entrypoint_path).encode()).hexdigest()[:12]
    module_name = f"techjam_candidate_{module_suffix}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load candidate entrypoint: {entrypoint_path}")
    module = importlib.util.module_from_spec(spec)
    candidate_dir = str(entrypoint_path.parent)
    sys.path.insert(0, candidate_dir)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.path.remove(candidate_dir)
    builder = getattr(module, "build_agent", None)
    if not callable(builder):
        raise ValueError(f"{entrypoint_path} must expose build_agent(catalog_path)")
    candidate = builder(catalog_path)
    required = ("reset", "respond", "debug_state")
    missing = [name for name in required if not callable(getattr(candidate, name, None))]
    has_grounding_probe = any(
        callable(getattr(candidate, name, None))
        for name in ("debug_clue_candidates", "_clue_candidates")
    )
    if not has_grounding_probe:
        missing.append("debug_clue_candidates")
    if missing:
        raise ValueError(
            f"candidate from {entrypoint_path} lacks NLP diagnostic methods: {missing}"
        )
    return candidate, str(entrypoint_path)


def clue_candidates(candidate: Any, clue: str, category: str | None) -> set[str]:
    """Read a candidate's diagnostic grounding result without ranking it."""

    probe = getattr(candidate, "debug_clue_candidates", None)
    if callable(probe):
        parameters = inspect.signature(probe).parameters.values()
        accepts_category = any(
            parameter.name == "category"
            or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        result = probe(clue, category=category) if accepts_category else probe(clue)
    else:
        result = candidate._clue_candidates(clue)

    # The active baseline returns ``(set[str], route)``. Candidate adapters may
    # expose the cleaner public form ``set[str]`` instead.
    values = result[0] if isinstance(result, tuple) else result
    if isinstance(values, dict):
        values = list(values)
    if not isinstance(values, (set, frozenset, list, tuple)):
        raise ValueError(
            "debug_clue_candidates(clue) must return ASINs or (ASINs, route)"
        )
    return {str(value) for value in values}


def grounding_reference_products(oracle: Agent, atom: str) -> set[str]:
    """Mirror the catalog route appropriate for the target metadata atom.

    Whole multi-token atoms use exact metadata matches. Short material/color
    atoms use the baseline's full-text special-word index, because treating only
    the exact singleton metadata field as relevant would unfairly reject valid
    products that mention the same material or color elsewhere.
    """

    key = normalize(atom)
    words = key.split()
    special_index = getattr(oracle, "special_word_to_asins", {})
    special = [word for word in words if word in special_index]
    if len(words) <= 2 and special:
        sets = [set(special_index[word]) for word in special if special_index[word]]
        if sets:
            return set.intersection(*sets)
    return set(oracle.atom_to_asins.get(key, set()))


def validate_fixture(
    cases: list[dict[str, Any]],
    oracle: Agent,
    excluded_targets: set[str],
) -> dict[str, Any]:
    if len(cases) != 100:
        raise ValueError(f"fixture must contain exactly 100 cases, found {len(cases)}")

    identifiers: set[str] = set()
    target_asins: set[str] = set()
    kind_counts: dict[str, int] = defaultdict(int)
    scenario_counts: dict[str, int] = defaultdict(int)
    all_messages: list[str] = []
    catalog_asins = set(oracle.asins)

    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("every case requires a non-empty string id")
        if case_id in identifiers:
            raise ValueError(f"duplicate case id: {case_id}")
        identifiers.add(case_id)

        kind = case.get("kind")
        scenario = case.get("scenario")
        if kind not in EXPECTED_KINDS:
            raise ValueError(f"{case_id}: unsupported kind {kind!r}")
        if scenario not in EXPECTED_SCENARIOS:
            raise ValueError(f"{case_id}: unsupported scenario {scenario!r}")
        kind_counts[str(kind)] += 1
        scenario_counts[str(scenario)] += 1

        messages = case.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 3:
            raise ValueError(f"{case_id}: messages must contain one to three turns")
        turns: list[int] = []
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError(f"{case_id}: every message must be an object")
            turn = message.get("turn")
            text = message.get("text")
            if not isinstance(turn, int) or isinstance(turn, bool):
                raise ValueError(f"{case_id}: message turn must be an integer")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{case_id}: message text must be non-empty")
            all_messages.append(text)
            turns.append(turn)
        if turns != list(range(1, len(messages) + 1)):
            raise ValueError(f"{case_id}: message turns must be consecutive from turn 1")

        expected = case.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"{case_id}: expected must be an object")
        category = expected.get("category")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"{case_id}: expected.category must be a non-empty string")
        first_message_key = normalize(messages[0]["text"])
        if normalize(category) not in first_message_key:
            raise ValueError(
                f"{case_id}: expected.category must be stated in the first message"
            )
        for field in ("positive_values", "negative_values", "inactive_values"):
            _string_list(expected.get(field), field=f"expected.{field}", case_id=case_id)

        target_asin = case.get("target_asin")
        if not isinstance(target_asin, str) or not target_asin:
            raise ValueError(f"{case_id}: target_asin must be a non-empty string")
        if target_asin not in catalog_asins:
            raise ValueError(f"{case_id}: target_asin is absent from the catalog")
        if target_asin in excluded_targets:
            raise ValueError(f"{case_id}: target_asin overlaps organizer public targets")
        if target_asin in target_asins:
            raise ValueError(f"{case_id}: duplicate target_asin {target_asin}")
        target_asins.add(target_asin)

        target_category = case.get("target_category")
        if not isinstance(target_category, str) or not target_category.strip():
            raise ValueError(f"{case_id}: target_category must be a non-empty string")
        category_key = normalize(target_category)
        if target_asin not in oracle.coarse_category_to_asins.get(category_key, set()):
            raise ValueError(
                f"{case_id}: target_category is not the target product's coarse category"
            )

        target_atoms = _string_list(
            case.get("target_atoms"),
            field="target_atoms",
            case_id=case_id,
        )
        if not isinstance(case.get("notes"), str):
            raise ValueError(f"{case_id}: notes must be a string")
        expected_atom_count = 0 if scenario == "boundary" else 2 if scenario == "compound" else 1
        if len(target_atoms) != expected_atom_count:
            raise ValueError(
                f"{case_id}: {scenario} requires {expected_atom_count} target atoms"
            )
        if len(expected["positive_values"]) != len(target_atoms):
            raise ValueError(
                f"{case_id}: positive_values and target_atoms must align one-to-one"
            )
        if scenario == "intent_override" and (
            len(messages) != 3 or not expected["inactive_values"]
        ):
            raise ValueError(
                f"{case_id}: intent_override requires three turns and an inactive old value"
            )
        if scenario == "negation" and not expected["negative_values"]:
            raise ValueError(f"{case_id}: negation requires a negative value")
        for atom in target_atoms:
            atom_products = oracle.atom_to_asins.get(normalize(atom), set())
            if target_asin not in atom_products:
                raise ValueError(
                    f"{case_id}: target atom {atom!r} is absent from target_asin"
                )
            if len(atom_products) > int(
                len(oracle.asins) * MAX_GROUNDING_CATALOG_FRACTION
            ):
                raise ValueError(
                    f"{case_id}: target atom {atom!r} is too broad for grounding"
                )

        if kind == "wrapper_exact_value":
            message_key = normalize(" ".join(str(item["text"]) for item in messages))
            exact_values = [
                *expected["positive_values"],
                *expected["negative_values"],
                *expected["inactive_values"],
            ]
            absent = [value for value in exact_values if normalize(value) not in message_key]
            if absent:
                raise ValueError(
                    f"{case_id}: wrapper_exact_value facts absent from message: {absent!r}"
                )

    expected_kind_counts = {
        "semantic_value_paraphrase": 35,
        "wrapper_exact_value": 65,
    }
    if dict(kind_counts) != expected_kind_counts:
        raise ValueError(
            f"unexpected kind distribution: {dict(kind_counts)!r}; "
            f"expected {expected_kind_counts!r}"
        )
    expected_scenario_counts = {
        "boundary": 13,
        "browsing": 18,
        "buying": 18,
        "compound": 17,
        "intent_override": 17,
        "negation": 17,
    }
    if dict(scenario_counts) != expected_scenario_counts:
        raise ValueError(
            f"unexpected scenario distribution: {dict(scenario_counts)!r}; "
            f"expected {expected_scenario_counts!r}"
        )
    if len(all_messages) != len(set(all_messages)):
        raise ValueError("all fixture messages must be unique")

    expected_ids = {f"hp_{index:03d}" for index in range(1, 101)}
    if identifiers != expected_ids:
        missing = sorted(expected_ids - identifiers)
        extra = sorted(identifiers - expected_ids)
        raise ValueError(f"fixture IDs must be hp_001..hp_100; missing={missing}, extra={extra}")

    return {
        "case_count": len(cases),
        "kind_counts": dict(sorted(kind_counts.items())),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "message_count": len(all_messages),
        "unique_message_count": len(set(all_messages)),
        "unique_target_count": len(target_asins),
        "organizer_public_target_overlap": 0,
    }


def _normalized_set(values: list[str]) -> set[str]:
    return {normalize(value) for value in values if normalize(value)}


def _state_texts(state: dict[str, Any], field: str) -> list[str]:
    return [str(item["text"]) for item in state[field]]


def evaluate_case(candidate: Any, oracle: Agent, case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case["id"])
    candidate.reset(case_id, {})
    for message in case["messages"]:
        candidate.respond(
            case_id,
            str(message["text"]),
            turn=int(message["turn"]),
            top_k=10,
        )

    state = candidate.debug_state(case_id)
    expected = case["expected"]

    expected_category = expected["category"]
    raw_actual_category = state.get("category")
    actual_category = "" if raw_actual_category is None else str(raw_actual_category)
    strict_category_pass = normalize(actual_category) == normalize(expected_category)
    category_fact_pass = category_state_matches(expected_category, raw_actual_category)

    expected_positive_texts = list(expected["positive_values"])
    actual_positive_texts = _state_texts(state, "current_intent")
    expected_negative_texts = list(expected["negative_values"])
    actual_negative_texts = _state_texts(state, "negative_evidence")
    expected_inactive_texts = list(expected["inactive_values"])
    actual_inactive_texts = [
        str(item["text"])
        for item in state["history"]
        if not item["active"] and not item["negated"]
    ]

    expected_positive = _normalized_set(expected_positive_texts)
    actual_positive = _normalized_set(actual_positive_texts)
    strict_positive_pass = actual_positive == expected_positive
    expected_negative = _normalized_set(expected_negative_texts)
    actual_negative = _normalized_set(actual_negative_texts)
    strict_negative_pass = actual_negative == expected_negative
    expected_inactive = _normalized_set(expected_inactive_texts)
    actual_inactive = _normalized_set(actual_inactive_texts)
    strict_inactive_pass = actual_inactive == expected_inactive

    strict_state_pass = (
        strict_category_pass
        and strict_positive_pass
        and strict_negative_pass
        and strict_inactive_pass
    )
    fact_threshold = 0.78 if case["kind"] == "wrapper_exact_value" else 0.55
    positive_fact_pass = match_facts(
        expected_positive_texts,
        actual_positive_texts,
        threshold=fact_threshold,
    ) is not None
    polarity_fact_pass = (
        match_facts(
            expected_negative_texts,
            actual_negative_texts,
            threshold=fact_threshold,
        )
        is not None
        and match_facts(
            expected_inactive_texts,
            actual_inactive_texts,
            threshold=fact_threshold,
        )
        is not None
    )
    deactivation_fact_pass = match_facts(
        [*expected_negative_texts, *expected_inactive_texts],
        [*actual_negative_texts, *actual_inactive_texts],
        threshold=fact_threshold,
    ) is not None
    fact_state_pass = category_fact_pass and positive_fact_pass and polarity_fact_pass
    intent_shape_pass = (
        category_fact_pass
        and len(actual_positive_texts) == len(expected_positive_texts)
        and len(actual_negative_texts) == len(expected_negative_texts)
        and len(actual_inactive_texts) == len(expected_inactive_texts)
    )

    target_atoms = list(case["target_atoms"])
    target_asin = str(case["target_asin"])
    grounding_applicable = bool(target_atoms)
    ungrounded_atoms: list[str] = []
    unselective_clues: list[dict[str, Any]] = []
    imprecise_clues: list[dict[str, Any]] = []
    candidate_set_sizes: list[int] = []
    grounding_reference_precisions: list[float] = []
    if grounding_applicable:
        for clue, atom in zip(expected_positive_texts, target_atoms):
            candidates = clue_candidates(candidate, clue, expected_category)
            candidate_set_sizes.append(len(candidates))
            reference_products = grounding_reference_products(oracle, atom)
            reference_precision = (
                len(candidates & reference_products) / len(candidates)
                if candidates
                else 0.0
            )
            grounding_reference_precisions.append(round(reference_precision, 6))
            selectivity_limit = int(
                len(oracle.asins) * MAX_GROUNDING_CATALOG_FRACTION
            )
            if target_asin not in candidates:
                ungrounded_atoms.append(atom)
            if len(candidates) > selectivity_limit:
                unselective_clues.append(
                    {
                        "clue": clue,
                        "candidate_count": len(candidates),
                        "maximum": selectivity_limit,
                    }
                )
            if reference_precision < MIN_GROUNDING_REFERENCE_PRECISION:
                imprecise_clues.append(
                    {
                        "clue": clue,
                        "candidate_count": len(candidates),
                        "reference_overlap_count": len(
                            candidates & reference_products
                        ),
                        "minimum_reference_precision": (
                            MIN_GROUNDING_REFERENCE_PRECISION
                        ),
                    }
                )
    grounding_pass: bool | None = (
        not ungrounded_atoms and not unselective_clues and not imprecise_clues
        if grounding_applicable
        else None
    )
    benchmark_pass = fact_state_pass and grounding_pass is not False

    failures: list[str] = []
    if not category_fact_pass:
        failures.append(
            f"category expected={expected_category!r} actual={actual_category!r}"
        )
    if not positive_fact_pass:
        failures.append(
            "positive expected="
            f"{sorted(expected_positive)!r} actual={sorted(actual_positive)!r}"
        )
    if not deactivation_fact_pass:
        failures.append(
            "deactivated expected="
            f"{sorted(expected_negative | expected_inactive)!r} "
            f"actual={sorted(actual_negative | actual_inactive)!r}"
        )
    if ungrounded_atoms:
        failures.append(f"ungrounded target atoms={ungrounded_atoms!r}")
    if unselective_clues:
        failures.append(f"unselective clues={unselective_clues!r}")
    if imprecise_clues:
        failures.append(f"low reference precision clues={imprecise_clues!r}")

    return {
        "id": case_id,
        "kind": case["kind"],
        "scenario": case["scenario"],
        "strict_state_pass": strict_state_pass,
        "intent_shape_pass": intent_shape_pass,
        "category_fact_pass": category_fact_pass,
        "positive_fact_pass": positive_fact_pass,
        "positive_fact_applicable": bool(expected_positive_texts),
        "deactivation_fact_pass": deactivation_fact_pass,
        "deactivation_fact_applicable": bool(
            expected_negative_texts or expected_inactive_texts
        ),
        "polarity_fact_pass": polarity_fact_pass,
        "polarity_fact_applicable": bool(
            expected_negative_texts or expected_inactive_texts
        ),
        "fact_state_pass": fact_state_pass,
        "grounding_applicable": grounding_applicable,
        "grounding_pass": grounding_pass,
        "candidate_set_sizes": candidate_set_sizes,
        "grounding_reference_precisions": grounding_reference_precisions,
        "benchmark_pass": benchmark_pass,
        "failures": failures,
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    strict_state_passes = sum(bool(result["strict_state_pass"]) for result in results)
    intent_shape_passes = sum(bool(result["intent_shape_pass"]) for result in results)
    category_fact_passes = sum(bool(result["category_fact_pass"]) for result in results)
    positive_applicable = [
        result for result in results if result["positive_fact_applicable"]
    ]
    positive_fact_passes = sum(
        bool(result["positive_fact_pass"]) for result in positive_applicable
    )
    deactivation_applicable = [
        result for result in results if result["deactivation_fact_applicable"]
    ]
    deactivation_fact_passes = sum(
        bool(result["deactivation_fact_pass"])
        for result in deactivation_applicable
    )
    fact_state_passes = sum(bool(result["fact_state_pass"]) for result in results)
    polarity_applicable = [
        result for result in results if result["polarity_fact_applicable"]
    ]
    polarity_fact_passes = sum(
        bool(result["polarity_fact_pass"]) for result in polarity_applicable
    )
    applicable = [result for result in results if result["grounding_applicable"]]
    grounding_passes = sum(bool(result["grounding_pass"]) for result in applicable)
    grounding_precisions = [
        precision
        for result in applicable
        for precision in result["grounding_reference_precisions"]
    ]
    benchmark_passes = sum(bool(result["benchmark_pass"]) for result in results)
    return {
        "case_count": count,
        "strict_state_pass_count": strict_state_passes,
        "strict_state_pass_rate": (
            round(strict_state_passes / count, 6) if count else None
        ),
        "intent_shape_pass_count": intent_shape_passes,
        "intent_shape_pass_rate": (
            round(intent_shape_passes / count, 6) if count else None
        ),
        "category_fact_pass_count": category_fact_passes,
        "category_fact_pass_rate": (
            round(category_fact_passes / count, 6) if count else None
        ),
        "positive_fact_applicable_count": len(positive_applicable),
        "positive_fact_pass_count": positive_fact_passes,
        "positive_fact_pass_rate": (
            round(positive_fact_passes / len(positive_applicable), 6)
            if positive_applicable
            else None
        ),
        "deactivation_fact_applicable_count": len(deactivation_applicable),
        "deactivation_fact_pass_count": deactivation_fact_passes,
        "deactivation_fact_pass_rate": (
            round(deactivation_fact_passes / len(deactivation_applicable), 6)
            if deactivation_applicable
            else None
        ),
        "fact_state_pass_count": fact_state_passes,
        "fact_state_pass_rate": (
            round(fact_state_passes / count, 6) if count else None
        ),
        "polarity_fact_applicable_count": len(polarity_applicable),
        "polarity_fact_pass_count": polarity_fact_passes,
        "polarity_fact_pass_rate": (
            round(polarity_fact_passes / len(polarity_applicable), 6)
            if polarity_applicable
            else None
        ),
        "grounding_applicable_count": len(applicable),
        "grounding_pass_count": grounding_passes,
        "grounding_pass_rate": (
            round(grounding_passes / len(applicable), 6) if applicable else None
        ),
        "grounding_reference_precision_mean": (
            round(sum(grounding_precisions) / len(grounding_precisions), 6)
            if grounding_precisions
            else None
        ),
        "benchmark_pass_count": benchmark_passes,
        "benchmark_pass_rate": round(benchmark_passes / count, 6) if count else None,
    }


def grouped_summary(
    results: list[dict[str, Any]],
    field: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[str(result[field])].append(result)
    return {name: aggregate(grouped[name]) for name in sorted(grouped)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the independent 100-case human paraphrase fixture"
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument(
        "--public-dataset",
        default="data/public_set.jsonl",
        help="used only to assert that fixture targets do not overlap public targets",
    )
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/independent_human_paraphrases.jsonl",
    )
    parser.add_argument(
        "--output",
        default="data/unseen_eval/independent_human_paraphrase_results.json",
    )
    parser.add_argument(
        "--entrypoint",
        help=(
            "candidate entrypoint.py exposing build_agent(catalog_path); "
            "defaults to starter.agent:Agent"
        ),
    )
    args = parser.parse_args()

    oracle = Agent(args.catalog)
    if args.entrypoint:
        candidate, candidate_name = load_candidate(args.catalog, args.entrypoint)
    else:
        candidate, candidate_name = oracle, "starter.agent:Agent"
    cases = load_jsonl(args.fixture)
    excluded_targets = load_excluded_targets(args.public_dataset)
    fixture_summary = validate_fixture(cases, oracle, excluded_targets)
    results = [evaluate_case(candidate, oracle, case) for case in cases]
    report = {
        "benchmark_note": (
            "Independent model-generated human-style diagnostic fixture; not an "
            "organizer score or evidence of private-test wording."
        ),
        "candidate": candidate_name,
        "fixture": fixture_summary,
        "overall": aggregate(results),
        "by_kind": grouped_summary(results, "kind"),
        "by_scenario": grouped_summary(results, "scenario"),
        "failed_cases": [result for result in results if not result["benchmark_pass"]],
        "cases": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    console_report = {
        key: value
        for key, value in report.items()
        if key not in {"cases", "failed_cases"}
    }
    console_report["failure_count"] = len(report["failed_cases"])
    console_report["failure_id_preview"] = [
        result["id"] for result in report["failed_cases"][:20]
    ]
    print(json.dumps(console_report, indent=2))


if __name__ == "__main__":
    main()
