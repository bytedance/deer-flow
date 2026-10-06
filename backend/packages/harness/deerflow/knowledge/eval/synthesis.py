"""Bottom-up question synthesis for the eval question bank (spec 2026-08-28 §6).

Generates candidate questions from one OR MORE documents' chunks instead of
from retrieval results — bottom-up synthesis cures the survivorship bias of
anchoring only what the system already recalls (the question source is the
corpus, not the retrieval output).

Multi-document joint synthesis (2026-09-02): chunks of every selected
document are flattened into ONE globally numbered list (each line prefixed
with its document name), so ``chunk_refs`` numbering stays unambiguous and
the anchor guard is unchanged — this is what makes cross-document multi-hop
questions possible.

Flow: numbered chunks → one LLM call → JSON candidates → two guards →
staging file → human review (accept/reject) → only ``accept_candidate``
writes the bank, through ``question_bank.add_question`` (the single write
path — no second route into the golden file).

Guards (order is contractual, never swap):

1. **Anchor mapping** — every ``chunk_refs`` entry must be a 1-based index
   of a real chunk of the flattened list; a hallucinated anchor drops the
   whole candidate.
2. **Schema validation** — the candidate (with a server ``c_`` id injected)
   must pass ``dataset.validate_question``, the same guard as manual creation.

Dropped candidates are counted, never surfaced as errors: fewer questions
beat dirty questions. The staging file is a single JSON document (not JSONL)
so metadata (doc_ids / generated_at / dropped) survives after the last
candidate is reviewed; every synthesis replaces it wholesale — the review
surface is always exactly one synthesis run's output.

Entity annotations are question-level, not chunk-level (2026-09-08 约束选择
修订): the prompt ships each chunk's index-time entity vocabulary and asks the
LLM to SELECT the subset the question actually examines; ``_guard_candidate``
filters every name outside the anchored chunks' vocabulary union, so selection
stays grounded (zero hallucination) while the annotation keeps question-level
granularity — a full-chunk union would dilute ``seed_hit_rate``'s denominator
with entities the query never seeds. The manual create path (no LLM) still
derives the chunk union via ``chunk_entities_union``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.knowledge.eval.dataset import GoldenDatasetError, GoldenQuestion, validate_question
from deerflow.knowledge.eval.question_bank import add_question

logger = logging.getLogger(__name__)

#: In-flight synthesis runs per KB (single-process asyncio counter, same
#: pattern as ``ondemand._IN_FLIGHT``) — feeds trigger idempotency and the
#: status endpoint's ``in_progress`` flag.
_SYNTH_IN_FLIGHT: dict[str, int] = {}

#: Per-staging-file locks for read-modify-write serialization (accept/reject
#: mutate the staging document; single-process scope, same boundary as the
#: question bank locks).
_LOCKS: dict[str, asyncio.Lock] = {}


class SynthesisDocNotReady(RuntimeError):
    """The source document is missing or has no indexed chunks — nothing to
    synthesize from. Raised *before* scheduling (router → 409), mirroring
    :class:`ondemand.EvalQuestionBankEmpty`."""


@dataclass(frozen=True)
class SynthesisCandidate:
    """One staged candidate — a full question payload plus staging metadata."""

    candidate_id: str
    query: str
    category: str
    expected_paths: tuple[str, ...]
    relevant_chunk_ids: tuple[str, ...]
    relevant_entities: tuple[str, ...]
    reference_answer: str | None
    doc_id: str
    generated_at: str


def synthesis_in_progress(kb_id: str) -> bool:
    """True while any synthesis run for the KB is active."""
    return _SYNTH_IN_FLIGHT.get(kb_id, 0) > 0


def begin_synthesis(kb_id: str) -> bool:
    """Mark a run in flight; False when one already is (idempotent trigger)."""
    if _SYNTH_IN_FLIGHT.get(kb_id, 0) > 0:
        return False
    _SYNTH_IN_FLIGHT[kb_id] = _SYNTH_IN_FLIGHT.get(kb_id, 0) + 1
    return True


def end_synthesis(kb_id: str) -> None:
    """Drain the counter (call from ``finally``); never goes negative."""
    _SYNTH_IN_FLIGHT[kb_id] = max(0, _SYNTH_IN_FLIGHT.get(kb_id, 0) - 1)


def new_candidate_id() -> str:
    """Staging-scope id: ``c_`` + 8 hex chars (bank ids stay ``q_``)."""
    return f"c_{uuid4().hex[:8]}"


def chunk_entities_union(chunks: Sequence[Mapping[str, Any]]) -> list[str]:
    """Order-preserving deduped union of the chunks' ``entities`` (2026-09-08).

    ``chunk.entities`` are the index-time graph extraction names — the same
    vocabulary as ``trace.seed_entities``. Two consumers: the synthesis guard
    uses the anchored union as the ALLOWED-SELECTION set (constrained choice,
    out-of-vocabulary names filtered), and the manual create path derives it
    directly as the annotation (no LLM in that route).
    """
    names: list[str] = []
    for chunk in chunks:
        for name in chunk.get("entities") or []:
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return names


def _lock(path: Path) -> asyncio.Lock:
    return _LOCKS.setdefault(str(path), asyncio.Lock())


def _default_llm_factory():
    """Synthesis: ``rag.synthesis_model`` → the RAG default → the first model (spec 2026-09-26 D4).

    Same chain and helper as the wiki generator it used to take as its precedent.
    """
    from deerflow.config.app_config import get_app_config
    from deerflow.knowledge.model_target import create_rag_chat_model, require_usable_rag_target

    config = get_app_config()
    return create_rag_chat_model(require_usable_rag_target(config, config.rag.synthesis_model, role="考题合成"), thinking=bool(config.rag.synthesis_thinking), app_config=config)


_SYSTEM_PROMPT = """你是知识库评测题库的出题员，基于给定文档的编号切片出评测题。切片可能来自多篇文档。

要求：
- single-hop 题（fact / relation 类）：答案锚定 1–3 个切片；
- multi-hop 题（concept 类）：答案需跨段落综合，锚定分布在不同位置的多个切片；
- query 禁止照抄切片原文，必须用自己的话提问；
- category 只能取 fact / relation / concept / global；
- expected_paths 从 vector / graph / wiki 中选（可多选，数组形式）；
- chunk_refs 是答案依据的切片编号列表（1 开始，全局编号）；
- relevant_entities 从所锚定切片（chunk_refs）的实体词汇表中挑选该题真正
  考察的实体子集（可空数组）；禁止发明词汇表外的名字。

只输出 JSON，不要其他文字：
{"questions": [{"query": "...", "category": "...", "expected_paths": ["..."], "chunk_refs": [1, 2], "relevant_entities": ["..."], "reference_answer": "..."}]}"""

#: Total chunk budget for ONE LLM call — multi-doc runs split it evenly
#: across documents, each keeping at least one chunk (no starvation).
MAX_SYNTH_CHUNKS = 60


def _sample_chunks(chunks: Sequence[Mapping[str, Any]], quota: int) -> list[Mapping[str, Any]]:
    """Even-stride deterministic sample; first and last chunks always stay."""
    total = len(chunks)
    if total <= quota:
        return list(chunks)
    if quota <= 1:
        return [chunks[total // 2]]
    step = (total - 1) / (quota - 1)
    return [chunks[round(index * step)] for index in range(quota)]


def _build_messages(docs: Sequence[tuple[str, str, Sequence[Mapping[str, Any]]]], count: int, flat_chunks: list[dict[str, Any]]) -> list:
    lines = "\n".join(f"[{index}] 《{chunk['doc_name']}》 实体词汇表: [{', '.join(chunk.get('entities') or [])}] {chunk.get('text', '')}" for index, chunk in enumerate(flat_chunks, start=1))
    doc_count = len(docs)
    user = f"以下共 {len(flat_chunks)} 个切片，来自 {doc_count} 篇文档（全局编号）：\n{lines}\n\n请生成 {count} 道题（single-hop 与 multi-hop 混合）。"
    if doc_count > 1:
        # Cross-doc synthesis is THE point of multi-select — demand at least
        # one question whose anchors span different documents.
        user += "\n其中至少 1 道为跨文档综合题（锚定切片分布在不同文档）。"
    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user)]


def _parse_llm_json(content: str) -> list[dict[str, Any]]:
    """Extract the questions list; any parse problem yields [] (dropped=0)."""
    text = content.strip()
    # LLMs frequently wrap JSON in code fences despite instructions.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        payload = json.loads(text.strip())
    except json.JSONDecodeError:
        logger.warning("synthesis: LLM output is not valid JSON; producing zero candidates")
        return []
    questions = payload.get("questions") if isinstance(payload, dict) else None
    return questions if isinstance(questions, list) else []


def _guard_candidate(raw: dict[str, Any], *, chunks: list[dict[str, Any]], candidate_id: str, generated_at: str) -> SynthesisCandidate | None:
    """Apply guard 1 (anchor mapping) then guard 2 (schema); None = drop.

    The anchor guard maps global 1-based indexes against the FLATTENED
    multi-doc chunk list — identical semantics to the single-doc design.
    The candidate's ``doc_id`` is derived from its anchored chunks: the
    distinct source documents, comma-joined in order of appearance.
    Entity annotations are the LLM's constrained selection filtered to the
    anchored vocabulary union (``chunk_entities_union``) — out-of-vocabulary
    (hallucinated) names are dropped, order preserved, deduped; an empty
    selection stays an honest no-annotation (no union fallback).
    """
    refs = raw.get("chunk_refs")
    if not isinstance(refs, list) or not refs:
        return None
    try:
        indexes = [int(ref) for ref in refs]
    except (TypeError, ValueError):
        return None
    if any(index < 1 or index > len(chunks) for index in indexes):
        return None  # 幻觉锚定：编号指向不存在的切片 → 整条丢弃
    anchored = [chunks[index - 1] for index in indexes]
    chunk_ids = tuple(chunk["chunk_id"] for chunk in anchored)
    source_docs = ",".join(dict.fromkeys(chunk["doc_id"] for chunk in anchored))
    # 约束选择（2026-09-08）：LLM 从锚定切片实体词汇表挑题面考察子集；
    # 词汇表外名字（幻觉）过滤，保序去重；空选择=诚实无标注。
    allowed = set(chunk_entities_union(anchored))
    entities = list(dict.fromkeys(name for name in (raw.get("relevant_entities") or []) if isinstance(name, str) and name in allowed))

    question_raw: dict[str, Any] = {
        "id": candidate_id,
        "query": raw.get("query"),
        "category": raw.get("category"),
        "expected_paths": raw.get("expected_paths"),
        "relevant_chunk_ids": list(chunk_ids),
        "relevant_entities": entities,
        "reference_answer": raw.get("reference_answer"),
    }
    try:
        question = validate_question(question_raw)
    except GoldenDatasetError as exc:
        logger.info("synthesis candidate %s dropped by schema guard: %s", candidate_id, exc)
        return None

    return SynthesisCandidate(
        candidate_id=candidate_id,
        query=question.query,
        category=question.category,
        expected_paths=question.expected_paths,
        relevant_chunk_ids=question.relevant_chunk_ids,
        relevant_entities=question.relevant_entities,
        reference_answer=question.reference_answer,
        doc_id=source_docs,
        generated_at=generated_at,
    )


def _write_staging(path: Path, *, kb_id: str, doc_ids: Sequence[str], generated_at: str, dropped: int, candidates: list[SynthesisCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kb_id": kb_id,
        "doc_ids": list(doc_ids),
        "generated_at": generated_at,
        "dropped": dropped,
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


async def load_staging(path: str | Path) -> dict[str, Any]:
    """Read the staging document; a missing file is an empty staging.

    Legacy single-value ``doc_id`` files normalize to ``doc_ids`` on read —
    the 2026-09-02 multi-doc upgrade never strands an existing staging file.
    """
    path = Path(path)
    if not path.exists():
        return {"kb_id": None, "doc_ids": [], "generated_at": None, "dropped": 0, "candidates": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("candidates", [])
    data.setdefault("dropped", 0)
    if "doc_ids" not in data:
        data["doc_ids"] = [data["doc_id"]] if data.get("doc_id") else []
    return data


async def synthesize_for_docs(
    kb_id: str,
    *,
    docs: Sequence[tuple[str, str, Sequence[Mapping[str, Any]]]],
    count: int,
    staging_path: str | Path,
    llm_factory: Any = None,
    generated_at: str | None = None,
) -> tuple[list[SynthesisCandidate], int]:
    """Generate candidates from one or more documents; merge into staging.

    ``docs`` is ``(doc_id, doc_name, chunks)`` per document. Every document's
    chunks are budget-split (MAX_SYNTH_CHUNKS shared, even-stride sampling)
    and flattened into one globally numbered list — that is what lets the LLM
    anchor a single question across documents. Returns ``(candidates,
    dropped)`` for THIS batch only. Never raises on bad LLM output — an
    unparsable response yields zero candidates (runtime exceptions from the
    LLM call itself propagate; the service layer owns that fallback).

    合并语义（2026-09-02 右键快捷出题）：暂存里已有未审候选时新批追加，
    不覆盖——快捷入口（单篇出一条）不得冲掉用户待审内容；doc_ids 保序
    并集，dropped 跨批累加。合成槽位全库单飞（in-flight 注册表），写入无竞争。
    """
    if not docs:
        raise ValueError("synthesize_for_docs requires at least one document")
    if generated_at is None:
        generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    quota = max(1, MAX_SYNTH_CHUNKS // len(docs))
    flat_chunks: list[dict[str, Any]] = []
    for doc_id, doc_name, chunks in docs:
        for chunk in _sample_chunks(chunks, quota):
            flat_chunks.append({**chunk, "doc_id": doc_id, "doc_name": doc_name})

    factory = llm_factory or _default_llm_factory
    llm = factory()
    response = await llm.ainvoke(_build_messages(docs, count, flat_chunks))

    candidates: list[SynthesisCandidate] = []
    used_ids: set[str] = set()
    raw_questions = _parse_llm_json(response.content)
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        candidate_id = new_candidate_id()
        while candidate_id in used_ids:
            candidate_id = new_candidate_id()
        candidate = _guard_candidate(raw, chunks=flat_chunks, candidate_id=candidate_id, generated_at=generated_at)
        if candidate is None:
            continue
        used_ids.add(candidate_id)
        candidates.append(candidate)
    dropped = max(0, len(raw_questions) - len(candidates))

    staging_path = Path(staging_path)
    async with _lock(staging_path):
        existing = await load_staging(staging_path)
        merged_doc_ids = list(dict.fromkeys([*(existing.get("doc_ids") or []), *(doc_id for doc_id, _, _ in docs)]))
        _write_staging(
            staging_path,
            kb_id=kb_id,
            doc_ids=merged_doc_ids,
            generated_at=generated_at,
            dropped=int(existing.get("dropped", 0)) + dropped,
            candidates=[*_existing_candidates(existing), *candidates],
        )
    return candidates, dropped


def _existing_candidates(data: dict[str, Any]) -> list[SynthesisCandidate]:
    """暂存里的旧候选还原为 dataclass（合并时与新批同构拼接）；
    脏行（缺字段）静默丢弃——守卫同款宽容。"""
    rows: list[SynthesisCandidate] = []
    for row in data.get("candidates") or []:
        try:
            rows.append(SynthesisCandidate(**{key: row[key] for key in SynthesisCandidate.__dataclass_fields__ if key in row}))
        except (TypeError, KeyError):
            continue
    return rows


async def accept_candidate(
    bank_path: str | Path,
    staging_path: str | Path,
    candidate_id: str,
    *,
    anchor_guard: Callable[[Sequence[str], str | None, bool], Awaitable[None]] | None = None,
    anchor_ack: bool = False,
) -> GoldenQuestion:
    """Move one staged candidate into the bank (the only write route).

    The bank write goes through ``question_bank.add_question`` — server id
    regeneration and schema guard included. KeyError when the candidate is
    unknown (already reviewed, or never existed). ``anchor_guard``/
    ``anchor_ack`` pass through to the write-path anchor verification (spec
    2026-10-05) so this port and the create port share one gate.
    """
    staging_path = Path(staging_path)
    async with _lock(staging_path):
        data = await load_staging(staging_path)
        rows = data["candidates"]
        row = next((item for item in rows if item.get("candidate_id") == candidate_id), None)
        if row is None:
            raise KeyError(candidate_id)

        question = await add_question(
            bank_path,
            query=row["query"],
            category=row["category"],
            expected_paths=row["expected_paths"],
            relevant_chunk_ids=row.get("relevant_chunk_ids") or [],
            relevant_entities=row.get("relevant_entities") or [],
            reference_answer=row.get("reference_answer"),
            anchor_guard=anchor_guard,
            anchor_ack=anchor_ack,
        )
        _write_staging(
            staging_path,
            kb_id=data.get("kb_id"),
            doc_ids=data.get("doc_ids") or [],
            generated_at=data.get("generated_at"),
            dropped=data.get("dropped", 0),
            candidates=[_row_to_candidate(item) for item in rows if item.get("candidate_id") != candidate_id],
        )
        return question


async def reject_candidate(staging_path: str | Path, candidate_id: str) -> str:
    """Drop one staged candidate without touching the bank; KeyError when unknown."""
    staging_path = Path(staging_path)
    async with _lock(staging_path):
        data = await load_staging(staging_path)
        rows = data["candidates"]
        if not any(item.get("candidate_id") == candidate_id for item in rows):
            raise KeyError(candidate_id)
        _write_staging(
            staging_path,
            kb_id=data.get("kb_id"),
            doc_ids=data.get("doc_ids") or [],
            generated_at=data.get("generated_at"),
            dropped=data.get("dropped", 0),
            candidates=[_row_to_candidate(item) for item in rows if item.get("candidate_id") != candidate_id],
        )
        return candidate_id


def _row_to_candidate(row: dict[str, Any]) -> SynthesisCandidate:
    return SynthesisCandidate(
        candidate_id=row["candidate_id"],
        query=row["query"],
        category=row["category"],
        expected_paths=tuple(row.get("expected_paths") or ()),
        relevant_chunk_ids=tuple(row.get("relevant_chunk_ids") or ()),
        relevant_entities=tuple(row.get("relevant_entities") or ()),
        reference_answer=row.get("reference_answer"),
        doc_id=row.get("doc_id", ""),
        generated_at=row.get("generated_at", ""),
    )
