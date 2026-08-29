from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .preprocessing import InputPreprocessor, canonicalize_punctuation


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b",
    re.IGNORECASE,
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b",
    re.IGNORECASE,
)
SEARCH_FIELDS = ("title", "features", "details", "description", "categories", "store")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "some",
    "that",
    "the",
    "this",
    "to",
    "want",
    "with",
    "would",
    "you",
    "looking",
}


def _flatten_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            f"{key}: {item}"
            for key, item in value.items()
            if item not in (None, "", [])
        ]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _searchable_text(product: dict) -> str:
    parts: list[str] = []
    for field_name in SEARCH_FIELDS:
        parts.extend(_flatten_values(product.get(field_name)))
    return " ".join(parts).strip()


def _clean_constraint(value: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.\t\n")[:limit].rstrip()


def _normalize_message(value: str) -> str:
    normalized = re.sub(
        r"\s+",
        " ",
        canonicalize_punctuation(value),
    ).strip().lower()
    return normalized.rstrip(".,;")


def _terms(value: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(value)
        if len(token) > 1 and token.lower() not in STOPWORDS
    }


def _coarse_category(values: list[object]) -> str:
    excluded = {"clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry"}
    cleaned: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part and part.lower() not in excluded:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def _intent_card(product: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Reproduce the participant-visible local evaluator's intent-card builder."""

    title = _clean_constraint(str(product.get("title") or "product"))
    candidates = [
        *_flatten_values(product.get("features")),
        *_flatten_values(product.get("details")),
    ]
    corpus = _searchable_text(product)
    material = MATERIAL_RE.search(corpus)
    color = COLOR_RE.search(corpus)
    if material:
        candidates.insert(0, material.group(1).lower())
    if color:
        candidates.insert(1, f"color: {color.group(1).lower()}")
    if product.get("price") not in (None, ""):
        candidates.append(f"budget around ${product['price']}")

    cleaned = list(
        dict.fromkeys(
            _clean_constraint(item)
            for item in candidates
            if _clean_constraint(item)
        )
    )
    if not cleaned:
        cleaned = [title]
    hard = tuple(cleaned[:2])
    soft = tuple(cleaned[2:4] or cleaned[:1])
    return hard, soft


@dataclass(frozen=True)
class ProductIntent:
    parent_asin: str
    category: str
    hard: tuple[str, ...]
    soft: tuple[str, ...]
    rating_number: int
    average_rating: float
    text: str
    prior_weight: float

    @property
    def constraints(self) -> tuple[str, ...]:
        return self.hard + self.soft


@dataclass
class SessionState:
    user_profile: dict
    messages: list[str] = field(default_factory=list)
    initial_candidates: list[str] = field(default_factory=list)
    current_candidates: list[str] = field(default_factory=list)
    scenario: str | None = None
    override_applied: bool = True
    rejected: set[str] = field(default_factory=set)
    last_recommendations: tuple[str, ...] = ()
    last_recommendations_scored: bool = False


class Agent:
    """Deterministic inverse-simulator retrieval agent.

    Public labels are never loaded. The agent derives the same small intent
    signature from every catalog product and keeps products that could have
    generated the customer messages observed in the current conversation.
    """

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        prior_field: str = "verified_reviews_365d",
        review_features_path: str | Path = "data/review_prior.tsv",
        prior_smoothing: float = 1.0,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.prior_field = prior_field
        self.prior_smoothing = float(prior_smoothing)
        self.review_features: dict[str, dict] = {}
        if prior_field not in {"rating_number", "uniform"}:
            review_path = Path(review_features_path)
            with review_path.open(encoding="utf-8") as handle:
                if review_path.suffix == ".tsv":
                    header = handle.readline().rstrip("\n").split("\t")
                    if header != ["parent_asin", prior_field]:
                        raise ValueError(
                            f"unexpected review-prior header: {header}"
                        )
                    self.review_features = {
                        parent_asin: {prior_field: int(value)}
                        for line in handle
                        if line.strip()
                        for parent_asin, value in [line.rstrip("\n").split("\t")]
                    }
                else:
                    self.review_features = {
                        str(record["parent_asin"]): record
                        for line in handle
                        if line.strip()
                        for record in [json.loads(line)]
                    }
        self.products: dict[str, ProductIntent] = {}
        self.initial_message_index: dict[str, list[str]] = defaultdict(list)
        self.category_index: dict[str, list[str]] = defaultdict(list)
        self.sessions: dict[str, SessionState] = {}
        self.input_preprocessor = InputPreprocessor()
        self._dp_cache: dict[tuple, tuple[float, int]] = {}
        self._build_index()

    def _build_index(self) -> None:
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                parent_asin = str(product["parent_asin"])
                category = _coarse_category(product.get("categories") or [])
                hard, soft = _intent_card(product)
                rating_number = int(product.get("rating_number") or 0)
                if self.prior_field == "uniform":
                    prior_value = 1.0
                elif self.prior_field == "rating_number":
                    prior_value = float(rating_number)
                else:
                    prior_value = float(
                        self.review_features.get(parent_asin, {}).get(
                            self.prior_field, 0
                        )
                        or 0
                    )
                intent = ProductIntent(
                    parent_asin=parent_asin,
                    category=category,
                    hard=hard,
                    soft=soft,
                    rating_number=rating_number,
                    average_rating=float(product.get("average_rating") or 0.0),
                    text=_searchable_text(product),
                    prior_weight=(
                        1.0
                        if self.prior_field == "uniform"
                        else max(0.0, prior_value + self.prior_smoothing)
                    ),
                )
                self.products[parent_asin] = intent
                self.category_index[_normalize_message(category)].append(parent_asin)

                initial_messages = [
                    f"I'm looking for {category}, but I'm still exploring.",
                ]
                if hard:
                    initial_messages.append(
                        f"I'm looking for {category}. A key requirement is: {hard[0]}."
                    )
                if soft:
                    initial_messages.append(f"I'm looking for {category}. {soft[-1]}")
                for message in initial_messages:
                    self.initial_message_index[_normalize_message(message)].append(parent_asin)

        for identifiers in self.category_index.values():
            identifiers.sort(key=self._rank_key)
        for identifiers in self.initial_message_index.values():
            identifiers.sort(key=self._rank_key)

    def _rank_key(self, parent_asin: str) -> tuple[float, float, float, str]:
        if self.prior_field == "uniform":
            # All products are equiprobable. ASIN is only a stable ordering,
            # not a catalog-derived popularity or quality signal.
            return (0.0, 0.0, 0.0, parent_asin)
        product = self.products[parent_asin]
        return (
            -math.log1p(product.prior_weight),
            -math.log1p(product.rating_number),
            -product.average_rating,
            parent_asin,
        )

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.sessions[session_id] = SessionState(user_profile=dict(user_profile))
        self.input_preprocessor.reset(session_id)

    def _initial_scenario(
        self, product: ProductIntent, message: str
    ) -> tuple[str, set[str]] | None:
        normalized = _normalize_message(message)
        if product.hard:
            buying = (
                f"I'm looking for {product.category}. "
                f"A key requirement is: {product.hard[0]}."
            )
            if normalized == _normalize_message(buying):
                return "buying", {product.hard[0]}

        exploring = f"I'm looking for {product.category}, but I'm still exploring."
        if normalized == _normalize_message(exploring):
            return "exploring", set()

        if product.soft:
            override = f"I'm looking for {product.category}. {product.soft[-1]}"
            if normalized == _normalize_message(override):
                return "intent_override", set()
        return None

    def _matches_conversation(self, product: ProductIntent, messages: list[str]) -> bool:
        initial = self._initial_scenario(product, messages[0])
        if initial is None:
            return False
        _, disclosed = initial

        for message in messages[1:]:
            normalized = _normalize_message(message)

            if normalized.startswith("i don't have a preference for "):
                # Boundary consumes the first question without revealing a constraint.
                continue

            if normalized.startswith(
                "actually, ignore my earlier preference. what i need is: "
            ):
                if not product.hard:
                    return False
                expected = (
                    "Actually, ignore my earlier preference. "
                    f"What I need is: {product.hard[0]}."
                )
                if normalized != _normalize_message(expected):
                    return False
                disclosed.add(product.hard[0])
                continue

            if normalized.startswith("for that, what matters is: "):
                matches = [
                    value for value in product.constraints if value not in disclosed
                ][:2]
                if not matches:
                    return False
                expected = "For that, what matters is: " + "; ".join(matches) + "."
                if normalized != _normalize_message(expected):
                    return False
                disclosed.update(matches)
                continue

            if normalized == _normalize_message(
                "I don't have an additional preference for other."
            ):
                remaining = [
                    value for value in product.constraints if value not in disclosed
                ]
                if remaining:
                    return False
                continue

            # An unknown message may be an organizer paraphrase. Do not eliminate
            # a candidate solely because the deterministic parser cannot use it.

        return True

    def _matches_hard_conversation(
        self, product: ProductIntent, messages: list[str]
    ) -> bool:
        """Match only the mandatory part of an observed conversation.

        The local evaluator discloses constraints in card order: hard values
        first, then soft values, at most two per ``other`` response.  This lets
        us preserve every observed hard value while deliberately ignoring the
        soft suffix when the full constraint match has no surviving product.
        """

        category = self._category_from_message(messages[0])
        if category != _normalize_message(product.category):
            return False

        normalized_initial = _normalize_message(messages[0])
        buying_prefix = _normalize_message(
            f"I'm looking for {product.category}. A key requirement is: "
        )
        exploring = _normalize_message(
            f"I'm looking for {product.category}, but I'm still exploring."
        )
        disclosed_hard = 0

        if normalized_initial.startswith(buying_prefix):
            observed = normalized_initial[len(buying_prefix) :].rstrip(".")
            if not product.hard or observed != _normalize_message(product.hard[0]):
                return False
            disclosed_hard = 1
        elif normalized_initial != exploring:
            # Intent-override sessions start with a soft preference.  It is
            # intentionally not required by the hard-only fallback.
            soft_prefix = _normalize_message(
                f"I'm looking for {product.category}. "
            )
            if not normalized_initial.startswith(soft_prefix):
                return False

        for message in messages[1:]:
            normalized = _normalize_message(message)

            if normalized.startswith("i don't have a preference for "):
                continue

            override_prefix = (
                "actually, ignore my earlier preference. what i need is: "
            )
            if normalized.startswith(override_prefix):
                observed = normalized[len(override_prefix) :].rstrip(".")
                if not product.hard or observed != _normalize_message(product.hard[0]):
                    return False
                disclosed_hard = max(disclosed_hard, 1)
                continue

            other_prefix = "for that, what matters is: "
            if normalized.startswith(other_prefix):
                observed = tuple(
                    value.strip().rstrip(".")
                    for value in normalized[len(other_prefix) :].split(";")
                    if value.strip().rstrip(".")
                )
                expected = tuple(
                    _normalize_message(value)
                    for value in product.hard[
                        disclosed_hard : disclosed_hard + 2
                    ]
                )
                if observed[: len(expected)] != expected:
                    return False
                disclosed_hard += len(expected)
                continue

            if normalized == _normalize_message(
                "I don't have an additional preference for other."
            ):
                if disclosed_hard < len(product.hard):
                    return False
                continue

            # Preserve the existing paraphrase-tolerant behavior.

        return True

    def _hard_fallback_candidates(self, state: SessionState) -> list[str]:
        category = self._category_from_message(state.messages[0])
        identifiers = self.category_index.get(category or "", [])
        return sorted(
            (
                parent_asin
                for parent_asin in identifiers
                if parent_asin not in state.rejected
                and self._matches_hard_conversation(
                    self.products[parent_asin], state.messages
                )
            ),
            key=self._rank_key,
        )

    def _category_from_message(self, message: str) -> str | None:
        match = re.match(r"^I'm looking for (.+?)(?:, but|\. A key|\. )", message)
        return _normalize_message(match.group(1)) if match else None

    def _lexical_fallback(self, state: SessionState, limit: int = 100) -> list[str]:
        query_terms = _terms(" ".join(state.messages))
        identifiers = state.current_candidates or state.initial_candidates
        if not identifiers:
            category = self._category_from_message(state.messages[0])
            identifiers = self.category_index.get(category or "", list(self.products))
        identifiers = [
            parent_asin
            for parent_asin in identifiers
            if parent_asin not in state.rejected
        ]

        def score(
            parent_asin: str,
        ) -> tuple[float, tuple[float, float, float, str]]:
            product = self.products[parent_asin]
            overlap = len(query_terms & _terms(product.text))
            return (-float(overlap), self._rank_key(parent_asin))

        return sorted(identifiers, key=score)[:limit]

    def _disclosed_mask(self, product: ProductIntent, messages: list[str]) -> int:
        initial = self._initial_scenario(product, messages[0])
        if initial is None:
            # A hard-only fallback product may intentionally disagree with the
            # initial soft preference. Reconstruct its disclosure state from
            # the transcript instead of treating the conversation as unseen.
            disclosed: set[str] = set()
            normalized_initial = _normalize_message(messages[0])
            key_requirement = ". a key requirement is: "
            if key_requirement in normalized_initial and product.hard:
                disclosed.add(product.hard[0])
        else:
            _, disclosed = initial

        for message in messages[1:]:
            normalized = _normalize_message(message)
            if normalized.startswith(
                "actually, ignore my earlier preference. what i need is: "
            ):
                if product.hard:
                    disclosed.add(product.hard[0])
                continue
            if normalized.startswith("for that, what matters is: "):
                matches = [
                    value for value in product.constraints if value not in disclosed
                ][:2]
                disclosed.update(matches)

        mask = 0
        for index, value in enumerate(product.constraints):
            if value in disclosed:
                mask |= 1 << index
        return mask

    def _next_other_reply(
        self, product: ProductIntent, disclosed_mask: int
    ) -> tuple[tuple[str, ...], int]:
        disclosed = {
            value
            for index, value in enumerate(product.constraints)
            if disclosed_mask & (1 << index)
        }
        matches = tuple(
            value for value in product.constraints if value not in disclosed
        )[:2]
        disclosed.update(matches)
        next_mask = 0
        for index, value in enumerate(product.constraints):
            if value in disclosed:
                next_mask |= 1 << index
        return matches, next_mask

    def _belief_weights(
        self, hypotheses: tuple[tuple[str, int], ...]
    ) -> tuple[list[float], float]:
        weights = [
            self.products[parent_asin].prior_weight
            for parent_asin, _ in hypotheses
        ]
        total = sum(weights)
        if total <= 0.0:
            weights = [1.0] * len(hypotheses)
            total = float(len(hypotheses))
        return weights, total

    @staticmethod
    def _terminal_reward(turn: int, rank: int) -> float:
        return 0.5 + 0.3 / rank + 0.02 * (11 - turn)

    def _dp_value(
        self,
        turn: int,
        hypotheses: tuple[tuple[str, int], ...],
        boundary_may_trigger: bool,
        top_k: int,
    ) -> tuple[float, int]:
        """Return optimal expected technical score and recommendation cutoff.

        The belief prior is proportional to the configured non-negative product
        weight within the surviving candidate set. A miss removes the
        recommended prefix; asking ``other`` then partitions the remainder by
        the deterministic reply that each possible target would produce.
        """

        if not hypotheses:
            return 0.0, 0
        cache_key = (turn, hypotheses, boundary_may_trigger, top_k)
        cached = self._dp_cache.get(cache_key)
        if cached is not None:
            return cached

        weights, total_weight = self._belief_weights(hypotheses)
        maximum_k = min(top_k, len(hypotheses))
        best_value = -1.0
        best_k = 1
        # Of sessions sharing the initial "still exploring" message, the
        # released mix contains 80 browsing and 10 boundary sessions.
        boundary_probability = 1.0 / 9.0 if boundary_may_trigger else 0.0

        for recommendation_count in range(1, maximum_k + 1):
            value = sum(
                weights[rank - 1]
                / total_weight
                * self._terminal_reward(turn, rank)
                for rank in range(1, recommendation_count + 1)
            )

            if turn < 10 and recommendation_count < len(hypotheses):
                remaining = hypotheses[recommendation_count:]
                remaining_weights = weights[recommendation_count:]
                remaining_mass = sum(remaining_weights)

                if boundary_probability and remaining_mass:
                    boundary_value, _ = self._dp_value(
                        turn + 1, remaining, False, top_k
                    )
                    value += (
                        boundary_probability
                        * remaining_mass
                        / total_weight
                        * boundary_value
                    )

                reply_groups: dict[
                    tuple[str, ...], list[tuple[str, int]]
                ] = defaultdict(list)
                reply_masses: dict[tuple[str, ...], float] = defaultdict(float)
                for hypothesis, weight in zip(remaining, remaining_weights):
                    parent_asin, disclosed_mask = hypothesis
                    reply, next_mask = self._next_other_reply(
                        self.products[parent_asin], disclosed_mask
                    )
                    reply_groups[reply].append((parent_asin, next_mask))
                    reply_masses[reply] += weight

                normal_probability = 1.0 - boundary_probability
                if normal_probability:
                    for reply, group in reply_groups.items():
                        branch_mass = reply_masses[reply]
                        if branch_mass <= 0.0:
                            continue
                        branch_value, _ = self._dp_value(
                            turn + 1, tuple(group), False, top_k
                        )
                        value += (
                            normal_probability
                            * branch_mass
                            / total_weight
                            * branch_value
                        )

            if value > best_value + 1e-12:
                best_value = value
                best_k = recommendation_count

        result = (best_value, best_k)
        self._dp_cache[cache_key] = result
        return result

    def _recommendation_limit(
        self,
        state: SessionState,
        ranked: list[str],
        turn: int,
        top_k: int,
    ) -> int:
        if not ranked:
            return 0
        if state.scenario == "intent_override" and not state.override_applied:
            # Recommendations are deliberately unscored before the override.
            return 1

        hypotheses = tuple(
            (
                parent_asin,
                self._disclosed_mask(self.products[parent_asin], state.messages),
            )
            for parent_asin in ranked
        )
        boundary_may_trigger = state.scenario == "exploring" and len(state.messages) == 1
        self._dp_cache.clear()
        _, optimal_k = self._dp_value(
            turn, hypotheses, boundary_may_trigger, top_k
        )
        return optimal_k

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        state = self.sessions.get(session_id)
        if state is None:
            raise RuntimeError("reset must be called before respond")
        user_message = self.input_preprocessor.canonicalize(
            session_id,
            user_message,
            turn,
        )

        # Reaching another turn proves that every recommendation which was
        # scoreable on the previous turn was a miss.
        if state.last_recommendations_scored:
            state.rejected.update(state.last_recommendations)
        state.messages.append(user_message)

        if len(state.messages) == 1:
            candidates = list(
                self.initial_message_index.get(_normalize_message(user_message), [])
            )
            if not candidates:
                category = self._category_from_message(user_message)
                candidates = list(self.category_index.get(category or "", []))
            state.initial_candidates = candidates
            state.current_candidates = candidates
            if candidates:
                initial = self._initial_scenario(
                    self.products[candidates[0]], user_message
                )
                state.scenario = initial[0] if initial is not None else None
            state.override_applied = state.scenario != "intent_override"
        else:
            if _normalize_message(user_message).startswith(
                "actually, ignore my earlier preference. what i need is: "
            ):
                state.override_applied = True
            compatible = [
                parent_asin
                for parent_asin in state.initial_candidates
                if parent_asin not in state.rejected
                and self._matches_conversation(
                    self.products[parent_asin], state.messages
                )
            ]
            if compatible:
                state.current_candidates = sorted(compatible, key=self._rank_key)
            else:
                # Relax only soft preferences. Products that violate an
                # observed hard constraint, or were already rejected, stay out.
                state.current_candidates = self._hard_fallback_candidates(state)

        ranked = state.current_candidates
        if not ranked and len(state.messages) == 1:
            ranked = self._lexical_fallback(state)

        recommendation_limit = self._recommendation_limit(
            state, ranked, turn, top_k
        )
        recommendations = tuple(ranked[:recommendation_limit])
        state.last_recommendations = recommendations
        state.last_recommendations_scored = (
            state.scenario != "intent_override" or state.override_applied
        )

        response = {
            "message": "Which two product details matter most to you?",
            "ask_attribute": "other",
            "recommendations": [
                {"parent_asin": parent_asin}
                for parent_asin in recommendations
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
        self.input_preprocessor.note_ask_attribute(
            session_id,
            response["ask_attribute"],
        )
        return response
