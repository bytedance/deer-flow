"""Deterministic, explainable capacity policies for canonical memory facts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

EVICTION_POLICY_CONFIDENCE = "confidence"
EVICTION_POLICY_HYBRID_V1 = "hybrid-v1"


@dataclass(frozen=True)
class FactEvictionScore:
    """One fact's bounded policy score and its explainable components."""

    value: float
    components: dict[str, float]


@dataclass(frozen=True)
class EvictedFact:
    """Metadata-only record for a fact removed by the capacity limit."""

    fact_id: str
    category: str
    score: float
    components: dict[str, float]


@dataclass(frozen=True)
class FactEvictionDecision:
    """Complete result of applying a capacity policy to one snapshot."""

    kept: list[dict[str, Any]]
    evicted: list[EvictedFact]
    scores: dict[str, FactEvictionScore]
    policy: str
    reserved_correction_slots: int = 0


def _bounded_number(value: Any, *, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(number, 1.0))


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decay(*, elapsed_days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 0.0
    return 2 ** (-max(0.0, elapsed_days) / half_life_days)


def _confirmation_freshness(
    fact: dict[str, Any],
    *,
    now: datetime,
    half_life_days: float,
    decay_exempt: bool = False,
) -> float:
    confirmed_at = _parse_datetime(fact.get("lastConfirmedAt"))
    if confirmed_at is not None:
        if decay_exempt:
            return 1.0
        elapsed = (now - confirmed_at).total_seconds() / 86400
        return _decay(elapsed_days=elapsed, half_life_days=half_life_days)

    created_at = _parse_datetime(fact.get("createdAt"))
    if created_at is None:
        return 0.0
    if decay_exempt:
        return 0.5
    elapsed = (now - created_at).total_seconds() / 86400
    # Creation is weaker evidence than an explicit user confirmation.
    return 0.5 * _decay(elapsed_days=elapsed, half_life_days=half_life_days)


def _normalized_access_heat(
    usage: dict[str, Any] | None,
    *,
    now: datetime,
    half_life_days: float,
) -> float:
    if not isinstance(usage, dict):
        return 0.0
    last_accessed_at = _parse_datetime(usage.get("lastAccessedAt"))
    raw_heat = usage.get("accessHeat")
    if last_accessed_at is None or raw_heat is None or isinstance(raw_heat, bool):
        return 0.0
    try:
        heat = float(raw_heat)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(heat) or heat <= 0:
        return 0.0
    elapsed = (now - last_accessed_at).total_seconds() / 86400
    decayed_heat = heat * _decay(elapsed_days=elapsed, half_life_days=half_life_days)
    return min(1.0, math.log1p(decayed_heat) / math.log(9))


def _score_fact(
    fact: dict[str, Any],
    *,
    policy: str,
    usage: dict[str, Any] | None,
    now: datetime,
    confidence_weight: float,
    confirmation_weight: float,
    access_weight: float,
    confirmation_half_life_days: float,
    access_half_life_days: float,
    decay_exempt_categories: set[str] | None = None,
) -> FactEvictionScore:
    confidence = _bounded_number(fact.get("confidence"), default=0.5)
    if policy == EVICTION_POLICY_CONFIDENCE:
        return FactEvictionScore(
            value=confidence,
            components={"confidence": confidence},
        )
    if policy != EVICTION_POLICY_HYBRID_V1:
        raise ValueError(f"Unknown fact eviction policy: {policy!r}")

    decay_exempt = False
    if decay_exempt_categories:
        cat = str(fact.get("category") or "").strip().lower()
        decay_exempt = cat in decay_exempt_categories

    confirmation = _confirmation_freshness(
        fact,
        now=now,
        half_life_days=confirmation_half_life_days,
        decay_exempt=decay_exempt,
    )
    access = _normalized_access_heat(
        usage,
        now=now,
        half_life_days=access_half_life_days,
    )
    value = confidence_weight * confidence + confirmation_weight * confirmation + access_weight * access
    return FactEvictionScore(
        value=value,
        components={
            "confidence": confidence,
            "confirmationFreshness": confirmation,
            "accessHeat": access,
        },
    )


def select_facts_for_capacity(
    facts: list[dict[str, Any]],
    *,
    max_facts: int,
    policy: str,
    usage: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
    confidence_weight: float = 0.65,
    confirmation_weight: float = 0.25,
    access_weight: float = 0.10,
    confirmation_half_life_days: float = 90,
    access_half_life_days: float = 30,
    correction_reserved_fraction: float = 0.10,
    correction_reserved_max: int = 10,
    reserved_categories: list[str] | tuple[str, ...] | None = None,
    decay_exempt_categories: list[str] | tuple[str, ...] | None = None,
) -> FactEvictionDecision:
    """Select facts under the configured cap without mutating the snapshot.

    ``confidence`` exactly preserves the historical ranking. ``hybrid-v1``
    combines three bounded signals and reserves only the minimum number of
    capacity slots for configured reserved categories (defaulting to correction);
    corrections take priority when included. Unused slots return to ordinary competition.
    """
    if isinstance(reserved_categories, str):
        raise TypeError("reserved_categories must be an iterable of strings, not a bare str")
    if isinstance(decay_exempt_categories, str):
        raise TypeError("decay_exempt_categories must be an iterable of strings, not a bare str")
    evaluated_at = (now or datetime.now(UTC)).astimezone(UTC)
    usage = usage or {}
    decay_exempt_set = {c.strip().lower() for c in decay_exempt_categories if isinstance(c, str) and c.strip()} if decay_exempt_categories else None
    indexed_facts = list(enumerate(facts))
    scores: dict[str, FactEvictionScore] = {}
    # Per-position scores: the input list may repeat a fact_id, and the public
    # ``scores`` dict keeps only the last write per id, so ranking and the
    # evicted audit must read each record's own score, not the shared id's.
    scored: list[FactEvictionScore] = []
    for index, fact in indexed_facts:
        fact_id = str(fact.get("id") or f"__missing_{index}")
        score = _score_fact(
            fact,
            policy=policy,
            usage=usage.get(fact_id),
            now=evaluated_at,
            confidence_weight=confidence_weight,
            confirmation_weight=confirmation_weight,
            access_weight=access_weight,
            confirmation_half_life_days=confirmation_half_life_days,
            access_half_life_days=access_half_life_days,
            decay_exempt_categories=decay_exempt_set,
        )
        scores[fact_id] = score
        scored.append(score)

    if len(indexed_facts) <= max_facts:
        return FactEvictionDecision(
            kept=list(facts),
            evicted=[],
            scores=scores,
            policy=policy,
        )

    ranked = sorted(
        indexed_facts,
        key=lambda item: (-scored[item[0]].value, item[0]),
    )
    reserved_correction_count = 0
    selected_indexes: set[int] = set()
    if policy == EVICTION_POLICY_HYBRID_V1 and max_facts > 0:
        target_categories = {c.strip().lower() for c in reserved_categories if isinstance(c, str) and c.strip()} if reserved_categories is not None else {"correction"}
        reserved_slots = min(
            correction_reserved_max,
            math.ceil(max_facts * correction_reserved_fraction),
        )
        reserved_candidates = [item for item in ranked if str(item[1].get("category") or "").strip().lower() in target_categories]
        reserved_candidates.sort(key=lambda item: str(item[1].get("category") or "").strip().lower() != "correction")
        reserved_count = min(reserved_slots, len(reserved_candidates), max_facts)
        reserved_candidates = reserved_candidates[:reserved_count]
        selected_indexes.update(index for index, _fact in reserved_candidates)
        reserved_correction_count = sum(str(fact.get("category") or "").strip().lower() == "correction" for _index, fact in reserved_candidates)

    for index, _fact in ranked:
        if len(selected_indexes) >= max(0, max_facts):
            break
        selected_indexes.add(index)

    kept = [fact for index, fact in ranked if index in selected_indexes]
    evicted: list[EvictedFact] = []
    for index, fact in reversed(ranked):
        if index in selected_indexes:
            continue
        fact_id = str(fact.get("id") or f"__missing_{index}")
        score = scored[index]
        evicted.append(
            EvictedFact(
                fact_id=fact_id,
                category=str(fact.get("category") or "context"),
                score=score.value,
                components=dict(score.components),
            )
        )

    return FactEvictionDecision(
        kept=kept,
        evicted=evicted,
        scores=scores,
        policy=policy,
        reserved_correction_slots=reserved_correction_count,
    )
