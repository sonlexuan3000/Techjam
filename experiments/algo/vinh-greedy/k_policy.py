"""Observable Top-K state and deterministic runtime artifact loading.

No evaluation label is accepted by this module.  It derives only compact
features from the inherited baseline Agent state and consumes a frozen lookup
artifact produced offline.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from starter.agent import Agent, Session, normalize


ACTIONS = tuple(range(1, 11))
DEFAULT_POLICY_PATH = Path(__file__).with_name("k_policy.json")


def baseline_action(turn: int, requested_top_k: int = 10) -> int:
    cap = max(0, min(int(requested_top_k), 10))
    if cap == 0:
        return 0
    scheduled = 1 if int(turn) == 1 else 2 if int(turn) == 2 else 10
    return min(scheduled, cap)


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    return "3+"


def _gain_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    return "2+"


def _remaining_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    return "2+"


def _pool_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 5:
        return "3-5"
    if value <= 10:
        return "6-10"
    if value <= 30:
        return "11-30"
    if value <= 100:
        return "31-100"
    if value <= 1000:
        return "101-1000"
    return ">1000"


def tie_bucket(value: int) -> str:
    if value <= 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 5:
        return "3-5"
    if value <= 10:
        return "6-10"
    return ">10"


def shown_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value <= 2:
        return "1-2"
    if value <= 10:
        return "3-10"
    return ">10"


@dataclass(frozen=True)
class PolicyState:
    turn: int
    remaining_other: str
    pool: str
    useful: str
    exact: str
    tie: str
    gain: str
    override: str
    no_information: str
    shown: str

    def full_tuple(self) -> tuple[object, ...]:
        return (
            "full",
            self.turn,
            self.remaining_other,
            self.pool,
            self.useful,
            self.exact,
            self.tie,
            self.gain,
            self.override,
            self.no_information,
            self.shown,
        )

    def hierarchy(self) -> tuple[tuple[object, ...], ...]:
        """Return global-to-local hierarchical backoff keys."""

        return (
            ("global",),
            ("turn", self.turn),
            ("turn_evidence", self.turn, self.useful),
            ("turn_pool_evidence", self.turn, self.pool, self.useful),
            (
                "turn_remaining_pool_evidence_shown",
                self.turn,
                self.remaining_other,
                self.pool,
                self.useful,
                self.shown,
            ),
            self.full_tuple(),
        )

    @staticmethod
    def encode_key(key: Sequence[object]) -> str:
        return json.dumps(tuple(key), separators=(",", ":"))

    def encode(self) -> str:
        return self.encode_key(self.full_tuple())


class StateEncoder:
    """Derive target-independent features using baseline retrieval semantics."""

    @staticmethod
    def conversation_signature(state: Session) -> tuple[object, ...]:
        return (
            state.category,
            tuple(
                (
                    clue.key,
                    clue.source,
                    clue.active,
                    clue.searchable,
                    clue.superseded,
                    clue.negated,
                )
                for clue in state.evidence
            ),
        )

    def useful_evidence(
        self,
        agent: Agent,
        state: Session,
    ) -> list[tuple[object, set[str], str]]:
        result: list[tuple[object, set[str], str]] = []
        for clue in state.retrieval_evidence:
            matches, kind = agent._clue_candidates(clue.text)
            if matches:
                result.append((clue, matches, kind))
        return result

    def pool_size(
        self,
        agent: Agent,
        state: Session,
        useful: list[tuple[object, set[str], str]] | None = None,
    ) -> int:
        """Mirror the baseline pool narrowing without altering retrieval."""

        category_key = normalize(state.category)
        category_set = set(agent.coarse_category_to_asins.get(category_key, set()))
        pool = set(category_set) if category_set else set(agent.asins)
        evidence = useful if useful is not None else self.useful_evidence(agent, state)
        ordered = sorted(
            (item for item in evidence if item[0].source != "catalog_fallback"),
            key=lambda item: (not item[0].active, len(item[1])),
        )
        for _clue, matches, _kind in ordered:
            narrowed = pool & matches
            if narrowed:
                pool = narrowed

        negatives: list[set[str]] = []
        for clue in state.negative_evidence:
            matches, _kind = agent._clue_candidates(clue.text)
            if matches:
                negatives.append(matches)
        if negatives:
            forbidden = set().union(*negatives)
            narrowed = pool - forbidden
            if narrowed:
                pool = narrowed
            else:
                global_allowed = set(agent.asins) - forbidden
                if global_allowed:
                    pool = global_allowed
        return len(pool)

    def relevance_signatures(
        self,
        agent: Agent,
        state: Session,
        asins: Sequence[str],
        useful: list[tuple[object, set[str], str]] | None = None,
    ) -> tuple[float, ...]:
        """Return the exact pre-popularity baseline score for each ASIN.

        Equality is exact; no arbitrary score threshold is introduced.  This
        duplicates the inherited score expression solely to measure tie size
        and never changes the returned ranking.
        """

        evidence = useful if useful is not None else self.useful_evidence(agent, state)
        category_key = normalize(state.category)
        category_set = set(agent.coarse_category_to_asins.get(category_key, set()))
        negatives: list[set[str]] = []
        for clue in state.negative_evidence:
            matches, _kind = agent._clue_candidates(clue.text)
            if matches:
                negatives.append(matches)
        total = max(len(agent.asins), 1)
        signatures: list[float] = []
        for asin in asins:
            value = 2.0 if asin in category_set else 0.0
            for clue, matches, kind in evidence:
                if asin not in matches:
                    continue
                idf = math.log((total + 1) / (len(matches) + 1))
                base = 10.0 if kind == "exact" else 4.0
                intent_weight = 1.5 if clue.active else 1.0
                if clue.source in {"override", "initial_requirement"}:
                    intent_weight += 0.25
                value += intent_weight * (base + idf)
            for matches in negatives:
                if asin in matches:
                    value -= 100.0
            signatures.append(value)
        return tuple(signatures)

    @staticmethod
    def leading_tie_size(
        ranked: Sequence[str],
        shown: set[str],
        signatures: Sequence[float],
    ) -> int:
        first_signature: float | None = None
        count = 0
        for asin, signature in zip(ranked, signatures):
            if asin in shown:
                continue
            if first_signature is None:
                first_signature = signature
            if signature != first_signature:
                break
            count += 1
        return max(count, 1)

    def encode(
        self,
        agent: Agent,
        state: Session,
        *,
        turn: int,
        last_evidence_gain: int,
        last_reply_had_no_information: bool,
        ranked: Sequence[str],
    ) -> PolicyState:
        useful = self.useful_evidence(agent, state)
        exact_count = sum(kind == "exact" for _clue, _matches, kind in useful)
        active_useful_count = sum(clue.active for clue, _matches, _kind in useful)
        ranked_head = tuple(ranked[:120])
        signatures = self.relevance_signatures(agent, state, ranked_head, useful)
        top_tie = self.leading_tie_size(ranked_head, state.shown, signatures)
        override_seen = any(clue.source == "override" for clue in state.evidence)
        return PolicyState(
            turn=max(1, min(int(turn), 10)),
            remaining_other=_remaining_bucket(max(0, 3 - state.other_calls)),
            pool=_pool_bucket(self.pool_size(agent, state, useful)),
            useful=_count_bucket(active_useful_count),
            exact=_count_bucket(exact_count),
            tie=tie_bucket(top_tie),
            gain=_gain_bucket(last_evidence_gain),
            override="1" if override_seen else "0",
            no_information="1" if last_reply_had_no_information else "0",
            shown=shown_bucket(len(state.shown)),
        )


class ConservativeKPolicy:
    """Choose from a globally accepted artifact with hierarchical backoff."""

    def __init__(self, artifact: Mapping[str, object]):
        self.artifact = dict(artifact)
        self.variant = str(self.artifact.get("selected_variant", "baseline"))
        self.minimum_samples = int(self.artifact.get("minimum_state_samples", 8))
        raw_actions = self.artifact.get("actions", {})
        self.actions = dict(raw_actions) if isinstance(raw_actions, dict) else {}
        gate = self.artifact.get("global_gate", {})
        self.global_gate = dict(gate) if isinstance(gate, dict) else {}
        canonical = json.dumps(self.artifact, sort_keys=True, separators=(",", ":"))
        self.fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: str | Path = DEFAULT_POLICY_PATH) -> "ConservativeKPolicy":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload)

    def choose(
        self,
        policy_state: PolicyState,
        *,
        requested_top_k: int,
    ) -> tuple[int, str]:
        cap = max(0, min(int(requested_top_k), 10))
        base = baseline_action(policy_state.turn, cap)
        if cap == 0:
            return 0, "cap_zero"
        if not bool(self.global_gate.get("accepted", False)):
            return base, "safety_gate"

        saw_sparse = False
        # Never use the cross-turn global level as a runtime action.  Turn is
        # the coarsest safe fallback because the baseline schedule depends on it.
        for level, key in reversed(list(enumerate(policy_state.hierarchy()[1:], 1))):
            entry = self.actions.get(PolicyState.encode_key(key))
            if not isinstance(entry, dict):
                continue
            if int(entry.get("samples", 0)) < self.minimum_samples:
                saw_sparse = True
                continue
            action = int(entry.get("k", base))
            if action not in ACTIONS:
                continue
            reason = str(entry.get("reason", "selected"))
            if action == baseline_action(policy_state.turn):
                if reason == "uncertainty":
                    return base, "uncertainty"
                return base, "baseline_selected"
            return min(action, cap), "accepted_exact" if level == 5 else "accepted_backoff"
        return base, "sparse_state" if saw_sparse else "unseen_state"
