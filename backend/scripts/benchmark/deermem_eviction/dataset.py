from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import load_json, sha256_file


class DatasetIntegrityError(ValueError):
    """Raised when an upstream dataset cannot satisfy the pinned protocol."""


@dataclass(frozen=True)
class EvidenceRecord:
    question_id: str
    question_type: str
    question: str
    answer: str
    question_date: str | None
    content: str


@dataclass(frozen=True)
class LongMemEvalDataset:
    path: Path
    sha256: str
    rows: tuple[dict[str, Any], ...]
    rows_by_id: dict[str, dict[str, Any]]


def _stringify_answer(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _selected_evidence_sessions(row: dict[str, Any]) -> list[tuple[Any, Any, list[dict[str, Any]]]]:
    session_ids = row.get("haystack_session_ids")
    dates = row.get("haystack_dates")
    sessions = row.get("haystack_sessions")
    if not isinstance(session_ids, list) or not isinstance(dates, list) or not isinstance(sessions, list):
        raise DatasetIntegrityError("LongMemEval row has invalid haystack arrays")
    if not (len(session_ids) == len(dates) == len(sessions)):
        raise DatasetIntegrityError("LongMemEval haystack arrays have different lengths")

    selected_sessions: list[tuple[Any, Any, list[dict[str, Any]]]] = []
    for session_id, date, turns in zip(session_ids, dates, sessions, strict=True):
        if not isinstance(turns, list):
            raise DatasetIntegrityError("LongMemEval session is not a turn list")
        valid_turns = [turn for turn in turns if isinstance(turn, dict) and isinstance(turn.get("content"), str)]
        selected = [turn for turn in valid_turns if turn.get("has_answer") is True]
        if not selected:
            selected = [turn for turn in valid_turns if str(turn.get("role") or "").lower() == "user"]
        if not selected:
            continue
        selected_sessions.append((session_id, date, selected))
    return selected_sessions


def extract_evidence(row: dict[str, Any]) -> str:
    rendered_sessions: list[str] = []
    for session_id, date, selected in _selected_evidence_sessions(row):
        lines = [f"SESSION {session_id} AT {date}"]
        lines.extend(f"{str(turn.get('role') or 'unknown').upper()}: {turn['content']}" for turn in selected)
        rendered_sessions.append("\n".join(lines))
    return "\n\n".join(rendered_sessions)


def evidence_record(row: dict[str, Any]) -> EvidenceRecord:
    question_id = row.get("question_id")
    question_type = row.get("question_type")
    question = row.get("question")
    if not all(isinstance(value, str) and value for value in (question_id, question_type, question)):
        raise DatasetIntegrityError("LongMemEval row is missing question identity fields")
    question_date = row.get("question_date")
    if question_date is not None and not isinstance(question_date, str):
        raise DatasetIntegrityError(f"LongMemEval question_date is invalid for {question_id}")
    return EvidenceRecord(
        question_id=question_id,
        question_type=question_type,
        question=question,
        answer=_stringify_answer(row.get("answer")),
        question_date=question_date,
        content=extract_evidence(row),
    )


def load_longmemeval(path: Path, *, expected_sha256: str) -> LongMemEvalDataset:
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise DatasetIntegrityError(f"LongMemEval SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}")
    raw = load_json(path)
    if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
        raise DatasetIntegrityError("LongMemEval root must be a list of objects")
    rows = tuple(raw)
    rows_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        question_id = row.get("question_id")
        if not isinstance(question_id, str) or not question_id:
            raise DatasetIntegrityError("LongMemEval row has an invalid question_id")
        if question_id in rows_by_id:
            raise DatasetIntegrityError(f"Duplicate LongMemEval question_id: {question_id}")
        rows_by_id[question_id] = row
    return LongMemEvalDataset(path=path, sha256=actual_sha256, rows=rows, rows_by_id=rows_by_id)


def build_distractor_bank(
    rows: Iterable[dict[str, Any]],
    *,
    allowed_types: set[str],
    min_evidence_chars: int,
    max_evidence_chars: int,
    limit: int,
) -> list[EvidenceRecord]:
    candidates: list[EvidenceRecord] = []
    for row in rows:
        if row.get("question_type") not in allowed_types:
            continue
        record = evidence_record(row)
        if min_evidence_chars <= len(record.content) <= max_evidence_chars:
            candidates.append(record)
    candidates.sort(key=lambda item: item.question_id)
    return candidates[:limit]
