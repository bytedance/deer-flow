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

import math
import re
from collections.abc import Iterator
from itertools import islice
from typing import Any

try:
    import jieba

    _jieba_available = True
except ImportError:  # pragma: no cover - exercised via the tokenizer fallback
    _jieba_available = False

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]+")

#: A token pair overlaps when the tokens are equal or one is a prefix of the
#: other (minimum 4 characters so short words do not over-match).
_PREFIX_MATCH_MIN_CHARS = 4

#: Shared bound for lexical ranking and near-duplicate similarity.
_SIMILARITY_TOKEN_BUDGET = 128
_TEXT_CHAR_BUDGET = 4096


def warm_tokenizer() -> None:
    """Load the optional segmenter's dictionary off the first-request path."""
    if _jieba_available:
        jieba.initialize()


def tokenize(text: str) -> list[str]:
    """Tokenize at most 4096 characters into at most 128 relevance tokens.

    Space-free CJK text without jieba falls back to character bigrams so
    Chinese queries still produce deterministic token overlap.
    """
    if not text:
        return []
    lowered = text[:_TEXT_CHAR_BUDGET].strip().lower()
    if _jieba_available:
        return list(islice((token for token in jieba.cut(lowered) if token.strip()), _SIMILARITY_TOKEN_BUDGET))

    def fallback_tokens() -> Iterator[str]:
        for match in _WORD_RE.finditer(lowered):
            part = match.group()
            if "\u3400" <= part[0] <= "\u9fff":
                if len(part) == 1:
                    yield part
                else:
                    for index in range(len(part) - 1):
                        yield part[index : index + 2]
            else:
                yield part

    return list(islice(fallback_tokens(), _SIMILARITY_TOKEN_BUDGET))


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
    """IDF-weighted query coverage in ``[0, 1]``.

    A containment signal (whole query inside the content, or vice versa)
    contributes one matched unit so unsegmented text such as CJK
    content still scores above zero without a segmenter.
    """
    query_text = (query or "")[:_TEXT_CHAR_BUDGET].strip().lower()
    return _lexical_relevance(query_text, tokenize(query_text), content, idf=idf)


def _lexical_relevance(query_text: str, query_tokens: list[str], content: str, *, idf: dict[str, float] | None) -> float:
    """Score coverage of a prepared query against bounded content tokens."""
    content_text = (content or "")[:_TEXT_CHAR_BUDGET].strip().lower()
    if not query_text or not content_text:
        return 0.0

    content_tokens = tokenize(content_text)
    containment = (query_text in content_text) or (content_text in query_text)
    if not query_tokens and not containment:
        return 0.0

    weights = idf or {}
    content_set = set(content_tokens)
    prefixes = {token[:_PREFIX_MATCH_MIN_CHARS] for token in content_set if len(token) >= _PREFIX_MATCH_MIN_CHARS}
    # Each distinct query token contributes its squared IDF at most once.
    # Compare the matched-query norm to the complete-query norm: repetition
    # cannot replace missing terms, and the result needs no clipping. The
    # norm ratio keeps useful partial matches competitive in confidence blends.
    matched_weight = total_weight = 1.0 if containment else 0.0
    for token in dict.fromkeys(query_tokens):
        weight = weights.get(token, 1.0) ** 2
        total_weight += weight
        if token in content_set or (len(token) >= _PREFIX_MATCH_MIN_CHARS and token[:_PREFIX_MATCH_MIN_CHARS] in prefixes):
            matched_weight += weight
    return math.sqrt(matched_weight / total_weight) if total_weight > 0.0 else 0.0


def _coerce_confidence(fact: dict[str, Any]) -> float:
    try:
        value = float(fact.get("confidence"))
        if not math.isfinite(value):
            raise ValueError
    except (TypeError, ValueError):
        return 0.0
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

    query_text = (query or "")[:_TEXT_CHAR_BUDGET].strip().lower()
    query_tokens = tokenize(query_text)
    scored: list[tuple[float, dict[str, Any]]] = []
    for fact in facts:
        content = fact.get("content")
        relevance = _lexical_relevance(query_text, query_tokens, content, idf=idf) if isinstance(content, str) else 0.0
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


def diversify(
    scored: list[tuple[float, dict[str, Any]]],
    *,
    similarity_weight: float,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Greedy MMR over ``(score, fact)`` pairs; returns facts (no mutation).

    ``similarity_weight == 0`` returns the score order unchanged.
    """
    ordered = iter_diversify(scored, similarity_weight=similarity_weight)
    return list(islice(ordered, max(0, limit))) if limit is not None else list(ordered)


def iter_diversify(scored: list[tuple[float, dict[str, Any]]], *, similarity_weight: float) -> Iterator[dict[str, Any]]:
    """Lazy MMR: tokenize each fact once and update penalties once per pick.

    Consumers can stop at their result or token budget without ranking the rest.
    Equal adjusted scores retain their input order.
    """
    if similarity_weight <= 0.0:
        yield from (fact for _, fact in scored)
        return
    token_sets = [set(tokenize(fact["content"])) if isinstance(fact.get("content"), str) else set() for _, fact in scored]
    remaining = list(range(len(scored)))
    penalties = [0.0] * len(scored)
    while remaining:
        best_index = 0
        best_adjusted = -math.inf
        for index, fact_index in enumerate(remaining):
            adjusted = scored[fact_index][0] - similarity_weight * penalties[fact_index]
            if adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        picked_index = remaining.pop(best_index)
        yield scored[picked_index][1]
        picked_tokens = token_sets[picked_index]
        for fact_index in remaining:
            tokens = token_sets[fact_index]
            similarity = len(tokens & picked_tokens) / len(tokens | picked_tokens) if tokens and picked_tokens else 0.0
            penalties[fact_index] = max(penalties[fact_index], similarity)


def order_facts_for_query(
    facts: list[dict[str, Any]],
    query: str,
    *,
    relevance_weight: float = 0.5,
    diversity_weight: float = 0.0,
    idf: dict[str, float] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Score by relevance+confidence, then diversify; used by search/injection."""
    scored = score_facts(facts, query, relevance_weight=relevance_weight, idf=idf)
    return diversify(scored, similarity_weight=diversity_weight, limit=limit)
