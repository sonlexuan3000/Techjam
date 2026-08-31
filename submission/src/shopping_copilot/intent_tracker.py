"""Catalog-grounded intent tracker used by the production inverse-DP agent."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .parser import parse_message


WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# These are the material/color words used by the public simulator, plus a few
# common alternatives needed to recognise a genuine same-slot override such as
# "leather" -> "canvas". Generic features are deliberately not exclusive:
# breathable and waterproof, for example, can both describe one product.
MATERIAL_ALIASES = {
    "acrylic": "acrylic",
    "canvas": "canvas",
    "cotton": "cotton",
    "denim": "denim",
    "fabric": "fabric",
    "fleece": "fleece",
    "leather": "leather",
    "linen": "linen",
    "mesh": "mesh",
    "metal": "metal",
    "nylon": "nylon",
    "plastic": "plastic",
    "polyester": "polyester",
    "rayon": "rayon",
    "rubber": "rubber",
    "silk": "silk",
    "spandex": "spandex",
    "suede": "suede",
    "velvet": "velvet",
    "wool": "wool",
}
COLOR_ALIASES = {
    "black": "black",
    "blue": "blue",
    "brown": "brown",
    "gray": "gray",
    "grey": "gray",
    "green": "green",
    "orange": "orange",
    "pink": "pink",
    "purple": "purple",
    "red": "red",
    "white": "white",
    "yellow": "yellow",
}
SIZE_ALIASES = {
    "extra small": "xs",
    "x small": "xs",
    "xs": "xs",
    "small": "s",
    "medium": "m",
    "large": "l",
    "extra large": "xl",
    "x large": "xl",
    "xl": "xl",
    "xxl": "xxl",
}
SPECIAL_WORDS = set(MATERIAL_ALIASES) | set(COLOR_ALIASES)
EXCLUSIVE_SLOTS = {"material", "color", "size", "budget"}

# Returning ten speculative candidates immediately can lock in a low reciprocal
# rank and end the session before clarification improves the ordering.  Spend
# the first two turns on one/two high-confidence candidates, then restore full
# Top-10 coverage from turn three onward.
EARLY_RECOMMENDATION_LIMITS = {1: 1, 2: 2}


def normalize(value: object) -> str:
    """Normalise catalog/user text for deterministic exact matching."""

    return " ".join(WORD_RE.findall(str(value).lower()))


def evaluator_clean(value: object, limit: int = 180) -> str:
    """Mirror the public evaluator's hidden-constraint cleanup."""

    cleaned = re.sub(r"\s+", " ", str(value)).strip(" -;,.\t\n")
    return cleaned[:limit].rstrip()


def metadata_atoms(product: dict) -> list[str]:
    """Return exact metadata strings that can become simulator clues."""

    atoms: list[str] = []
    for field_name in ("features", "description", "categories"):
        value = product.get(field_name)
        if isinstance(value, list):
            atoms.extend(str(item) for item in value if item not in (None, ""))
        elif value not in (None, ""):
            atoms.append(str(value))

    details = product.get("details")
    if isinstance(details, dict):
        atoms.extend(
            f"{key}: {value}"
            for key, value in details.items()
            if value not in (None, "", [])
        )
    elif details not in (None, ""):
        atoms.append(str(details))

    for field_name in ("title", "store"):
        if product.get(field_name) not in (None, ""):
            atoms.append(str(product[field_name]))
    return atoms


def full_text(product: dict) -> str:
    return " ".join(metadata_atoms(product))


def coarse_category(values: list[object]) -> str:
    excluded = {"clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry"}
    cleaned: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part and part.lower() not in excluded:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def _phrase_present(normalized_text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized_text} "


def slot_signatures(text: str) -> dict[str, tuple[str, ...]]:
    """Return every confident exclusive slot represented in ``text``."""

    key = normalize(text)
    result: dict[str, tuple[str, ...]] = {}

    synthetic_leather_phrases = ("faux leather", "pu leather", "synthetic leather")
    if any(_phrase_present(key, phrase) for phrase in synthetic_leather_phrases):
        materials = {"synthetic_leather"}
    else:
        materials = {
            canonical
            for phrase, canonical in MATERIAL_ALIASES.items()
            if _phrase_present(key, phrase)
        }
    if materials:
        result["material"] = tuple(sorted(materials))

    colors = {
        canonical
        for phrase, canonical in COLOR_ALIASES.items()
        if _phrase_present(key, phrase)
    }
    if colors:
        result["color"] = tuple(sorted(colors))

    # Match longest size phrases first so "extra large" is not also "large".
    sizes: set[str] = set()
    for phrase in sorted(SIZE_ALIASES, key=lambda value: (-len(value.split()), -len(value))):
        if _phrase_present(key, phrase):
            sizes.add(SIZE_ALIASES[phrase])
            break
    if sizes:
        result["size"] = tuple(sorted(sizes))

    if "budget" in key or "$" in text or re.search(r"\b(?:under|below|around)\s+\d", key):
        amounts = tuple(re.findall(r"\d+(?:\.\d+)?", key))
        result["budget"] = amounts or (key,)

    return result


def slot_signature(text: str) -> tuple[str, tuple[str, ...]]:
    """Return one primary slot for state display and simple diagnostics.

    Conflict detection uses :func:`slot_signatures` so a phrase such as
    ``black leather`` can still conflict on color even though material is its
    primary display slot.
    """

    signatures = slot_signatures(text)
    for slot in ("material", "color", "size", "budget"):
        if slot in signatures:
            return slot, signatures[slot]
    return "feature", ()


@dataclass
class Clue:
    text: str
    source: str
    slot: str
    values: tuple[str, ...]
    active: bool = True
    searchable: bool = True
    superseded: bool = False
    negated: bool = False

    @property
    def key(self) -> str:
        return normalize(self.text)


@dataclass
class Session:
    profile: dict = field(default_factory=dict)
    category: str = ""
    evidence: list[Clue] = field(default_factory=list)
    other_calls: int = 0
    shown: set[str] = field(default_factory=set)

    @property
    def current_intent(self) -> list[Clue]:
        return [clue for clue in self.evidence if clue.active and not clue.negated]

    @property
    def retrieval_evidence(self) -> list[Clue]:
        return [clue for clue in self.evidence if clue.searchable and not clue.negated]

    @property
    def negative_evidence(self) -> list[Clue]:
        return [clue for clue in self.evidence if clue.negated]


class Agent:
    """Exact-evidence agent with conflict-aware intent overrides.

    ``current_intent`` represents what the customer still asks for, while
    ``retrieval_evidence`` retains every target clue leaked by the simulator.
    An overridden clue remains useful evidence unless the new value conflicts
    in the same exclusive slot (for example leather to canvas).
    """

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        self.asins: list[str] = []
        self.rating_numbers: dict[str, float] = {}
        self.atom_to_asins: dict[str, set[str]] = defaultdict(set)
        self.coarse_category_to_asins: dict[str, set[str]] = defaultdict(set)
        self.special_word_to_asins: dict[str, set[str]] = defaultdict(set)
        self.sessions: dict[str, Session] = {}
        self._build_index()

    def _build_index(self) -> None:
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                asin = str(product["parent_asin"])
                self.asins.append(asin)
                rating_number = product.get("rating_number", 0)
                if (
                    isinstance(rating_number, (int, float))
                    and not isinstance(rating_number, bool)
                    and math.isfinite(float(rating_number))
                    and rating_number >= 0
                ):
                    self.rating_numbers[asin] = float(rating_number)
                else:
                    self.rating_numbers[asin] = 0.0

                category = normalize(coarse_category(product.get("categories") or []))
                if category:
                    self.coarse_category_to_asins[category].add(asin)

                for atom in metadata_atoms(product):
                    for variant in (str(atom), evaluator_clean(atom)):
                        key = normalize(variant)
                        if key:
                            self.atom_to_asins[key].add(asin)

                # The evaluator may append this synthetic constraint when a
                # sparsely described target has a catalog price.
                if product.get("price") not in (None, ""):
                    budget_key = normalize(f"budget around ${product['price']}")
                    self.atom_to_asins[budget_key].add(asin)

                words = set(WORD_RE.findall(full_text(product).lower())) & SPECIAL_WORDS
                for word in words:
                    self.special_word_to_asins[word].add(asin)

        self.atom_to_asins = dict(self.atom_to_asins)
        self.coarse_category_to_asins = dict(self.coarse_category_to_asins)
        self.special_word_to_asins = dict(self.special_word_to_asins)

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.sessions[session_id] = Session(profile=dict(user_profile or {}))

    def _add_clue(
        self,
        state: Session,
        value: str,
        source: str,
        *,
        active: bool = True,
        searchable: bool = True,
    ) -> Clue | None:
        value = evaluator_clean(value)
        key = normalize(value)
        if not key:
            return None

        for clue in state.evidence:
            if clue.key != key:
                continue
            # A simulator quirk may reveal a superseded preference again. Do
            # not silently reactivate it; only a new explicit override can.
            if source == "override":
                clue.active = active
                clue.searchable = searchable
                clue.superseded = False
                clue.negated = False
                clue.source = source
            elif not clue.superseded and not clue.negated:
                clue.active = clue.active or active
                clue.searchable = clue.searchable or searchable
            return clue

        slot, values = slot_signature(value)
        clue = Clue(
            text=value,
            source=source,
            slot=slot,
            values=values,
            active=active,
            searchable=searchable,
        )
        state.evidence.append(clue)
        return clue

    @staticmethod
    def _same_slot_conflict(old: Clue, new: Clue) -> bool:
        old_signatures = slot_signatures(old.text)
        new_signatures = slot_signatures(new.text)
        for slot in EXCLUSIVE_SLOTS & old_signatures.keys() & new_signatures.keys():
            if set(old_signatures[slot]).isdisjoint(new_signatures[slot]):
                return True
        return False

    @staticmethod
    def _same_semantic_value(first: str, second: str) -> bool:
        first_signatures = slot_signatures(first)
        second_signatures = slot_signatures(second)
        for slot in EXCLUSIVE_SLOTS & first_signatures.keys() & second_signatures.keys():
            if not set(first_signatures[slot]).isdisjoint(second_signatures[slot]):
                return True
        return False

    def _apply_override(
        self,
        state: Session,
        new_value: str,
        explicit_old_value: str | None = None,
    ) -> None:
        if explicit_old_value:
            old_key = normalize(explicit_old_value)
            old_candidates = [clue for clue in state.current_intent if clue.key == old_key]
            if not old_candidates:
                old_candidates = [
                    clue
                    for clue in state.current_intent
                    if self._same_semantic_value(clue.text, explicit_old_value)
                ]
        else:
            old_candidates = []

        if not old_candidates:
            initial = [
                clue for clue in state.current_intent if clue.source == "initial_preference"
            ]
            old_candidates = initial[-1:] if initial else state.current_intent[-1:]

        new_slot, new_values = slot_signature(new_value)
        preview = Clue(
            text=evaluator_clean(new_value),
            source="override",
            slot=new_slot,
            values=new_values,
        )

        for old in old_candidates:
            old.active = False
            old.superseded = True
            # Keep non-conflicting old target evidence; disable only a confident
            # same-slot replacement such as material leather -> canvas.
            if self._same_slot_conflict(old, preview):
                old.searchable = False

        self._add_clue(state, new_value, "override")

        # Override targets cannot score before this turn, so allow an earlier
        # recommendation to be emitted again immediately.
        state.shown.clear()

    def _apply_negation(self, state: Session, value: str) -> None:
        value = evaluator_clean(value)
        key = normalize(value)
        if not key:
            return

        matched = False
        for clue in state.evidence:
            if clue.key == key or clue.key in key or key in clue.key:
                clue.active = False
                clue.searchable = False
                clue.superseded = True
                clue.negated = True
                matched = True

        if not matched:
            clue = self._add_clue(
                state,
                value,
                "negation",
                active=False,
                searchable=False,
            )
            if clue:
                clue.negated = True

    def _clue_candidates(self, clue: str) -> tuple[set[str], str]:
        key = normalize(clue)
        words = key.split()

        exact = self.atom_to_asins.get(key)
        if exact and len(words) > 1:
            return set(exact), "exact"

        # Generated singleton material/color clues can come from anywhere in
        # the target's text rather than from a whole metadata atom.
        special = [word for word in words if word in SPECIAL_WORDS]
        if len(words) <= 2 and special:
            sets = [self.special_word_to_asins.get(word, set()) for word in special]
            nonempty = [values for values in sets if values]
            if nonempty:
                return set.intersection(*map(set, nonempty)), "word"

        if exact:
            return set(exact), "exact"
        return set(), "none"

    def _split_revealed_payload(self, payload: str) -> list[str]:
        """Recover one/two clues without blindly splitting internal semicolons."""

        payload = evaluator_clean(payload)
        if not payload:
            return []

        alternatives: list[list[str]] = [[payload]]
        catalog_parts = self._catalog_phrases_in_message(
            payload,
            allow_singletons=True,
        )
        if catalog_parts:
            alternatives.append(catalog_parts)
        for index, char in enumerate(payload):
            if char != ";":
                continue
            left = evaluator_clean(payload[:index])
            right = evaluator_clean(payload[index + 1 :])
            if left and right:
                alternatives.append([left, right])

        total = max(len(self.asins), 1)

        def quality(parts: list[str]) -> tuple[int, int, float]:
            matched = 0
            candidate_sets: list[set[str]] = []
            for part in parts:
                candidates, _kind = self._clue_candidates(part)
                if candidates:
                    matched += 1
                    candidate_sets.append(candidates)
            common = set.intersection(*candidate_sets) if candidate_sets else set()
            all_parts_share_product = int(matched == len(parts) and bool(common))
            rarity = math.log((total + 1) / (len(common) + 1)) if common else 0.0
            return all_parts_share_product, matched, rarity

        if not alternatives:
            return [payload]
        best = max(alternatives, key=quality)
        if quality(best)[1] == 0:
            return [payload]
        return best

    def _catalog_phrases_in_message(
        self,
        message: str,
        category: str = "",
        *,
        allow_singletons: bool = False,
    ) -> list[str]:
        """Find exact multi-token catalog atoms inside an unknown wrapper.

        Messages are short, so enumerating their bounded token n-grams is much
        cheaper than scanning every catalog phrase.  Original character spans
        are returned so punctuation such as ``100%`` and ``Color:`` survives.
        """

        tokens = list(WORD_RE.finditer(message))
        if not tokens:
            return []

        category_key = normalize(category)
        candidates: list[tuple[int, int, int, str]] = []
        max_words = min(40, len(tokens))
        for start in range(len(tokens)):
            upper = min(len(tokens), start + max_words)
            minimum_end = start if allow_singletons else start + 1
            for end in range(upper, minimum_end, -1):
                key = " ".join(token.group(0).lower() for token in tokens[start:end])
                if key == category_key or key not in self.atom_to_asins:
                    continue
                char_start = tokens[start].start()
                char_end = tokens[end - 1].end()
                candidates.append(
                    (end - start, char_start, char_end, message[char_start:char_end])
                )
                break

        selected: list[tuple[int, int, str]] = []
        for _length, char_start, char_end, raw in sorted(
            candidates,
            key=lambda item: (-item[0], item[1]),
        ):
            if any(char_start < end and char_end > start for start, end, _ in selected):
                continue
            selected.append((char_start, char_end, raw))

        return [raw for _start, _end, raw in sorted(selected)]

    def _parse(self, state: Session, message: str, turn: int) -> None:
        parsed = parse_message(message, turn=turn)
        if parsed.category and not state.category:
            state.category = evaluator_clean(parsed.category)

        if parsed.action == "override" and parsed.payload:
            self._apply_override(state, parsed.payload, parsed.explicit_old_value)
            return

        if parsed.action == "negate" and parsed.payload:
            # Some catalog features are care instructions whose literal text
            # starts with "Please avoid ...". If a private wrapper returns one
            # of those atoms bare, prefer the exact catalog evidence unless the
            # payload clearly refers to an already-active clue.
            full_key = normalize(evaluator_clean(message))
            payload_key = normalize(parsed.payload)
            refers_to_active_clue = any(
                clue.key == payload_key
                or clue.key in payload_key
                or payload_key in clue.key
                for clue in state.current_intent
            )
            if full_key in self.atom_to_asins and not refers_to_active_clue:
                self._add_clue(
                    state,
                    evaluator_clean(message),
                    "catalog_fallback",
                )
                return
            self._apply_negation(state, parsed.payload)
            return

        if parsed.action == "add" and parsed.payload:
            source = parsed.source or "revealed"
            if source == "compact_initial_preference":
                candidates, _kind = self._clue_candidates(parsed.payload)
                if candidates:
                    self._add_clue(state, parsed.payload, "initial_preference")
                return
            parts = (
                self._split_revealed_payload(parsed.payload)
                if source == "revealed"
                else [parsed.payload]
            )
            for part in parts:
                self._add_clue(state, part, source)
            return

        if parsed.action == "ignore":
            return

        # Last-resort wrapper tolerance: recover exact catalog phrases without
        # rewriting them.  Single-token constraints still require an explicit
        # payload cue or a reply made entirely of that catalog atom, which
        # avoids treating generic wrapper words as evidence.
        category = parsed.category or state.category
        message_tokens = WORD_RE.findall(message)
        allow_singletons = (
            len(message_tokens) == 1
            and normalize(message) in self.atom_to_asins
        )
        for phrase in self._catalog_phrases_in_message(
            message,
            category,
            allow_singletons=allow_singletons,
        ):
            self._add_clue(state, phrase, "catalog_fallback")

    def _rank(self, state: Session) -> list[str]:
        category_key = normalize(state.category)
        category_set = set(self.coarse_category_to_asins.get(category_key, set()))

        useful: list[tuple[Clue, set[str], str]] = []
        for clue in state.retrieval_evidence:
            matches, kind = self._clue_candidates(clue.text)
            if matches:
                useful.append((clue, matches, kind))

        negatives: list[set[str]] = []
        for clue in state.negative_evidence:
            matches, _kind = self._clue_candidates(clue.text)
            if matches:
                negatives.append(matches)

        pool = set(category_set) if category_set else set(self.asins)

        # Active intent always anchors the pool. Inactive historical evidence
        # may narrow that active pool only when compatible, so a stale/noisy
        # clue can never displace every candidate satisfying the new override.
        ordered_evidence = sorted(
            (
                item
                for item in useful
                if item[0].source != "catalog_fallback"
            ),
            key=lambda item: (not item[0].active, len(item[1])),
        )
        for _clue, matches, _kind in ordered_evidence:
            narrowed = pool & matches
            if narrowed:
                pool = narrowed

        if negatives:
            forbidden = set().union(*negatives)
            narrowed = pool - forbidden
            if narrowed:
                pool = narrowed
            else:
                # Do not force explicitly forbidden products to the front just
                # because every member of the previous pool matched them.
                global_allowed = set(self.asins) - forbidden
                if global_allowed:
                    pool = global_allowed

        total = max(len(self.asins), 1)

        def score(asin: str) -> float:
            value = 2.0 if asin in category_set else 0.0
            for clue, matches, kind in useful:
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
            return value

        # Popularity is deliberately only a tie-break. A highly rated product
        # can never outrank a better constraint match, but among equally
        # relevant candidates the item with more ratings is the safer prior.
        def rank_key(asin: str) -> tuple[float, float, str]:
            return -score(asin), -self.rating_numbers[asin], asin

        ranked_pool = sorted(pool, key=rank_key)
        outside = sorted(
            (asin for asin in self.asins if asin not in pool),
            key=rank_key,
        )
        return ranked_pool + outside

    def debug_state(self, session_id: str) -> dict:
        """Return deterministic state for tests and a future demo wrapper."""

        state = self.sessions[session_id]

        def dump(clue: Clue) -> dict:
            return {
                "text": clue.text,
                "source": clue.source,
                "slot": clue.slot,
                "values": list(clue.values),
                "active": clue.active,
                "searchable": clue.searchable,
                "superseded": clue.superseded,
                "negated": clue.negated,
            }

        return {
            "category": state.category,
            "current_intent": [dump(clue) for clue in state.current_intent],
            "retrieval_evidence": [dump(clue) for clue in state.retrieval_evidence],
            "negative_evidence": [dump(clue) for clue in state.negative_evidence],
            "history": [dump(clue) for clue in state.evidence],
            "other_calls": state.other_calls,
            "shown_count": len(state.shown),
        }

    @staticmethod
    def _recommendation_limit(turn: int, requested_top_k: int) -> int:
        requested = max(0, min(int(requested_top_k), 10))
        early_limit = EARLY_RECOMMENDATION_LIMITS.get(int(turn), 10)
        return min(requested, early_limit)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before respond")

        state = self.sessions[session_id]
        self._parse(state, user_message, turn)

        ranked = self._rank(state)
        limit = self._recommendation_limit(turn, top_k)
        unseen = [asin for asin in ranked if asin not in state.shown]
        chosen = unseen[:limit]
        if len(chosen) < limit:
            remaining = limit - len(chosen)
            chosen.extend(
                [asin for asin in ranked if asin not in chosen][:remaining]
            )
        state.shown.update(chosen)

        if state.other_calls < 3:
            ask_attribute: str | None = "other"
            state.other_calls += 1
        else:
            ask_attribute = None

        return {
            "message": (
                "What other requirements matter most to you?"
                if ask_attribute
                else "Here are the closest remaining matches."
            ),
            "ask_attribute": ask_attribute,
            "recommendations": [{"parent_asin": asin} for asin in chosen],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
