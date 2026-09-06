from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .dataset import EvidenceRecord

Scenario = Literal["confirmation_help", "access_help", "confidence_control", "noisy_signal_control", "correction_reserve"]


@dataclass(frozen=True)
class PreparedCase:
    case_id: str
    source: Literal["longmemeval", "synthetic"]
    scenario: Scenario
    question_type: str
    question: str
    answer: str
    question_date: str | None
    evaluation_time: datetime
    facts: list[dict[str, Any]]
    usage: dict[str, dict[str, Any]]
    support_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class _FactMetadata:
    confidence: float
    category: str
    created_days_ago: int
    last_confirmed_days_ago: int | None = None
    access_heat: float = 0.0


def _timestamp_days_ago(now: datetime, days: int) -> str:
    value = now.astimezone(UTC) - timedelta(days=days)
    return value.isoformat().removesuffix("+00:00") + "Z"


def _support_metadata(scenario: Scenario) -> _FactMetadata:
    if scenario == "confirmation_help":
        return _FactMetadata(confidence=0.70, category="context", created_days_ago=180, last_confirmed_days_ago=7)
    if scenario == "access_help":
        return _FactMetadata(confidence=0.70, category="context", created_days_ago=180, access_heat=8)
    if scenario == "confidence_control":
        return _FactMetadata(confidence=0.95, category="context", created_days_ago=30)
    if scenario == "noisy_signal_control":
        return _FactMetadata(confidence=0.90, category="context", created_days_ago=180)
    if scenario == "correction_reserve":
        return _FactMetadata(confidence=0.65, category="correction", created_days_ago=180)
    raise ValueError(f"Unknown evaluation scenario: {scenario}")


def _distractor_metadata(scenario: Scenario, *, index: int, outranking_count: int, question_type: str) -> _FactMetadata:
    category = "preference" if question_type == "single-session-preference" else "context"
    if scenario in {"confirmation_help", "access_help"}:
        confidence = 0.94 - 0.02 * index if index < outranking_count else 0.68 - 0.02 * (index - outranking_count)
        return _FactMetadata(confidence=confidence, category=category, created_days_ago=180)
    if scenario == "confidence_control":
        if index < 5:
            return _FactMetadata(confidence=0.94 - 0.02 * index, category=category, created_days_ago=180)
        return _FactMetadata(
            confidence=0.70,
            category=category,
            created_days_ago=180,
            last_confirmed_days_ago=7 if index % 2 == 1 else None,
            access_heat=8 if index % 2 == 0 else 0,
        )
    if scenario == "noisy_signal_control":
        has_noise = index < outranking_count
        return _FactMetadata(
            confidence=0.70,
            category=category,
            created_days_ago=180,
            last_confirmed_days_ago=7 if has_noise and index % 2 == 1 else None,
            access_heat=8 if has_noise and index % 2 == 0 else 0,
        )
    if scenario == "correction_reserve":
        confidence = 0.90 - 0.03 * index if index < outranking_count else 0.60 - 0.02 * (index - outranking_count)
        return _FactMetadata(confidence=confidence, category=category, created_days_ago=180)
    raise ValueError(f"Unknown evaluation scenario: {scenario}")


def _fact(record: EvidenceRecord, metadata: _FactMetadata, *, fact_id: str, evaluation_time: datetime) -> tuple[dict[str, Any], dict[str, Any] | None]:
    fact: dict[str, Any] = {
        "id": fact_id,
        "content": record.content,
        "category": metadata.category,
        "confidence": metadata.confidence,
        "createdAt": _timestamp_days_ago(evaluation_time, metadata.created_days_ago),
        "source": f"deermem-eviction-eval:{record.question_id}",
    }
    if metadata.last_confirmed_days_ago is not None:
        fact["lastConfirmedAt"] = _timestamp_days_ago(evaluation_time, metadata.last_confirmed_days_ago)
        fact["confirmationCount"] = 1
    usage = None
    if metadata.access_heat > 0:
        usage = {
            "accessHeat": metadata.access_heat,
            "accessCount": int(metadata.access_heat),
            "lastAccessedAt": evaluation_time.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z",
        }
    return fact, usage


def build_case(
    *,
    support: EvidenceRecord,
    distractors: list[EvidenceRecord],
    scenario: Scenario,
    loss_rank: int,
    evaluation_time: datetime,
    source: Literal["longmemeval", "synthetic"] | None = None,
) -> PreparedCase:
    if len(distractors) != 9:
        raise ValueError("The pr4789 reproduction protocol requires exactly nine distractors")
    if not 1 <= loss_rank <= 10:
        raise ValueError("loss_rank must be between 1 and 10")
    source_ids = [support.question_id, *(item.question_id for item in distractors)]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("A prepared pool cannot contain duplicate source records")

    facts: list[dict[str, Any]] = []
    usage: dict[str, dict[str, Any]] = {}
    support_fact_id = f"gold_{support.question_id}"
    support_fact, support_usage = _fact(support, _support_metadata(scenario), fact_id=support_fact_id, evaluation_time=evaluation_time)
    facts.append(support_fact)
    if support_usage is not None:
        usage[support_fact_id] = support_usage

    outranking_count = loss_rank - 1
    for index, record in enumerate(distractors):
        metadata = _distractor_metadata(scenario, index=index, outranking_count=outranking_count, question_type=record.question_type)
        fact_id = f"d_{support.question_id}_{index}_{record.question_id}"
        fact, fact_usage = _fact(record, metadata, fact_id=fact_id, evaluation_time=evaluation_time)
        facts.append(fact)
        if fact_usage is not None:
            usage[fact_id] = fact_usage

    facts.sort(key=lambda fact: str(fact["id"]))
    resolved_source = source or ("synthetic" if scenario == "correction_reserve" else "longmemeval")
    return PreparedCase(
        case_id=support.question_id,
        source=resolved_source,
        scenario=scenario,
        question_type=support.question_type,
        question=support.question,
        answer=support.answer,
        question_date=support.question_date,
        evaluation_time=evaluation_time.astimezone(UTC),
        facts=facts,
        usage=usage,
        support_fact_ids=(support_fact_id,),
    )
