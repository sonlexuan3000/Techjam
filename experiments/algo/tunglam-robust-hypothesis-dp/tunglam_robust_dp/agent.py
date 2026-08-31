from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path

from submission.src.shopping_copilot.core import (
    Agent as IntegratedAgent,
    ProductIntent,
    SessionState,
    _normalize_message,
)
from submission.src.shopping_copilot.parser import ParsedMessage, parse_message


SCENARIO_PRIOR = {
    "buying": 0.40,
    "browsing": 0.40,
    "intent_override": 0.15,
    "boundary": 0.05,
}

PHRASE_ALIASES = {
    "not wet in rain": "waterproof",
    "not heavy": "lightweight",
    "keep dry in rain": "waterproof",
    "water resistant": "waterproof",
    "water proof": "waterproof",
    "non slip": "traction",
    "anti slip": "traction",
    "good grip": "traction",
    "good traction": "traction",
    "rubber outsole": "traction",
    "rubber sole": "traction",
    "machine washable": "washable",
    "easy to clean": "washable",
    "moisture wicking": "dry",
    "moisture management": "dry",
    "light weight": "lightweight",
    "extra room": "wide",
}
WORD_ALIASES = {
    "airflow": "breathable",
    "amplifoam": "comfort",
    "breathability": "breathable",
    "breathable": "breathable",
    "cushion": "comfort",
    "cushioned": "comfort",
    "cushioning": "comfort",
    "comfortable": "comfort",
    "comfort": "comfort",
    "dry": "dry",
    "durability": "durable",
    "durable": "durable",
    "flexibility": "flexible",
    "flexible": "flexible",
    "grip": "traction",
    "light": "lightweight",
    "lightweight": "lightweight",
    "mesh": "breathable",
    "rain": "waterproof",
    "roomy": "wide",
    "running": "run",
    "sturdy": "durable",
    "traction": "traction",
    "ventilated": "breathable",
    "ventilation": "breathable",
    "washable": "washable",
    "waterproof": "waterproof",
    "wide": "wide",
}
SEMANTIC_STOPWORDS = {
    "a",
    "about",
    "and",
    "be",
    "can",
    "for",
    "good",
    "have",
    "i",
    "in",
    "is",
    "it",
    "long",
    "me",
    "my",
    "need",
    "of",
    "on",
    "one",
    "prefer",
    "product",
    "shoe",
    "shoes",
    "something",
    "that",
    "the",
    "this",
    "to",
    "want",
    "with",
}
SEMANTIC_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
SEMANTIC_CONCEPTS = frozenset(
    set(PHRASE_ALIASES.values()) | set(WORD_ALIASES.values())
)


def _stem(token: str) -> str:
    if token in WORD_ALIASES:
        return WORD_ALIASES[token]
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
        if len(token) >= 2 and token[-1] == token[-2]:
            token = token[:-1]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return WORD_ALIASES.get(token, token)


def semantic_terms(value: str) -> frozenset[str]:
    normalized = " ".join(SEMANTIC_TOKEN_RE.findall(str(value).lower()))
    padded = f" {normalized} "
    for phrase, canonical in sorted(
        PHRASE_ALIASES.items(),
        key=lambda item: -len(item[0]),
    ):
        padded = padded.replace(f" {phrase} ", f" {canonical} ")
    result = {
        _stem(token)
        for token in padded.split()
        if token not in SEMANTIC_STOPWORDS and len(token) > 1
    }
    return frozenset(token for token in result if token)


def semantic_similarity(
    query: frozenset[str],
    candidate: frozenset[str],
) -> float:
    if not query or not candidate:
        return 0.0
    overlap = len(query & candidate)
    if overlap == 0:
        return 0.0
    query_coverage = overlap / len(query)
    compact_precision = overlap / min(len(candidate), max(len(query), 3))
    return 0.8 * query_coverage + 0.2 * min(1.0, compact_precision)


@dataclass
class ScenarioPosterior:
    probabilities: dict[str, float] = field(
        default_factory=lambda: dict(SCENARIO_PRIOR)
    )
    confirmed: str | None = None

    def _renormalize(self) -> None:
        total = sum(self.probabilities.values())
        if total <= 0:
            self.probabilities = {
                "buying": 0.5,
                "browsing": 0.5,
                "intent_override": 0.0,
                "boundary": 0.0,
            }
            return
        self.probabilities = {
            name: value / total
            for name, value in self.probabilities.items()
        }

    def observe(self, parsed: ParsedMessage, turn: int) -> None:
        if parsed.action == "override":
            self.probabilities = {
                name: float(name == "intent_override")
                for name in SCENARIO_PRIOR
            }
            self.confirmed = "intent_override"
            return

        # Wording is soft evidence only. No initial wrapper is allowed to make
        # a future override certain or impossible.
        if turn == 1:
            likelihood = {name: 1.0 for name in SCENARIO_PRIOR}
            if parsed.source == "initial_requirement":
                likelihood.update(
                    buying=3.0,
                    browsing=0.75,
                    intent_override=1.0,
                    boundary=0.75,
                )
            elif parsed.source in {
                "initial_preference",
                "compact_initial_preference",
            }:
                likelihood.update(
                    buying=0.75,
                    browsing=1.0,
                    intent_override=3.0,
                    boundary=0.75,
                )
            elif parsed.action in {"none", "ignore"}:
                likelihood.update(
                    buying=0.75,
                    browsing=2.5,
                    intent_override=1.0,
                    boundary=1.5,
                )
            self.probabilities = {
                name: self.probabilities[name] * likelihood[name]
                for name in SCENARIO_PRIOR
            }
            self._renormalize()

        if parsed.action == "ignore" and turn <= 2:
            self.probabilities["boundary"] *= 4.0
            self._renormalize()

        # The specification guarantees that an override arrives on turn 3 or
        # 4. Once a non-override turn 4 has been observed, that branch is dead.
        if turn >= 4:
            self.probabilities["intent_override"] = 0.0
            self._renormalize()
            if self.confirmed is None:
                self.confirmed = max(
                    self.probabilities,
                    key=self.probabilities.get,
                )

    @property
    def label(self) -> str:
        return self.confirmed or "unconfirmed"


class Agent(IntegratedAgent):
    """Inverse-DP variant that treats early scenario routing as uncertain.

    Normal-session misses are rejected immediately, while every recommendation
    before turn four is also retained as a reversible pending-override history.
    A real override rolls that history back. This represents both scoring
    worlds without trusting the initial message wrapper.
    """

    semantic_focus_threshold = 0.60
    # A semantic interpretation is allowed to become a focus tier only when
    # it is selective. Broad concepts such as "washable" or "comfortable"
    # remain soft ranking evidence in the inherited recovery path.
    semantic_focus_max_candidates = 25

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        prior_field: str = "uniform",
        prior_smoothing: float = 0.0,
        prior_path: str | Path | None = None,
    ) -> None:
        super().__init__(
            catalog_path,
            prior_field=prior_field,
            prior_smoothing=prior_smoothing,
            prior_path=prior_path,
        )
        self.scenario_posteriors: dict[str, ScenarioPosterior] = {}
        # Index only the small alias vocabulary. Exact values already use the
        # integrated catalog index; duplicating every arbitrary metadata token
        # here would roughly double startup memory for no semantic benefit.
        self.semantic_profiles: dict[str, tuple[frozenset[str], ...]] = {}
        for parent_asin, product in self.products.items():
            profiles = tuple(
                concepts
                for value in product.constraints
                if (concepts := semantic_terms(value) & SEMANTIC_CONCEPTS)
            )
            if profiles:
                self.semantic_profiles[parent_asin] = profiles
        self.semantic_inverted: dict[str, set[str]] = {}
        for parent_asin, profiles in self.semantic_profiles.items():
            for term in set().union(*profiles) if profiles else set():
                self.semantic_inverted.setdefault(term, set()).add(parent_asin)

    def reset(self, session_id: str, user_profile: dict) -> None:
        super().reset(session_id, user_profile)
        self.scenario_posteriors[session_id] = ScenarioPosterior()

    @staticmethod
    def _scenario_from_parsed(parsed: ParsedMessage) -> str:
        del parsed
        return "unconfirmed"

    def _initial_scenario(
        self,
        product: ProductIntent,
        message: str,
    ) -> tuple[str, set[str]] | None:
        result = super()._initial_scenario(product, message)
        if result is None:
            return None
        _released_label, disclosed = result
        return "unconfirmed", disclosed

    def _semantic_clues(
        self,
        session_id: str,
    ) -> list[frozenset[str]]:
        tracker_state = self.intent_tracker.sessions[session_id]
        return [
            terms
            for clue in tracker_state.current_intent
            if (terms := semantic_terms(clue.text))
        ]

    def _semantic_focus(
        self,
        session_id: str,
        state: SessionState,
    ) -> list[str]:
        tracker_state = self.intent_tracker.sessions[session_id]
        clues = list(tracker_state.current_intent)
        if not clues:
            return []

        universe = set(state.trusted_universe or self.all_product_ids)
        tracker_state = self.intent_tracker.sessions[session_id]
        category = _normalize_message(tracker_state.category)
        category_ids = set(self.category_index.get(category, []))
        if category_ids:
            universe &= category_ids

        candidates = set(universe)
        semantic_queries: list[frozenset[str]] = []
        saw_unmatched_clue = False
        for clue in clues:
            exact, _route = self.intent_tracker._clue_candidates(clue.text)
            if exact:
                candidates &= exact
                continue

            query = semantic_terms(clue.text) & SEMANTIC_CONCEPTS
            if not query:
                return []
            seeded: set[str] = set()
            for term in query:
                seeded.update(self.semantic_inverted.get(term, set()))
            if not seeded:
                return []
            candidates &= seeded
            semantic_queries.append(query)
            saw_unmatched_clue = True
        candidates.difference_update(state.rejected)
        if (
            not saw_unmatched_clue
            or not candidates
            or len(candidates) > self.semantic_focus_max_candidates
        ):
            return []

        scored: list[tuple[float, float, str]] = []
        for parent_asin in candidates:
            profiles = self.semantic_profiles.get(parent_asin, ())
            similarities = [
                max(
                    (
                        semantic_similarity(clue, profile)
                        for profile in profiles
                    ),
                    default=0.0,
                )
                for clue in semantic_queries
            ]
            if similarities and min(similarities) >= self.semantic_focus_threshold:
                scored.append(
                    (
                        -min(similarities),
                        -sum(similarities),
                        parent_asin,
                    )
                )

        scored.sort(
            key=lambda item: (
                item[0],
                item[1],
                self._rank_key(item[2]),
            )
        )
        return [parent_asin for _minimum, _total, parent_asin in scored]

    def _degraded_candidate_tiers(
        self,
        session_id: str,
        state: SessionState,
        *,
        reopen_focus: bool = False,
    ) -> tuple[list[str], list[str]]:
        tracker_state = self.intent_tracker.sessions[session_id]
        needs_semantics = any(
            not self.intent_tracker._clue_candidates(clue.text)[0]
            for clue in tracker_state.current_intent
        )
        if needs_semantics:
            semantic_focus = self._semantic_focus(session_id, state)
            if semantic_focus:
                return semantic_focus, []

        focus, recovery = super()._degraded_candidate_tiers(
            session_id,
            state,
            reopen_focus=reopen_focus,
        )
        if focus:
            return focus, recovery
        return focus, recovery

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self.scenario_posteriors:
            raise RuntimeError("reset must be called before respond")

        parsed = parse_message(str(user_message or ""), turn=turn)
        posterior = self.scenario_posteriors[session_id]
        posterior.observe(parsed, turn)

        state = self.sessions[session_id]
        if turn > 1:
            state.scenario = posterior.label
        response = super().respond(
            session_id,
            user_message,
            turn,
            top_k,
        )
        state.scenario = posterior.label
        if posterior.probabilities["intent_override"] == 0.0:
            # The guaranteed turn-3/4 window has closed. Stop retaining the
            # reversible branch so later normal misses stay final.
            state.pre_override_recommendations.clear()
        state.last_policy_mode = (
            f"{state.last_policy_mode}|scenario={posterior.label}"
        )
        return response

    def debug_algorithm_stats(self, session_id: str) -> dict:
        stats = super().debug_algorithm_stats(session_id)
        posterior = self.scenario_posteriors[session_id]
        stats["scenario_posterior"] = {
            name: round(value, 6)
            for name, value in posterior.probabilities.items()
        }
        stats["scenario_confirmed"] = posterior.confirmed
        return stats
