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
from dataclasses import dataclass
from functools import cached_property

from deerflow.skills.types import Skill

logger = logging.getLogger(__name__)

MAX_RESULTS = 5


def _compile_catalog_regex(pattern: str) -> re.Pattern[str]:
    """Compile ``pattern`` case-insensitively, falling back to literal match.

    Search queries come from the model, so an invalid regex (e.g. an unbalanced
    paren) must degrade to a literal substring match rather than raise.
    """
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


# NOTE: frozen=True without slots=True keeps __dict__, which is what lets the
# @cached_property fields below cache (they write to instance.__dict__, bypassing
# the frozen __setattr__). Do NOT add slots=True or hash/names break at runtime.
@dataclass(frozen=True)
class SkillCatalog:
    """Immutable catalog of skills.  Pure search, no mutation.

    Query forms (mirror ``DeferredToolCatalog.search``):

    - ``"select:data-analysis,deep-research"`` — exact match by name.
    - ``"+podcast gen"`` — require *podcast* in the name, rank by *gen*.
    - ``"chart visualization"`` — regex match on name + description.
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
        query = query.strip()
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
            required = parts[0].lower()
            candidates = [s for s in self.skills if required in s.name.lower()]
            if len(parts) > 1:
                pattern = _compile_catalog_regex(parts[1])
                candidates.sort(
                    key=lambda s: _catalog_regex_score(pattern, s),
                    reverse=True,
                )
            return candidates[:MAX_RESULTS]

        # ── Free-text regex search ─────────────────────────────────────
        regex = _compile_catalog_regex(query)
        scored: list[tuple[int, Skill]] = []
        for s in self.skills:
            searchable = f"{s.name} {s.description or ''}"
            if regex.search(searchable):
                # Name match scores higher than description-only match.
                scored.append((2 if regex.search(s.name) else 1, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored][:MAX_RESULTS]


def _catalog_regex_score(pattern: re.Pattern[str], s: Skill) -> int:
    """Count regex hits across name + description for ranking."""
    return len(pattern.findall(f"{s.name} {s.description or ''}"))
