"""孤儿向量对账清扫（spec 2026-10-04；2026-10-05 D4/D5/D6）。

以业务库为准绳：四集合各扫一遍（无 kb 过滤）→ 按 payload ``kb_id`` 分组 →
kb 行缺的整组清（D4：旧枚举"活库表"看不见的那批）、行在的逐点查行；收集
候选 → 复核一遍 → 只删复核后仍缺失的。两段式兜住卡片创建路径"向量先于行"
的窗口（knowledge_service.py:941-950）与开关翻转窗口（D5）。
不建持久记录、不碰业务行与文件；单集合失败记录后继续；幂等可重复。

同模块还有两件同轮步骤：
- **文件侧对账** ``reconcile_files``（spec 2026-10-05 §2.2）：walk ``knowledge/``
  目录树、同一把准绳（业务行存在性）。
- **代次回收** ``sweep_generations``（§2.6）：名字 ≠ 声明宽度代的家族集合整删。
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from deerflow.knowledge.wiki.generator import wiki_generation_in_progress
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

_COLLECTION_KEYS: tuple[str, ...] = ("chunks", "entities", "wiki_entries", "manual_cards")
_CHUNK_CHECK_BATCH = 512
#: 点龄门（spec 2026-10-05 D2=甲）：toggle-on 的 [upsert→行写] 窗口里新点龄≈0，
#: 低于宽限永不进候选——窗口单调关闭；无 updated_at 键=老、照删。
_CARD_ORPHAN_GRACE_SECONDS = 60.0


@dataclass(slots=True)
class SweepReport:
    scanned: dict[str, int] = field(default_factory=lambda: {key: 0 for key in _COLLECTION_KEYS})
    deleted: dict[str, int] = field(default_factory=lambda: {key: 0 for key in _COLLECTION_KEYS})
    deleted_kb_groups: dict[str, int] = field(default_factory=lambda: {key: 0 for key in _COLLECTION_KEYS})
    skipped: dict[str, int] = field(default_factory=lambda: {key: 0 for key in _COLLECTION_KEYS})
    failed: list[str] = field(default_factory=list)


def _note_failed(report: SweepReport, key: str) -> None:
    if key not in report.failed:
        report.failed.append(key)


def _group_by_kb(records) -> dict[str, list]:
    groups: dict[str, list] = {}
    for record in records:
        kb_id = (record.payload or {}).get("kb_id")
        if kb_id:
            groups.setdefault(kb_id, []).append(record)
    return groups


async def sweep_round(*, store, vector_store, graph_store, wiki_store, skip_kb_ids: set[str] | None = None) -> SweepReport:
    """一轮集合级清扫（D4）：组内闸跳过 → kb 行缺整组清、行在逐点判（均两段式）。

    ``skip_kb_ids`` 与 wiki 腿在飞并集构成组内闸（对活库与已删库组一视同仁）。
    """
    report = SweepReport()
    skip = skip_kb_ids or set()
    steps = (
        ("chunks", vector_store.chunks_collection, _sweep_chunks, _deleted_kb_chunks),
        ("entities", vector_store.entities_collection, _sweep_entities, _deleted_kb_entities),
        ("wiki_entries", vector_store.wiki_entries_collection, _sweep_wiki_entries, _deleted_kb_wiki_entries),
        ("manual_cards", vector_store.manual_cards_collection, _sweep_manual_cards, _deleted_kb_manual_cards),
    )
    for key, collection, live_step, group_step in steps:
        try:
            records = await vector_store.scroll_collection(collection)
            report.scanned[key] = len(records)
            groups = _group_by_kb(records)
            live_groups: dict[str, list] = {}
            group_candidates: list[str] = []
            for kb_id, group_records in groups.items():
                if kb_id in skip or wiki_generation_in_progress(kb_id):
                    continue
                if await store.get_kb(kb_id) is None:
                    group_candidates.append(kb_id)
                else:
                    live_groups[kb_id] = group_records
            for kb_id, group_records in live_groups.items():
                try:
                    await live_step(report, records=group_records, store=store, vector_store=vector_store, graph_store=graph_store, wiki_store=wiki_store, kb_id=kb_id)
                except Exception:
                    logger.exception("orphan sweep failed for kb %s collection %s; continuing", kb_id, key)
                    _note_failed(report, key)
            still_gone = [kb_id for kb_id in group_candidates if await store.get_kb(kb_id) is None]
            report.skipped[key] += len(group_candidates) - len(still_gone)
            for kb_id in still_gone:
                try:
                    report.deleted_kb_groups[key] += await group_step(groups[kb_id], store=store, vector_store=vector_store, kb_id=kb_id)
                except Exception:
                    logger.exception("orphan sweep failed for deleted kb %s collection %s; continuing", kb_id, key)
                    _note_failed(report, key)
        except Exception:
            logger.exception("orphan sweep failed for collection %s; continuing", key)
            _note_failed(report, key)
    if any(report.deleted.values()) or any(report.deleted_kb_groups.values()) or report.failed:
        logger.info(
            "orphan sweep round scanned=%s deleted=%s deleted_kb_groups=%s skipped=%s failed=%s",
            report.scanned,
            report.deleted,
            report.deleted_kb_groups,
            report.skipped,
            report.failed,
        )
    return report


async def _existing_chunk_ids(store, chunk_ids: list[str], kb_id: str) -> set[str]:
    found: set[str] = set()
    for start in range(0, len(chunk_ids), _CHUNK_CHECK_BATCH):
        batch = chunk_ids[start : start + _CHUNK_CHECK_BATCH]
        rows = await store.get_chunks_by_ids(batch, kb_id=kb_id)
        found.update(row["chunk_id"] for row in rows)
    return found


async def _sweep_chunks(report: SweepReport, *, records, store, vector_store, graph_store, wiki_store, kb_id: str) -> None:
    ids = sorted({(record.payload or {}).get("chunk_id") for record in records if (record.payload or {}).get("chunk_id")})
    if not ids:
        return
    live = await _existing_chunk_ids(store, ids, kb_id)
    candidates = [chunk_id for chunk_id in ids if chunk_id not in live]
    if not candidates:
        return
    confirmed_live = await _existing_chunk_ids(store, candidates, kb_id)
    still_orphans = [chunk_id for chunk_id in candidates if chunk_id not in confirmed_live]
    report.skipped["chunks"] += len(candidates) - len(still_orphans)
    if still_orphans:
        await vector_store.delete_chunks(still_orphans)
        report.deleted["chunks"] += len(still_orphans)


async def _sweep_entities(report: SweepReport, *, records, store, vector_store, graph_store, wiki_store, kb_id: str) -> None:
    names = sorted({(record.payload or {}).get("name") for record in records if (record.payload or {}).get("name")})
    if not names:
        return
    live = {row["name"] for row in await graph_store.list_entities(kb_id)}
    candidates = [name for name in names if name not in live]
    if not candidates:
        return
    live_again = {row["name"] for row in await graph_store.list_entities(kb_id)}
    still_orphans = [name for name in candidates if name not in live_again]
    report.skipped["entities"] += len(candidates) - len(still_orphans)
    if still_orphans:
        await vector_store.delete_entities(kb_id, still_orphans)
        report.deleted["entities"] += len(still_orphans)


async def _sweep_wiki_entries(report: SweepReport, *, records, store, vector_store, graph_store, wiki_store, kb_id: str) -> None:
    title_by_id: dict[str, str] = {}
    for record in records:
        payload = record.payload or {}
        if payload.get("entry_id"):
            title_by_id[payload["entry_id"]] = payload.get("title") or ""
    if not title_by_id:
        return
    live = {row["id"] for row in await wiki_store.list_entries(kb_id)}
    candidates = [entry_id for entry_id in title_by_id if entry_id not in live]
    if not candidates:
        return
    live_again = {row["id"] for row in await wiki_store.list_entries(kb_id)}
    still_orphans = [entry_id for entry_id in candidates if entry_id not in live_again]
    report.skipped["wiki_entries"] += len(candidates) - len(still_orphans)
    titles = [title_by_id[entry_id] for entry_id in still_orphans if title_by_id[entry_id]]
    if titles:
        await vector_store.delete_wiki_entries(kb_id, titles)
        report.deleted["wiki_entries"] += len(titles)


async def _card_is_live(store, card_id: str) -> bool:
    """D5：行存在**且**开关开才保留（关开关失败留下的残留点才是孤儿）。"""
    card = await store.get_manual_card(card_id)
    return card is not None and bool(card.get("include_in_wiki_search"))


async def _sweep_manual_cards(report: SweepReport, *, records, store, vector_store, graph_store, wiki_store, kb_id: str) -> None:
    card_ids = sorted({(record.payload or {}).get("card_id") for record in records if (record.payload or {}).get("card_id")})
    if not card_ids:
        return
    updated_by_id: dict[str, float] = {}
    for record in records:
        payload = record.payload or {}
        if payload.get("card_id"):
            updated_by_id[payload["card_id"]] = float(payload.get("updated_at") or 0.0)
    now = time.time()
    candidates = [card_id for card_id in card_ids if not await _card_is_live(store, card_id) and now - updated_by_id.get(card_id, 0.0) > _CARD_ORPHAN_GRACE_SECONDS]
    if not candidates:
        return
    still_orphans = [card_id for card_id in candidates if not await _card_is_live(store, card_id)]
    report.skipped["manual_cards"] += len(candidates) - len(still_orphans)
    if still_orphans:
        await vector_store.delete_manual_cards(still_orphans)
        report.deleted["manual_cards"] += len(still_orphans)


# ── 已删库组（D4） ─────────────────────────────────────────────────────


async def _deleted_kb_chunks(records, *, store, vector_store, kb_id: str) -> int:
    ids = sorted({(record.payload or {}).get("chunk_id") for record in records if (record.payload or {}).get("chunk_id")})
    if not ids:
        return 0
    await vector_store.delete_chunks(ids)
    return len(ids)


async def _deleted_kb_entities(records, *, store, vector_store, kb_id: str) -> int:
    names = sorted({(record.payload or {}).get("name") for record in records if (record.payload or {}).get("name")})
    if not names:
        return 0
    await vector_store.delete_entities(kb_id, names)
    return len(names)


async def _deleted_kb_wiki_entries(records, *, store, vector_store, kb_id: str) -> int:
    titles = sorted({(record.payload or {}).get("title") for record in records if (record.payload or {}).get("title")})
    if not titles:
        return 0
    await vector_store.delete_wiki_entries(kb_id, titles)
    return len(titles)


async def _deleted_kb_manual_cards(records, *, store, vector_store, kb_id: str) -> int:
    card_ids = sorted({(record.payload or {}).get("card_id") for record in records if (record.payload or {}).get("card_id")})
    if not card_ids:
        return 0
    await vector_store.delete_manual_cards(card_ids)
    return len(card_ids)


# ── 代次回收（D6，spec §2.6） ─────────────────────────────────────────


@dataclass(slots=True)
class GenerationReport:
    dropped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: str | None = None


async def sweep_generations(*, vector_store, declared_width: int) -> GenerationReport:
    """回收非声明宽度的代次集合。

    前置=声明代的四个集合**全部在位**——否则旧代可能是唯一副本（手改宽度
    没走迁移态），必须停手。命中家族名（前缀 + 四种 kind + 可选 ``_数字``
    后缀）且 ≠ 声明代的集合整删，逐个吞错（并发删"已不存在"属正常）。
    锚点=声明宽度（调用方传 ``effective_dimension()``），不用任何持有的实例。
    """
    report = GenerationReport()
    declared = set(vector_store.names_at_width(declared_width))
    names = await vector_store.list_all_collections()
    if not declared.issubset(names):
        report.skipped = "the declared generation is not fully present"
        logger.info("generation sweep skipped: declared width %d generation is not fully present", declared_width)
        return report
    family = re.compile(rf"{re.escape(vector_store.collection_prefix)}_(?:{'|'.join(_COLLECTION_KEYS)})(?:_\d+)?$")
    leftovers = sorted(name for name in names if name not in declared and family.fullmatch(name))
    for name in leftovers:
        try:
            if await vector_store.drop_collection(name):
                report.dropped.append(name)
        except Exception:
            logger.exception("generation sweep failed to drop %s; next round retries", name)
            report.failed.append(name)
    if report.dropped or report.failed:
        logger.info("generation sweep declared_width=%d dropped=%s failed=%s", declared_width, report.dropped, report.failed)
    return report


# ── 文件侧对账（spec 2026-10-05 §2.2） ──────────────────────────────────


@dataclass(slots=True)
class FileReconcileReport:
    kb_dirs: int = 0
    doc_dirs: int = 0
    removed_docs: int = 0
    removed_kbs: int = 0
    kept: int = 0
    failed: list[str] = field(default_factory=list)


async def reconcile_files(*, data_dir: str | Path, store, skip_kb_ids: set[str] | None = None) -> FileReconcileReport:
    """Walk ``knowledge/`` and remove trees whose business rows are gone.

    判据（Task 0 实测的布局）：只有 ``<kb_id>/<doc_id>`` 形状的子目录才算文档
    目录；kb 级直挂文件（golden.jsonl / eval_candidates.json）不属对账面。
    kb 行缺 → 整棵清；doc 行缺（或 kb_id 不匹配）→ 整目录清。两段式：收集
    候选 → 复核行仍缺 → 再删（覆盖上传 write→insert 在途窗口）；忙库整库跳过；
    失败仅记录、下轮重试；幂等。
    """
    report = FileReconcileReport()
    root = Path(data_dir) / "knowledge"
    skip = skip_kb_ids or set()
    if not root.is_dir():
        return report

    kb_candidates: list[Path] = []
    doc_candidates: list[Path] = []
    for kb_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        kb_id = kb_dir.name
        if kb_id in skip:
            continue
        report.kb_dirs += 1
        if await store.get_kb(kb_id) is None:
            kb_candidates.append(kb_dir)
            continue
        for doc_dir in sorted(p for p in kb_dir.iterdir() if p.is_dir()):
            report.doc_dirs += 1
            doc = await store.get_document(doc_dir.name)
            if doc is None or doc["kb_id"] != kb_id:
                doc_candidates.append(doc_dir)

    still_kb_orphans = [kb_dir for kb_dir in kb_candidates if await store.get_kb(kb_dir.name) is None]
    report.kept += len(kb_candidates) - len(still_kb_orphans)
    still_doc_orphans: list[Path] = []
    for doc_dir in doc_candidates:
        doc = await store.get_document(doc_dir.name)
        if doc is None or doc["kb_id"] != doc_dir.parent.name:
            still_doc_orphans.append(doc_dir)
        else:
            report.kept += 1

    for doc_dir in still_doc_orphans:
        if await _remove_tree(doc_dir, report):
            report.removed_docs += 1
    for kb_dir in still_kb_orphans:
        if await _remove_tree(kb_dir, report):
            report.removed_kbs += 1
    if report.removed_docs or report.removed_kbs or report.failed:
        logger.info(
            "file reconcile scanned kb_dirs=%d doc_dirs=%d removed_docs=%d removed_kbs=%d kept=%d failed=%s",
            report.kb_dirs,
            report.doc_dirs,
            report.removed_docs,
            report.removed_kbs,
            report.kept,
            report.failed,
        )
    return report


async def _remove_tree(path: Path, report: FileReconcileReport) -> bool:
    try:
        await run_file_io(shutil.rmtree, path, ignore_errors=True)
        return True
    except Exception:
        logger.exception("file reconcile failed to remove %s; next round retries", path)
        report.failed.append(str(path))
        return False
