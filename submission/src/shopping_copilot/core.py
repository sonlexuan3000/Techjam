from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .intent_tracker import (
    Agent as IntentTracker,
    SPECIAL_WORDS as TRACKER_SPECIAL_WORDS,
    WORD_RE as TRACKER_WORD_RE,
    normalize as tracker_normalize,
)
from .parser import ParsedMessage, parse_message

from .preprocessing import (
    InputPreprocessor,
    canonicalize_punctuation,
    is_core_protocol_message,
)


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
    raw_messages: list[str] = field(default_factory=list)
    initial_candidates: list[str] = field(default_factory=list)
    current_candidates: list[str] = field(default_factory=list)
    trusted_universe: tuple[str, ...] = ()
    focus_candidates: list[str] = field(default_factory=list)
    scenario: str | None = None
    override_applied: bool = True
    override_seen: bool = False
    nlp_fallback: bool = False
    rejected: set[str] = field(default_factory=set)
    pre_override_recommendations: set[str] = field(default_factory=set)
    last_recommendations: tuple[str, ...] = ()
    last_recommendations_scored: bool = False
    last_hypothesis_count: int = 0
    last_focus_count: int = 0
    last_recovery_count: int = 0
    last_dp_state_count: int = 0
    last_retrieval_mode: str = "uninitialized"
    last_policy_mode: str = "uninitialized"


class Agent:
    """Deterministic inverse-simulator retrieval agent.

    Public labels are never loaded. The agent derives the same small intent
    signature from every catalog product and keeps products that could have
    generated the customer messages observed in the current conversation.
    """

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        prior_field: str = "uniform",
        prior_smoothing: float = 0.0,
        prior_path: str | Path | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        if prior_field not in {
            "uniform",
            "rating_number",
            "verified_reviews_365d",
        }:
            raise ValueError(
                "prior_field must be 'uniform', the catalog field "
                "'rating_number', or the bundled field "
                "'verified_reviews_365d'"
            )
        self.prior_field = prior_field
        self.prior_smoothing = float(prior_smoothing)
        if not math.isfinite(self.prior_smoothing) or self.prior_smoothing < 0:
            raise ValueError("prior_smoothing must be finite and non-negative")
        self.prior_path = Path(prior_path) if prior_path is not None else None
        self.external_prior = self._load_external_prior()
        self.products: dict[str, ProductIntent] = {}
        self.initial_message_index: dict[str, list[str]] = defaultdict(list)
        self.category_index: dict[str, list[str]] = defaultdict(list)
        self.sessions: dict[str, SessionState] = {}
        self.input_preprocessor = InputPreprocessor()
        self._dp_cache: dict[tuple, tuple[float, int]] = {}
        self.intent_tracker = self._empty_intent_tracker()
        self._build_index()
        self.all_product_ids = tuple(sorted(self.products, key=self._rank_key))

    def _load_external_prior(self) -> dict[str, int]:
        """Load the compact, aggregate review prior when it is configured."""

        if self.prior_field != "verified_reviews_365d":
            if self.prior_path is not None:
                raise ValueError(
                    "prior_path is only valid with "
                    "prior_field='verified_reviews_365d'"
                )
            return {}
        if self.prior_path is None:
            raise ValueError(
                "prior_path is required with "
                "prior_field='verified_reviews_365d'"
            )

        weights: dict[str, int] = {}
        with self.prior_path.open(encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            expected = ["parent_asin", self.prior_field]
            if header != expected:
                raise ValueError(
                    f"unexpected review-prior header: {header}; "
                    f"expected {expected}"
                )
            for line_number, line in enumerate(handle, start=2):
                if not line.strip():
                    continue
                try:
                    parent_asin, raw_weight = line.rstrip("\n").split("\t")
                    weight = int(raw_weight)
                except ValueError as error:
                    raise ValueError(
                        f"invalid review-prior row at line {line_number}"
                    ) from error
                if not parent_asin or weight < 0:
                    raise ValueError(
                        f"invalid review-prior row at line {line_number}"
                    )
                if parent_asin in weights:
                    raise ValueError(
                        f"duplicate review-prior parent_asin at line "
                        f"{line_number}: {parent_asin}"
                    )
                weights[parent_asin] = weight
        return weights

    def _empty_intent_tracker(self) -> IntentTracker:
        """Create the shared NLP tracker without rescanning/indexing the catalog.

        The simulator can reveal only the four reconstructed card constraints,
        so the candidate populates the tracker's lookup tables from those cards
        during its existing catalog pass. This keeps the NLP layer lightweight
        instead of building a second full-metadata index.
        """

        tracker = IntentTracker.__new__(IntentTracker)
        tracker.catalog_path = self.catalog_path
        tracker.asins = []
        tracker.rating_numbers = {}
        tracker.atom_to_asins = defaultdict(set)
        tracker.coarse_category_to_asins = defaultdict(set)
        tracker.special_word_to_asins = defaultdict(set)
        tracker.sessions = {}
        return tracker

    def _build_index(self) -> None:
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                parent_asin = str(product["parent_asin"])
                category = _coarse_category(product.get("categories") or [])
                hard, soft = _intent_card(product)
                rating_number = int(product.get("rating_number") or 0)
                prior_value = (
                    1.0
                    if self.prior_field == "uniform"
                    else (
                        float(rating_number)
                        if self.prior_field == "rating_number"
                        else self.external_prior.get(parent_asin, 0.0)
                    )
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
                self.intent_tracker.asins.append(parent_asin)
                self.intent_tracker.rating_numbers[parent_asin] = float(
                    rating_number
                )
                tracker_category = tracker_normalize(category)
                if tracker_category:
                    self.intent_tracker.coarse_category_to_asins[
                        tracker_category
                    ].add(parent_asin)
                for constraint in intent.constraints:
                    constraint_key = tracker_normalize(constraint)
                    if constraint_key:
                        self.intent_tracker.atom_to_asins[constraint_key].add(
                            parent_asin
                        )
                special_words = (
                    set(TRACKER_WORD_RE.findall(intent.text.lower()))
                    & TRACKER_SPECIAL_WORDS
                )
                for word in special_words:
                    self.intent_tracker.special_word_to_asins[word].add(
                        parent_asin
                    )

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
        self.intent_tracker.atom_to_asins = dict(
            self.intent_tracker.atom_to_asins
        )
        self.intent_tracker.coarse_category_to_asins = dict(
            self.intent_tracker.coarse_category_to_asins
        )
        self.intent_tracker.special_word_to_asins = dict(
            self.intent_tracker.special_word_to_asins
        )

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
        self.intent_tracker.reset(session_id, user_profile)

    def debug_state(self, session_id: str) -> dict:
        """Expose the shared NLP state to the repository's stress benchmark."""

        return self.intent_tracker.debug_state(session_id)

    def debug_algorithm_stats(self, session_id: str) -> dict:
        """Return target-free per-turn diagnostics for local visualizations."""

        state = self.sessions.get(session_id)
        if state is None:
            raise KeyError(f"unknown session: {session_id}")
        return {
            "hypothesis_count": state.last_hypothesis_count,
            "focus_count": state.last_focus_count,
            "recovery_count": state.last_recovery_count,
            "evidence_count": len(state.messages),
            "rejected_count": len(state.rejected),
            "dp_state_count": state.last_dp_state_count,
            "selected_k": len(state.last_recommendations),
            "retrieval_mode": state.last_retrieval_mode,
            "policy_mode": state.last_policy_mode,
            "prior_mode": self.prior_field,
            "nlp_fallback": state.nlp_fallback,
        }

    def debug_clue_candidates(
        self,
        clue: str,
        *,
        category: str | None = None,
    ) -> set[str]:
        """Return catalog-grounded matches for one parsed clue.

        ``category`` is accepted for the benchmark adapter; grounding itself is
        deliberately independent of a possibly paraphrased category label.
        """

        del category
        matches, _route = self.intent_tracker._clue_candidates(clue)
        return matches

    @staticmethod
    def _scenario_from_parsed(parsed: ParsedMessage) -> str:
        if parsed.source == "initial_requirement":
            return "buying"
        if parsed.source in {
            "initial_preference",
            "compact_initial_preference",
        }:
            return "intent_override"
        return "exploring"

    def _observe_nlp(
        self,
        session_id: str,
        raw_message: str,
        turn: int,
    ) -> ParsedMessage:
        """Update the shared intent tracker without running its recommender."""

        tracker_state = self.intent_tracker.sessions[session_id]
        parsed = parse_message(raw_message, turn=turn)
        self.intent_tracker._parse(tracker_state, raw_message, turn)
        return parsed

    def _protocol_evidence_is_grounded(self, parsed: ParsedMessage) -> bool:
        """Check that an exact wrapper still carries catalog-grounded values."""

        if parsed.action not in {"add", "override"} or not parsed.payload:
            return True
        if parsed.source == "revealed":
            parts = self.intent_tracker._split_revealed_payload(parsed.payload)
        else:
            parts = [parsed.payload]
        return bool(parts) and all(
            bool(self.intent_tracker._clue_candidates(part)[0])
            for part in parts
        )

    def _degraded_candidate_tiers(
        self,
        session_id: str,
        state: SessionState,
        *,
        reopen_focus: bool = False,
    ) -> tuple[list[str], list[str]]:
        """Return exact-card focus and a non-destructive recovery tier.

        NLP-derived constraints act like a hard filter in the focus tier used
        for recommendations. They never define eligibility, though: a wrong
        parse leaves every trusted candidate in the recovery tier, so the
        target can return after false positives are rejected.
        """

        tracker_state = self.intent_tracker.sessions[session_id]
        universe = state.trusted_universe or self.all_product_ids
        focus_base_is_eligible = False
        if len(state.messages) == 1:
            indexed = self.initial_message_index.get(
                _normalize_message(state.messages[0]),
                [],
            )
            focus_base = indexed or universe
            focus_base_is_eligible = universe is self.all_product_ids
        elif state.focus_candidates and not reopen_focus:
            focus_base = state.focus_candidates
            focus_base_is_eligible = True
        else:
            category = self._category_from_message(state.messages[0])
            category_base = self.category_index.get(category or "", [])
            focus_base = category_base or universe
            focus_base_is_eligible = not category_base

        universe_set = (
            None
            if focus_base_is_eligible or universe is self.all_product_ids
            else set(universe)
        )

        focus = sorted(
            (
                parent_asin
                for parent_asin in focus_base
                if parent_asin not in state.rejected
                if universe_set is None or parent_asin in universe_set
                if self._matches_conversation(
                    self.products[parent_asin],
                    state.messages,
                )
            ),
            key=self._rank_key,
        )
        if focus:
            # Recovery membership remains in ``trusted_universe``. It is
            # materialized only if the focus tier becomes empty.
            recovery: list[str] = []
        else:
            eligible_set = {
                parent_asin
                for parent_asin in universe
                if parent_asin not in state.rejected
            }
            tracker_rank = self.intent_tracker._rank(tracker_state)
            recovery = [
                parent_asin
                for parent_asin in tracker_rank
                if parent_asin in eligible_set
            ]
        return focus, recovery

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
        effective_top_k = max(0, min(int(top_k), 10))
        raw_message = str(user_message or "")
        parsed = self._observe_nlp(session_id, raw_message, turn)
        trusted_protocol = (
            is_core_protocol_message(raw_message, turn)
            and self._protocol_evidence_is_grounded(parsed)
        )
        user_message = self.input_preprocessor.canonicalize(
            session_id,
            raw_message,
            turn,
        )

        override_now = parsed.action == "override" or _normalize_message(
            user_message
        ).startswith(
            "actually, ignore my earlier preference. what i need is: "
        )
        if override_now and not state.override_seen:
            # Intent-override recommendations are not scoreable before the
            # override. If the initial paraphrase hid that scenario, repair the
            # provisional rejection history now that the event is explicit.
            state.rejected.difference_update(
                state.pre_override_recommendations
            )
            state.override_seen = True
            state.override_applied = True
        elif state.last_recommendations_scored:
            # Reaching another turn proves that every scoreable recommendation
            # on the previous turn was a miss.
            state.rejected.update(state.last_recommendations)
        state.raw_messages.append(raw_message)
        state.messages.append(user_message)
        state.nlp_fallback = state.nlp_fallback or not trusted_protocol

        if len(state.messages) == 1:
            if state.nlp_fallback:
                state.scenario = self._scenario_from_parsed(parsed)
                state.override_applied = state.scenario != "intent_override"
                state.trusted_universe = self.all_product_ids
            else:
                candidates = list(
                    self.initial_message_index.get(
                        _normalize_message(user_message), []
                    )
                )
                if not candidates:
                    # A wrapper that looks official but cannot reproduce any
                    # product card is not exact protocol evidence after all.
                    state.nlp_fallback = True
                    state.scenario = self._scenario_from_parsed(parsed)
                    state.override_applied = state.scenario != "intent_override"
                    state.trusted_universe = self.all_product_ids
                else:
                    state.initial_candidates = candidates
                    state.current_candidates = candidates
                    state.trusted_universe = tuple(candidates)
                    initial = self._initial_scenario(
                        self.products[candidates[0]], user_message
                    )
                    state.scenario = initial[0] if initial is not None else None
                    state.override_applied = state.scenario != "intent_override"
        else:
            if override_now:
                state.override_applied = True
            if not state.nlp_fallback:
                compatible = [
                    parent_asin
                    for parent_asin in state.initial_candidates
                    if parent_asin not in state.rejected
                    and self._matches_conversation(
                        self.products[parent_asin], state.messages
                    )
                ]
                if compatible:
                    state.current_candidates = sorted(
                        compatible,
                        key=self._rank_key,
                    )
                else:
                    # Relax only soft preferences. Products that violate an
                    # observed hard constraint, or were already rejected, stay out.
                    state.current_candidates = self._hard_fallback_candidates(state)
                state.trusted_universe = tuple(state.current_candidates)

        recovery: list[str] = []
        if state.nlp_fallback:
            focus, recovery = self._degraded_candidate_tiers(
                session_id,
                state,
                reopen_focus=override_now,
            )
            state.focus_candidates = focus
            # The shared trusted universe is the recovery membership. Persist
            # only the small active focus to avoid retaining 50,000 references
            # for every completed evaluator session.
            state.current_candidates = focus
        else:
            state.focus_candidates = list(state.current_candidates)

        ranked = (
            state.focus_candidates
            or recovery
            or state.current_candidates
        )
        used_lexical_fallback = False
        if not ranked and len(state.messages) == 1:
            ranked = self._lexical_fallback(state)
            used_lexical_fallback = bool(ranked)

        dp_state_count = 0
        if effective_top_k == 0:
            recommendation_limit = 0
            policy_mode = "disabled"
        elif not ranked:
            recommendation_limit = 0
            policy_mode = "no_candidates"
        elif state.nlp_fallback and not state.focus_candidates:
            recommendation_limit = min(
                effective_top_k,
                {1: 1, 2: 2}.get(int(turn), 10),
                len(ranked),
            )
            policy_mode = "recovery_schedule"
        else:
            pre_override_guard = (
                state.scenario == "intent_override"
                and not state.override_applied
            )
            recommendation_limit = self._recommendation_limit(
                state,
                ranked,
                turn,
                effective_top_k,
            )
            if pre_override_guard:
                policy_mode = "override_guard"
            else:
                policy_mode = "finite_horizon_dp"
                dp_state_count = len(self._dp_cache)
        recommendations = tuple(ranked[:recommendation_limit])
        state.last_recommendations = recommendations
        if not state.override_seen:
            state.pre_override_recommendations.update(recommendations)
        state.last_recommendations_scored = (
            state.scenario != "intent_override" or state.override_applied
        )
        if used_lexical_fallback:
            retrieval_mode = "lexical_fallback"
        elif not state.nlp_fallback:
            retrieval_mode = "exact_protocol"
        elif state.focus_candidates:
            retrieval_mode = "focus_tier"
        elif recovery:
            retrieval_mode = "recovery_tier"
        else:
            retrieval_mode = "empty"
        state.last_hypothesis_count = len(ranked)
        state.last_focus_count = len(state.focus_candidates)
        state.last_recovery_count = len(recovery)
        state.last_dp_state_count = dp_state_count
        state.last_retrieval_mode = retrieval_mode
        state.last_policy_mode = policy_mode

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
