#!/usr/bin/env python3
"""Offline rank-aware adaptive-K experiment for Khoa's shopping agent.

This module calls the existing reranker, captures its full (pre-truncation)
ordering, and then replays K in {1, 3, 5, 10} against the official deterministic
simulator without target-dependent inference.

Its saved JSON artifact is directly loadable through ``Agent(...,
adaptive_k_model_path=...)``.  Ground-truth target identifiers are used only
for offline labels, oracle planning, and evaluation.

One correction to the proposed equation is important.  If ``V_next`` is a
positive expected continuation *value*, Bellman's equation is

    Q(K) = immediate_hit_value + P(R > K) * V_next(state, K)

rather than subtracting the second term.  Subtracting a non-negative future
value makes Q monotonically favour larger K and cannot express the intended
"defer a weak hit to obtain a better rank" trade-off.  The output logs both
versions for auditability; ``--q-mode requested-minus`` can reproduce the
literal proposed equation, while the default selects with the Bellman form.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_ROOT = Path(__file__).resolve().parent
for import_path in (str(PROJECT_ROOT), str(CANDIDATE_ROOT)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - exercised only outside project venv
    raise SystemExit(
        "NumPy is required. Run this script with .venv/bin/python."
    ) from exc

from evaluator.local_evaluator import (  # noqa: E402
    MAX_TURNS,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
)
from src.adaptive_k import (  # noqa: E402
    ALLOWED_K,
    FEATURE_NAMES,
    AdaptiveKModel,
    RankedCandidate,
    RankingContext,
    apply_override_k10_guard,
    compute_q_values,
    extract_rank_features,
    technical_utility,
)
from src.agent import Agent, SessionState, _terms  # noqa: E402


K_VALUES = ALLOWED_K
FRONTIER_SIZE = MAX_TURNS * max(K_VALUES) + 75
CACHE_VERSION = 2
DEFAULT_OVERRIDE_GUARD_THRESHOLDS: tuple[float | None, ...] = (
    None,
    0.0,
    0.0025,
    0.005,
    0.01,
    0.02,
    0.03,
    0.05,
)

_WORKER_HARNESS: RankingHarness | None = None  # assigned after class definition in workers
_WORKER_CATEGORIES: dict[str, list[str]] | None = None
_WORKER_PRODUCTS: dict[str, dict] | None = None
_WORKER_POLICY: ArtifactAdaptivePolicy | None = None  # assigned after class definition
_WORKER_SWEEP_POLICIES: tuple[tuple[float | None, ArtifactAdaptivePolicy], ...] = ()
_WORKER_RUN_ORACLE = True


@dataclass
class TurnTemplate:
    turn: int
    intent: str
    mode: str
    clear_recommended: bool
    hit_eligible: bool
    context: RankingContext
    order: tuple[RankedCandidate, ...]
    order_ids: tuple[str, ...]
    position: dict[str, int]
    order_digest: str


@dataclass(frozen=True)
class SessionOutcome:
    sample_id: str
    scenario_type: str
    hit: bool
    first_hit_turn: int | None
    best_rank: int | None
    selected_ks: tuple[int, ...]

    @property
    def reciprocal_rank(self) -> float:
        return 0.0 if self.best_rank is None else 1.0 / self.best_rank

    @property
    def utility(self) -> float:
        if not self.hit or self.first_hit_turn is None or self.best_rank is None:
            return 0.0
        return hit_utility(self.first_hit_turn, self.best_rank)


@dataclass(frozen=True)
class OracleResult:
    value: float
    first_hit_turn: int | None
    best_rank: int | None
    actions: tuple[int, ...]
    states_visited: int


def hit_utility(turn: int, rank: int) -> float:
    """Per-session contribution to the official aggregate TechnicalScore."""
    return technical_utility(turn, rank)


class RankingHarness:
    """Expose the current Agent's full ordering without altering its scorer."""

    def __init__(self, catalog_path: str | Path) -> None:
        self.agent = Agent(catalog_path)

    def reset(self, session_id: str, profile: dict) -> None:
        self.agent.reset(session_id, profile)

    def observe(self, session_id: str, message: str, turn: int, hit_eligible: bool) -> TurnTemplate:
        state = self.agent._sessions[session_id]
        label = self.agent._classify_turn(state, message, turn)
        self.agent._update_state(state, label, message, turn)
        recommended_before_rank = set(state.recommended)
        self.agent.last_ranking_components = []
        self.agent._rank(state, max(K_VALUES), turn)
        state.recommended = recommended_before_rank

        weights = self.agent.rerank_weights
        ranked: list[RankedCandidate] = []
        for parent_asin, _, rating, components in self.agent.last_ranking_components:
            score = (
                weights["hard"] * components["hard"]
                + weights["semantic"] * components["semantic"]
                + weights["lexical"] * components["lexical"]
                + weights["soft"] * components["soft"]
                + weights["recent"] * components["current"]
                - weights["exclusion"] * components["exclusion"]
            )
            ranked.append(RankedCandidate(parent_asin, score, rating, dict(components)))
        # last_ranking_components is already in the reranker's exact order.
        order_ids = tuple(item.parent_asin for item in ranked)
        digest = hashlib.sha256("\0".join(order_ids).encode()).hexdigest()
        constraint_counts = Counter(constraint.kind for constraint in state.constraints)
        query_terms = _terms(" ".join(state.query_parts)) or state.profile_terms
        context = RankingContext(
            turn=turn,
            intent=state.intent,
            mode=state.mode,
            active_constraint_count=sum(
                constraint.kind != "exclusion" for constraint in state.constraints
            ),
            hard_constraint_count=constraint_counts["hard"],
            soft_constraint_count=constraint_counts["soft"],
            category_constraint_count=constraint_counts["category"],
            exclusion_constraint_count=constraint_counts["exclusion"],
            unique_attribute_count=len({item.attribute for item in state.constraints}),
            unavailable_attribute_count=len(state.unavailable_attributes),
            evidence_turns=state.evidence_turns,
            query_term_count=len(query_terms),
            unique_query_term_count=len(set(query_terms)),
            profile_term_count=len(state.profile_terms),
            recommended_count=0,
            override_seen="O1_OVERRIDE" in state.intent_history,
            candidate_count=len(ranked),
        )
        replay_features = extract_rank_features(ranked[:75], context)
        runtime_features = self.agent.last_rank_state.get("features", {})
        for name in FEATURE_NAMES:
            if not math.isclose(
                float(replay_features[name]),
                float(runtime_features.get(name, math.nan)),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise RuntimeError(f"template/runtime feature mismatch for {name}")
        return TurnTemplate(
            turn=turn,
            intent=state.intent,
            mode=state.mode,
            clear_recommended=label == "O1_OVERRIDE",
            hit_eligible=hit_eligible,
            context=context,
            order=tuple(ranked[:FRONTIER_SIZE]),
            order_ids=order_ids,
            position={parent_asin: index + 1 for index, parent_asin in enumerate(order_ids)},
            order_digest=digest,
        )


def build_templates(
    harness: RankingHarness,
    sample: dict,
    categories: dict[str, list[str]],
    products: dict[str, dict],
) -> tuple[list[TurnTemplate], str]:
    """Build all ten evidence/ranking states; K never influences user replies."""
    session_id = f"adaptive_k_{sample['sample_id']}"
    harness.reset(session_id, sample["user_profile"])
    target = str(sample["ground_truth"]["parent_asin"])
    intent_card, behavior = materialize_hidden_fields(sample, products)
    effective_sample = {**sample, "intent_card": intent_card, "behavior": behavior}
    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    message = initial_message(
        effective_sample,
        coarse_category(categories.get(target, [])),
        disclosed,
    )
    templates: list[TurnTemplate] = []
    for turn in range(1, MAX_TURNS + 1):
        template = harness.observe(session_id, message, turn, override_applied)
        templates.append(template)
        if turn == MAX_TURNS:
            break
        override = effective_sample.get("behavior", {}).get("override") or {}
        if not override_applied and turn + 1 == int(override.get("turn", 3)):
            override_applied = True
            new_value = str(override.get("new_value", ""))
            if new_value:
                disclosed.add(new_value)
            message = str(override.get("message", "Actually, please ignore my earlier preference."))
        else:
            message, boundary_used = customer_reply(
                effective_sample,
                "other",
                disclosed,
                boundary_used,
            )
    return templates, target


def _fresh_items(
    template: TurnTemplate,
    recommended: frozenset[str],
    limit: int = FRONTIER_SIZE,
) -> list[RankedCandidate]:
    result: list[RankedCandidate] = []
    for item in template.order:
        if item.parent_asin not in recommended:
            result.append(item)
            if len(result) >= limit:
                break
    return result


def _fresh_ids(order: Sequence[str], recommended: frozenset[str], limit: int = 10) -> list[str]:
    result: list[str] = []
    for parent_asin in order:
        if parent_asin not in recommended:
            result.append(parent_asin)
            if len(result) >= limit:
                break
    return result


def target_rank(template: TurnTemplate, target: str, recommended: frozenset[str]) -> int | None:
    if target in recommended:
        return None
    base_rank = template.position.get(target)
    if base_rank is None:
        return None
    removed_above = sum(
        1
        for parent_asin in recommended
        if (position := template.position.get(parent_asin)) is not None and position < base_rank
    )
    return base_rank - removed_above


def ranking_features(template: TurnTemplate, recommended: frozenset[str]) -> dict[str, float]:
    fresh_items = _fresh_items(template, recommended, FRONTIER_SIZE)
    retrieved_count = len(template.position) - sum(
        parent_asin in template.position for parent_asin in recommended
    )
    context = replace(
        template.context,
        recommended_count=len(recommended),
        candidate_count=max(0, retrieved_count),
    )
    features = extract_rank_features(fresh_items, context)
    return {name: float(features[name]) for name in FEATURE_NAMES}


def state_signature(recommended: frozenset[str]) -> str:
    return hashlib.sha256("\0".join(sorted(recommended)).encode()).hexdigest()[:16]


PolicyDecision = tuple[int, dict[str, Any] | None]


def simulate_policy(
    sample: dict,
    templates: Sequence[TurnTemplate],
    target: str,
    decide: Any,
    *,
    collect_rows: bool = False,
) -> tuple[SessionOutcome, list[dict[str, Any]], list[dict[str, Any]]]:
    recommended = frozenset()
    selected_ks: list[int] = []
    rows: list[dict[str, Any]] = []
    policy_logs: list[dict[str, Any]] = []
    hit_turn: int | None = None
    hit_rank: int | None = None
    for template in templates:
        if template.clear_recommended:
            recommended = frozenset()
        features = ranking_features(template, recommended)
        rank = target_rank(template, target, recommended)
        k, debug = decide(features, template.turn)
        if k not in K_VALUES:
            raise ValueError(f"policy selected unsupported K={k}")
        fresh = _fresh_ids(template.order_ids, recommended, max(K_VALUES))
        shown = fresh[:k]
        action_hit = template.hit_eligible and target in shown
        row = {
            "sample_id": str(sample["sample_id"]),
            "scenario_type": str(sample["scenario_type"]),
            "turn": template.turn,
            "intent": template.intent,
            "recommended_signature": state_signature(recommended),
            "features": features,
            "target_rank": rank,
            "target_rank_class": 10 if rank is None or rank > 10 else rank - 1,
            "selected_k": k,
            "hit_eligible": template.hit_eligible,
            "action_hit": action_hit,
        }
        if collect_rows:
            rows.append(row)
        if debug is not None:
            policy_logs.append({
                "sample_id": str(sample["sample_id"]),
                "scenario_type": str(sample["scenario_type"]),
                "turn": template.turn,
                "true_target_rank": rank,
                **debug,
            })
        selected_ks.append(k)
        recommended = frozenset((*recommended, *shown))
        if action_hit:
            hit_turn = template.turn
            hit_rank = shown.index(target) + 1
            break
    outcome = SessionOutcome(
        sample_id=str(sample["sample_id"]),
        scenario_type=str(sample["scenario_type"]),
        hit=hit_turn is not None,
        first_hit_turn=hit_turn,
        best_rank=hit_rank,
        selected_ks=tuple(selected_ks),
    )
    for row in rows:
        row["continuation_target"] = outcome.utility if not row["action_hit"] else None
    return outcome, rows, policy_logs


def fixed_decider(k: int) -> Any:
    return lambda _features, _turn: (k, None)


def _better_oracle(left: tuple[float, int | None, int | None, tuple[int, ...]], right: tuple[float, int | None, int | None, tuple[int, ...]]) -> tuple[float, int | None, int | None, tuple[int, ...]]:
    """Deterministic oracle tie break: value, earlier hit, better rank, larger K."""
    def key(item: tuple[float, int | None, int | None, tuple[int, ...]]) -> tuple[float, int, int, tuple[int, ...]]:
        value, turn, rank, actions = item
        return (
            round(value, 14),
            -(turn if turn is not None else MAX_TURNS + 1),
            -(rank if rank is not None else max(K_VALUES) + 1),
            actions,
        )
    return left if key(left) >= key(right) else right


def oracle_policy(
    templates: Sequence[TurnTemplate],
    target: str,
) -> OracleResult:
    """Exact target-aware dynamic program; never callable by the live agent."""
    memo: dict[tuple[int, frozenset[str]], tuple[float, int | None, int | None, tuple[int, ...]]] = {}
    state_counter = 0

    def stable_tail(index: int, recommended: frozenset[str]) -> tuple[float, int | None, int | None, tuple[int, ...]] | None:
        template = templates[index]
        if not template.hit_eligible:
            return None
        digest = template.order_digest
        if any(
            future.clear_recommended
            or not future.hit_eligible
            or future.order_digest != digest
            for future in templates[index + 1 :]
        ):
            return None
        fresh_order = tuple(
            parent_asin for parent_asin in template.order_ids if parent_asin not in recommended
        )
        try:
            target_index = fresh_order.index(target)
        except ValueError:
            return (0.0, None, None, tuple(max(K_VALUES) for _ in templates[index:]))
        tail_memo: dict[tuple[int, int], tuple[float, int | None, int | None, tuple[int, ...]]] = {}

        def solve_tail(turn_index: int, offset: int) -> tuple[float, int | None, int | None, tuple[int, ...]]:
            key = (turn_index, offset)
            if key in tail_memo:
                return tail_memo[key]
            relative_rank = target_index - offset + 1
            best = (-1.0, None, None, tuple())
            for k in K_VALUES:
                if 1 <= relative_rank <= k:
                    candidate = (
                        hit_utility(templates[turn_index].turn, relative_rank),
                        templates[turn_index].turn,
                        relative_rank,
                        (k,),
                    )
                elif turn_index + 1 >= len(templates):
                    candidate = (0.0, None, None, (k,))
                else:
                    suffix = solve_tail(turn_index + 1, min(len(fresh_order), offset + k))
                    candidate = (suffix[0], suffix[1], suffix[2], (k, *suffix[3]))
                best = _better_oracle(best, candidate)
            tail_memo[key] = best
            return best

        return solve_tail(index, 0)

    def solve(index: int, recommended: frozenset[str]) -> tuple[float, int | None, int | None, tuple[int, ...]]:
        nonlocal state_counter
        template = templates[index]
        if template.clear_recommended:
            recommended = frozenset()
        key = (index, recommended)
        if key in memo:
            return memo[key]
        state_counter += 1
        stable = stable_tail(index, recommended)
        if stable is not None:
            memo[key] = stable
            return stable
        fresh = _fresh_ids(template.order_ids, recommended, max(K_VALUES))
        rank = target_rank(template, target, recommended)
        best = (-1.0, None, None, tuple())
        for k in K_VALUES:
            shown = fresh[:k]
            if template.hit_eligible and rank is not None and rank <= k:
                candidate = (hit_utility(template.turn, rank), template.turn, rank, (k,))
            elif index + 1 >= len(templates):
                candidate = (0.0, None, None, (k,))
            else:
                next_recommended = frozenset((*recommended, *shown))
                suffix = solve(index + 1, next_recommended)
                candidate = (suffix[0], suffix[1], suffix[2], (k, *suffix[3]))
            best = _better_oracle(best, candidate)
        memo[key] = best
        return best

    value, hit_turn, rank, actions = solve(0, frozenset())
    return OracleResult(value, hit_turn, rank, actions, state_counter)


class CalibratedCDFTrainer:
    """Four NumPy sigmoid heads for P(R<=1/3/5/10), plus isotonic calibration."""

    def __init__(self) -> None:
        self.mean = np.empty(0, dtype=np.float64)
        self.scale = np.empty(0, dtype=np.float64)
        self.weights = np.empty((0, len(K_VALUES)), dtype=np.float64)
        self.calibrators: dict[int, dict[str, list[float]]] = {}

    @staticmethod
    def matrix(rows: Sequence[dict[str, Any]]) -> np.ndarray:
        return np.asarray(
            [[float(row["features"][name]) for name in FEATURE_NAMES] for row in rows],
            dtype=np.float64,
        )

    def design(self, matrix: np.ndarray) -> np.ndarray:
        return np.column_stack((np.ones(len(matrix)), (matrix - self.mean) / self.scale))

    def fit(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        epochs: int,
        batch_size: int,
        learning_rate: float,
        l2: float,
        seed: int,
    ) -> None:
        if not rows:
            raise ValueError("rank-model training rows are empty")
        matrix = self.matrix(rows)
        exact_classes = np.asarray([int(row["target_rank_class"]) for row in rows])
        labels = np.column_stack([exact_classes < k for k in K_VALUES]).astype(np.float64)
        self.mean = matrix.mean(axis=0)
        self.scale = matrix.std(axis=0)
        self.scale[self.scale < 1e-8] = 1.0
        design = self.design(matrix)
        self.weights = np.zeros((design.shape[1], len(K_VALUES)), dtype=np.float64)
        first = np.zeros_like(self.weights)
        second = np.zeros_like(self.weights)
        rng = np.random.default_rng(seed)
        step = 0
        for _ in range(epochs):
            permutation = rng.permutation(len(design))
            for start in range(0, len(design), batch_size):
                indexes = permutation[start : start + batch_size]
                batch = design[indexes]
                batch_labels = labels[indexes]
                logits = np.clip(batch @ self.weights, -60.0, 60.0)
                probabilities = 1.0 / (1.0 + np.exp(-logits))
                gradient = batch.T @ (probabilities - batch_labels) / len(batch)
                gradient[1:] += l2 * self.weights[1:]
                step += 1
                first = 0.9 * first + 0.1 * gradient
                second = 0.999 * second + 0.001 * gradient * gradient
                first_hat = first / (1.0 - 0.9**step)
                second_hat = second / (1.0 - 0.999**step)
                self.weights -= learning_rate * first_hat / (np.sqrt(second_hat) + 1e-8)

    def raw_probabilities(self, rows: Sequence[dict[str, Any]]) -> np.ndarray:
        logits = np.clip(self.design(self.matrix(rows)) @ self.weights, -60.0, 60.0)
        return 1.0 / (1.0 + np.exp(-logits))

    @staticmethod
    def _isotonic_knots(predictions: np.ndarray, labels: np.ndarray) -> dict[str, list[float]]:
        order = np.argsort(predictions)
        predictions = predictions[order]
        labels = labels[order]
        bins = [indexes for indexes in np.array_split(np.arange(len(labels)), min(20, len(labels))) if len(indexes)]
        x_values: list[float] = []
        y_values: list[float] = []
        weights: list[int] = []
        for indexes in bins:
            x_value = float(predictions[indexes].mean())
            y_value = float(labels[indexes].mean())
            if x_values and x_value <= x_values[-1] + 1e-12:
                total = weights[-1] + len(indexes)
                y_values[-1] = (y_values[-1] * weights[-1] + y_value * len(indexes)) / total
                weights[-1] = total
            else:
                x_values.append(x_value)
                y_values.append(y_value)
                weights.append(len(indexes))
        # Weighted pool-adjacent-violators, retaining strictly increasing x.
        blocks: list[list[float]] = []
        for index, (y_value, weight) in enumerate(zip(y_values, weights)):
            blocks.append([y_value, float(weight), float(index), float(index)])
            while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
                right = blocks.pop()
                left = blocks.pop()
                total = left[1] + right[1]
                blocks.append([
                    (left[0] * left[1] + right[0] * right[1]) / total,
                    total,
                    left[2],
                    right[3],
                ])
        calibrated = [0.0] * len(x_values)
        for mean, _, first_index, last_index in blocks:
            for index in range(int(first_index), int(last_index) + 1):
                calibrated[index] = max(0.0, min(1.0, mean))
        if len(x_values) < 2:
            rate = float(labels.mean())
            return {"x": [0.0, 1.0], "y": [rate, rate]}
        return {"x": x_values, "y": calibrated}

    def calibrate(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        raw = self.raw_probabilities(rows)
        classes = np.asarray([int(row["target_rank_class"]) for row in rows])
        self.calibrators = {
            k: self._isotonic_knots(raw[:, index], (classes < k).astype(np.float64))
            for index, k in enumerate(K_VALUES)
        }

    def rank_heads_payload(self) -> dict[str, Any]:
        return {
            str(k): {
                "bias": float(self.weights[0, index]),
                "weights": self.weights[1:, index].tolist(),
                "link": "sigmoid",
                "calibration": self.calibrators[k],
            }
            for index, k in enumerate(K_VALUES)
        }


class SharedContinuationTrainer:
    """One target-free V_next head shared by every K, as requested."""

    def __init__(self) -> None:
        self.bias = 0.0
        self.weights = np.empty(0, dtype=np.float64)

    def fit(
        self,
        rows: Sequence[dict[str, Any]],
        rank_trainer: CalibratedCDFTrainer,
        *,
        l2: float,
    ) -> None:
        usable = [row for row in rows if row.get("continuation_target") is not None]
        if not usable:
            raise ValueError("continuation-model training rows are empty")
        design = rank_trainer.design(rank_trainer.matrix(usable))
        targets = np.asarray([float(row["continuation_target"]) for row in usable])
        penalty = np.eye(design.shape[1], dtype=np.float64) * l2
        penalty[0, 0] = 0.0
        weights = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
        self.bias = float(weights[0])
        self.weights = weights[1:]

    def payload(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "weights": self.weights.tolist(),
            "link": "identity",
        }


class ArtifactAdaptivePolicy:
    """Offline adapter with exactly the runtime AdaptiveKModel semantics."""

    def __init__(
        self,
        model: AdaptiveKModel,
        *,
        q_mode: Literal["bellman", "requested-minus"] = "bellman",
        override_k10_q_margin_threshold: float | None = None,
    ) -> None:
        self.model = model
        self.q_mode = q_mode
        if override_k10_q_margin_threshold is not None:
            threshold = float(override_k10_q_margin_threshold)
            if not math.isfinite(threshold) or threshold < 0.0:
                raise ValueError(
                    "override K=10 Q-margin threshold must be finite and non-negative"
                )
            override_k10_q_margin_threshold = threshold
        self.override_k10_q_margin_threshold = override_k10_q_margin_threshold

    def decide(self, features: dict[str, float], turn: int) -> PolicyDecision:
        prediction = self.model.predict(features, turn)
        q_spec, q_bellman = compute_q_values(
            prediction.rank_masses,
            turn,
            prediction.continuation_values,
            K_VALUES,
        )
        objective = q_bellman if self.q_mode == "bellman" else q_spec
        base_selected_k = max(
            K_VALUES,
            key=(
                (lambda k: (objective[k], -k))
                if self.q_mode == "bellman"
                else (lambda k: (objective[k], k))
            ),
        )
        is_override_turn = float(features.get("intent_O1_OVERRIDE", 0.0)) >= 0.5
        selected_k, override_guard_applied, override_q_margin_to_k10 = (
            apply_override_k10_guard(
                base_selected_k,
                objective,
                is_override_turn=is_override_turn,
                q_margin_threshold=self.override_k10_q_margin_threshold,
            )
        )
        selection_reason = "q_bellman" if self.q_mode == "bellman" else "q_spec"
        if override_guard_applied:
            selection_reason = "override_uncertainty_fallback"
        return selected_k, {
            "rank_cdf": {str(k): float(prediction.cdf[k]) for k in K_VALUES},
            "rank_probabilities": {
                str(rank): float(prediction.rank_masses[rank]) for rank in range(1, 11)
            },
            "p_rank_gt_10": float(prediction.miss_probability),
            "v_next": {str(k): float(prediction.continuation_values[k]) for k in K_VALUES},
            "q_spec": {str(k): float(q_spec[k]) for k in K_VALUES},
            "q_bellman": {str(k): float(q_bellman[k]) for k in K_VALUES},
            "objective": "bellman" if self.q_mode == "bellman" else "spec",
            "is_override_turn": is_override_turn,
            "base_selected_k": base_selected_k,
            "override_q_margin_threshold": self.override_k10_q_margin_threshold,
            "override_q_margin_to_k10": override_q_margin_to_k10,
            "override_guard_applied": override_guard_applied,
            "selection_reason": selection_reason,
            "selected_k": selected_k,
        }


def empirical_rank_priors(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    counts = Counter(
        int(row["target_rank"])
        for row in rows
        if row.get("target_rank") is not None and 1 <= int(row["target_rank"]) <= 10
    )
    # Add-one smoothing keeps every within-bin rank representable.
    return {str(rank): float(counts[rank] + 1) for rank in range(1, 11)}


def save_model(
    path: Path,
    rank_trainer: CalibratedCDFTrainer,
    continuation_trainer: SharedContinuationTrainer,
    rank_priors: dict[str, float],
    metadata: dict[str, Any],
) -> AdaptiveKModel:
    payload = {
        "schema_version": 1,
        "feature_names": list(FEATURE_NAMES),
        "normalization": {
            "mean": rank_trainer.mean.tolist(),
            "scale": rank_trainer.scale.tolist(),
        },
        "rank_heads": rank_trainer.rank_heads_payload(),
        "continuation_heads": {"default": continuation_trainer.payload()},
        "rank_priors": rank_priors,
        "metadata": metadata,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return AdaptiveKModel.from_json(path)


def unique_rank_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["sample_id"]), int(row["turn"]), str(row["recommended_signature"]))
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def metric_summary(outcomes: Sequence[SessionOutcome]) -> dict[str, Any]:
    if not outcomes:
        return {
            "sample_count": 0,
            "hit_rate_at_10": 0.0,
            "mrr": 0.0,
            "mttc": None,
            "efficiency": 0.0,
            "technical_score": 0.0,
        }
    count = len(outcomes)
    hit_rate = sum(outcome.hit for outcome in outcomes) / count
    mrr = sum(outcome.reciprocal_rank for outcome in outcomes) / count
    mttc = sum(
        outcome.first_hit_turn if outcome.first_hit_turn is not None else MAX_TURNS + 1
        for outcome in outcomes
    ) / count
    efficiency = max(0.0, min(1.0, (11.0 - mttc) / 10.0))
    technical = 0.5 * hit_rate + 0.3 * mrr + 0.2 * efficiency
    return {
        "sample_count": count,
        "hit_rate_at_10": round(hit_rate, 6),
        "mrr": round(mrr, 6),
        "mttc": round(mttc, 6),
        "efficiency": round(efficiency, 6),
        "technical_score": round(technical, 6),
    }


def scenario_summary(outcomes: Sequence[SessionOutcome]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[SessionOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.scenario_type].append(outcome)
    return {scenario: metric_summary(grouped[scenario]) for scenario in sorted(grouped)}


def oracle_as_outcome(sample: dict, result: OracleResult) -> SessionOutcome:
    return SessionOutcome(
        sample_id=str(sample["sample_id"]),
        scenario_type=str(sample["scenario_type"]),
        hit=result.first_hit_turn is not None,
        first_hit_turn=result.first_hit_turn,
        best_rank=result.best_rank,
        selected_ks=result.actions,
    )


def stratified_split(
    samples: Sequence[dict],
    *,
    seed: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["scenario_type"])].append(sample)
    rng = random.Random(seed)
    scenarios = sorted(grouped)
    for group in grouped.values():
        rng.shuffle(group)

    def quotas(fraction: float, desired_total: int, capacities: dict[str, int]) -> dict[str, int]:
        exact = {name: len(grouped[name]) * fraction for name in scenarios}
        result = {name: min(capacities[name], int(exact[name])) for name in scenarios}
        remaining = desired_total - sum(result.values())
        order = sorted(
            scenarios,
            key=lambda name: (exact[name] - math.floor(exact[name]), capacities[name], name),
            reverse=True,
        )
        while remaining > 0:
            progressed = False
            for name in order:
                if result[name] < capacities[name] and remaining > 0:
                    result[name] += 1
                    remaining -= 1
                    progressed = True
            if not progressed:
                raise RuntimeError("could not allocate exact stratified split")
        return result

    total = len(samples)
    train_total = int(total * 0.70)
    calibration_total = int(total * 0.15)
    capacities = {name: len(grouped[name]) for name in scenarios}
    train_quota = quotas(0.70, train_total, capacities)
    remaining_capacity = {
        name: capacities[name] - train_quota[name] for name in scenarios
    }
    calibration_quota = quotas(0.15, calibration_total, remaining_capacity)
    train: list[dict] = []
    calibration: list[dict] = []
    heldout: list[dict] = []
    for scenario in scenarios:
        group = grouped[scenario]
        train_end = train_quota[scenario]
        calibration_end = train_end + calibration_quota[scenario]
        train.extend(group[:train_end])
        calibration.extend(group[train_end:calibration_end])
        heldout.extend(group[calibration_end:])
    rng.shuffle(train)
    rng.shuffle(calibration)
    rng.shuffle(heldout)
    return train, calibration, heldout


def file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _open_text(path: Path, mode: str) -> Any:
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def save_cache(path: Path, metadata: dict[str, Any], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _open_text(path, "w") as handle:
        handle.write(json.dumps({"type": "metadata", **metadata}, sort_keys=True) + "\n")
        for row in rows:
            handle.write(json.dumps({"type": "row", **row}, sort_keys=True) + "\n")


def load_cache(path: Path, expected: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _open_text(path, "r") as handle:
        first = json.loads(next(handle))
        metadata = {key: value for key, value in first.items() if key != "type"}
        if metadata != expected:
            raise ValueError("trajectory cache metadata does not match this run")
        for line in handle:
            value = json.loads(line)
            value.pop("type", None)
            rows.append(value)
    return rows


def collect_split_rows(
    harness: RankingHarness,
    samples: Sequence[dict],
    categories: dict[str, list[str]],
    products: dict[str, dict],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, 1):
        templates, target = build_templates(harness, sample, categories, products)
        for k in K_VALUES:
            _, trajectory, _ = simulate_policy(
                sample,
                templates,
                target,
                fixed_decider(k),
                collect_rows=True,
            )
            rows.extend(trajectory)
        if index % 25 == 0 or index == len(samples):
            print(f"collected trajectories: {index}/{len(samples)}", flush=True)
    return rows


def _initialize_worker(
    catalog_path: str,
    model_path: str | None = None,
    q_mode: str = "bellman",
    run_oracle: bool = True,
) -> None:
    """Give each process its own immutable catalog index and ranking harness."""
    global _WORKER_HARNESS, _WORKER_CATEGORIES, _WORKER_PRODUCTS
    global _WORKER_POLICY, _WORKER_RUN_ORACLE
    _, _WORKER_CATEGORIES, _WORKER_PRODUCTS = catalog_index(catalog_path)
    _WORKER_HARNESS = RankingHarness(catalog_path)
    _WORKER_POLICY = (
        ArtifactAdaptivePolicy(
            AdaptiveKModel.from_json(model_path),
            q_mode=q_mode,  # type: ignore[arg-type]
        )
        if model_path is not None
        else None
    )
    _WORKER_RUN_ORACLE = run_oracle


def override_guard_threshold_label(threshold: float | None) -> str:
    """Stable JSON/result key for one override-guard configuration."""
    return "none" if threshold is None else format(threshold, ".12g")


def parse_override_guard_thresholds(value: str) -> tuple[float | None, ...]:
    """Parse ``none,0,.005`` while preserving order and rejecting bad values."""
    thresholds: list[float | None] = []
    seen: set[float | None] = set()
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if not item:
            continue
        threshold: float | None
        if item in {"none", "off", "disabled"}:
            threshold = None
        else:
            try:
                threshold = float(item)
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    f"invalid override-guard threshold: {raw_item!r}"
                ) from exc
            if not math.isfinite(threshold) or threshold < 0.0:
                raise argparse.ArgumentTypeError(
                    "override-guard thresholds must be finite and non-negative"
                )
        if threshold not in seen:
            seen.add(threshold)
            thresholds.append(threshold)
    if not thresholds:
        raise argparse.ArgumentTypeError("provide at least one override-guard threshold")
    return tuple(thresholds)


def _initialize_override_guard_sweep_worker(
    catalog_path: str,
    model_path: str,
    q_mode: str,
    thresholds: tuple[float | None, ...],
) -> None:
    """Load the catalog/model once, then reuse one policy per threshold."""
    global _WORKER_SWEEP_POLICIES
    _initialize_worker(catalog_path, model_path, q_mode, False)
    if _WORKER_POLICY is None:
        raise RuntimeError("override-guard sweep model failed to initialize")
    model = _WORKER_POLICY.model
    _WORKER_SWEEP_POLICIES = tuple(
        (
            threshold,
            ArtifactAdaptivePolicy(
                model,
                q_mode=q_mode,  # type: ignore[arg-type]
                override_k10_q_margin_threshold=threshold,
            ),
        )
        for threshold in thresholds
    )


def _sweep_one_sample(
    sample: dict,
    templates: Sequence[TurnTemplate],
    target: str,
    policies: Sequence[tuple[float | None, ArtifactAdaptivePolicy]],
) -> dict[str, dict[str, Any]]:
    """Replay every guard threshold over a single, shared template trajectory."""
    result: dict[str, dict[str, Any]] = {}
    for threshold, policy in policies:
        outcome, _, logs = simulate_policy(sample, templates, target, policy.decide)
        override_turn_logs = [log for log in logs if bool(log.get("is_override_turn"))]
        eligible = [
            log for log in override_turn_logs if int(log.get("base_selected_k", 10)) < 10
        ]
        fallback = [log for log in eligible if bool(log.get("override_guard_applied"))]
        margins = [
            float(log["override_q_margin_to_k10"])
            for log in eligible
            if log.get("override_q_margin_to_k10") is not None
        ]
        result[override_guard_threshold_label(threshold)] = {
            "outcome": outcome,
            "override_turn_decisions": len(override_turn_logs),
            "eligible_decisions": len(eligible),
            "fallback_turns": len(fallback),
            "fallback_session": bool(fallback),
            "eligible_margin_sum": sum(margins),
            "eligible_margin_min": min(margins) if margins else None,
            "eligible_margin_max": max(margins) if margins else None,
        }
    return result


def _override_guard_sweep_worker(sample: dict) -> dict[str, dict[str, Any]]:
    if (
        _WORKER_HARNESS is None
        or _WORKER_CATEGORIES is None
        or _WORKER_PRODUCTS is None
        or not _WORKER_SWEEP_POLICIES
    ):
        raise RuntimeError("override-guard sweep worker was not initialized")
    templates, target = build_templates(
        _WORKER_HARNESS,
        sample,
        _WORKER_CATEGORIES,
        _WORKER_PRODUCTS,
    )
    return _sweep_one_sample(sample, templates, target, _WORKER_SWEEP_POLICIES)


def _collect_worker(sample: dict) -> list[dict[str, Any]]:
    if _WORKER_HARNESS is None or _WORKER_CATEGORIES is None or _WORKER_PRODUCTS is None:
        raise RuntimeError("collection worker was not initialized")
    templates, target = build_templates(
        _WORKER_HARNESS,
        sample,
        _WORKER_CATEGORIES,
        _WORKER_PRODUCTS,
    )
    rows: list[dict[str, Any]] = []
    for k in K_VALUES:
        _, trajectory, _ = simulate_policy(
            sample,
            templates,
            target,
            fixed_decider(k),
            collect_rows=True,
        )
        rows.extend(trajectory)
    return rows


def collect_split_rows_parallel(
    catalog_path: Path,
    samples: Sequence[dict],
    workers: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_worker,
        initargs=(str(catalog_path),),
    ) as executor:
        for index, trajectory in enumerate(executor.map(_collect_worker, samples), 1):
            rows.extend(trajectory)
            if index % 25 == 0 or index == len(samples):
                print(f"collected trajectories: {index}/{len(samples)}", flush=True)
    return rows


def calibration_report(model: AdaptiveKModel, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    unique = unique_rank_rows(rows)
    if not unique:
        return {"rows": 0}
    labels = np.asarray([int(row["target_rank_class"]) for row in unique], dtype=np.int64)
    predicted_by_k = {
        k: np.asarray([
            model.predict(row["features"], int(row["turn"])).cdf[k]
            for row in unique
        ])
        for k in K_VALUES
    }
    report: dict[str, Any] = {"rows": len(unique)}
    binary_losses: list[float] = []
    for k in K_VALUES:
        observed = (labels < k).astype(np.float64)
        predicted = predicted_by_k[k]
        report[f"p_rank_le_{k}_brier"] = round(float(np.mean((predicted - observed) ** 2)), 6)
        report[f"p_rank_le_{k}_predicted_mean"] = round(float(predicted.mean()), 6)
        report[f"p_rank_le_{k}_observed_mean"] = round(float(observed.mean()), 6)
        binary_losses.append(float(np.mean(-observed * np.log(np.maximum(predicted, 1e-15)) - (1.0 - observed) * np.log(np.maximum(1.0 - predicted, 1e-15)))))
    report["mean_binary_log_loss"] = round(float(np.mean(binary_losses)), 6)
    return report


def evaluate_heldout(
    harness: RankingHarness,
    samples: Sequence[dict],
    categories: dict[str, list[str]],
    products: dict[str, dict],
    policy: ArtifactAdaptivePolicy,
    *,
    run_oracle: bool,
    log_limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fixed: dict[int, list[SessionOutcome]] = {k: [] for k in K_VALUES}
    adaptive: list[SessionOutcome] = []
    oracle_outcomes: list[SessionOutcome] = []
    oracle_states = 0
    logs: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, 1):
        templates, target = build_templates(harness, sample, categories, products)
        for k in K_VALUES:
            outcome, _, _ = simulate_policy(sample, templates, target, fixed_decider(k))
            fixed[k].append(outcome)
        if run_oracle:
            oracle_result = oracle_policy(templates, target)
            oracle_states += oracle_result.states_visited
            oracle_outcomes.append(oracle_as_outcome(sample, oracle_result))
        learned, _, learned_logs = simulate_policy(sample, templates, target, policy.decide)
        adaptive.append(learned)
        if log_limit < 0 or len(logs) < log_limit:
            remaining = log_limit - len(logs) if log_limit >= 0 else len(learned_logs)
            logs.extend(learned_logs[:remaining])
        if index % 25 == 0 or index == len(samples):
            print(f"evaluated held-out sessions: {index}/{len(samples)}", flush=True)

    result: dict[str, Any] = {
        "fixed": {
            str(k): {
                "overall": metric_summary(fixed[k]),
                "by_scenario": scenario_summary(fixed[k]),
            }
            for k in K_VALUES
        },
    }
    if run_oracle:
        oracle_metrics = metric_summary(oracle_outcomes)
        fixed_10_metrics = metric_summary(fixed[10])
        result["oracle"] = {
            "overall": oracle_metrics,
            "by_scenario": scenario_summary(oracle_outcomes),
            "k_counts": dict(sorted(Counter(k for outcome in oracle_outcomes for k in outcome.selected_ks).items())),
            "average_general_dp_states": round(oracle_states / max(1, len(samples)), 3),
            "technical_upside_over_fixed_10": round(
                oracle_metrics["technical_score"] - fixed_10_metrics["technical_score"],
                6,
            ),
        }
    result["adaptive"] = {
        "overall": metric_summary(adaptive),
        "by_scenario": scenario_summary(adaptive),
        "k_counts": dict(sorted(Counter(k for outcome in adaptive for k in outcome.selected_ks).items())),
    }
    return result, logs


def _evaluation_worker(sample: dict) -> dict[str, Any]:
    if (
        _WORKER_HARNESS is None
        or _WORKER_CATEGORIES is None
        or _WORKER_PRODUCTS is None
        or _WORKER_POLICY is None
    ):
        raise RuntimeError("evaluation worker was not initialized")
    templates, target = build_templates(
        _WORKER_HARNESS,
        sample,
        _WORKER_CATEGORIES,
        _WORKER_PRODUCTS,
    )
    fixed: dict[int, SessionOutcome] = {}
    for k in K_VALUES:
        fixed[k], _, _ = simulate_policy(sample, templates, target, fixed_decider(k))
    oracle_result = oracle_policy(templates, target) if _WORKER_RUN_ORACLE else None
    learned, _, logs = simulate_policy(sample, templates, target, _WORKER_POLICY.decide)
    return {
        "fixed": fixed,
        "oracle": (
            oracle_as_outcome(sample, oracle_result) if oracle_result is not None else None
        ),
        "oracle_states": oracle_result.states_visited if oracle_result is not None else 0,
        "adaptive": learned,
        "logs": logs,
    }


def evaluate_heldout_parallel(
    catalog_path: Path,
    model_path: Path,
    samples: Sequence[dict],
    *,
    workers: int,
    q_mode: str,
    run_oracle: bool,
    log_limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fixed: dict[int, list[SessionOutcome]] = {k: [] for k in K_VALUES}
    adaptive: list[SessionOutcome] = []
    oracle_outcomes: list[SessionOutcome] = []
    oracle_states = 0
    logs: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_worker,
        initargs=(str(catalog_path), str(model_path), q_mode, run_oracle),
    ) as executor:
        for index, item in enumerate(executor.map(_evaluation_worker, samples), 1):
            for k in K_VALUES:
                fixed[k].append(item["fixed"][k])
            adaptive.append(item["adaptive"])
            if item["oracle"] is not None:
                oracle_outcomes.append(item["oracle"])
                oracle_states += int(item["oracle_states"])
            if log_limit < 0 or len(logs) < log_limit:
                remaining = log_limit - len(logs) if log_limit >= 0 else len(item["logs"])
                logs.extend(item["logs"][:remaining])
            if index % 25 == 0 or index == len(samples):
                print(f"evaluated held-out sessions: {index}/{len(samples)}", flush=True)

    result: dict[str, Any] = {
        "fixed": {
            str(k): {
                "overall": metric_summary(fixed[k]),
                "by_scenario": scenario_summary(fixed[k]),
            }
            for k in K_VALUES
        }
    }
    if run_oracle:
        oracle_metrics = metric_summary(oracle_outcomes)
        fixed_10_metrics = metric_summary(fixed[10])
        result["oracle"] = {
            "overall": oracle_metrics,
            "by_scenario": scenario_summary(oracle_outcomes),
            "k_counts": dict(sorted(Counter(k for outcome in oracle_outcomes for k in outcome.selected_ks).items())),
            "average_general_dp_states": round(oracle_states / max(1, len(samples)), 3),
            "technical_upside_over_fixed_10": round(
                oracle_metrics["technical_score"] - fixed_10_metrics["technical_score"],
                6,
            ),
        }
    result["adaptive"] = {
        "overall": metric_summary(adaptive),
        "by_scenario": scenario_summary(adaptive),
        "k_counts": dict(sorted(Counter(k for outcome in adaptive for k in outcome.selected_ks).items())),
    }
    return result, logs


def _summarize_override_guard_sweep(
    records: Sequence[dict[str, dict[str, Any]]],
    thresholds: Sequence[float | None],
) -> dict[str, Any]:
    """Aggregate validation-only sweep records and select by TechnicalScore."""
    summaries: dict[str, dict[str, Any]] = {}
    exact_selection_values: dict[str, tuple[float, float, float, float]] = {}
    for threshold in thresholds:
        label = override_guard_threshold_label(threshold)
        items = [record[label] for record in records]
        outcomes = [item["outcome"] for item in items]
        overall = metric_summary(outcomes)
        eligible_count = sum(int(item["eligible_decisions"]) for item in items)
        fallback_turns = sum(int(item["fallback_turns"]) for item in items)
        margins_min = [
            float(item["eligible_margin_min"])
            for item in items
            if item["eligible_margin_min"] is not None
        ]
        margins_max = [
            float(item["eligible_margin_max"])
            for item in items
            if item["eligible_margin_max"] is not None
        ]
        margin_sum = sum(float(item["eligible_margin_sum"]) for item in items)
        summaries[label] = {
            "threshold": threshold,
            "overall": overall,
            "by_scenario": scenario_summary(outcomes),
            "k_counts": dict(
                sorted(Counter(k for outcome in outcomes for k in outcome.selected_ks).items())
            ),
            "guard_diagnostics": {
                "override_turn_decisions": sum(
                    int(item["override_turn_decisions"]) for item in items
                ),
                "base_k_below_10_decisions": eligible_count,
                "fallback_turns": fallback_turns,
                "fallback_sessions": sum(bool(item["fallback_session"]) for item in items),
                "fallback_rate_when_eligible": round(
                    fallback_turns / eligible_count if eligible_count else 0.0,
                    6,
                ),
                "eligible_margin_mean": (
                    round(margin_sum / eligible_count, 8) if eligible_count else None
                ),
                "eligible_margin_min": round(min(margins_min), 8) if margins_min else None,
                "eligible_margin_max": round(max(margins_max), 8) if margins_max else None,
            },
        }
        count = max(1, len(outcomes))
        exact_selection_values[label] = (
            sum(outcome.utility for outcome in outcomes) / count,
            sum(outcome.hit for outcome in outcomes) / count,
            sum(outcome.reciprocal_rank for outcome in outcomes) / count,
            sum(
                outcome.first_hit_turn
                if outcome.first_hit_turn is not None
                else MAX_TURNS + 1
                for outcome in outcomes
            )
            / count,
        )

    baseline = summaries.get("none")
    if baseline is not None:
        baseline_score = float(baseline["overall"]["technical_score"])
        for summary in summaries.values():
            summary["technical_score_delta_vs_no_guard"] = round(
                float(summary["overall"]["technical_score"]) - baseline_score,
                6,
            )

    def selection_key(threshold: float | None) -> tuple[float, float, float, float, float]:
        label = override_guard_threshold_label(threshold)
        technical, hit_rate, mrr, mttc = exact_selection_values[label]
        # Prefer no guard, then the smaller threshold, when every metric ties.
        aggressiveness = -1.0 if threshold is None else threshold
        return technical, hit_rate, mrr, -mttc, -aggressiveness

    selected_threshold = max(thresholds, key=selection_key)
    selected_label = override_guard_threshold_label(selected_threshold)
    return {
        "data_scope": "calibration_split_only",
        "selection_metric": "validation TechnicalScore; HitRate, MRR, MTTC, then smaller guard",
        "heldout_used_for_selection": False,
        "threshold_order": [override_guard_threshold_label(value) for value in thresholds],
        "thresholds": summaries,
        "selected": {
            "label": selected_label,
            "threshold": selected_threshold,
            "overall": summaries[selected_label]["overall"],
            "guard_diagnostics": summaries[selected_label]["guard_diagnostics"],
        },
    }


def evaluate_override_guard_sweep(
    harness: RankingHarness,
    samples: Sequence[dict],
    categories: dict[str, list[str]],
    products: dict[str, dict],
    model: AdaptiveKModel,
    *,
    q_mode: Literal["bellman", "requested-minus"],
    thresholds: Sequence[float | None],
) -> dict[str, Any]:
    """Serial validation sweep; templates are built exactly once per sample."""
    policies = tuple(
        (
            threshold,
            ArtifactAdaptivePolicy(
                model,
                q_mode=q_mode,
                override_k10_q_margin_threshold=threshold,
            ),
        )
        for threshold in thresholds
    )
    records: list[dict[str, dict[str, Any]]] = []
    for index, sample in enumerate(samples, 1):
        templates, target = build_templates(harness, sample, categories, products)
        records.append(_sweep_one_sample(sample, templates, target, policies))
        if index % 25 == 0 or index == len(samples):
            print(f"swept validation sessions: {index}/{len(samples)}", flush=True)
    return _summarize_override_guard_sweep(records, thresholds)


def evaluate_override_guard_sweep_parallel(
    catalog_path: Path,
    model_path: Path,
    samples: Sequence[dict],
    *,
    workers: int,
    q_mode: Literal["bellman", "requested-minus"],
    thresholds: Sequence[float | None],
) -> dict[str, Any]:
    """Multiprocess validation sweep with one template build per worker/sample."""
    threshold_tuple = tuple(thresholds)
    records: list[dict[str, dict[str, Any]]] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_override_guard_sweep_worker,
        initargs=(str(catalog_path), str(model_path), q_mode, threshold_tuple),
    ) as executor:
        for index, record in enumerate(
            executor.map(_override_guard_sweep_worker, samples),
            1,
        ):
            records.append(record)
            if index % 25 == 0 or index == len(samples):
                print(f"swept validation sessions: {index}/{len(samples)}", flush=True)
    return _summarize_override_guard_sweep(records, thresholds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/unseen_eval/dev_set.jsonl")
    parser.add_argument(
        "--cache",
        default="experiments/algo/khoa-tbd/adaptive_k_trajectories.jsonl.gz",
        help="Training/calibration trajectory cache; pass an empty string to disable.",
    )
    parser.add_argument(
        "--model-out",
        default="experiments/algo/khoa-tbd/adaptive_k_model.json",
    )
    parser.add_argument(
        "--output",
        default="experiments/algo/khoa-tbd/adaptive_k_results.json",
    )
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument(
        "--evaluation-scope",
        choices=("heldout", "all"),
        default="heldout",
        help=(
            "Evaluate the untouched 15%% split, or all dataset sessions. "
            "The all-session score is partly in-sample and is not an unbiased estimate."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Worker processes; each owns one catalog/ranking index. Use 1 for serial debugging.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Stratified smoke-test limit; 0 uses all sessions.")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--rank-l2", type=float, default=1e-4)
    parser.add_argument("--continuation-l2", type=float, default=1.0)
    parser.add_argument(
        "--q-mode",
        choices=("bellman", "requested-minus"),
        default="bellman",
    )
    parser.add_argument(
        "--override-guard-sweep",
        action="store_true",
        help=(
            "Evaluate override-turn K=10 guard thresholds on the 15%% "
            "calibration/validation split only; held-out sessions are not evaluated."
        ),
    )
    parser.add_argument(
        "--override-guard-thresholds",
        type=parse_override_guard_thresholds,
        default=DEFAULT_OVERRIDE_GUARD_THRESHOLDS,
        metavar="LIST",
        help=(
            "Comma-separated guard thresholds for --override-guard-sweep "
            "(default: none,0,.0025,.005,.01,.02,.03,.05)."
        ),
    )
    parser.add_argument("--skip-oracle", action="store_true")
    parser.add_argument(
        "--log-limit",
        type=int,
        default=-1,
        help="Maximum adaptive turn logs in output; -1 logs every held-out turn.",
    )
    parser.add_argument("--force-cache", action="store_true")
    return parser.parse_args()


def stratified_limit(samples: Sequence[dict], limit: int, seed: int) -> list[dict]:
    if limit <= 0 or limit >= len(samples):
        return list(samples)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["scenario_type"])].append(sample)
    rng = random.Random(seed)
    for group in grouped.values():
        rng.shuffle(group)
    result: list[dict] = []
    scenarios = sorted(grouped)
    while len(result) < limit and any(grouped.values()):
        for scenario in scenarios:
            if grouped[scenario] and len(result) < limit:
                result.append(grouped[scenario].pop())
    rng.shuffle(result)
    return result


def main() -> None:
    args = parse_args()
    if args.override_guard_sweep and args.q_mode != "bellman":
        raise SystemExit(
            "--override-guard-sweep requires --q-mode bellman because the guard "
            "threshold is defined as the Bellman Q margin to K=10."
        )
    catalog_path = Path(args.catalog)
    dataset_path = Path(args.dataset)
    samples = stratified_limit(load_jsonl(dataset_path), args.limit, args.seed)
    train_samples, calibration_samples, heldout_samples = stratified_split(samples, seed=args.seed)
    if not train_samples or not calibration_samples or not heldout_samples:
        raise SystemExit("Need enough cases for non-empty 70/15/15 splits; increase --limit.")
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    print(
        f"split: train={len(train_samples)} calibration={len(calibration_samples)} "
        f"heldout={len(heldout_samples)}",
        flush=True,
    )

    categories: dict[str, list[str]] | None = None
    products: dict[str, dict] | None = None
    harness: RankingHarness | None = None
    if args.workers == 1:
        _, categories, products = catalog_index(catalog_path)
        harness = RankingHarness(catalog_path)
    cache_metadata = {
        "cache_version": CACHE_VERSION,
        "catalog": file_fingerprint(catalog_path),
        "dataset": file_fingerprint(dataset_path),
        "seed": args.seed,
        "limit": args.limit,
        "train_ids": [str(sample["sample_id"]) for sample in train_samples],
        "calibration_ids": [str(sample["sample_id"]) for sample in calibration_samples],
    }
    cache_path = Path(args.cache) if args.cache else None
    rows: list[dict[str, Any]]
    if cache_path and cache_path.exists() and not args.force_cache:
        print(f"loading trajectory cache: {cache_path}", flush=True)
        rows = load_cache(cache_path, cache_metadata)
    else:
        marked_train = [dict(sample, _adaptive_split="train") for sample in train_samples]
        marked_calibration = [dict(sample, _adaptive_split="calibration") for sample in calibration_samples]
        marked_samples = [*marked_train, *marked_calibration]
        if args.workers == 1:
            assert harness is not None and categories is not None and products is not None
            rows = collect_split_rows(harness, marked_samples, categories, products)
        else:
            rows = collect_split_rows_parallel(catalog_path, marked_samples, args.workers)
        split_by_id = {
            str(sample["sample_id"]): str(sample["_adaptive_split"])
            for sample in [*marked_train, *marked_calibration]
        }
        for row in rows:
            row["split"] = split_by_id[str(row["sample_id"])]
        if cache_path:
            print(f"saving trajectory cache: {cache_path}", flush=True)
            save_cache(cache_path, cache_metadata, rows)

    train_rows = [row for row in rows if row["split"] == "train"]
    calibration_rows = [row for row in rows if row["split"] == "calibration"]
    rank_train = unique_rank_rows(train_rows)
    rank_calibration = unique_rank_rows(calibration_rows)
    print(
        f"training rows: rank={len(rank_train)} continuation={len(train_rows)}; "
        f"calibration rank rows={len(rank_calibration)}",
        flush=True,
    )
    rank_trainer = CalibratedCDFTrainer()
    rank_trainer.fit(
        rank_train,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        l2=args.rank_l2,
        seed=args.seed,
    )
    rank_trainer.calibrate(rank_calibration)
    continuation_trainer = SharedContinuationTrainer()
    continuation_trainer.fit(train_rows, rank_trainer, l2=args.continuation_l2)
    model_metadata = {
        "seed": args.seed,
        "dataset": file_fingerprint(dataset_path),
        "catalog": file_fingerprint(catalog_path),
        "split_counts": {
            "train": len(train_samples),
            "calibration": len(calibration_samples),
            "heldout": len(heldout_samples),
        },
        "rank_training_rows": len(rank_train),
        "continuation_training_rows": sum(
            row.get("continuation_target") is not None for row in train_rows
        ),
        "feature_count": len(FEATURE_NAMES),
        "rank_heads": list(K_VALUES),
        "continuation_head": "shared_default",
        "q_mode": args.q_mode,
    }
    model_path = Path(args.model_out)
    loaded_model = save_model(
        model_path,
        rank_trainer,
        continuation_trainer,
        empirical_rank_priors(rank_train),
        model_metadata,
    )
    if dict(loaded_model.metadata) != model_metadata:
        raise RuntimeError("saved adaptive-K model failed metadata round trip")

    if args.override_guard_sweep:
        thresholds = tuple(args.override_guard_thresholds)
        print(
            "override-guard validation thresholds: "
            + ", ".join(override_guard_threshold_label(value) for value in thresholds),
            flush=True,
        )
        if args.workers == 1:
            assert harness is not None and categories is not None and products is not None
            guard_sweep = evaluate_override_guard_sweep(
                harness,
                calibration_samples,
                categories,
                products,
                loaded_model,
                q_mode=args.q_mode,
                thresholds=thresholds,
            )
        else:
            guard_sweep = evaluate_override_guard_sweep_parallel(
                catalog_path,
                model_path,
                calibration_samples,
                workers=args.workers,
                q_mode=args.q_mode,
                thresholds=thresholds,
            )
        result = {
            "configuration": {
                **vars(args),
                "catalog": str(catalog_path),
                "dataset": str(dataset_path),
                "k_values": K_VALUES,
                "q_equation": (
                    "sum_r<=K p(r|s)*U(t,r) + p(R>K|s)*V_next(s,K)"
                ),
            },
            "split_counts": model_metadata["split_counts"],
            "model": model_metadata,
            "calibration": calibration_report(loaded_model, calibration_rows),
            "override_guard_validation_sweep": guard_sweep,
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        concise = {
            "split_counts": result["split_counts"],
            "calibration": result["calibration"],
            "override_guard_validation_sweep": guard_sweep,
            "model_path": str(model_path),
            "output_path": str(output_path),
        }
        print(json.dumps(concise, indent=2), flush=True)
        return

    learned_policy = ArtifactAdaptivePolicy(
        loaded_model,
        q_mode=args.q_mode,
    )
    evaluation_samples = samples if args.evaluation_scope == "all" else heldout_samples
    evaluation_key = "all_2000" if args.evaluation_scope == "all" else "heldout"
    if args.workers == 1:
        assert harness is not None and categories is not None and products is not None
        evaluation, adaptive_logs = evaluate_heldout(
            harness,
            evaluation_samples,
            categories,
            products,
            learned_policy,
            run_oracle=not args.skip_oracle,
            log_limit=args.log_limit,
        )
    else:
        evaluation, adaptive_logs = evaluate_heldout_parallel(
            catalog_path,
            model_path,
            evaluation_samples,
            workers=args.workers,
            q_mode=args.q_mode,
            run_oracle=not args.skip_oracle,
            log_limit=args.log_limit,
        )
    result = {
        "configuration": {
            **vars(args),
            "catalog": str(catalog_path),
            "dataset": str(dataset_path),
            "k_values": K_VALUES,
            "q_equation": (
                "sum_r<=K p(r|s)*U(t,r) + p(R>K|s)*V_next(s,K)"
                if args.q_mode == "bellman"
                else "sum_r<=K p(r|s)*U(t,r) - p(R>K|s)*V_next(s,K)"
            ),
        },
        "split_counts": model_metadata["split_counts"],
        "model": model_metadata,
        "calibration": calibration_report(loaded_model, calibration_rows),
        evaluation_key: evaluation,
        "adaptive_turn_logs": adaptive_logs,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    concise = {
        "split_counts": result["split_counts"],
        "calibration": result["calibration"],
        evaluation_key: result[evaluation_key],
        "model_path": str(model_path),
        "output_path": str(output_path),
    }
    print(json.dumps(concise, indent=2), flush=True)


if __name__ == "__main__":
    main()
