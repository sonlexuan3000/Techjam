"""Lightweight, wrapper-tolerant parsing for the shopping simulator.

The participant inputs are short, pre-cleaned English messages.  The parser is
therefore deliberately deterministic and dependency-free: it recognizes event
families, preserves catalog-derived payload text, and leaves product matching to
the Agent.  It does not rewrite a hard constraint with a generative model.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_SMART_PUNCTUATION = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
)


@dataclass(frozen=True)
class ParsedMessage:
    """One state transition extracted from a user message."""

    category: str | None = None
    action: str = "none"
    payload: str | None = None
    source: str | None = None
    explicit_old_value: str | None = None


def _canonical_text(value: str) -> str:
    return value.translate(_SMART_PUNCTUATION)


def _clean_capture(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n\"'")
    value = re.sub(
        r"(?:,\s*)?(?:if possible|please|thanks|thank you)\s*[.!?]*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip()


_CATEGORY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bi(?:'m| am)\s+looking\s+for\s+(?P<value>.+?)(?=,\s*but\b|[.;]|$)",
        (
            r"\bi(?:'m| am)\s+shopping\s+for\s+(?P<value>.+?)"
            r"(?=,\s*(?:and|but)\b|\s+and\s+could\s+use\b|[.;]|$)"
        ),
        r"\bi(?:'m| am)\s+considering\s+(?P<value>.+?)(?=,\s*but\b|[.;]|$)",
        r"\bi(?:'m| am)\s+after\s+(?P<value>.+?)(?=\s*:|[.;]|$)",
        r"\bi\s+need\s+(?P<value>.+?)(?=[.;]|$)",
        r"\b(?:please\s+)?help\s+me\s+(?:find|explore)\s+(?P<value>.+?)(?=[.;]|$)",
        r"\bi(?:'d| would)\s+like\s+to\s+browse\s+(?P<value>.+?)(?=[.;]|$)",
        r"^\s*for\s+(?P<value>.+?)(?=,\s*(?:my|the|a)\b|[.;]|$)",
    )
)


def _extract_category(message: str) -> str | None:
    for pattern in _CATEGORY_PATTERNS:
        match = pattern.search(message)
        if match:
            category = _clean_capture(match.group("value"))
            if category:
                return category
    return None


_OVERRIDE_MARKERS = re.compile(
    r"\b(?:actually|changed?\s+my\s+mind|correction|set\s+aside|replace|"
    r"instead\s+of|ignore\s+(?:my\s+)?(?:earlier|previous)|no\s+longer\s+matters)\b",
    re.IGNORECASE,
)

_OVERRIDE_PAYLOAD_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwhat\s+i\s+need(?:\s+now)?\s+is\s*:\s*(?P<value>.+)$",
        r"\bmy\s+(?:new\s+)?requirement\s+is\s*:\s*(?P<value>.+)$",
        r"\bplease\s+prioritize\s*:\s*(?P<value>.+)$",
        r"\bwith\s+this\s+requirement\s*:\s*(?P<value>.+)$",
        r"\bmy\s+new\s+preference\s+is\s*:\s*(?P<value>.+)$",
        r"\bi\s+now\s+(?:need|want|prefer)\s*:\s*(?P<value>.+)$",
    )
)

_FROM_TO_OVERRIDE = re.compile(
    r"\b(?:switch|change|move)(?:\s+my\s+preference)?\s+from\s+"
    r"(?P<old>.+?)\s+to\s+(?P<new>.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)


def _extract_override(message: str) -> tuple[str, str | None] | None:
    from_to = _FROM_TO_OVERRIDE.search(message)
    if from_to:
        return _clean_capture(from_to.group("new")), _clean_capture(from_to.group("old"))

    if not _OVERRIDE_MARKERS.search(message):
        return None

    for pattern in _OVERRIDE_PAYLOAD_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        payload = _clean_capture(match.group("value"))
        explicit_old: str | None = None
        instead = re.match(r"(.+?)\s+instead\s+of\s+(.+)$", payload, re.IGNORECASE)
        if instead:
            payload = _clean_capture(instead.group(1))
            explicit_old = _clean_capture(instead.group(2))
        return payload, explicit_old
    return None


_NO_PREFERENCE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:do\s+not|don't)\s+have\b.*\b(?:preferences?|requirements?)\b",
        r"\bno\s+(?:(?:additional|extra|further)\s+)?(?:preferences?|requirements?)\b",
        r"\bnothing\s+else\s+(?:comes\s+to\s+mind|matters)\b",
        r"\bi(?:'m| am)\s+(?:open|flexible)\s+(?:on|about|there)\b",
        r"\bisn't\s+something\s+i\s+care\s+about\b",
        r"\bpreferences?\s+(?:are|is)\s+still\s+open\b",
        r"\b(?:have\s+not|haven't)\s+settled\s+on\b",
        r"\bno\s+firm\s+requirements?\b",
    )
)

_NO_ATTRIBUTE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bask\s+(?:me\s+)?(?:about\s+)?(?:one\s+)?(?:specific|focused|concrete|particular)\s+attribute\b",
        r"\bnarrow\s+(?:it|this)\s+down\s+first\b",
        r"\bnot\s+ready\s+to\s+choose\b",
        r"\baren't\s+quite\s+right\b",
    )
)


def _should_ignore(message: str) -> bool:
    return any(pattern.search(message) for pattern in (*_NO_PREFERENCE_PATTERNS, *_NO_ATTRIBUTE_PATTERNS))


_PAYLOAD_PATTERNS = tuple(
    (source, re.compile(pattern, re.IGNORECASE))
    for source, pattern in (
        ("revealed", r"\b(?:for\s+that,\s*)?what\s+matters\s+is\s*:\s*(?P<value>.+)$"),
        ("revealed", r"\bthese\s+points\s+matter\s+to\s+me\s*:\s*(?P<value>.+)$"),
        ("revealed", r"\bwhat\s+i\s+care\s+about\s+for\s+that\s*:\s*(?P<value>.+)$"),
        ("revealed", r"\bwhat\s+matters\s+to\s+me\s+(?:is|are)\s*:\s*(?P<value>.+)$"),
        ("revealed", r"\bmy\s+(?:main\s+)?priorities\s+are\s*:\s*(?P<value>.+)$"),
        ("revealed", r"\brelevant\s+requirements?\s+or\s+preferences?\s+are\s*:\s*(?P<value>.+)$"),
        ("revealed", r"\btake\s+these\s+into\s+account\s*:\s*(?P<value>.+)$"),
        ("initial_requirement", r"\ba\s+key\s+requirement\s+is\s*:\s*(?P<value>.+)$"),
        (
            "initial_requirement",
            r"\bone\s+requirement\s+i\s+can't\s+compromise\s+on\s+is\s*:\s*(?P<value>.+)$",
        ),
        ("initial_requirement", r"\bit\s+must\s+satisfy\s*:\s*(?P<value>.+)$"),
        ("initial_requirement", r"\bthis\s+is\s+essential\s*:\s*(?P<value>.+)$"),
        ("initial_requirement", r"\bmy\s+main\s+requirement\s+is\s*:\s*(?P<value>.+)$"),
        ("initial_requirement", r"\bthe\s+non-negotiable\s+is\s*:\s*(?P<value>.+)$"),
        (
            "initial_requirement",
            (
                r"\b(?:my|the)\s+(?:absolute|top|primary|most\s+important)\s+"
                r"(?:requirement|priority|must-have)\s+(?:is|would\s+be)\s*:?\s*"
                r"(?P<value>.+)$"
            ),
        ),
        (
            "initial_requirement",
            (
                r"\b(?:it|this|the\s+item|the\s+product)\s+(?:absolutely\s+)?must\s+"
                r"(?:be|have|include|support|offer)\s*:?\s*(?P<value>.+)$"
            ),
        ),
        ("initial_preference", r"\bone\s+thing\s+i\s+care\s+about\s+is\s*:\s*(?P<value>.+)$"),
        ("initial_preference", r"\bmy\s+current\s+preference\s+is\s*:\s*(?P<value>.+)$"),
        ("initial_preference", r"\bfor\s+now,?\s+i\s+prefer\s*:\s*(?P<value>.+)$"),
        ("initial_preference", r"\bi(?:'d| would)\s+like\s+this\s+if\s+possible\s*:\s*(?P<value>.+)$"),
    )
)


def _extract_payload(message: str) -> tuple[str, str] | None:
    for source, pattern in _PAYLOAD_PATTERNS:
        match = pattern.search(message)
        if match:
            payload = _clean_capture(match.group("value"))
            if payload:
                return source, payload
    return None


_NEGATION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:don't|do\s+not)\s+want\s+(?P<value>.+?)(?:\s+anymore|[.,]|$)",
        (
            r"^\s*(?:actually[,;]?\s*)?(?P<value>.+?)\s+is\s+no\s+longer\s+"
            r"acceptable(?:\s+to\s+me)?(?:[.,]|$)"
        ),
        r"\b(?:please\s+)?exclude\s+(?P<value>.+?)\s+from\s+(?:the\s+)?options?(?:[.,]|$)",
        r"\banything\s+but\s+(?P<value>.+?)(?:,\s*please|[.!]|$)",
        r"^\s*(?:actually[,;]?\s*)?(?:please\s+)?avoid\s+(?P<value>.+?)(?:[.,]|$)",
    )
)


def _extract_negation(message: str) -> str | None:
    for pattern in _NEGATION_PATTERNS:
        match = pattern.search(message)
        if match:
            value = _clean_capture(match.group("value"))
            if value:
                return value
    return None


def parse_message(message: str, *, turn: int) -> ParsedMessage:
    """Parse one message while preserving catalog-derived value strings.

    Ordering is intentional.  A disclosed feature may itself contain words like
    ``without`` or ``avoid``; recognized wrappers must win before standalone
    negation detection.
    """

    canonical = _canonical_text(str(message or ""))
    # The simulator introduces the category on turn one. Restricting category
    # extraction to that turn prevents a later answer such as ``I need cotton``
    # from replacing a missing category with a preference value.
    category = _extract_category(canonical) if turn == 1 else None

    override = _extract_override(canonical)
    if override:
        payload, explicit_old = override
        return ParsedMessage(
            category=category,
            action="override",
            payload=payload,
            source="override",
            explicit_old_value=explicit_old,
        )

    disclosed = _extract_payload(canonical)
    if disclosed:
        source, payload = disclosed
        return ParsedMessage(
            category=category,
            action="add",
            payload=payload,
            source=source,
        )

    # A single reply can say that one slot is flexible and still disclose a
    # different hard requirement. Explicit payload cues above therefore win.
    if _should_ignore(canonical):
        return ParsedMessage(category=category, action="ignore")

    negated = _extract_negation(canonical)
    if negated:
        return ParsedMessage(
            category=category,
            action="negate",
            payload=negated,
            source="negation",
        )

    # The official override session starts with ``category. raw preference``.
    # Named preference wrappers above are preferred; this retains compatibility
    # with the compact official form without treating browsing text as evidence.
    if turn == 1 and category and "." in canonical:
        remainder = canonical.split(".", 1)[1].strip()
        if remainder:
            return ParsedMessage(
                category=category,
                action="add",
                payload=remainder,
                source="compact_initial_preference",
            )

    return ParsedMessage(category=category)
