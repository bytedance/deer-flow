from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.benchmark.deermem_eviction.dataset import DatasetIntegrityError, build_distractor_bank, extract_evidence, load_longmemeval


def _row(question_id: str, question_type: str, content: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": f"Question for {question_id}?",
        "answer": "answer",
        "question_date": "2026/08/13 (Thu) 10:00",
        "haystack_session_ids": [f"session-{question_id}"],
        "haystack_dates": ["2026/08/01 (Sat) 09:00"],
        "haystack_sessions": [[{"role": "user", "content": content, "has_answer": True}]],
    }


def test_load_longmemeval_rejects_hash_mismatch(tmp_path: Path) -> None:
    dataset_path = tmp_path / "oracle.json"
    dataset_path.write_text("[]")

    with pytest.raises(DatasetIntegrityError, match="SHA-256 mismatch"):
        load_longmemeval(dataset_path, expected_sha256="0" * 64)


def test_load_longmemeval_indexes_unique_rows(tmp_path: Path) -> None:
    rows = [_row("b", "knowledge-update", "b" * 50), _row("a", "temporal-reasoning", "a" * 50)]
    payload = json.dumps(rows).encode()
    dataset_path = tmp_path / "oracle.json"
    dataset_path.write_bytes(payload)

    dataset = load_longmemeval(dataset_path, expected_sha256=hashlib.sha256(payload).hexdigest())

    assert sorted(dataset.rows_by_id) == ["a", "b"]


def test_extract_evidence_uses_marked_turns_and_per_session_user_fallback() -> None:
    row = {
        "haystack_session_ids": ["s1", "s2"],
        "haystack_dates": ["2026/01/01", "2026/01/02"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "ignore unmarked", "has_answer": False},
                {"role": "assistant", "content": "marked answer", "has_answer": True},
            ],
            [
                {"role": "user", "content": "fallback user"},
                {"role": "assistant", "content": "ignore fallback assistant"},
            ],
        ],
    }

    assert extract_evidence(row) == ("SESSION s1 AT 2026/01/01\nASSISTANT: marked answer\n\nSESSION s2 AT 2026/01/02\nUSER: fallback user")


def test_distractor_bank_is_filtered_sorted_and_bounded() -> None:
    rows = [
        _row("z", "single-session-user", "z" * 60),
        _row("a", "single-session-preference", "a" * 60),
        _row("wrong-type", "knowledge-update", "x" * 60),
        _row("too-long", "single-session-user", "x" * 800),
    ]

    bank = build_distractor_bank(rows, allowed_types={"single-session-user", "single-session-preference"}, min_evidence_chars=40, max_evidence_chars=700, limit=40)

    assert [item.question_id for item in bank] == ["a", "z"]
