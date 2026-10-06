"""Wiki entry generation: triggered batch + dirty incremental (spec §3.5).

- **Eligibility (2026-08-12 revision, ratio head retired)**: an entity earns
  an entry when it passes the hygiene gate (``is_low_quality_entity_name``)
  AND spans at least two chunks — single-chunk entities are served by the
  vector path directly. No total cap; score (degree + frequency) only orders
  generation.
- **Material-bundle batching**: entities whose source-chunk sets overlap
  (Jaccard ≥ 0.5, ≤7 per bundle) share one LLM call returning a JSON array of
  entries; bundles with missing titles or unparseable output fall back to
  per-entity generation.
- **Triggered batch**: the first generation runs once the KB's indexing
  completion crosses a threshold (or the user clicks "生成百科" — the API
  simply calls ``generate_wiki`` directly); afterwards the KB runs in dirty
  incremental mode.
- **Dirty incremental**: a newly indexed doc marks the entries of its touched
  entities ``dirty``; ``generate_wiki(only_dirty=True)`` regenerates those
  per-entity against their *current* source chunks and clears the flag, and
  also backfills eligible entities that have no entry yet (≤40 new per run).
- **Supplement as direction (spec 2026-09-12)**: an entry's supplement layer is
  user-written guidance for how it should be written. Every path that rewrites
  an *existing* entry (dirty refresh, per-entry regenerate, the guided slice of
  a full rebuild) passes it into the user message as ``WIKI_DIRECTION_HEADER``.
  The batch path serves backfill only — entities with no entry have no
  supplement — so it stays untouched.

Each entry is written by the main model (stable long-form Chinese), full text
stored in ``wiki_entries``, dense vector (title + content head) upserted to
``kb_wiki_entries`` with a pointer-only payload.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import func, select

from deerflow.knowledge.embed_texts import wiki_entry_embed_text
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.normalizer import is_low_quality_entity_name
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.models import DocumentRow
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import KnowledgeVectorStore, WikiEntryUpsert
from deerflow.knowledge.wiki.store import WikiStore, wiki_entry_id

logger = logging.getLogger(__name__)

#: Max new entries written per incremental run (spec §3.5 2026-08-12 pacing).
DEFAULT_BACKFILL_LIMIT = 40
#: Entities per material-bundle LLM call (spec §3.5 2026-08-12 batching).
BATCH_BUNDLE_SIZE = 7
#: Min Jaccard overlap between an entity's chunks and a bundle's union.
BATCH_JACCARD_THRESHOLD = 0.5
#: Fraction of documents that must be ready before auto-triggering (spec §3.7).
DEFAULT_TRIGGER_THRESHOLD = 0.9

#: In-flight generation runs per KB (single-process asyncio counter). Feeds the
#: library-level ``wiki: generating`` sub-status on the documents endpoint —
#: covers both the manual button and the worker's auto trigger (spec §5 P3).
_IN_FLIGHT: dict[str, int] = {}


def wiki_generation_in_progress(kb_id: str) -> bool:
    """True while any ``generate_wiki`` run for the KB is active."""
    return _IN_FLIGHT.get(kb_id, 0) > 0


#: Terminal status of the most recent ``generate_wiki`` run per KB
#: (single-process, same scope as ``_IN_FLIGHT``). Feeds the entries
#: payload's ``last_run`` so a crashed run never masquerades as 已更新
#: (P1 失败可见性, 2026-08-14).
_LAST_RUN: dict[str, str] = {}


def wiki_last_run_status(kb_id: str) -> str | None:
    """``"succeeded"`` / ``"failed"`` / ``None`` (never ran in this process)."""
    return _LAST_RUN.get(kb_id)


WIKI_SYSTEM_PROMPT = """你是知识库百科撰写者。根据给定的实体信息与来源切片，撰写一篇简明的中文百科条目：
- 第一行输出 markdown 一级标题（# 实体名）。
- 正文 2~4 段：先给定义与定位，再展开关键事实、与其他实体的关系，最后补充应用场景或注意事项（若材料支持）。
- 严格依据给定材料撰写，材料没有的信息不要编造；不要输出参考文献或链接。"""

WIKI_BATCH_SYSTEM_PROMPT = """你是知识库百科撰写者。根据给定的来源切片，为实体清单中的每个实体各撰写一篇简明的中文百科条目：
- 只输出一个 JSON 数组，每个元素形如 {"title": "实体名", "content": "正文"}；title 必须逐字取自实体清单。
- 每篇 content 以 markdown 一级标题（# 实体名）开头，正文 2~4 段：先给定义与定位，再展开关键事实、与其他实体的关系，最后补充应用场景或注意事项（若材料支持）。
- 严格依据给定材料撰写，材料没有的信息不要编造；不要输出参考文献或链接；不要输出 JSON 数组以外的任何内容。"""

#: 补充层注入段的表头。放在 user message（而非系统提示词）里：系统提示词是静态前缀，
#: 逐条目的方向不该改写它。措辞同时说明优先级（人工指令优先于切片）与护栏
#: （不得引入材料与要求之外的信息）。
WIKI_DIRECTION_HEADER = "用户在补充层写下的要求（人工指令，优先于来源切片；仍不得引入材料与要求之外的信息）："


class _LLM(Protocol):
    async def ainvoke(self, messages: Any) -> Any: ...


class _Embedder(Protocol):
    batch_size: int

    async def embed(self, texts: Sequence[str], *, text_type: str = "document") -> list[EmbeddingResult]: ...


@dataclass(slots=True)
class WikiStats:
    """Outcome of one ``generate_wiki`` run."""

    selected: int = 0
    generated: int = 0
    #: Dirty entries pruned because their entity vanished or lost eligibility
    #: (失格即删, 2026-08-14 拍板方案 A).
    pruned: int = 0
    #: Writes blocked by the mid-run eligibility re-check (2026-08-23 竞态防护):
    #: the entity lost eligibility/vanished between the eligibility snapshot and
    #: the write (user deleted a source document mid-generation).
    skipped_stale: int = 0
    titles: list[str] = field(default_factory=list)


async def _is_currently_eligible(graph_store: GraphStore, kb_id: str, name: str) -> bool:
    """写入前资格重验（轻量版）：与 ``select_eligible_entities`` 同源规则
    （hygiene 门 ∧ 跨切片 freq≥2），但跳过 ``load_networkx``——写入点只问 0/1，
    不需要 degree 排序。"""
    if is_low_quality_entity_name(name):
        return False
    for row in await graph_store.list_entities(kb_id):
        if row["name"] == name:
            return len(row.get("source_chunk_ids") or []) >= 2
    return False


async def select_eligible_entities(graph_store: GraphStore, kb_id: str) -> list[dict[str, Any]]:
    """Entities that earn a wiki entry, ordered by generation priority.

    Eligibility (spec §3.5 2026-08-12 revision): pass the hygiene gate
    (``is_low_quality_entity_name``) AND span at least two chunks — an entity
    living in a single chunk is served by the vector path directly, so an
    entry would only restate that one section. No total cap; the score
    (NetworkX degree in+out + ``len(source_chunk_ids)``) merely orders the
    output, ties broken by name for determinism.
    """
    entities = await graph_store.list_entities(kb_id)
    candidates = [row for row in entities if not is_low_quality_entity_name(row["name"]) and len(row.get("source_chunk_ids") or []) >= 2]
    if not candidates:
        return []
    graph = await graph_store.load_networkx(kb_id)
    return sorted(
        candidates,
        key=lambda row: (-(int(graph.degree(row["name"])) if graph.has_node(row["name"]) else 0) - len(row.get("source_chunk_ids") or []), row["name"]),
    )


def plan_entry_batches(rows: Sequence[dict[str, Any]], *, batch_size: int = BATCH_BUNDLE_SIZE, jaccard_threshold: float = BATCH_JACCARD_THRESHOLD) -> list[list[dict[str, Any]]]:
    """Pack entities into material bundles sharing one LLM call (spec §3.5).

    Greedy, in the caller's (score) order: an entity joins the first bundle
    whose chunk union overlaps its own chunks at Jaccard ≥ ``jaccard_threshold``
    and still has room (≤ ``batch_size``); otherwise it opens a new bundle.
    Deterministic — same input yields the same bundles.
    """
    batches: list[list[dict[str, Any]]] = []
    unions: list[set[str]] = []
    for row in rows:
        chunks = set(row.get("source_chunk_ids") or [])
        placed = False
        for batch, union in zip(batches, unions, strict=True):
            if len(batch) >= batch_size:
                continue
            shared = chunks & union
            if shared and len(shared) / len(chunks | union) >= jaccard_threshold:
                batch.append(row)
                union |= chunks
                placed = True
                break
        if not placed:
            batches.append([row])
            unions.append(set(chunks))
    return batches


async def wiki_trigger_ready(store: KnowledgeStore, kb_id: str, *, threshold: float = DEFAULT_TRIGGER_THRESHOLD) -> bool:
    """True when the share of ``ready`` documents meets the threshold.

    A KB with no documents never auto-triggers (spec §3.7 鸡生蛋问题: the
    first batch is triggered manually or by this completion check).
    """
    async with store._sf() as session:
        total = int((await session.execute(select(func.count()).select_from(DocumentRow).where(DocumentRow.kb_id == kb_id))).scalar_one())
        if total == 0:
            return False
        ready = int((await session.execute(select(func.count()).select_from(DocumentRow).where(DocumentRow.kb_id == kb_id, DocumentRow.status == "ready"))).scalar_one())
    return ready / total >= threshold


async def mark_dirty_for_entities(wiki_store: WikiStore, kb_id: str, entity_names: Collection[str]) -> int:
    """New-document hook: flag the entries of the touched entities as dirty."""
    return await wiki_store.mark_dirty_for_titles(kb_id, entity_names)


def _default_llm():
    """Wiki writing: ``rag.wiki_model`` → the RAG default → the first model (spec 2026-09-26 D4).

    The same chain, helper and call shape as extraction and the judge: the name is resolved
    here and handed to the untouched factory, which is what makes the RAG default picker in
    the settings view govern this role too.
    """
    from deerflow.config.app_config import get_app_config
    from deerflow.knowledge.model_target import create_rag_chat_model, require_usable_rag_target

    config = get_app_config()
    return create_rag_chat_model(require_usable_rag_target(config, config.rag.wiki_model, role="百科生成"), thinking=bool(config.rag.wiki_thinking), app_config=config)


def _parse_batch_response(text: str, expected_titles: set[str]) -> dict[str, str]:
    """Parse a bundle response into ``{title: content}``; unparseable payloads
    and titles outside the requested roster are dropped (caller falls back)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}
    entries: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if title in expected_titles and content:
            entries[title] = content
    return entries


def _normalized_direction(value: str | None) -> str | None:
    """空白串与 ``None`` 同义（与 service 侧 ``_normalized_supplement`` 同一条规则）。"""
    text = (value or "").strip()
    return text or None


async def _direction_moved_since_snapshot(wiki_store: WikiStore, kb_id: str, title: str, guidance: str | None) -> bool:
    """这一轮生成期间，该条目的补充层被改过吗？

    保存补充层时若已有 run 在跑，``KnowledgeService.update_wiki_entry`` 只能标脏
    （待更新）；本次写入若照旧写 ``ready``，就把那枚待更新记号擦掉了 —— 方向留在
    库里却再也不会有下一轮来处理它（2026-09-12 真栈实测）。发现方向已动就写回
    ``dirty``，把这条交给下一次生成。条目不存在（backfill 首次生成）天然为 False。
    """
    entry = await wiki_store.get_entry(wiki_entry_id(kb_id, title))
    if entry is None:
        return False
    return _normalized_direction(entry.get("supplement_content")) != _normalized_direction(guidance)


async def _persist_entry(
    wiki_store: WikiStore,
    vector_store: KnowledgeVectorStore | None,
    graph_store: GraphStore,
    *,
    kb_id: str,
    row: dict[str, Any],
    content: str,
    embedder: _Embedder | None,
    stats: WikiStats,
    guidance: str | None = None,
) -> None:
    """Store one entry: business row + dense vector, and account for it.

    写入前资格重验（2026-08-23 竞态防护）：LLM 生成耗时数十秒，期间用户删除
    来源文档可致实体失格/消失——无重验则 upsert 会把幽灵条目写回。拦截时
    顺带补删残留旧条目（快照合格使它们不在 stale_titles 清理范围），否则
    dirty 条目永挂。删除顺序与级联规则一致：Qdrant 先行失败吞掉，业务行必删。

    ``guidance`` 是本轮开始时抓到的方向；写前与库中值再比一次，动了就写 ``dirty``
    （见 ``_direction_moved_since_snapshot``）。
    """
    if not await _is_currently_eligible(graph_store, kb_id, row["name"]):
        stats.skipped_stale += 1
        if vector_store is not None:
            try:
                await vector_store.delete_wiki_entries(kb_id, [row["name"]])
            except Exception:
                logger.exception("qdrant delete_wiki_entries failed for stale entry %s", row["name"])
        stats.pruned += await wiki_store.delete_entries(kb_id, [row["name"]])
        logger.info("wiki entry write skipped: %s lost eligibility mid-run (stale entry pruned)", row["name"])
        return
    status = "dirty" if await _direction_moved_since_snapshot(wiki_store, kb_id, row["name"], guidance) else "ready"
    entry = await wiki_store.upsert_entry(kb_id, title=row["name"], content=content, source_chunk_ids=list(row.get("source_chunk_ids") or []), status=status)
    if vector_store is not None and embedder is not None:
        (embedding,) = await embedder.embed([wiki_entry_embed_text(row["name"], content)])
        await vector_store.upsert_wiki_entries([WikiEntryUpsert(entry_id=entry["id"], kb_id=kb_id, title=row["name"], dense=embedding.dense)])
    stats.generated += 1
    stats.titles.append(row["name"])


async def _write_entry(
    store: KnowledgeStore,
    wiki_store: WikiStore,
    vector_store: KnowledgeVectorStore | None,
    graph_store: GraphStore,
    *,
    kb_id: str,
    row: dict[str, Any],
    llm: _LLM,
    embedder: _Embedder | None,
    stats: WikiStats,
    guidance: str | None = None,
) -> None:
    """Per-entity generation: the dirty refresh and bundle-fallback path.

    ``guidance`` is the entry's supplement layer (spec 2026-09-12): the direction
    the user wrote for how this entry should read. It is injected only when
    non-blank, so an entry without a supplement produces the byte-identical
    prompt this path produced before the feature.
    """
    chunk_ids = list(row.get("source_chunk_ids") or [])
    chunks = await store.get_chunks_by_ids(chunk_ids)
    materials = "\n\n".join(f"【切片 {i + 1}】{chunk['text']}" for i, chunk in enumerate(chunks))
    direction = (guidance or "").strip()
    direction_block = f"{WIKI_DIRECTION_HEADER}\n{direction}\n\n" if direction else ""
    messages = [
        {"role": "system", "content": WIKI_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (f"实体：{row['name']}\n类型：{row.get('type') or '未分类'}\n已有描述：{row.get('description') or '无'}\n\n{direction_block}来源切片：\n{materials or '（无切片材料）'}"),
        },
    ]
    response = await llm.ainvoke(messages)
    content = str(response.content).strip()
    if not content:
        logger.warning("wiki generation returned empty content for entity %s, skipped", row["name"])
        return
    await _persist_entry(wiki_store, vector_store, graph_store, kb_id=kb_id, row=row, content=content, embedder=embedder, stats=stats, guidance=guidance)


async def _write_bundle(
    store: KnowledgeStore,
    wiki_store: WikiStore,
    vector_store: KnowledgeVectorStore | None,
    graph_store: GraphStore,
    *,
    kb_id: str,
    rows: list[dict[str, Any]],
    llm: _LLM,
    embedder: _Embedder | None,
    stats: WikiStats,
) -> None:
    """One LLM call per material bundle; misses fall back to ``_write_entry``."""
    chunk_ids = sorted({cid for row in rows for cid in (row.get("source_chunk_ids") or [])})
    chunks = await store.get_chunks_by_ids(chunk_ids)
    materials = "\n\n".join(f"【切片 {i + 1}】{chunk['text']}" for i, chunk in enumerate(chunks))
    roster = "、".join(row["name"] for row in rows)
    messages = [
        {"role": "system", "content": WIKI_BATCH_SYSTEM_PROMPT},
        {"role": "user", "content": f"实体清单：{roster}\n\n来源切片：\n{materials or '（无切片材料）'}"},
    ]
    response = await llm.ainvoke(messages)
    written = _parse_batch_response(str(response.content), {row["name"] for row in rows})
    for row in rows:
        content = written.get(row["name"])
        if content is None:
            logger.warning("wiki bundle missed entity %s; falling back to single generation", row["name"])
            await _write_entry(store, wiki_store, vector_store, graph_store, kb_id=kb_id, row=row, llm=llm, embedder=embedder, stats=stats)
        else:
            await _persist_entry(wiki_store, vector_store, graph_store, kb_id=kb_id, row=row, content=content, embedder=embedder, stats=stats)


async def generate_wiki(
    store: KnowledgeStore,
    graph_store: GraphStore,
    wiki_store: WikiStore,
    vector_store: KnowledgeVectorStore | None = None,
    *,
    kb_id: str,
    llm: _LLM | None = None,
    embedder: _Embedder | None = None,
    only_dirty: bool = False,
    backfill_limit: int = DEFAULT_BACKFILL_LIMIT,
) -> WikiStats:
    """Generate (or regenerate) wiki entries for a KB.

    Default mode processes every eligible entity (triggered batch).
    ``only_dirty=True`` regenerates dirty entries per-entity and backfills
    eligible entities lacking an entry — at most ``backfill_limit`` new
    entries per run; the queued remainder is picked up by later triggers
    (spec §3.5 2026-08-12 revision).
    """
    if llm is None:
        llm = _default_llm()

    _IN_FLIGHT[kb_id] = _IN_FLIGHT.get(kb_id, 0) + 1
    try:
        if only_dirty:
            dirty = await wiki_store.list_entries(kb_id, status="dirty")
            # One eligibility evaluation feeds singles / backfill / prune alike
            # (精确匹配 title == entity name, 精度保持现状).
            eligible_rows = await select_eligible_entities(graph_store, kb_id)
            eligible_by_name = {row["name"]: row for row in eligible_rows}
            singles = [(eligible_by_name[entry["title"]], entry.get("supplement_content")) for entry in dirty if entry["title"] in eligible_by_name]
            # 失格即删 (2026-08-14 拍板, 方案 A): a dirty entry whose entity
            # vanished from the graph or fell below the eligibility bar is
            # pruned here — the same rule the Task 12 / re-extract cascades
            # already apply — otherwise its dirty badge could never drain.
            # Ready entries of ineligible entities stay untouched: the
            # incremental run only owns the dirty set.
            stale_titles = [entry["title"] for entry in dirty if entry["title"] not in eligible_by_name]
            # 2026-08-12 revision (spec §3.5): backfill = eligible entities
            # without an entry (any status counts — idempotent), paced per run.
            entry_titles = {entry["title"] for entry in await wiki_store.list_entries(kb_id)}
            backfill = [row for row in eligible_rows if row["name"] not in entry_titles][:backfill_limit]
        else:
            stale_titles = []
            backfill = await select_eligible_entities(graph_store, kb_id)
            # A full rebuild hands every eligible entity to the batch path, whose
            # prompt cannot carry per-entry guidance — so entries that DO have a
            # supplement layer are pulled back onto the per-entity path instead of
            # silently losing their direction (spec 2026-09-12).
            existing = {entry["title"]: entry for entry in await wiki_store.list_entries(kb_id)}
            singles = [(row, (existing.get(row["name"]) or {}).get("supplement_content")) for row in backfill if ((existing.get(row["name"]) or {}).get("supplement_content") or "").strip()]
            guided_titles = {row["name"] for row, _ in singles}
            backfill = [row for row in backfill if row["name"] not in guided_titles]

        stats = WikiStats(selected=len(singles) + len(backfill))
        if stale_titles:
            # Qdrant first, failures logged and swallowed — mirrors the
            # service-layer cascade ordering rule: a vector outage must never
            # strand the business-row delete. ``delete_entries`` is idempotent,
            # so a mid-run crash simply re-prunes on the next trigger.
            if vector_store is not None:
                try:
                    await vector_store.delete_wiki_entries(kb_id, stale_titles)
                except Exception:
                    logger.exception("qdrant delete_wiki_entries failed during wiki prune for kb %s (%d titles)", kb_id, len(stale_titles))
            stats.pruned = await wiki_store.delete_entries(kb_id, stale_titles)
            logger.info("wiki regeneration: pruned %d disqualified/vanished dirty entries for kb %s", stats.pruned, kb_id)
        # Per-entity work (dirty refresh + the guided slice of a full rebuild) runs
        # one call at a time: a handful, not worth bundling — and the guidance is
        # per-entry, which a shared batch prompt cannot express.
        for row, guidance in singles:
            await _write_entry(store, wiki_store, vector_store, graph_store, kb_id=kb_id, row=row, llm=llm, embedder=embedder, stats=stats, guidance=guidance)
        for bundle in plan_entry_batches(backfill):
            await _write_bundle(store, wiki_store, vector_store, graph_store, kb_id=kb_id, rows=bundle, llm=llm, embedder=embedder, stats=stats)
        _LAST_RUN[kb_id] = "succeeded"
        return stats
    except Exception:
        _LAST_RUN[kb_id] = "failed"
        raise
    finally:
        remaining = _IN_FLIGHT.get(kb_id, 0) - 1
        if remaining > 0:
            _IN_FLIGHT[kb_id] = remaining
        else:
            _IN_FLIGHT.pop(kb_id, None)


async def regenerate_wiki_entries(
    store: KnowledgeStore,
    graph_store: GraphStore,
    wiki_store: WikiStore,
    vector_store: KnowledgeVectorStore | None = None,
    *,
    kb_id: str,
    entry_ids: Sequence[str],
    llm: _LLM | None = None,
    embedder: _Embedder | None = None,
) -> WikiStats:
    """Regenerate specific wiki entries by id (per-entry 局部更新/重建).

    The user hand-picks the entries, so entity selection is already done — this
    is the same atomic rewrite as the dirty refresh (``_write_entry``): map each
    ``entry_id`` to its title, resolve the entity's *current* source chunks, and
    re-run the single-entity LLM pass (clears ``dirty``, preserves the
    supplement layer **and feeds it back as the entry's direction**, re-embeds).
    Entries whose entity vanished from the graph
    are pruned here (失格即删, same rule as the incremental stale branch);
    entities that still exist but lost eligibility are caught by the write-time
    re-check in ``_persist_entry``.

    Shares the ``_IN_FLIGHT`` / ``_LAST_RUN`` counters with ``generate_wiki``, so
    a per-entry run is mutually exclusive with a library-level one (no
    overlapping LLM runs on the same KB) and feeds the same 更新中 / completion
    signals.
    """
    if llm is None:
        llm = _default_llm()

    _IN_FLIGHT[kb_id] = _IN_FLIGHT.get(kb_id, 0) + 1
    try:
        entities_by_name = {row["name"]: row for row in await graph_store.list_entities(kb_id)}
        targets: list[tuple[dict[str, Any], str | None]] = []
        orphan_titles: list[str] = []
        for entry_id in entry_ids:
            entry = await wiki_store.get_entry(entry_id)
            if entry is None or entry["kb_id"] != kb_id:
                continue
            row = entities_by_name.get(entry["title"])
            if row is None:
                # Entity gone → the entry is an orphan; prune it (vector first,
                # failures swallowed — mirrors the module cascade ordering).
                orphan_titles.append(entry["title"])
            else:
                targets.append((row, entry.get("supplement_content")))

        stats = WikiStats(selected=len(targets))
        if orphan_titles:
            if vector_store is not None:
                try:
                    await vector_store.delete_wiki_entries(kb_id, orphan_titles)
                except Exception:
                    logger.exception("qdrant delete_wiki_entries failed during regen orphan prune for kb %s (%d titles)", kb_id, len(orphan_titles))
            stats.pruned = await wiki_store.delete_entries(kb_id, orphan_titles)
            logger.info("wiki regeneration: pruned %d orphaned entries for kb %s", stats.pruned, kb_id)
        for row, guidance in targets:
            await _write_entry(store, wiki_store, vector_store, graph_store, kb_id=kb_id, row=row, llm=llm, embedder=embedder, stats=stats, guidance=guidance)
        _LAST_RUN[kb_id] = "succeeded"
        return stats
    except Exception:
        _LAST_RUN[kb_id] = "failed"
        raise
    finally:
        remaining = _IN_FLIGHT.get(kb_id, 0) - 1
        if remaining > 0:
            _IN_FLIGHT[kb_id] = remaining
        else:
            _IN_FLIGHT.pop(kb_id, None)
