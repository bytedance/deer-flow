"""VideoShotStore contract tests (spec 2026-09-08 §3, plan Task 2).

Covers the frozen semantics: the ``(doc_id, shot_index)`` unique key, the
resume-safe upsert contract (present keys overwrite, absent keys persist),
the pending query that drives caption-leg resume, and the idempotent
per-document cascade delete.
"""

from __future__ import annotations

import pytest

from deerflow.knowledge.video.store import VideoShotStore

pytestmark = pytest.mark.asyncio


def _shot(index: int, start_ms: int, end_ms: int, **extra) -> dict:
    return {"shot_index": index, "start_ms": start_ms, "end_ms": end_ms, **extra}


async def test_bulk_upsert_and_list_round_trip(session_factory):
    store = VideoShotStore(session_factory)

    written = await store.bulk_upsert_shots("doc-1", kb_id="kb-1", shots=[_shot(0, 0, 5000), _shot(1, 5000, 12400, asr_text="你好")])
    rows = await store.list_shots("doc-1")

    assert written == 2
    assert [row["shot_index"] for row in rows] == [0, 1]  # 按 start_ms 升序 = 写入序
    assert rows[0]["start_ms"] == 0
    assert rows[0]["end_ms"] == 5000
    assert rows[0]["kb_id"] == "kb-1"
    # 列默认值：三路原文皆空、关键帧可缺、resume 状态机起点 pending
    assert rows[0]["asr_text"] == ""
    assert rows[0]["ocr_text"] == ""
    assert rows[0]["caption"] == ""
    assert rows[0]["keyframe_path"] is None
    assert rows[0]["caption_status"] == "pending"
    assert rows[1]["asr_text"] == "你好"
    assert len(rows[0]["id"]) == 32  # uuid hex
    assert isinstance(rows[0]["created_at"], str)  # coerce_iso 后出 dict


async def test_upsert_update_only_overwrites_present_keys(session_factory):
    """resume/重跑安全契约：第二次写入未出现的键保持旧值；caption_status
    不被隐式重置（状态重置属于 recaption 流程，Task 8b）。"""
    store = VideoShotStore(session_factory)
    await store.bulk_upsert_shots("doc-1", kb_id="kb-1", shots=[_shot(0, 0, 5000, asr_text="第一段")])
    await store.bulk_upsert_shots("doc-1", kb_id="kb-1", shots=[{"shot_index": 0, "caption": "讲师开场", "caption_status": "done"}])

    rows = await store.list_shots("doc-1")

    assert len(rows) == 1  # (doc_id, shot_index) 唯一键：更新而非追加
    assert rows[0]["asr_text"] == "第一段"  # 未出现的键保持旧值
    assert rows[0]["start_ms"] == 0
    assert rows[0]["end_ms"] == 5000
    assert rows[0]["caption"] == "讲师开场"
    assert rows[0]["caption_status"] == "done"


async def test_upsert_skips_partial_insert_when_row_absent(session_factory):
    """删除与索引竞态契约：行已消失且 payload 缺非空列（start_ms/end_ms）时跳过，
    绝不插 NULL 行（2026-09-09 事故：同名重复上传 cascade 删行后，caption 腿的
    部分键 upsert 走 INSERT 分支，autoflush 插 NULL start_ms 炸掉整条索引腿）；
    同批中已有行的映射照常更新。"""
    store = VideoShotStore(session_factory)
    await store.bulk_upsert_shots("doc-1", kb_id="kb-1", shots=[_shot(0, 0, 5000)])

    written = await store.bulk_upsert_shots(
        "doc-1",
        kb_id="kb-1",
        shots=[{"shot_index": 0, "caption": "更新已有行"}, {"shot_index": 7, "caption": "行已消失", "caption_status": "done"}],
    )
    rows = await store.list_shots("doc-1")

    assert written == 1  # 仅已有行计入；缺行且缺非空列的映射被跳过
    assert len(rows) == 1  # 没有插出 NULL start_ms 的脏行
    assert rows[0]["caption"] == "更新已有行"
    assert rows[0]["caption_status"] == "pending"  # 跳过不影响其余行的状态机


async def test_same_shot_index_coexists_across_documents(session_factory):
    """唯一约束 scoped 到 (doc_id, shot_index)：跨文档同序号互不冲突。"""
    store = VideoShotStore(session_factory)
    await store.bulk_upsert_shots("doc-1", kb_id="kb-1", shots=[_shot(0, 0, 5000)])
    await store.bulk_upsert_shots("doc-2", kb_id="kb-1", shots=[_shot(0, 0, 3000)])

    assert len(await store.list_shots("doc-1")) == 1
    assert len(await store.list_shots("doc-2")) == 1


async def test_list_pending_shots_drives_resume(session_factory):
    """pending 查询是 caption 腿 resume 的唯一入口：done/empty 不重跑。"""
    store = VideoShotStore(session_factory)
    await store.bulk_upsert_shots(
        "doc-1",
        kb_id="kb-1",
        shots=[_shot(0, 0, 5000), _shot(1, 5000, 9000), _shot(2, 9000, 12000)],
    )
    await store.bulk_upsert_shots(
        "doc-1",
        kb_id="kb-1",
        shots=[{"shot_index": 0, "caption_status": "done"}, {"shot_index": 2, "caption_status": "empty"}],
    )

    pending = await store.list_pending_shots("doc-1")

    assert [row["shot_index"] for row in pending] == [1]  # 只剩 pending，升序


async def test_delete_by_doc_is_cascading_and_idempotent(session_factory):
    store = VideoShotStore(session_factory)
    await store.bulk_upsert_shots("doc-1", kb_id="kb-1", shots=[_shot(0, 0, 5000), _shot(1, 5000, 9000)])
    await store.bulk_upsert_shots("doc-2", kb_id="kb-1", shots=[_shot(0, 0, 3000)])

    assert await store.delete_by_doc("doc-1") == 2
    assert await store.list_shots("doc-1") == []
    assert len(await store.list_shots("doc-2")) == 1  # 别的文档不受牵连
    assert await store.delete_by_doc("doc-1") == 0  # 幂等：再删返 0

    assert await store.bulk_upsert_shots("doc-3", kb_id="kb-1", shots=[]) == 0  # 空 payload 短路
