"""Skill catalog — deferred skill discovery at runtime.

Mirrors ``DeferredToolCatalog`` from ``tool_search.py``: an immutable, searchable
catalog that lets the LLM discover skill metadata on demand rather than having
every skill's full description baked into the system prompt.

The agent sees skill names in ``<skill_index>`` but cannot read their metadata
until it calls ``describe_skill``.  This keeps the system prompt compact and
prefix-cache friendly while still giving the model autonomous skill discovery.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)

MAX_RESULTS = 5
MAX_QUERY_CHARS = 256
MAX_QUERY_TERMS = 16

_NAME_SEPARATOR_RE = re.compile(r"[-_./]+")
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_IGNORED_SINGLE_ASCII_TERMS = frozenset({"a", "i"})


def _normalize_search_text(value: str) -> str:
    """Return Unicode-normalized, separator-aware text for matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _NAME_SEPARATOR_RE.sub(" ", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _query_terms(query: str) -> tuple[str, ...]:
    """Extract a bounded set of unique literal intent terms.

    The English article/pronoun ``a``/``I`` are discarded because they would
    otherwise match almost every catalog entry. Other single-character terms
    stay meaningful for skills such as C++ or R.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for term in _TOKEN_RE.findall(_normalize_search_text(query[:MAX_QUERY_CHARS])):
        if term in _IGNORED_SINGLE_ASCII_TERMS:
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) == MAX_QUERY_TERMS:
            break
    return tuple(terms)


def _contains_term(text: str, term: str) -> bool:
    if len(term) == 1 and term.isascii():
        return term in _TOKEN_RE.findall(text)
    return term in text


def _intent_score(skill: Skill, *, normalized_query: str, terms: tuple[str, ...]) -> tuple[int, int, int, int, int] | None:
    """Score one skill by intent coverage without external retrieval state."""
    normalized_name = _normalize_search_text(skill.name)
    normalized_description = _normalize_search_text(skill.description or "")
    name_matches = tuple(_contains_term(normalized_name, term) for term in terms)
    description_matches = tuple(_contains_term(normalized_description, term) for term in terms)
    name_hits = sum(name_matches)
    matched_terms = sum(name_match or description_match for name_match, description_match in zip(name_matches, description_matches, strict=True))
    if not matched_terms:
        return None

    return (
        int(normalized_name == normalized_query),
        matched_terms,
        int(normalized_query in normalized_name),
        name_hits,
        int(normalized_query in normalized_description),
    )


def _rank_by_intent(skills: list[Skill], query: str, *, include_unmatched: bool = False) -> list[Skill]:
    normalized_query = _normalize_search_text(query)
    terms = _query_terms(query)
    if not normalized_query or not terms:
        return skills[:MAX_RESULTS] if include_unmatched else []

    scored: list[tuple[tuple[int, int, int, int, int], Skill]] = []
    unmatched: list[Skill] = []
    for skill in skills:
        score = _intent_score(skill, normalized_query=normalized_query, terms=terms)
        if score is None:
            unmatched.append(skill)
        else:
            scored.append((score, skill))

    # Python's sort is stable, so equal-score skills retain catalog order.
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [skill for _, skill in scored]
    if include_unmatched:
        ranked.extend(unmatched)
    return ranked[:MAX_RESULTS]


# NOTE: frozen=True without slots=True keeps __dict__, which is what lets the
# @cached_property fields below cache (they write to instance.__dict__, bypassing
# the frozen __setattr__). Do NOT add slots=True or hash/names break at runtime.
@dataclass(frozen=True)
class SkillCatalog:
    """Immutable catalog of skills.  Pure search, no mutation.

    Query forms (mirror ``DeferredToolCatalog.search``):

    - ``"select:data-analysis,deep-research"`` — exact match by name.
    - ``"+podcast gen"`` — require *podcast* in the name, rank by *gen*.
    - ``"chart visualization"`` — multi-term intent match on name + description.
    """

    skills: tuple[Skill, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        """All skill names in insertion order."""
        return frozenset(s.name for s in self.skills)

    def search(self, query: str) -> list[Skill]:
        """Match *query* against skill names and descriptions.

        Returns at most ``MAX_RESULTS`` skills, ranked by relevance.
        """
        query = query[:MAX_QUERY_CHARS].strip()
        if not query:
            return []

        # ── Exact selection ────────────────────────────────────────────
        if query.startswith("select:"):
            wanted = {n.strip() for n in query[7:].split(",")}
            return [s for s in self.skills if s.name in wanted]

        # ── Required-prefix search ─────────────────────────────────────
        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []  # bare "+" with no required token
            required = _normalize_search_text(parts[0])
            if not _TOKEN_RE.search(required):
                return []
            candidates = [s for s in self.skills if required in _normalize_search_text(s.name)]
            if len(parts) > 1:
                return _rank_by_intent(candidates, parts[1], include_unmatched=True)
            return candidates[:MAX_RESULTS]

        # ── Free-text intent search ────────────────────────────────────
        return _rank_by_intent(list(self.skills), query)
