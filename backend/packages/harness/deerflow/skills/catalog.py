"""Skill catalog — deferred skill discovery at runtime.

Like ``DeferredToolCatalog`` from ``tool_search.py``, this immutable catalog
exposes metadata on demand instead of embedding full descriptions in prompts.
Query forms are shared, but skills intentionally use literal intent ranking
rather than the tool catalog's free-text regex matching.

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


@dataclass(frozen=True)
class _SearchEntry:
    skill: Skill
    normalized_name: str
    normalized_description: str


def _intent_score(entry: _SearchEntry, *, normalized_query: str, terms: tuple[str, ...]) -> tuple[int, int, int, int, int] | None:
    """Score one skill by intent coverage without external retrieval state."""
    normalized_name = entry.normalized_name
    normalized_description = entry.normalized_description
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


def _rank_by_intent(entries: tuple[_SearchEntry, ...], query: str, *, include_unmatched: bool = False) -> list[Skill]:
    normalized_query = _normalize_search_text(query)
    terms = _query_terms(query)
    if not normalized_query or not terms:
        return [entry.skill for entry in entries[:MAX_RESULTS]] if include_unmatched else []

    scored: list[tuple[tuple[int, int, int, int, int], Skill]] = []
    unmatched: list[Skill] = []
    for entry in entries:
        score = _intent_score(entry, normalized_query=normalized_query, terms=terms)
        if score is None:
            unmatched.append(entry.skill)
        else:
            scored.append((score, entry.skill))

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

    Query forms (shared with tool search; ranking semantics differ):

    - ``"select:data-analysis,deep-research"`` — exact match by name.
    - ``"+podcast gen"`` — require *podcast* in the name, rank by *gen*.
    - ``"chart visualization"`` — multi-term intent match on name + description.
    """

    skills: tuple[Skill, ...]

    @cached_property
    def names(self) -> frozenset[str]:
        """All skill names in insertion order."""
        return frozenset(s.name for s in self.skills)

    @cached_property
    def _search_index(self) -> tuple[_SearchEntry, ...]:
        """Normalize immutable skill metadata once per catalog, in catalog order."""
        return tuple(_SearchEntry(skill, _normalize_search_text(skill.name), _normalize_search_text(skill.description or "")) for skill in self.skills)

    def search(self, query: str) -> list[Skill]:
        """Match *query* against skill names and descriptions.

        Exact ``select:`` queries have no query-length or result cap.
        Other queries use at most ``MAX_QUERY_CHARS`` characters and return
        at most ``MAX_RESULTS`` skills, ranked by relevance.
        """
        query = query.strip()
        if not query:
            return []

        # ── Exact selection ────────────────────────────────────────────
        if query.startswith("select:"):
            wanted = {n.strip() for n in query[7:].split(",")}
            return [s for s in self.skills if s.name in wanted]

        query = query[:MAX_QUERY_CHARS]

        # ── Required-prefix search ─────────────────────────────────────
        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            if not parts:
                return []  # bare "+" with no required token
            required = _normalize_search_text(parts[0])
            if not _TOKEN_RE.search(required):
                return []
            candidates = tuple(entry for entry in self._search_index if required in entry.normalized_name)
            if len(parts) > 1:
                return _rank_by_intent(candidates, parts[1], include_unmatched=True)
            return [entry.skill for entry in candidates[:MAX_RESULTS]]

        # ── Free-text intent search ────────────────────────────────────
        return _rank_by_intent(self._search_index, query)
