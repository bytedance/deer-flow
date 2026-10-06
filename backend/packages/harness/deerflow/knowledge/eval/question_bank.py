"""Per-KB golden question bank file operations (spec 2026-08-27 §4.1/§4.2).

The question bank is runtime data — one JSONL per knowledge base at
``{data_dir}/knowledge/{kb_id}/golden.jsonl`` (the same directory tree the
documents live under) — not a git fixture. Two error classes are deliberately
distinct because the API maps them differently:

- ``QuestionBankInvalidQuestion``: the *new* input violates the golden schema
  → caller-visible 422, the client fixes the payload;
- ``QuestionBankCorrupted``: the *existing* file fails ``load_golden``
  (hand-edited dirty line) → 500 naming the offending line; dirty questions
  silently pollute every metric built on them, so this never gets skipped.

Schema validation is delegated to ``dataset.validate_question`` — UI writes
and CLI loads share one guard. Writes go through read-modify-write of the
whole file (50–100 questions scale) with a tmp sibling + ``os.replace``, so a
crash mid-write can never leave a half-written bank behind; a per-path
``asyncio.Lock`` serializes concurrent mutations within the process.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from deerflow.knowledge.eval.dataset import GoldenDatasetError, GoldenQuestion, load_golden, validate_question


class QuestionBankInvalidQuestion(GoldenDatasetError):
    """The new question violates the golden schema — input problem."""


class QuestionBankCorrupted(GoldenDatasetError):
    """The existing bank content fails validation — operational problem."""


# Per-file locks for read-modify-write serialization (single-process scope,
# same boundary as the wiki _IN_FLIGHT registry). asyncio.Lock creation has no
# await between get and set, so the registry itself needs no lock.
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock(path: Path) -> asyncio.Lock:
    return _LOCKS.setdefault(str(path), asyncio.Lock())


def new_question_id() -> str:
    """Server-side id: ``q_`` + 8 hex chars; collision retries are free."""
    return f"q_{uuid4().hex[:8]}"


async def load_questions(path: str | Path) -> list[GoldenQuestion]:
    """Load the whole bank; a missing file is an empty bank, not an error."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        return load_golden(path)
    except GoldenDatasetError as exc:
        raise QuestionBankCorrupted(str(exc)) from exc


async def add_question(
    path: str | Path,
    *,
    query: str,
    category: str,
    expected_paths: Sequence[str],
    relevant_chunk_ids: list[str] | tuple[str, ...] = (),
    relevant_entities: list[str] | tuple[str, ...] = (),
    reference_answer: str | None = None,
    anchor_guard: Callable[[Sequence[str], str | None, bool], Awaitable[None]] | None = None,
    anchor_ack: bool = False,
) -> GoldenQuestion:
    """Validate + append one question; returns the stored (server-id) question.

    Writes always use the canonical ``expected_paths`` list format (spec
    2026-08-28 §3); the validator accepts legacy single-value lines on read,
    so banks with mixed generations stay loadable until touched.

    ``anchor_guard`` is the write-path anchor verification (spec 2026-10-05)
    — injected by the two real write ports, default off keeps this module
    file-layer pure. ``anchor_ack`` is the one-shot human confirm flag that
    overrides term-level blocks (never a missing chunk).
    """

    path = Path(path)
    async with _lock(path):
        existing = await load_questions(path)

        raw: dict[str, Any] = {
            "id": new_question_id(),
            "query": query,
            "category": category,
            "expected_paths": list(expected_paths),
            "relevant_chunk_ids": list(relevant_chunk_ids),
            "relevant_entities": list(relevant_entities),
            "reference_answer": reference_answer,
        }
        existing_ids = {question.id for question in existing}
        while raw["id"] in existing_ids:
            raw["id"] = new_question_id()
        try:
            question = validate_question(raw)
        except GoldenDatasetError as exc:
            raise QuestionBankInvalidQuestion(str(exc)) from exc

        if anchor_guard is not None:
            await anchor_guard(list(relevant_chunk_ids), reference_answer, anchor_ack)

        _atomic_write(path, [*existing, question])
        return question


async def update_question(
    path: str | Path,
    question_id: str,
    *,
    relevant_chunk_ids: Sequence[str],
    relevant_entities: Sequence[str] | None = None,
    anchor_guard: Callable[[Sequence[str], str | None, bool], Awaitable[None]] | None = None,
    anchor_ack: bool = False,
) -> GoldenQuestion:
    """Rewrite one question's anchors; returns the updated question (KeyError when absent).

    与 ``add_question`` 并列的第二写入口（spec 2026-10-05 anchor-edit 对）：
    只动锚（+可选实体），题面/分类/预期路径/参考答案原样保留；清空
    ``relevant_chunk_ids`` = 解除锚定（与添加框无锚题同态）。``relevant_entities``
    为 ``None`` 保持原值。guard 注入形状与 ``add_question`` 一致（默认 None=不拦），
    核验用**存库的** ``reference_answer`` 对新锚跑。
    """

    path = Path(path)
    async with _lock(path):
        existing = await load_questions(path)
        target = next((question for question in existing if question.id == question_id), None)
        if target is None:
            raise KeyError(question_id)

        raw: dict[str, Any] = {
            "id": target.id,
            "query": target.query,
            "category": target.category,
            "expected_paths": list(target.expected_paths),
            "relevant_chunk_ids": list(relevant_chunk_ids),
            "relevant_entities": list(target.relevant_entities if relevant_entities is None else relevant_entities),
            "reference_answer": target.reference_answer,
        }
        try:
            question = validate_question(raw)
        except GoldenDatasetError as exc:
            raise QuestionBankInvalidQuestion(str(exc)) from exc

        if anchor_guard is not None:
            await anchor_guard(list(relevant_chunk_ids), question.reference_answer, anchor_ack)

        _atomic_write(path, [question if item.id == question_id else item for item in existing])
        return question


async def delete_question(path: str | Path, question_id: str) -> str:
    """Remove one question by id; returns the removed id (KeyError when absent)."""

    path = Path(path)
    async with _lock(path):
        existing = await load_questions(path)
        remaining = [question for question in existing if question.id != question_id]
        if len(remaining) == len(existing):
            raise KeyError(question_id)
        _atomic_write(path, remaining)
        return question_id


def _atomic_write(path: Path, questions: list[GoldenQuestion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            for question in questions:
                stream.write(json.dumps(asdict(question), ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
