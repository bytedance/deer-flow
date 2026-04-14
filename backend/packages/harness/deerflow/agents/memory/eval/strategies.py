from __future__ import annotations

from datetime import UTC, datetime

from deerflow.agents.memory.eval.types import RankedFact
from deerflow.agents.memory.retrieval_trace import CandidateFact

try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False


def _estimate_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Estimate token count for *text*.

    Uses tiktoken when available (accurate for CJK / mixed-script content),
    otherwise falls back to ``len(text) // 4`` which is a reasonable
    approximation for ASCII-heavy English but under-counts for Chinese.

    Note: ``prompt.py`` already contains a near-identical ``_count_tokens``
    helper, but it is module-private (leading underscore) and ``prompt.py``
    is a protected file that must not be modified.  Duplicating the tiny
    function here keeps the eval module self-contained without breaking
    encapsulation or touching protected code.
    """
    if not _TIKTOKEN_AVAILABLE:
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        return len(text) // 4


class ConfidenceOnlyStrategy:
    @property
    def name(self) -> str:
        return "confidence_only"

    def rank(self, candidates: list[CandidateFact], *, max_tokens: int) -> list[RankedFact]:
        ranked = sorted(enumerate(candidates), key=lambda item: item[1].confidence, reverse=True)
        results: list[RankedFact] = []
        tokens_used = 0

        for new_rank, (original_rank, fact) in enumerate(ranked):
            token_cost = _estimate_tokens(fact.content_preview)
            included = tokens_used + token_cost <= max_tokens
            if included:
                tokens_used += token_cost
            results.append(
                RankedFact(
                    fact_id=fact.fact_id,
                    category=fact.category,
                    original_rank=original_rank,
                    new_rank=new_rank,
                    score=fact.confidence,
                    score_components={"confidence": fact.confidence},
                    included=included,
                    token_cost=token_cost,
                )
            )

        return results


class MultiSignalStrategy:
    _CATEGORY_BOOSTS = {
        "correction": 1.3,
        "preference": 1.1,
        "knowledge": 1.0,
        "goal": 1.0,
        "context": 0.9,
        "behavior": 0.9,
    }

    def __init__(self, *, reference_time: datetime | None = None) -> None:
        self._reference_time = reference_time or datetime.now(UTC)

    @property
    def name(self) -> str:
        return "multi_signal"

    def rank(self, candidates: list[CandidateFact], *, max_tokens: int) -> list[RankedFact]:
        scored: list[tuple[int, CandidateFact, float, float, float, float]] = []
        for original_rank, fact in enumerate(candidates):
            confidence = fact.confidence
            recency = self._recency_score(fact.created_at)
            category_boost = self._CATEGORY_BOOSTS.get(fact.category, 1.0)
            composite = 0.4 * confidence + 0.35 * recency + 0.25 * category_boost
            scored.append((original_rank, fact, confidence, recency, category_boost, composite))

        ranked = sorted(scored, key=lambda item: item[5], reverse=True)
        results: list[RankedFact] = []
        tokens_used = 0

        for new_rank, (original_rank, fact, confidence, recency, category_boost, composite) in enumerate(ranked):
            token_cost = _estimate_tokens(fact.content_preview)
            included = tokens_used + token_cost <= max_tokens
            if included:
                tokens_used += token_cost
            results.append(
                RankedFact(
                    fact_id=fact.fact_id,
                    category=fact.category,
                    original_rank=original_rank,
                    new_rank=new_rank,
                    score=composite,
                    score_components={
                        "confidence": confidence,
                        "recency": recency,
                        "category_boost": category_boost,
                        "composite": composite,
                    },
                    included=included,
                    token_cost=token_cost,
                )
            )

        return results

    def _recency_score(self, created_at: str | None) -> float:
        if created_at is None:
            return 0.0

        try:
            created_at_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0

        if created_at_dt.tzinfo is None:
            created_at_dt = created_at_dt.replace(tzinfo=UTC)

        age_days = (self._reference_time - created_at_dt).days
        return 0.5 ** (age_days / 30)
