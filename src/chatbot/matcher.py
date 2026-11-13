"""Lightweight NLU: map free text to the most likely support query type.

Uses only the standard library (``difflib``) — no heavy ML dependencies.
The matcher combines two signals:

1. **Keyword overlap** — how many of a query type's keywords appear in the
   user's text (token-aware, so "refund" matches "refunds").
2. **Fuzzy ratio** — ``difflib.SequenceMatcher`` similarity between the text
   and each keyword, to tolerate typos like "refnud".

The two signals are blended into a single confidence score in ``[0, 1]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .knowledge import get_query_types

# Minimum confidence required before we trust a free-text match. Below this we
# treat the input as ambiguous and either fall back to AI or escalate.
DEFAULT_THRESHOLD = 0.30

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into word tokens."""
    return _TOKEN_RE.findall(text.lower())


def _fuzzy_ratio(a: str, b: str) -> float:
    """Return a 0..1 similarity ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class MatchResult:
    """Result of matching free text against the knowledge base.

    Attributes:
        query_id: The id of the best-matching query type (e.g. ``"returns"``).
        label: Human-readable label of that query type.
        score: Confidence score in ``[0, 1]``.
        confident: ``True`` when ``score`` meets the threshold.
    """

    query_id: str | None
    label: str | None
    score: float
    confident: bool


def _score_query_type(tokens: list[str], raw_text: str, qt: dict[str, Any]) -> float:
    """Compute a blended confidence score for one query type."""
    keywords: list[str] = [k.lower() for k in qt.get("keywords", [])]
    if not keywords:
        return 0.0

    token_set = set(tokens)
    overlap_hits = 0
    best_fuzzy = 0.0

    for kw in keywords:
        kw_tokens = kw.split()
        # Multi-word keyword: count it as a hit if the whole phrase appears.
        if len(kw_tokens) > 1:
            if kw in raw_text:
                overlap_hits += 2  # phrase matches are strong signals
            continue
        # Single-word keyword: exact token membership.
        if kw in token_set:
            overlap_hits += 1
        # Fuzzy comparison against each user token (typo tolerance).
        for tok in tokens:
            if len(tok) >= 3 and len(kw) >= 3:
                ratio = _fuzzy_ratio(tok, kw)
                if ratio > best_fuzzy:
                    best_fuzzy = ratio

    # Normalise overlap by a soft cap so a couple of strong hits suffice.
    overlap_score = min(overlap_hits / 3.0, 1.0)

    # Only count high fuzzy ratios; ignore weak coincidental similarity.
    fuzzy_score = best_fuzzy if best_fuzzy >= 0.75 else 0.0

    # Blend: keyword overlap is the primary signal, fuzzy is supporting.
    return round(0.7 * overlap_score + 0.3 * fuzzy_score, 4)


def match(text: str, threshold: float = DEFAULT_THRESHOLD) -> MatchResult:
    """Match free text to the best query type.

    Args:
        text: The user's typed message.
        threshold: Minimum score to be considered a confident match.

    Returns:
        A :class:`MatchResult`. When nothing scores above ``threshold`` the
        result has ``confident=False`` (caller may use AI fallback / escalate),
        but ``query_id`` still holds the best guess (or ``None`` if no signal).
    """
    tokens = _tokenize(text)
    raw_text = text.lower()

    best_id: str | None = None
    best_label: str | None = None
    best_score = 0.0

    for qt in get_query_types():
        # "other" is a catch-all; don't let it win on weak signals.
        score = _score_query_type(tokens, raw_text, qt)
        if score > best_score:
            best_score = score
            best_id = qt.get("id")
            best_label = qt.get("label")

    return MatchResult(
        query_id=best_id if best_score > 0 else None,
        label=best_label if best_score > 0 else None,
        score=best_score,
        confident=best_score >= threshold,
    )
