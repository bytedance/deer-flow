"""Shared search utilities for memory fact retrieval.

Provides both keyword-based and vector-based search, used by:
- ``forget_tool`` (keyword + optional vector)
- ``search_memory_tool`` (keyword + vector)
- ``format_memory_for_injection`` (vector ranking)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from deerflow.agents.memory.embeddings import cosine_similarity

logger = logging.getLogger(__name__)


def compute_keyword_score(content: str, query: str) -> float:
    """Compute a keyword-relevance score between content and a search query.

    Uses substring match + word overlap. Returns a float, higher = more relevant.
    """
    content_lower = content.casefold()
    query_lower = query.casefold()

    score = 0.0

    # Direct substring match — big boost
    if query_lower in content_lower:
        score += 10.0

    # Word-level overlap
    query_words = set(re.findall(r"[a-zA-Z一-鿿]+", query_lower))
    content_words = set(re.findall(r"[a-zA-Z一-鿿]+", content_lower))

    if query_words and content_words:
        overlap = len(query_words & content_words)
        score += overlap / max(len(query_words), 1) * 5.0

    return score


def rank_facts(
    facts: list[dict[str, Any]],
    query: str,
    *,
    max_results: int = 10,
    keyword_weight: float = 0.3,
    vector_weight: float = 0.7,
) -> list[tuple[dict[str, Any], float]]:
    """Rank facts by relevance to a query, combining keyword + vector scores.

    Args:
        facts: List of fact dicts (must have 'content'; may have 'embedding').
        query: Search query string.
        max_results: Maximum results to return.
        keyword_weight: Weight for keyword-match score (0-1).
        vector_weight: Weight for embedding cosine similarity (0-1).

    Returns:
        List of ``(fact, combined_score)`` tuples, highest score first.
    """
    query_embedding = None  # lazy: compute once

    scored: list[tuple[dict[str, Any], float]] = []
    for fact in facts:
        content = fact.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue

        # Keyword score
        kw_score = compute_keyword_score(content, query)

        # Vector score (only if fact has an embedding)
        vec_score = 0.0
        fact_embedding = fact.get("embedding")
        if fact_embedding and isinstance(fact_embedding, list) and len(fact_embedding) > 0:
            if query_embedding is None:
                from deerflow.agents.memory.embeddings import compute_embedding

                query_embedding = compute_embedding(query)
            vec_score = cosine_similarity(query_embedding, fact_embedding)

        combined = keyword_weight * kw_score + vector_weight * vec_score
        scored.append((fact, combined))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_results]


def find_facts_by_content(
    facts: list[dict[str, Any]],
    query: str,
    *,
    max_results: int = 5,
    min_score: float = 0.5,
) -> list[tuple[dict[str, Any], float]]:
    """Simple keyword-based fact search. Backward-compatible alias.

    Uses only keyword scoring (no vector). Good for exact-match use cases
    like ``forget_tool`` where you want literal matches, not semantic.
    """
    scored: list[tuple[dict[str, Any], float]] = []
    for fact in facts:
        content = fact.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        score = compute_keyword_score(content, query)
        if score >= min_score:
            scored.append((fact, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_results]


def format_fact_list(facts: list[tuple[dict[str, Any], float]], title: str = "Memories") -> str:
    """Format ranked facts into a human-readable string.

    Args:
        facts: List of ``(fact, score)`` tuples.
        title: Section title.

    Returns:
        Formatted string, or ``"No matches."`` if empty.
    """
    if not facts:
        return "No matches."

    lines = [
        f"<{title}>",
    ]
    for i, (fact, score) in enumerate(facts, 1):
        content = fact.get("content", "(empty)")
        cat = fact.get("category", "?")
        conf = fact.get("confidence", "?")
        # Show vector score when available and > 0
        has_vec = bool(fact.get("embedding"))
        score_str = f"rel={score:.2f}" if has_vec else ""
        lines.append(f'  {i}. [{cat}|{conf}] {content}  {score_str}')

    lines.append(f"</{title}>")
    return "\n".join(lines)
