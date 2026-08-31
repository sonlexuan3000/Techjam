"""Runtime support for a calibrated, rank-aware adaptive-K policy.

The module is deliberately independent of ``Agent`` and of evaluator labels.
It consumes only a ranked candidate list and observable conversation state at
inference time.  Training code may serialize linear heads and calibration
knots to JSON; this module has no third-party runtime dependency.

Two Q functions are exposed.  ``q_spec`` implements the formula in the policy
brief literally.  With the same non-negative continuation value for each K it
is monotone in K, so it always prefers the largest available K.  ``q_bellman``
treats a miss as leading to the value of the next turn and is therefore the
useful adaptive objective.  Both are logged so an experiment can audit that
distinction.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


ALLOWED_K: tuple[int, ...] = (1, 3, 5, 10)
MAX_RANK = 10
MAX_TURNS = 10
EPSILON = 1e-12

INTENT_LABELS: tuple[str, ...] = (
    "B1_EXACT_BUYING",
    "B2_ATTRIBUTE_BUYING",
    "B3_SEMANTIC_BUYING",
    "R1_VERY_BROAD_BROWSING",
    "R2_PREFERENCE_BROWSING",
    "R3_BROWSING_TO_BUYING",
    "O1_OVERRIDE",
    "O2_NON_CONFLICTING_UPDATE",
    "X1_NO_PREFERENCE",
    "X2_MISSING_ATTRIBUTE",
)

COMPONENT_NAMES: tuple[str, ...] = (
    "hard",
    "semantic",
    "lexical",
    "soft",
    "current",
    "exclusion",
)

FEATURE_NAMES: tuple[str, ...] = (
    "turn_norm",
    "turns_remaining_norm",
    "candidate_count_log1p",
    "recommended_count_log1p",
    "query_term_count_log1p",
    "unique_query_term_count_log1p",
    "profile_term_count_log1p",
    "evidence_turns_norm",
    "active_constraint_count",
    "hard_constraint_count",
    "soft_constraint_count",
    "category_constraint_count",
    "exclusion_constraint_count",
    "unique_attribute_count",
    "unavailable_attribute_count",
    "mode_buying",
    "override_seen",
    "score_top1",
    "score_mean_top10",
    "score_std_top10",
    "score_span_top10",
    "score_margin_1_2",
    "score_margin_1_3",
    "score_margin_1_5",
    "score_margin_1_10",
    "relative_margin_1_2",
    "relative_margin_1_3",
    "relative_margin_1_5",
    "relative_margin_1_10",
    "softmax_top1_probability",
    "softmax_entropy_top10",
    "has_rank_1",
    "has_rank_3",
    "has_rank_5",
    "has_rank_10",
    "rating_top1",
    "rating_margin_1_2",
    "top1_hard",
    "top1_semantic",
    "top1_lexical",
    "top1_soft",
    "top1_current",
    "top1_exclusion",
    "component_margin_hard",
    "component_margin_semantic",
    "component_margin_lexical",
    "component_margin_soft",
    "component_margin_current",
    "component_margin_exclusion",
    "top10_overlap_hard",
    "top10_overlap_semantic",
    "top10_overlap_lexical",
    "top10_overlap_soft",
    "top10_overlap_current",
    "top10_overlap_exclusion",
    "top1_component_vote_fraction",
    *(f"intent_{label}" for label in INTENT_LABELS),
)


def _finite(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clip_probability(value: object) -> float:
    return min(1.0, max(0.0, _finite(value)))


def technical_utility(turn: int, rank: int, max_turns: int = MAX_TURNS) -> float:
    """Return one session's TechnicalScore contribution for a hit.

    For the competition's ten-turn evaluator this is exactly
    ``0.5 + 0.3 / rank + 0.2 * (11 - turn) / 10``.  A miss has utility zero and
    is represented outside this function.
    """

    if max_turns <= 0:
        raise ValueError("max_turns must be positive")
    if not 1 <= turn <= max_turns:
        raise ValueError(f"turn must be in [1, {max_turns}]")
    if rank <= 0:
        raise ValueError("rank must be positive")
    efficiency = (max_turns + 1 - turn) / max_turns
    return 0.5 + 0.3 / rank + 0.2 * efficiency


def project_monotone_cdf(cdf: Mapping[int, float]) -> dict[int, float]:
    """Clip and L2-project CDF values onto a non-decreasing sequence.

    Independent calibrated binary heads can cross (for example P(R<=3) may be
    lower than P(R<=1)).  Equal-weight pool-adjacent-violators is sufficient to
    repair those small inconsistencies without making any target-dependent
    inference-time decision.
    """

    if not cdf:
        raise ValueError("cdf must contain at least one threshold")
    ordered = sorted((int(rank), _clip_probability(value)) for rank, value in cdf.items())
    if ordered[0][0] <= 0:
        raise ValueError("CDF thresholds must be positive")
    if len({rank for rank, _ in ordered}) != len(ordered):
        raise ValueError("CDF thresholds must be unique")

    # Each block is [mean, weight, first_position, last_position].
    blocks: list[list[float | int]] = []
    for position, (_, value) in enumerate(ordered):
        blocks.append([value, 1.0, position, position])
        while len(blocks) >= 2 and float(blocks[-2][0]) > float(blocks[-1][0]):
            right = blocks.pop()
            left = blocks.pop()
            weight = float(left[1]) + float(right[1])
            mean = (
                float(left[0]) * float(left[1]) + float(right[0]) * float(right[1])
            ) / weight
            blocks.append([mean, weight, int(left[2]), int(right[3])])

    projected = [0.0] * len(ordered)
    for mean, _, first, last in blocks:
        for position in range(int(first), int(last) + 1):
            projected[position] = _clip_probability(mean)
    return {rank: projected[position] for position, (rank, _) in enumerate(ordered)}


def cdf_to_rank_masses(
    cdf: Mapping[int, float],
    rank_priors: Mapping[int, float] | None = None,
    max_rank: int = MAX_RANK,
) -> tuple[dict[int, float], float]:
    """Convert possibly sparse CDF heads into exact rank masses.

    When the artifact has only the requested 1/3/5/10 heads, probability inside
    each interval is divided according to ``rank_priors`` learned on training
    sessions.  Uniform allocation is the deterministic fallback.  Artifacts
    with heads for every rank need no approximation.
    """

    if max_rank <= 0:
        raise ValueError("max_rank must be positive")
    projected = project_monotone_cdf(cdf)
    thresholds = sorted(projected)
    if thresholds[-1] != max_rank:
        raise ValueError(f"CDF must include the terminal threshold {max_rank}")
    if thresholds[-1] > max_rank:
        raise ValueError("CDF threshold exceeds max_rank")

    priors = {
        rank: max(0.0, _finite((rank_priors or {}).get(rank, 1.0), 1.0))
        for rank in range(1, max_rank + 1)
    }
    masses = {rank: 0.0 for rank in range(1, max_rank + 1)}
    previous_rank = 0
    previous_cdf = 0.0
    for threshold in thresholds:
        interval = list(range(previous_rank + 1, threshold + 1))
        interval_mass = max(0.0, projected[threshold] - previous_cdf)
        prior_total = sum(priors[rank] for rank in interval)
        if prior_total <= EPSILON:
            for rank in interval:
                masses[rank] = interval_mass / len(interval)
        else:
            for rank in interval:
                masses[rank] = interval_mass * priors[rank] / prior_total
        previous_rank = threshold
        previous_cdf = projected[threshold]

    miss_probability = max(0.0, 1.0 - previous_cdf)
    # Protect downstream Q values from tiny floating-point normalization drift.
    total = sum(masses.values()) + miss_probability
    if total <= EPSILON:
        return masses, 1.0
    if abs(total - 1.0) > EPSILON:
        masses = {rank: value / total for rank, value in masses.items()}
        miss_probability /= total
    return masses, miss_probability


def compute_q_values(
    rank_masses: Mapping[int, float],
    turn: int,
    continuation_values: Mapping[int, float] | float | None = None,
    allowed_k: Sequence[int] = ALLOWED_K,
    max_turns: int = MAX_TURNS,
    *,
    continuation_value: float | None = None,
) -> tuple[dict[int, float], dict[int, float]]:
    """Calculate the literal and Bellman-sign Q values for every K.

    ``q_spec`` uses ``hit_value - P(miss) * V_next`` exactly as requested.
    ``q_bellman`` uses ``hit_value + P(miss) * V_next`` because continuing is
    an alternative future outcome, not a cost.  The latter can genuinely select
    a smaller K when deferring a low-rank hit has higher expected value.
    """

    options = tuple(sorted({int(value) for value in allowed_k if int(value) > 0}))
    if not options:
        raise ValueError("allowed_k must contain a positive value")
    if continuation_value is not None:
        if continuation_values is not None:
            raise ValueError("pass continuation_values or continuation_value, not both")
        continuation_values = continuation_value
    if continuation_values is None:
        continuation_by_k = {k: 0.0 for k in options}
    elif isinstance(continuation_values, Mapping):
        continuation_by_k = {
            k: _clip_probability(continuation_values.get(k, 0.0)) for k in options
        }
    else:
        shared_continuation = _clip_probability(continuation_values)
        continuation_by_k = {k: shared_continuation for k in options}
    probability_by_rank = {
        rank: max(0.0, _finite(rank_masses.get(rank, 0.0)))
        for rank in range(1, max(options) + 1)
    }
    total_known = sum(probability_by_rank.values())
    if total_known > 1.0 + 1e-9:
        probability_by_rank = {
            rank: probability / total_known for rank, probability in probability_by_rank.items()
        }

    q_spec: dict[int, float] = {}
    q_bellman: dict[int, float] = {}
    for k in options:
        hit_value = sum(
            probability_by_rank[rank] * technical_utility(turn, rank, max_turns)
            for rank in range(1, k + 1)
        )
        hit_probability = sum(probability_by_rank[rank] for rank in range(1, k + 1))
        miss_probability = max(0.0, 1.0 - hit_probability)
        continuation = continuation_by_k[k]
        q_spec[k] = hit_value - miss_probability * continuation
        q_bellman[k] = hit_value + miss_probability * continuation
    return q_spec, q_bellman


def apply_override_k10_guard(
    base_selected_k: int,
    q_values: Mapping[int, float],
    *,
    is_override_turn: bool,
    q_margin_threshold: float | None,
) -> tuple[int, bool, float | None]:
    """Temporarily widen an uncertain override-turn decision to K=10.

    The uncertainty signal is the learned action's Q advantage over K=10. A
    small advantage means the shorter-list decision is fragile. This helper is
    target-free and shared by live inference and offline policy replay.
    """

    if q_margin_threshold is not None:
        q_margin_threshold = float(q_margin_threshold)
        if not math.isfinite(q_margin_threshold) or q_margin_threshold < 0.0:
            raise ValueError("override K=10 Q-margin threshold must be finite and non-negative")
    if 10 not in q_values or base_selected_k == 10:
        return base_selected_k, False, None
    margin = max(0.0, _finite(q_values.get(base_selected_k)) - _finite(q_values.get(10)))
    if (
        is_override_turn
        and q_margin_threshold is not None
        and margin <= q_margin_threshold + EPSILON
    ):
        return 10, True, margin
    return base_selected_k, False, margin


@dataclass(frozen=True)
class RankedCandidate:
    """Observable reranker output used by feature extraction."""

    parent_asin: str
    score: float
    rating: float = 0.0
    components: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RankingContext:
    """Target-free conversation facts available when K is selected."""

    turn: int
    intent: str
    mode: str = "browsing"
    active_constraint_count: int = 0
    hard_constraint_count: int = 0
    soft_constraint_count: int = 0
    category_constraint_count: int = 0
    exclusion_constraint_count: int = 0
    unique_attribute_count: int = 0
    unavailable_attribute_count: int = 0
    evidence_turns: int = 0
    query_term_count: int = 0
    unique_query_term_count: int = 0
    profile_term_count: int = 0
    recommended_count: int = 0
    # Offline replay may retain only the leading feature window.  Supplying the
    # observable full retrieval count preserves feature parity without keeping
    # every candidate object alive; normal Agent calls also populate it.
    candidate_count: int | None = None
    override_seen: bool = False
    max_turns: int = MAX_TURNS


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def extract_rank_features(
    candidates: Sequence[RankedCandidate],
    context: RankingContext,
    agreement_window: int = 75,
) -> dict[str, float]:
    """Build the stable feature schema used by training and inference.

    ``candidates`` must already be in the existing reranker's order after
    filtering products recommended on earlier turns.  No target identifier or
    target-derived value is accepted by this API.
    """

    if context.max_turns <= 0:
        raise ValueError("context.max_turns must be positive")
    if not 1 <= context.turn <= context.max_turns:
        raise ValueError("context.turn is outside the configured turn range")
    if agreement_window <= 0:
        raise ValueError("agreement_window must be positive")

    result = {name: 0.0 for name in FEATURE_NAMES}
    result.update({
        "turn_norm": context.turn / context.max_turns,
        "turns_remaining_norm": (context.max_turns - context.turn) / context.max_turns,
        "candidate_count_log1p": math.log1p(
            len(candidates)
            if context.candidate_count is None
            else max(0, context.candidate_count)
        ),
        "recommended_count_log1p": math.log1p(max(0, context.recommended_count)),
        "query_term_count_log1p": math.log1p(max(0, context.query_term_count)),
        "unique_query_term_count_log1p": math.log1p(max(0, context.unique_query_term_count)),
        "profile_term_count_log1p": math.log1p(max(0, context.profile_term_count)),
        "evidence_turns_norm": max(0, context.evidence_turns) / context.max_turns,
        "active_constraint_count": float(max(0, context.active_constraint_count)),
        "hard_constraint_count": float(max(0, context.hard_constraint_count)),
        "soft_constraint_count": float(max(0, context.soft_constraint_count)),
        "category_constraint_count": float(max(0, context.category_constraint_count)),
        "exclusion_constraint_count": float(max(0, context.exclusion_constraint_count)),
        "unique_attribute_count": float(max(0, context.unique_attribute_count)),
        "unavailable_attribute_count": float(max(0, context.unavailable_attribute_count)),
        "mode_buying": float(context.mode == "buying"),
        "override_seen": float(context.override_seen),
    })
    if context.intent in INTENT_LABELS:
        result[f"intent_{context.intent}"] = 1.0
    if not candidates:
        return result

    top = list(candidates[:10])
    scores = [_finite(candidate.score) for candidate in top]
    score_mean = _mean(scores)
    score_std = _std(scores)
    score_span = max(scores) - min(scores)
    result.update({
        "score_top1": scores[0],
        "score_mean_top10": score_mean,
        "score_std_top10": score_std,
        "score_span_top10": score_span,
        "rating_top1": _finite(top[0].rating),
    })

    scale = max(score_std, abs(scores[0]) * 0.05, EPSILON)
    for rank in (2, 3, 5, 10):
        available = len(scores) >= rank
        if rank in (3, 5, 10):
            result[f"has_rank_{rank}"] = float(available)
        margin = scores[0] - scores[rank - 1] if available else 0.0
        result[f"score_margin_1_{rank}"] = margin
        result[f"relative_margin_1_{rank}"] = margin / scale
    result["has_rank_1"] = 1.0
    if len(top) >= 2:
        result["rating_margin_1_2"] = _finite(top[0].rating) - _finite(top[1].rating)

    # Scale-invariant score concentration and entropy among the visible top 10.
    temperature = max(score_std, EPSILON)
    exponentials = [math.exp(max(-60.0, min(0.0, (score - scores[0]) / temperature))) for score in scores]
    denominator = sum(exponentials)
    probabilities = [value / denominator for value in exponentials]
    result["softmax_top1_probability"] = probabilities[0]
    if len(probabilities) > 1:
        entropy = -sum(probability * math.log(max(probability, EPSILON)) for probability in probabilities)
        result["softmax_entropy_top10"] = entropy / math.log(len(probabilities))

    first = top[0]
    for name in COMPONENT_NAMES:
        result[f"top1_{name}"] = _finite(first.components.get(name, 0.0))

    # Agreement is computed only inside the leading window to keep this feature
    # extractor cheap compared with catalog retrieval and reranking.
    window = list(candidates[:agreement_window])
    main_top_ids = {candidate.parent_asin for candidate in top}
    component_votes = 0
    for name in COMPONENT_NAMES:
        component_order = sorted(
            window,
            key=lambda candidate: (
                -_finite(candidate.components.get(name, 0.0)),
                -_finite(candidate.rating),
                candidate.parent_asin,
            ),
        )
        component_top = component_order[:10]
        component_ids = {candidate.parent_asin for candidate in component_top}
        result[f"top10_overlap_{name}"] = _jaccard(main_top_ids, component_ids)
        if component_order and component_order[0].parent_asin == first.parent_asin:
            component_votes += 1
        if len(component_order) >= 2:
            result[f"component_margin_{name}"] = (
                _finite(component_order[0].components.get(name, 0.0))
                - _finite(component_order[1].components.get(name, 0.0))
            )
    result["top1_component_vote_fraction"] = component_votes / len(COMPONENT_NAMES)
    return result


def vectorize_features(
    features: Mapping[str, float],
    feature_names: Sequence[str] = FEATURE_NAMES,
    means: Sequence[float] | None = None,
    scales: Sequence[float] | None = None,
) -> tuple[float, ...]:
    """Order and optionally standardize a feature mapping."""

    names = tuple(feature_names)
    means = tuple(means) if means is not None else (0.0,) * len(names)
    scales = tuple(scales) if scales is not None else (1.0,) * len(names)
    if len(means) != len(names) or len(scales) != len(names):
        raise ValueError("normalization vectors must match feature_names")
    vector: list[float] = []
    for name, mean, scale in zip(names, means, scales):
        denominator = _finite(scale, 1.0)
        if abs(denominator) <= EPSILON:
            denominator = 1.0
        vector.append((_finite(features.get(name, 0.0)) - _finite(mean)) / denominator)
    return tuple(vector)


@dataclass(frozen=True)
class PiecewiseCalibrator:
    """Small JSON-serializable monotone probability calibrator."""

    x: tuple[float, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.x or len(self.x) != len(self.y):
            raise ValueError("calibration x/y knots must be non-empty and equal length")
        if any(left >= right for left, right in zip(self.x, self.x[1:])):
            raise ValueError("calibration x knots must be strictly increasing")
        if any(left > right for left, right in zip(self.y, self.y[1:])):
            raise ValueError("calibration y knots must be non-decreasing")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PiecewiseCalibrator":
        return cls(
            tuple(_finite(value) for value in payload.get("x", ())),
            tuple(_clip_probability(value) for value in payload.get("y", ())),
        )

    def predict(self, value: float) -> float:
        value = _clip_probability(value)
        if value <= self.x[0]:
            return _clip_probability(self.y[0])
        if value >= self.x[-1]:
            return _clip_probability(self.y[-1])
        for index in range(1, len(self.x)):
            if value <= self.x[index]:
                left_x, right_x = self.x[index - 1], self.x[index]
                fraction = (value - left_x) / (right_x - left_x)
                return _clip_probability(
                    self.y[index - 1] + fraction * (self.y[index] - self.y[index - 1])
                )
        return _clip_probability(self.y[-1])


@dataclass(frozen=True)
class LinearHead:
    """A calibrated linear predictor loaded from an offline artifact."""

    bias: float
    weights: tuple[float, ...]
    link: Literal["sigmoid", "identity"] = "sigmoid"
    calibrator: PiecewiseCalibrator | None = None

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        feature_names: Sequence[str],
    ) -> "LinearHead":
        raw_weights = payload.get("weights", ())
        if isinstance(raw_weights, Mapping):
            weights = tuple(_finite(raw_weights.get(name, 0.0)) for name in feature_names)
        else:
            weights = tuple(_finite(value) for value in raw_weights)
        if len(weights) != len(feature_names):
            raise ValueError("linear head weight count must match feature_names")
        link = str(payload.get("link", "sigmoid"))
        if link not in {"sigmoid", "identity"}:
            raise ValueError(f"unsupported linear-head link: {link}")
        calibration = payload.get("calibration")
        return cls(
            bias=_finite(payload.get("bias", 0.0)),
            weights=weights,
            link=link,  # type: ignore[arg-type]
            calibrator=(
                PiecewiseCalibrator.from_dict(calibration)
                if isinstance(calibration, Mapping)
                else None
            ),
        )

    def predict(self, vector: Sequence[float]) -> float:
        if len(vector) != len(self.weights):
            raise ValueError("feature vector length does not match linear head")
        value = self.bias + sum(weight * feature for weight, feature in zip(self.weights, vector))
        if self.link == "sigmoid":
            if value >= 0.0:
                probability = 1.0 / (1.0 + math.exp(-min(value, 60.0)))
            else:
                exponential = math.exp(max(value, -60.0))
                probability = exponential / (1.0 + exponential)
        else:
            probability = _clip_probability(value)
        return self.calibrator.predict(probability) if self.calibrator else probability


@dataclass(frozen=True)
class RankPrediction:
    cdf: Mapping[int, float]
    rank_masses: Mapping[int, float]
    miss_probability: float
    continuation_values: Mapping[int, float]


@dataclass(frozen=True)
class AdaptiveKModel:
    """Calibrated rank-CDF and continuation-value model."""

    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    rank_heads: Mapping[int, LinearHead]
    continuation_heads: Mapping[int, LinearHead]
    default_continuation_head: LinearHead | None = None
    rank_priors: Mapping[int, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> "AdaptiveKModel":
        with Path(path).open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError("adaptive-K artifact root must be an object")
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AdaptiveKModel":
        version = int(payload.get("schema_version", 1))
        if version != 1:
            raise ValueError(f"unsupported adaptive-K schema_version: {version}")
        feature_names = tuple(str(name) for name in payload.get("feature_names", FEATURE_NAMES))
        if not feature_names or len(set(feature_names)) != len(feature_names):
            raise ValueError("feature_names must be non-empty and unique")
        unknown_features = set(feature_names) - set(FEATURE_NAMES)
        if unknown_features:
            raise ValueError(f"unknown adaptive-K features: {sorted(unknown_features)}")

        normalization = payload.get("normalization", {})
        if not isinstance(normalization, Mapping):
            raise ValueError("normalization must be an object")
        means = tuple(_finite(value) for value in normalization.get("mean", (0.0,) * len(feature_names)))
        scales = tuple(_finite(value, 1.0) for value in normalization.get("scale", (1.0,) * len(feature_names)))
        if len(means) != len(feature_names) or len(scales) != len(feature_names):
            raise ValueError("normalization vectors must match feature_names")

        rank_payload = payload.get("rank_heads")
        if not isinstance(rank_payload, Mapping):
            raise ValueError("rank_heads must be an object")
        rank_heads = {
            int(threshold): LinearHead.from_dict(head, feature_names)
            for threshold, head in rank_payload.items()
            if isinstance(head, Mapping)
        }
        missing_thresholds = set(ALLOWED_K) - set(rank_heads)
        if missing_thresholds:
            raise ValueError(f"rank_heads missing thresholds: {sorted(missing_thresholds)}")
        if max(rank_heads) != MAX_RANK:
            raise ValueError(f"rank_heads must terminate at rank {MAX_RANK}")

        continuation_payload = payload.get("continuation_heads", {})
        if not isinstance(continuation_payload, Mapping):
            raise ValueError("continuation_heads must be an object")
        continuation_heads = {
            int(k): LinearHead.from_dict(head, feature_names)
            for k, head in continuation_payload.items()
            if str(k) != "default" and isinstance(head, Mapping)
        }
        default_payload = continuation_payload.get("default")
        default_head = (
            LinearHead.from_dict(default_payload, feature_names)
            if isinstance(default_payload, Mapping)
            else None
        )
        if default_head is None:
            missing_continuation = set(ALLOWED_K) - set(continuation_heads)
            if missing_continuation:
                raise ValueError(
                    f"continuation_heads missing K values: {sorted(missing_continuation)}"
                )

        raw_priors = payload.get("rank_priors", {})
        if not isinstance(raw_priors, Mapping):
            raise ValueError("rank_priors must be an object")
        rank_priors = {
            rank: max(0.0, _finite(raw_priors.get(str(rank), raw_priors.get(rank, 1.0)), 1.0))
            for rank in range(1, MAX_RANK + 1)
        }
        metadata = payload.get("metadata", {})
        return cls(
            feature_names=feature_names,
            means=means,
            scales=scales,
            rank_heads=rank_heads,
            continuation_heads=continuation_heads,
            default_continuation_head=default_head,
            rank_priors=rank_priors,
            metadata=metadata if isinstance(metadata, Mapping) else {},
        )

    def predict(self, features: Mapping[str, float], turn: int = 1) -> RankPrediction:
        vector = vectorize_features(features, self.feature_names, self.means, self.scales)
        raw_cdf = {threshold: head.predict(vector) for threshold, head in self.rank_heads.items()}
        cdf = project_monotone_cdf(raw_cdf)
        rank_masses, miss_probability = cdf_to_rank_masses(cdf, self.rank_priors, MAX_RANK)
        continuation_values: dict[int, float] = {}
        for k in ALLOWED_K:
            if turn >= MAX_TURNS:
                continuation_values[k] = 0.0
                continue
            head = self.continuation_heads.get(k, self.default_continuation_head)
            if head is None:  # Guard for manually constructed invalid instances.
                raise ValueError(f"no continuation head for K={k}")
            continuation_values[k] = _clip_probability(head.predict(vector))
        return RankPrediction(cdf, rank_masses, miss_probability, continuation_values)


@dataclass(frozen=True)
class AdaptiveKDecision:
    selected_k: int
    objective: Literal["spec", "bellman"]
    cdf: Mapping[int, float]
    rank_masses: Mapping[int, float]
    miss_probability: float
    continuation_values: Mapping[int, float]
    q_spec: Mapping[int, float]
    q_bellman: Mapping[int, float]
    feature_values: Mapping[str, float]
    base_selected_k: int
    override_guard_applied: bool
    override_q_margin_to_k10: float | None
    override_q_margin_threshold: float | None
    selection_reason: str

    def as_log(self, include_features: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "policy": "rank_aware_adaptive_k",
            "objective": self.objective,
            "rank_cdf": {str(rank): round(value, 8) for rank, value in sorted(self.cdf.items())},
            "rank_probabilities": {
                str(rank): round(value, 8) for rank, value in sorted(self.rank_masses.items())
            },
            "p_rank_gt_10": round(self.miss_probability, 8),
            "v_next": {
                str(k): round(value, 8) for k, value in sorted(self.continuation_values.items())
            },
            "q_spec": {str(k): round(value, 8) for k, value in sorted(self.q_spec.items())},
            "q_bellman": {
                str(k): round(value, 8) for k, value in sorted(self.q_bellman.items())
            },
            "base_selected_k": self.base_selected_k,
            "override_guard_applied": self.override_guard_applied,
            "override_q_margin_to_k10": (
                None
                if self.override_q_margin_to_k10 is None
                else round(self.override_q_margin_to_k10, 8)
            ),
            "override_q_margin_threshold": self.override_q_margin_threshold,
            "selection_reason": self.selection_reason,
            "selected_k": self.selected_k,
        }
        if include_features:
            payload["features"] = {
                name: round(value, 8) for name, value in sorted(self.feature_values.items())
            }
        return payload


class RankAwareAdaptiveKPolicy:
    """Inference-only policy; ground truth is intentionally absent from its API."""

    def __init__(
        self,
        model: AdaptiveKModel,
        objective: Literal["spec", "bellman"] = "bellman",
        include_features_in_log: bool = False,
        override_k10_q_margin_threshold: float | None = None,
    ) -> None:
        if objective not in {"spec", "bellman"}:
            raise ValueError("objective must be 'spec' or 'bellman'")
        self.model = model
        self.objective = objective
        self.include_features_in_log = include_features_in_log
        if override_k10_q_margin_threshold is not None:
            threshold = float(override_k10_q_margin_threshold)
            if not math.isfinite(threshold) or threshold < 0.0:
                raise ValueError("override K=10 Q-margin threshold must be finite and non-negative")
            override_k10_q_margin_threshold = threshold
        self.override_k10_q_margin_threshold = override_k10_q_margin_threshold
        self.last_decision: AdaptiveKDecision | None = None

    @classmethod
    def from_json(
        cls,
        path: str | Path,
        objective: Literal["spec", "bellman"] = "bellman",
        include_features_in_log: bool = False,
        override_k10_q_margin_threshold: float | None = None,
    ) -> "RankAwareAdaptiveKPolicy":
        return cls(
            AdaptiveKModel.from_json(path),
            objective,
            include_features_in_log,
            override_k10_q_margin_threshold,
        )

    def choose(
        self,
        candidates: Sequence[RankedCandidate],
        context: RankingContext,
        top_k: int = MAX_RANK,
    ) -> AdaptiveKDecision:
        options = tuple(k for k in ALLOWED_K if k <= max(0, int(top_k)))
        if not options:
            empty = AdaptiveKDecision(
                selected_k=0,
                objective=self.objective,
                cdf={},
                rank_masses={},
                miss_probability=1.0,
                continuation_values={},
                q_spec={},
                q_bellman={},
                feature_values=extract_rank_features(candidates, context),
                base_selected_k=0,
                override_guard_applied=False,
                override_q_margin_to_k10=None,
                override_q_margin_threshold=self.override_k10_q_margin_threshold,
                selection_reason="no_available_k",
            )
            self.last_decision = empty
            return empty

        features = extract_rank_features(candidates, context)
        prediction = self.model.predict(features, context.turn)
        continuation = {k: prediction.continuation_values[k] for k in options}
        q_spec, q_bellman = compute_q_values(
            prediction.rank_masses,
            context.turn,
            continuation,
            options,
            context.max_turns,
        )
        objective_values = q_spec if self.objective == "spec" else q_bellman
        # The literal specification weakly favors expanding K, including when
        # all remaining rank mass is zero; retain that behavior in its tie
        # break so the degeneracy is visible.  The Bellman policy prefers the
        # shorter list on a true utility tie.
        base_selected_k = max(
            options,
            key=(
                (lambda k: (objective_values[k], k))
                if self.objective == "spec"
                else (lambda k: (objective_values[k], -k))
            ),
        )
        selected_k, override_guard_applied, override_q_margin_to_k10 = (
            apply_override_k10_guard(
                base_selected_k,
                objective_values,
                is_override_turn=context.intent == "O1_OVERRIDE",
                q_margin_threshold=self.override_k10_q_margin_threshold,
            )
        )
        selection_reason = f"q_{self.objective}"
        if override_guard_applied:
            selection_reason = "override_uncertainty_fallback"
        decision = AdaptiveKDecision(
            selected_k=selected_k,
            objective=self.objective,
            cdf=prediction.cdf,
            rank_masses=prediction.rank_masses,
            miss_probability=prediction.miss_probability,
            continuation_values=continuation,
            q_spec=q_spec,
            q_bellman=q_bellman,
            feature_values=features,
            base_selected_k=base_selected_k,
            override_guard_applied=override_guard_applied,
            override_q_margin_to_k10=override_q_margin_to_k10,
            override_q_margin_threshold=self.override_k10_q_margin_threshold,
            selection_reason=selection_reason,
        )
        self.last_decision = decision
        return decision

    # ``select`` is a convenient policy-style alias for callers that use that
    # terminology; both methods have identical behavior.
    select = choose

    def last_log(self) -> dict[str, Any]:
        return (
            self.last_decision.as_log(self.include_features_in_log)
            if self.last_decision is not None
            else {}
        )


__all__ = [
    "ALLOWED_K",
    "FEATURE_NAMES",
    "MAX_RANK",
    "MAX_TURNS",
    "AdaptiveKDecision",
    "AdaptiveKModel",
    "LinearHead",
    "PiecewiseCalibrator",
    "RankAwareAdaptiveKPolicy",
    "RankPrediction",
    "RankedCandidate",
    "RankingContext",
    "apply_override_k10_guard",
    "cdf_to_rank_masses",
    "compute_q_values",
    "extract_rank_features",
    "project_monotone_cdf",
    "technical_utility",
    "vectorize_features",
]
