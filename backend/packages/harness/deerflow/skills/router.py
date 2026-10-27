"""Dynamic Skill Router (Route C / RFC-003 Pillar 2).

Implements Just-In-Time (JIT) skill intent routing based on:
- Google Research harness2: "Always-On Prose is the Expensive Option"
- ai-agent-book Chapter 2: Dynamic Prompts and Agent Skills

Replaces static, bloated always-on prompt listings with instant, zero-LLM
intent matching, activating relevant skills on-demand to preserve prompt prefix
and maximize KV cache efficiency.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from deerflow.skills.types import Skill

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "it",
        "this",
        "that",
        "please",
        "can",
        "you",
        "me",
        "my",
        "we",
        "our",
        "help",
        "with",
        "do",
        "how",
        "what",
        "where",
        "请",
        "帮",
        "我",
        "做",
        "下",
        "的",
        "了",
        "和",
        "在",
        "用",
        "个",
        "怎么",
        "如何",
    }
)


def _extract_intent_tokens(text: str) -> set[str]:
    """Extract normalized meaningful intent tokens."""
    if not text:
        return set()
    norm = unicodedata.normalize("NFKC", text).casefold()
    tokens = set()
    for tok in _TOKEN_RE.findall(norm):
        if tok not in _STOP_WORDS and len(tok) > 1:
            tokens.add(tok)
    return tokens


@dataclass(frozen=True)
class SkillMatchResult:
    """Scored skill match for a given user query."""

    skill: Skill
    score: float
    matched_tokens: tuple[str, ...]
    is_name_match: bool


class DynamicSkillRouter:
    """Zero-LLM intent router for on-demand skill activation."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self.skills: list[Skill] = list(skills or [])

    def register_skill(self, skill: Skill) -> None:
        self.skills.append(skill)

    def route_intent(
        self,
        query: str,
        threshold: float = 0.3,
        top_k: int = 3,
    ) -> list[SkillMatchResult]:
        """Score candidate skills against query tokens and return relevant matches."""
        query_tokens = _extract_intent_tokens(query)
        if not query_tokens:
            return []

        scored_results: list[SkillMatchResult] = []

        for skill in self.skills:
            if not getattr(skill, "enabled", True):
                continue

            name_tokens = _extract_intent_tokens(skill.name)
            desc_tokens = _extract_intent_tokens(skill.description or "")

            # Exact name or prefix match has highest weight
            name_matches = query_tokens.intersection(name_tokens)
            desc_matches = query_tokens.intersection(desc_tokens)

            is_name_match = len(name_matches) > 0

            # Scoring:
            # - Name matches: 0.5 per matching token (up to 1.0)
            # - Description matches: 0.15 per matching token (up to 0.6)
            name_score = min(1.0, len(name_matches) * 0.5)
            desc_score = min(0.6, len(desc_matches) * 0.15)

            total_score = name_score + desc_score

            all_matched = tuple(sorted(name_matches.union(desc_matches)))

            if total_score >= threshold:
                scored_results.append(
                    SkillMatchResult(
                        skill=skill,
                        score=round(total_score, 3),
                        matched_tokens=all_matched,
                        is_name_match=is_name_match,
                    )
                )

        # Sort descending by score, then name match priority
        scored_results.sort(key=lambda r: (r.score, r.is_name_match), reverse=True)
        return scored_results[:top_k]

    def render_jit_skill_context(self, matched_results: list[SkillMatchResult]) -> str:
        """Render a concise system prompt context containing only the triggered skills."""
        if not matched_results:
            return ""

        lines = [
            "<activated_skills>",
            "The following specialized skills have been dynamically activated for this turn based on your task intent:",
            "",
        ]
        for match in matched_results:
            skill = match.skill
            lines.append(f"### Skill: {skill.name} (relevance: {match.score})")
            if skill.description:
                lines.append(f"Description: {skill.description}")
            if skill.allowed_tools:
                tools_str = ", ".join(skill.allowed_tools) if isinstance(skill.allowed_tools, (list, tuple)) else str(skill.allowed_tools)
                lines.append(f"Allowed Tools: {tools_str}")
            lines.append("")

        lines.append("</activated_skills>")
        return "\n".join(lines)
