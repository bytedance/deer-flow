"""孤儿向量对账清扫（spec 2026-10-04；2026-10-05 D4/D5/D6）。

以业务库为准绳：chunks 集合扫一遍（无 kb 过滤）→ 按 payload ``kb_id`` 分组 →
kb 行缺的整组清（D4：旧枚举"活库表"看不见的那批）、行在的逐点查行；收集
候选 → 复核一遍 → 只删复核后仍缺失的。两段式兜住写入在途窗口。
不建持久记录、不碰业务行与文件；失败记录后继续；幂等可重复。

同模块还有两件同轮步骤：
- **文件侧对账** ``reconcile_files``（spec 2026-10-05 §2.2）：walk ``knowledge/``
  目录树、同一把准绳（业务行存在性）。
- **代次回收** ``sweep_generations``（§2.6）：名字 ≠ 声明宽度代的家族集合整删。
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

_COLLECTION_KEYS: tuple[str, ...] = ("chunks",)
_CHUNK_CHECK_BATCH = 512


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


async def sweep_round(*, store, vector_store, skip_kb_ids: set[str] | None = None) -> SweepReport:
    """一轮集合级清扫（D4）：组内闸跳过 → kb 行缺整组清、行在逐点判（均两段式）。

    ``skip_kb_ids`` 构成组内闸（对活库与已删库组一视同仁）。
    """
    report = SweepReport()
    skip = skip_kb_ids or set()
    steps = (("chunks", vector_store.chunks_collection, _sweep_chunks, _deleted_kb_chunks),)
    for key, collection, live_step, group_step in steps:
        try:
            records = await vector_store.scroll_collection(collection)
            report.scanned[key] = len(records)
            groups = _group_by_kb(records)
            live_groups: dict[str, list] = {}
            group_candidates: list[str] = []
            for kb_id, group_records in groups.items():
                if kb_id in skip:
                    continue
                if await store.get_kb(kb_id) is None:
                    group_candidates.append(kb_id)
                else:
                    live_groups[kb_id] = group_records
            for kb_id, group_records in live_groups.items():
                try:
                    await live_step(report, records=group_records, store=store, vector_store=vector_store, kb_id=kb_id)
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


async def _sweep_chunks(report: SweepReport, *, records, store, vector_store, kb_id: str) -> None:
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


# ── 已删库组（D4） ─────────────────────────────────────────────────────


async def _deleted_kb_chunks(records, *, store, vector_store, kb_id: str) -> int:
    ids = sorted({(record.payload or {}).get("chunk_id") for record in records if (record.payload or {}).get("chunk_id")})
    if not ids:
        return 0
    await vector_store.delete_chunks(ids)
    return len(ids)


# ── 代次回收（D6，spec §2.6） ─────────────────────────────────────────


@dataclass(slots=True)
class GenerationReport:
    dropped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: str | None = None


async def sweep_generations(*, vector_store, declared_width: int) -> GenerationReport:
    """回收非声明宽度的代次集合。

    前置=声明代的集合**全部在位**——否则旧代可能是唯一副本（手改宽度
    没走迁移态），必须停手。命中家族名（前缀 + kind + 可选 ``_数字``
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
    目录；kb 级直挂文件（golden.jsonl）不属对账面。
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
