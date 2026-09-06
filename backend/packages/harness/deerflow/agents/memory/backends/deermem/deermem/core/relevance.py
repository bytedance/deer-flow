"""Deterministic lexical relevance ranking for DeerMem retrieval.

Pure-Python and network-free helpers behind the optional relevance-aware
retrieval strategy (issue #4495):

- ``lexical_relevance`` — idf-weighted token overlap between a query and a
  fact's content, plus a containment signal so unsegmented (CJK) text stays
  usable without jieba;
- ``score_facts`` / ``rank_facts`` — combine lexical relevance with the
  existing fact confidence (``relevance_weight * relevance +
  (1 - relevance_weight) * confidence``);
- ``diversify`` — greedy MMR selection that demotes near-duplicate facts.

All helpers treat caller-owned fact dicts as read-only; ranking returns new
lists. Token matching is case-insensitive with prefix matching for shared
stems (``database``/``databases``), mirroring the retrieval layer's
dependency-free style.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    import jieba

    _jieba_available = True
except ImportError:  # pragma: no cover - exercised via the tokenizer fallback
    _jieba_available = False

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")

#: A token pair overlaps when the tokens are equal or one is a prefix of the
#: other (minimum 4 characters so short words do not over-match).
_PREFIX_MATCH_MIN_CHARS = 4

#: How many content tokens participate in near-duplicate similarity.
_SIMILARITY_TOKEN_BUDGET = 128


def tokenize(text: str) -> list[str]:
    """Tokenize for relevance scoring (jieba when available, else words).

    Space-free CJK text without jieba falls back to character bigrams so
    Chinese queries still produce deterministic token overlap.
    """
    if not text or not text.strip():
        return []
    lowered = text.strip().lower()
    if _jieba_available:
        return [token for token in jieba.cut(lowered) if token.strip()]
    tokens = _WORD_RE.findall(lowered)
    if tokens:
        return tokens
    parts = lowered.split()
    if len(parts) == 1 and any("一" <= char <= "鿿" for char in lowered):
        return [lowered[index : index + 2] for index in range(len(lowered) - 1)]
    return [part for part in parts if part]


def _common_prefix_length(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def _tokens_overlap(left: str, right: str) -> bool:
    """Match equal tokens, full-word prefixes, or a shared stem (>=4 chars).

    The shared-stem rule covers inflection without a stemmer: ``linting``
    matches ``lints`` via their common prefix ``lint``, while short words
    like ``cat`` never match ``category``.
    """
    # Single-character tokens are stopword-like noise; never match them.
    if len(left) < 2 or len(right) < 2:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if longer.startswith(shorter):
        return len(shorter) >= 4
    return _common_prefix_length(left, right) >= _PREFIX_MATCH_MIN_CHARS


def build_idf(corpus: list[list[str]]) -> dict[str, float]:
    """Smoothed inverse document frequency over a token corpus.

    Tokens shared by every document get the smallest weight (1.0); rarer
    tokens get larger weights. Tokens absent from the corpus are handled by
    ``lexical_relevance`` with the default weight.
    """
    document_count = len(corpus)
    if document_count == 0:
        return {}
    document_frequency: dict[str, int] = {}
    for tokens in corpus:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    return {token: math.log((document_count + 1) / (frequency + 1)) + 1.0 for token, frequency in document_frequency.items()}


def lexical_relevance(
    query: str,
    content: str,
    *,
    idf: dict[str, float] | None = None,
) -> float:
    """Cosine similarity of idf-weighted token sets in ``[0, 1]``.

    A containment signal (whole query inside the content, or vice versa)
    joins both vectors as a synthetic token so unsegmented text such as CJK
    content still scores above zero without a segmenter.
    """
    query_text = (query or "").strip().lower()
    content_text = (content or "").strip().lower()
    if not query_text or not content_text:
        return 0.0

    query_tokens = tokenize(query_text)
    content_tokens = tokenize(content_text)
    containment = (query_text in content_text) or (content_text in query_text)
    if not query_tokens and not containment:
        return 0.0

    weights = idf or {}
    default_weight = 1.0

    def weighted_vector(tokens: list[str], synthetic: bool) -> dict[str, float]:
        vector: dict[str, float] = {}
        for token in tokens:
            vector[token] = vector.get(token, 0.0) + weights.get(token, default_weight)
        if synthetic:
            vector[query_text] = vector.get(query_text, 0.0) + default_weight
        return vector

    query_vector = weighted_vector(query_tokens, synthetic=containment)
    content_vector = weighted_vector(content_tokens, synthetic=containment)
    if not content_vector:
        return 0.0

    overlap = 0.0
    for token, query_weight in query_vector.items():
        content_weight = content_vector.get(token, 0.0)
        if content_weight > 0.0:
            overlap += query_weight * content_weight
            continue
        for content_token, token_weight in content_vector.items():
            if _tokens_overlap(token, content_token):
                overlap += query_weight * token_weight
                break

    if overlap <= 0.0:
        return 0.0

    # Query-side normalization only: the score measures how much of the query
    # a fact covers and applies no length penalty to longer facts. For a
    # fixed query this is monotone in the matched weight, so ranking order
    # follows the idf-weighted overlap.
    query_norm = math.sqrt(sum(weight * weight for weight in query_vector.values()))
    if query_norm == 0.0:
        return 0.0
    return min(1.0, overlap / query_norm)


def _coerce_confidence(fact: dict[str, Any]) -> float:
    try:
        value = float(fact.get("confidence"))
        if not math.isfinite(value):
            raise ValueError
    except (TypeError, ValueError):
        return 0.5
    return min(1.0, max(0.0, value))


def score_facts(
    facts: list[dict[str, Any]],
    query: str,
    *,
    relevance_weight: float = 0.5,
    idf: dict[str, float] | None = None,
) -> list[tuple[float, dict[str, Any]]]:
    """Return ``(combined_score, fact)`` pairs sorted descending (no mutation).

    ``relevance_weight == 0`` short-circuits to the legacy confidence-only
    ordering without computing relevance.
    """
    if relevance_weight <= 0.0:
        return [
            (confidence, fact)
            for confidence, fact in sorted(
                ((_coerce_confidence(fact), fact) for fact in facts),
                key=lambda pair: pair[0],
                reverse=True,
            )
        ]

    scored: list[tuple[float, dict[str, Any]]] = []
    for fact in facts:
        content = fact.get("content")
        relevance = lexical_relevance(query, content, idf=idf) if isinstance(content, str) else 0.0
        confidence = _coerce_confidence(fact)
        combined = relevance_weight * relevance + (1.0 - relevance_weight) * confidence
        scored.append((combined, fact))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored


def rank_facts(
    facts: list[dict[str, Any]],
    query: str,
    *,
    relevance_weight: float = 0.5,
    idf: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Convenience wrapper: ``score_facts`` without the scores."""
    return [fact for _, fact in score_facts(facts, query, relevance_weight=relevance_weight, idf=idf)]


def _content_similarity(left: str, right: str) -> float:
    """Jaccard similarity over bounded, case-folded token sets."""
    left_set = set(tokenize(left)[:_SIMILARITY_TOKEN_BUDGET])
    right_set = set(tokenize(right)[:_SIMILARITY_TOKEN_BUDGET])
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def diversify(
    scored: list[tuple[float, dict[str, Any]]],
    *,
    similarity_weight: float,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Greedy MMR over ``(score, fact)`` pairs; returns facts (no mutation).

    ``similarity_weight == 0`` returns the score order unchanged.
    """
    if similarity_weight <= 0.0 or not scored:
        ordered = [fact for _, fact in scored]
        return ordered[:limit] if limit is not None else ordered

    remaining = list(scored)
    picked: list[tuple[float, dict[str, Any]]] = []
    while remaining and (limit is None or len(picked) < limit):
        best_index = 0
        best_adjusted = -math.inf
        for index, (score, fact) in enumerate(remaining):
            content = fact.get("content")
            content_text = content if isinstance(content, str) else ""
            worst_similarity = 0.0
            for _, picked_fact in picked:
                picked_content = picked_fact.get("content")
                picked_text = picked_content if isinstance(picked_content, str) else ""
                similarity = _content_similarity(content_text, picked_text)
                if similarity > worst_similarity:
                    worst_similarity = similarity
            adjusted = score - similarity_weight * worst_similarity
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        picked.append(remaining.pop(best_index))
    return [fact for _, fact in picked]


def order_facts_for_query(
    facts: list[dict[str, Any]],
    query: str,
    *,
    relevance_weight: float = 0.5,
    diversity_weight: float = 0.0,
    idf: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Score by relevance+confidence, then diversify; used by search/injection."""
    scored = score_facts(facts, query, relevance_weight=relevance_weight, idf=idf)
    if diversity_weight > 0.0:
        return diversify(scored, similarity_weight=diversity_weight)
    return [fact for _, fact in scored]
