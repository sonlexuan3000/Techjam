from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

try:
    from .adaptive_k import (
        ALLOWED_K,
        RankAwareAdaptiveKPolicy,
        RankedCandidate,
        RankingContext,
        extract_rank_features,
    )
except ImportError:  # Support loading this file directly during local experiments.
    from adaptive_k import (  # type: ignore[no-redef]
        ALLOWED_K,
        RankAwareAdaptiveKPolicy,
        RankedCandidate,
        RankingContext,
        extract_rank_features,
    )


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
IntentLabel = Literal[
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
]
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "those", "options", "not", "quite", "right", "yet", "ask", "about", "one",
    "specific", "attribute", "for", "what", "matters", "need", "actually",
    "ignore", "earlier", "preference", "additional", "have", "please", "your",
    "judgment", "still", "exploring", "key", "requirement",
}


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _normalize(value: object) -> str:
    return " ".join(TOKEN_RE.findall(_text(value).lower()))


def _price(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Constraint:
    text: str
    terms: tuple[str, ...]
    turn: int
    kind: Literal["hard", "soft", "category", "exclusion"]
    attribute: str


@dataclass
class ProductDocument:
    parent_asin: str
    counts: Counter[str]
    fields: dict[str, str]
    rating_confidence: float
    price: float | None


@dataclass
class SessionState:
    profile_terms: list[str] = field(default_factory=list)
    query_parts: list[str] = field(default_factory=list)
    recommended: set[str] = field(default_factory=set)
    mode: Literal["buying", "browsing"] = "browsing"
    intent: IntentLabel = "R1_VERY_BROAD_BROWSING"
    intent_history: list[IntentLabel] = field(default_factory=list)
    evidence_turns: int = 0
    unavailable_attributes: set[str] = field(default_factory=set)
    constraints: list[Constraint] = field(default_factory=list)
    preference_count: int = 0


class Agent:
    """Dynamic-intent conversational retriever with no LLM dependency."""

    DEFAULT_RERANK_WEIGHTS = {
        "hard": 1.75,
        "semantic": 1.0,
        "lexical": 0.75,
        "soft": 0.5,
        "recent": 2.0,
        "exclusion": 2.0,
    }

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        rerank_weights: dict[str, float] | None = None,
        *,
        adaptive_k_model_path: str | Path | None = None,
        adaptive_k_objective: Literal["spec", "bellman"] = "bellman",
        override_k10_q_margin_threshold: float | None = None,
        fixed_k: int | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.rerank_weights = dict(self.DEFAULT_RERANK_WEIGHTS)
        if rerank_weights:
            unknown = set(rerank_weights) - set(self.rerank_weights)
            if unknown:
                raise ValueError(f"unknown rerank weights: {sorted(unknown)}")
            self.rerank_weights.update(
                (name, float(value)) for name, value in rerank_weights.items()
            )
        if fixed_k is not None and fixed_k not in ALLOWED_K:
            raise ValueError(f"fixed_k must be one of {ALLOWED_K}")
        if fixed_k is not None and adaptive_k_model_path is not None:
            raise ValueError("fixed_k and adaptive_k_model_path are mutually exclusive")
        self.fixed_k = fixed_k
        self._adaptive_k_policy = (
            RankAwareAdaptiveKPolicy.from_json(
                adaptive_k_model_path,
                objective=adaptive_k_objective,
                override_k10_q_margin_threshold=override_k10_q_margin_threshold,
            )
            if adaptive_k_model_path is not None
            else None
        )
        self.connection = sqlite3.connect(":memory:")
        self._sessions: dict[str, SessionState] = {}
        self._documents: list[ProductDocument] = []
        self._document_frequency: Counter[str] = Counter()
        self._postings: dict[str, list[int]] = defaultdict(list)
        # Populated by _rank for offline coefficient tuning.  Keeping this as
        # debug-only state does not change the Agent response contract.
        self.last_ranking_components: list[tuple[str, int, float, dict[str, float]]] = []
        self.last_recommendation_policy: dict[str, Any] = {}
        # ``ranked_ids`` is deliberately target-free.  The offline development
        # collector joins it with a hidden label after ``respond`` returns.
        self.last_rank_state: dict[str, Any] = {}
        self.last_adaptive_k_log: dict[str, Any] = {}
        self.adaptive_k_logs: list[dict[str, Any]] = []
        # Consecutive late turns frequently carry no new evidence.  Cache only
        # the most recent immutable raw scoring result; recommendation filtering
        # and K selection still run on every turn.
        self._last_score_cache_key: tuple[Any, ...] | None = None
        self._last_score_cache: tuple[
            list[tuple[float, float, str]],
            dict[str, dict[str, float]],
            list[tuple[str, int, float, dict[str, float]]],
        ] | None = None
        self._build_index()

    def _build_index(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, str, str, str, str, str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                searchable = " ".join(
                    _text(product.get(field))
                    for field in ("title", "categories", "features", "details", "store", "description")
                )
                counts = Counter(_terms(searchable))
                document_index = len(self._documents)
                average_rating = float(product.get("average_rating") or 0.0)
                rating_number = max(0, int(product.get("rating_number") or 0))
                document = ProductDocument(
                    parent_asin=str(product["parent_asin"]),
                    counts=counts,
                    fields={
                        field: _normalize(product.get(field))
                        for field in ("title", "categories", "features", "details", "store", "description")
                    },
                    rating_confidence=(average_rating / 5.0) * math.log1p(rating_number),
                    price=_price(product.get("price")),
                )
                self._documents.append(document)
                self._document_frequency.update(counts.keys())
                for term in counts:
                    self._postings[term].append(document_index)
                batch.append(
                    (
                        str(product["parent_asin"]),
                        _text(product.get("title")),
                        _text(product.get("categories")),
                        _text(product.get("features")),
                        _text(product.get("details")),
                        _text(product.get("store")),
                        _text(product.get("description")),
                    )
                )
                if len(batch) >= 1000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        self.connection.commit()

    def reset(self, session_id: str, user_profile: dict) -> None:
        tags = user_profile.get("preference_tags") or []
        self._sessions[session_id] = SessionState(profile_terms=_terms(_text(tags)))

    @staticmethod
    def _classify_turn(state: SessionState, message: str, turn: int) -> IntentLabel:
        """Map each turn to an actionable intent state, not a permanent user class."""
        lowered = message.lower()
        terms = _terms(message)
        if re.search(r"\bactually\b.*\bignore\b", message, re.I):
            return "O1_OVERRIDE"
        if "don't have a preference" in lowered or "use your judgment" in lowered:
            return "X1_NO_PREFERENCE"
        if "don't have an additional preference" in lowered or "not quite right yet" in lowered:
            return "X2_MISSING_ATTRIBUTE"
        if re.search(r"\b(?:something for|suitable for|works for|use it for)\b", lowered):
            return "B3_SEMANTIC_BUYING"
        if turn == 1 and ("still exploring" in lowered or len(terms) <= 3):
            return "R1_VERY_BROAD_BROWSING"
        if turn == 1 and "key requirement" in lowered:
            # Long copied feature text is exact buying; short values such as
            # colors and materials are structured attribute buying.
            return "B1_EXACT_BUYING" if len(terms) >= 8 else "B2_ATTRIBUTE_BUYING"
        if state.mode == "browsing" and state.evidence_turns == 0:
            return "R2_PREFERENCE_BROWSING"
        if state.mode == "browsing":
            return "R3_BROWSING_TO_BUYING"
        return "O2_NON_CONFLICTING_UPDATE"

    @staticmethod
    def _constraint_attribute(text: str) -> str:
        lowered = text.lower()
        if re.search(r"\b(?:black|white|blue|red|pink|green|brown|gr[ae]y|purple|yellow|orange)\b", lowered):
            return "color"
        if re.search(r"\b(?:cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b", lowered):
            return "material"
        if re.search(r"(?:\$|\b(?:budget|under|below|less than)\b)\s*\d*", lowered):
            return "budget"
        if re.search(r"\b(?:size|small|medium|large|wide|narrow|xl|xxl)\b", lowered):
            return "size"
        if re.search(r"\b(?:brand|manufacturer|store)\b", lowered):
            return "brand"
        if re.search(r"\b(?:style|fit|sleeve|neck|closure)\b", lowered):
            return "style"
        return "feature"

    @staticmethod
    def _update_state(state: SessionState, label: IntentLabel, message: str, turn: int) -> None:
        state.intent = label
        state.intent_history.append(label)
        if label in {"B1_EXACT_BUYING", "B2_ATTRIBUTE_BUYING", "B3_SEMANTIC_BUYING"}:
            state.mode = "buying"
        elif label == "R1_VERY_BROAD_BROWSING":
            state.mode = "browsing"
        elif label == "R3_BROWSING_TO_BUYING":
            state.mode = "buying"
        elif label == "O1_OVERRIDE":
            # Previously displayed products must be eligible under the revised
            # intent. Query evidence is retained as low-cost recall context;
            # the explicit replacement is appended and therefore weighted too.
            state.recommended.clear()
            state.mode = "buying"
        elif label in {"X1_NO_PREFERENCE", "X2_MISSING_ATTRIBUTE"}:
            state.unavailable_attributes.add("other")

        if label not in {"R1_VERY_BROAD_BROWSING", "X1_NO_PREFERENCE", "X2_MISSING_ATTRIBUTE"}:
            state.evidence_turns += 1

        if label not in {"X1_NO_PREFERENCE", "X2_MISSING_ATTRIBUTE"}:
            state.query_parts.append(message)
            chunks: list[tuple[str, Literal["preference", "category", "negative"]]] = []
            if ":" in message:
                chunks.extend((chunk, "preference") for chunk in message.rsplit(":", 1)[1].split(";"))
            category_match = re.search(r"\blooking for\s+(.+?)(?:,|\.|$)", message, re.I)
            if category_match:
                chunks.append((category_match.group(1), "category"))
            chunks.extend(
                (match.group(1), "negative")
                for match in re.finditer(
                    r"\b(?:not|without|exclude|avoid)\s+([a-z0-9][a-z0-9 -]{1,60}?)(?=,|;|\.|$)",
                    message,
                    re.I,
                )
            )
            for chunk, source in chunks:
                negative_match = None if source == "negative" else re.search(
                    r"\b(?:not|without|exclude|avoid)\s+([a-z0-9][a-z0-9 -]{1,60})", chunk, re.I
                )
                if negative_match:
                    chunk = negative_match.group(1)
                normalized = _normalize(chunk)
                terms = tuple(_terms(chunk))
                if not normalized or not terms:
                    continue
                attribute = Agent._constraint_attribute(chunk)
                if negative_match or source == "negative":
                    kind: Literal["hard", "soft", "category", "exclusion"] = "exclusion"
                elif source == "category":
                    kind = "category"
                elif state.preference_count < 2:
                    kind = "hard"
                    state.preference_count += 1
                else:
                    kind = "soft"
                    state.preference_count += 1
                if label == "O1_OVERRIDE":
                    state.constraints = [
                        item for item in state.constraints
                        if item.kind == "category" or item.attribute != attribute
                    ]
                if all(item.text != normalized or item.kind != kind for item in state.constraints):
                    state.constraints.append(Constraint(normalized, terms, turn, kind, attribute))

    def _score_candidates(
        self,
        state: SessionState,
        query_counts: Counter[str],
    ) -> tuple[list[tuple[float, float, str]], dict[str, dict[str, float]]]:
        """Run the unchanged reranker and return its complete ordered scores."""
        # Exact simulator replies are copied from catalog metadata.  IDF-weighted
        # coverage strongly rewards the rare identifying words in those replies,
        # without allowing repeated conversational boilerplate to dominate.
        document_count = len(self._documents)
        weights = {
            term: math.log((document_count + 1) / (self._document_frequency[term] + 1)) + 1.0
            for term in query_counts
        }
        candidate_indexes: set[int] = set()
        for term in query_counts:
            candidate_indexes.update(self._postings.get(term, ()))
        components: list[tuple[str, dict[str, float]]] = []
        latest_turn = max((item.turn for item in state.constraints), default=0)
        for document_index in candidate_indexes:
            product = self._documents[document_index]
            parent_asin, document = product.parent_asin, product.counts
            matched = 0.0
            saturation = 0.0
            for term, query_frequency in query_counts.items():
                frequency = document.get(term, 0)
                if frequency:
                    weight = weights[term]
                    matched += weight * min(query_frequency, frequency)
                    saturation += weight * math.log1p(frequency)
            if not matched:
                continue
            values = {
                "lexical": matched + 0.08 * saturation,
                "phrase": 0.0,
                "hard": 0.0,
                "soft": 0.0,
                "current": 0.0,
                "semantic": 0.0,
                "exclusion": 0.0,
                "category": 0.0,
                "profile": 0.0,
                "rating": product.rating_confidence,
            }
            hard_total = 0
            hard_matches = 0.0
            semantic_total = 0
            semantic_matches = 0.0
            for constraint in state.constraints:
                unique_terms = set(constraint.terms)
                if not unique_terms:
                    continue
                coverage = sum(term in document for term in unique_terms) / len(unique_terms)
                exact_fields = [
                    field for field in ("features", "title", "details", "description", "categories")
                    if len(constraint.terms) >= 2 and constraint.text in product.fields[field]
                ]
                exact = bool(exact_fields)
                match_strength = 1.0 if exact else coverage
                if constraint.kind != "exclusion":
                    semantic_total += 1
                    semantic_matches += match_strength
                if exact:
                    field_bonus = {"features": 5.0, "title": 4.0, "details": 3.0,
                                   "description": 2.0, "categories": 1.5}
                    specificity = min(2.0, 0.35 * len(constraint.terms))
                    values["phrase"] += specificity * max(field_bonus[field] for field in exact_fields)
                if constraint.kind == "hard":
                    hard_total += 1
                    hard_matches += match_strength
                elif constraint.kind == "soft":
                    values["soft"] += match_strength
                elif constraint.kind == "category":
                    values["category"] += match_strength
                elif constraint.kind == "exclusion":
                    values["exclusion"] = max(values["exclusion"], match_strength)
                if constraint.turn == latest_turn:
                    values["current"] += match_strength
            values["semantic"] = semantic_matches / semantic_total if semantic_total else 0.0
            values["hard"] = hard_matches / hard_total if hard_total else 0.0
            values["profile"] = (
                sum(term in document for term in set(state.profile_terms)) / len(set(state.profile_terms))
                if state.profile_terms else 0.0
            )
            components.append((parent_asin, values))

        normalized: dict[str, dict[str, float]] = {parent_asin: {} for parent_asin, _ in components}
        positive_names = ("lexical", "hard", "soft", "current", "semantic")
        for name in positive_names:
            column = [values[name] for _, values in components]
            low, high = (min(column), max(column)) if column else (0.0, 0.0)
            scale = high - low
            for parent_asin, values in components:
                normalized[parent_asin][name] = (values[name] - low) / scale if scale else 0.0

        scored: list[tuple[float, float, str]] = []
        component_by_id: dict[str, dict[str, float]] = {}
        for parent_asin, values in components:
            item = normalized[parent_asin]
            component_by_id[parent_asin] = {**item, "exclusion": values["exclusion"]}
            rerank_weights = self.rerank_weights
            score = (
                rerank_weights["hard"] * item["hard"]
                + rerank_weights["semantic"] * item["semantic"]
                + rerank_weights["lexical"] * item["lexical"]
                + rerank_weights["soft"] * item["soft"]
                + rerank_weights["recent"] * item["current"]
                - rerank_weights["exclusion"] * values["exclusion"]
            )
            scored.append((score, values["rating"], parent_asin))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return scored, component_by_id

    def _rank(self, state: SessionState, top_k: int, turn: int) -> list[dict]:
        self.last_recommendation_policy = {}
        self.last_rank_state = {}
        self.last_adaptive_k_log = {}
        self.last_ranking_components = []
        query_terms = _terms(" ".join(state.query_parts))
        if not query_terms:
            query_terms = state.profile_terms
        query_counts = Counter(query_terms)
        if not query_counts:
            return []

        score_cache_key = (
            tuple(sorted(query_counts.items())),
            tuple(state.constraints),
            tuple(sorted(self.rerank_weights.items())),
        )
        if score_cache_key == self._last_score_cache_key and self._last_score_cache is not None:
            scored, component_by_id, ranking_components = self._last_score_cache
        else:
            scored, component_by_id = self._score_candidates(state, query_counts)
            ranking_components = [
                (parent_asin, rank, rating, component_by_id[parent_asin])
                for rank, (_, rating, parent_asin) in enumerate(scored, start=1)
            ]
            self._last_score_cache_key = score_cache_key
            self._last_score_cache = (scored, component_by_id, ranking_components)
        self.last_ranking_components = ranking_components

        # K is chosen only after the existing retrieval and reranking order is
        # complete.  Previously displayed products are filtered exactly as
        # before, so changing the policy can only change the returned prefix.
        fresh_scored: list[tuple[float, float, str]] = []
        for scored_item in scored:
            if scored_item[2] not in state.recommended:
                fresh_scored.append(scored_item)
                if len(fresh_scored) >= 75:
                    break
        fresh_candidate_count = len(scored) - sum(
            parent_asin in component_by_id for parent_asin in state.recommended
        )
        # Feature extraction only inspects the first 75 products for component
        # agreement.  Avoid allocating tens of thousands of dataclass objects
        # for broad queries while retaining the exact full candidate count.
        feature_candidates = [
            RankedCandidate(
                parent_asin=parent_asin,
                score=score,
                rating=rating,
                components=component_by_id[parent_asin],
            )
            for score, rating, parent_asin in fresh_scored[:75]
        ]
        # Keep early lists short while evidence is sparse, then widen them as
        # constraints accumulate. Overrides and late turns prioritize recall:
        # the user has already paid the clarification cost, so return top_k.
        active_constraint_count = sum(
            constraint.kind != "exclusion" for constraint in state.constraints
        )
        recovery = "O1_OVERRIDE" in state.intent_history or turn >= 5
        constraint_counts = Counter(constraint.kind for constraint in state.constraints)
        context = RankingContext(
            turn=turn,
            intent=state.intent,
            mode=state.mode,
            active_constraint_count=active_constraint_count,
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
            recommended_count=len(state.recommended),
            candidate_count=fresh_candidate_count,
            override_seen="O1_OVERRIDE" in state.intent_history,
        )
        feature_values = extract_rank_features(feature_candidates, context)
        self.last_rank_state = {
            "turn": turn,
            "intent": state.intent,
            "mode": state.mode,
            "features": feature_values,
            # Development labels are joined offline through the complete
            # ``last_ranking_components`` ordering; live inference retains only
            # the decision frontier and never receives the target identifier.
            "ranked_ids": [parent_asin for _, _, parent_asin in fresh_scored[:10]],
            "top10_ids": [parent_asin for _, _, parent_asin in fresh_scored[:10]],
            "reranker_scores": [score for score, _, _ in fresh_scored[:10]],
            "candidate_count": fresh_candidate_count,
        }

        if self.fixed_k is not None:
            requested_k = self.fixed_k
            policy_name = f"fixed_{self.fixed_k}"
        elif self._adaptive_k_policy is not None:
            decision = self._adaptive_k_policy.choose(feature_candidates, context, top_k)
            requested_k = decision.selected_k
            policy_name = "rank_aware_adaptive_k"
            self.last_adaptive_k_log = decision.as_log()
        elif recovery:
            requested_k = 10
            policy_name = "constraint_schedule"
        elif active_constraint_count <= 2:
            requested_k = 3
            policy_name = "constraint_schedule"
        elif active_constraint_count <= 5:
            requested_k = 5
            policy_name = "constraint_schedule"
        else:
            requested_k = 10
            policy_name = "constraint_schedule"
        result_limit = max(0, min(requested_k, top_k))
        self.last_recommendation_policy = {
            "policy": policy_name,
            "active_constraint_count": active_constraint_count,
            "recovery": int(recovery),
            "k": result_limit,
        }
        fresh = [parent_asin for _, _, parent_asin in fresh_scored[:result_limit]]
        state.recommended.update(fresh)
        return [{"parent_asin": parent_asin} for parent_asin in fresh]

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self._sessions:
            raise RuntimeError("reset must be called before respond")
        state = self._sessions[session_id]
        label = self._classify_turn(state, user_message, turn)
        self._update_state(state, label, user_message, turn)
        recommendations = self._rank(state, top_k, turn)
        if self.last_adaptive_k_log:
            self.last_adaptive_k_log = {
                "session_id": session_id,
                "turn": turn,
                **self.last_adaptive_k_log,
            }
            self.adaptive_k_logs.append(self.last_adaptive_k_log)
        return {
            "message": "What other specific requirement or feature matters most?",
            "ask_attribute": "other",
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
