"""视频镜头卡进 L1 检索评测的最小集成用例（spec 2026-09-08 §6，plan Task 11）。

证明 spec §6 的核心断言——「镜头卡作为 chunk 自动进入 L1（确定性检索）与
recall@k、path_accuracy 全部现有指标」——**零改造**成立：视频镜头卡的 chunk_id
（``{doc_id}#{shot_index:04d}``，doc_id 是 32 位小写 hex）天然匹配 golden schema 的
``relevant_chunk_ids`` 正则，卡正文（``shot_card.assemble_card_body`` 冻结三段）即
嵌入文本。故本用例建一个 fake 视频 KB（真实 store：视频文档 + 三张镜头卡 chunk，
分别主导造题指引的视觉描述 / 口述 / 屏幕文字三类），跑生产同款 ``run_layer1_for_kb``
编排，断言 recall@k 有数。向量检索用 stub searcher（真实 embedding 非本用例关注点；
L1 编排 / 指标计算 / 持久化全走真实链路）。
"""

from __future__ import annotations

import uuid

import pytest

from deerflow.knowledge.eval import ondemand
from deerflow.knowledge.eval.question_bank import add_question
from deerflow.knowledge.eval.runner import ScoredHit
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.video.shot_card import assemble_card_body, chunk_id_for_shot, heading_path_for_shot

pytestmark = pytest.mark.asyncio

KB = "kb-video-eval"
OWNER = str(uuid.UUID(int=1234567890))
GENERATED_AT = "2026-09-09T10:00:00+00:00"
VIDEO_NAME = "退休制度培训.mp4"

# 三张镜头卡的三路原文，分别主导一类造题（spec §6 / video-kb-question-authoring.md）：
# 视觉描述型（caption）/ 口述型（asr）/ 屏幕文字型（ocr）。full 模式下每张卡仍是冻结
# 三段（空路补「（无）」），主导路只是语义上该题的命中依据。
_SHOTS = [
    dict(caption="讲师站在白板前讲解退休制度", asr_text="", ocr_text=""),
    dict(caption="", asr_text="退休年龄按渐进式延迟方案执行", ocr_text=""),
    dict(caption="", asr_text="", ocr_text="第三章 退休制度 第十五条"),
]


@pytest.fixture
def store(session_factory):
    return KnowledgeStore(session_factory)


@pytest.fixture(autouse=True)
def _clean_in_flight():
    yield
    ondemand._IN_FLIGHT.pop(KB, None)
    ondemand._PROGRESS.pop(KB, None)


async def _seed_video_kb(store: KnowledgeStore) -> tuple[str, list[str]]:
    """建 fake 视频 KB：一个 .mp4 文档 + 三张镜头卡 chunk（生产同款 shot_card 组装）。

    镜头卡即 spec §2「镜头卡 = chunk」的落库形态：chunk_id 扁平序、卡正文是冻结三段。
    insert 后从 store 读回，返回 ``(doc_id, 按镜头序的 chunk_id 列表)``——下游用真实
    store 往返的 chunk_id，证明镜头卡确实是 KB 里的 chunk（而非凭空构造的 id）。
    """
    await store.create_kb(kb_id=KB, owner_id=OWNER, name="视频库")
    doc_id = uuid.uuid4().hex
    await store.create_document(
        doc_id=doc_id,
        kb_id=KB,
        uploader_id=OWNER,
        name=VIDEO_NAME,
        size_bytes=2048,
        storage_path=f"/data/{doc_id}/{VIDEO_NAME}",
    )
    await store.insert_chunks(
        [
            {
                "chunk_id": chunk_id_for_shot(doc_id, index),
                "doc_id": doc_id,
                "kb_id": KB,
                "chunk_index": index,
                "text": assemble_card_body(**shot),
                "heading_path": heading_path_for_shot(VIDEO_NAME, index),
            }
            for index, shot in enumerate(_SHOTS)
        ]
    )
    stored = await store.list_chunks(doc_id)
    return doc_id, [chunk["chunk_id"] for chunk in stored]


def _searchers_hitting(hit_chunk_ids: list[str]) -> dict:
    """stub searchers：vector 路按序命中给定镜头卡（模拟向量检索召回，分数递减）。"""

    async def vector_fn(query: str, top_k: int):
        return tuple(ScoredHit(chunk_id=cid, score=0.9 - 0.01 * i) for i, cid in enumerate(hit_chunk_ids[:top_k]))

    async def empty_fn(query: str, top_k: int):
        return ()

    return {"vector": vector_fn, "graph": empty_fn, "wiki": empty_fn}


async def test_shot_card_chunk_ids_are_valid_golden_anchors(store, tmp_path) -> None:
    """镜头卡 chunk_id 可直接作 golden ``relevant_chunk_ids``（零 schema 改造）。

    ``add_question`` 内部 ``validate_question`` 强制每条 relevant_chunk_id 匹配
    ``<32-hex doc_id>#NNNN``（dataset._CHUNK_ID_RE）；镜头卡 chunk_id 通过校验 =
    天然兼容现有评测锚定，无需为视频引入任何新 schema 或降级语义。
    """
    _doc_id, chunk_ids = await _seed_video_kb(store)

    golden = tmp_path / "golden.jsonl"
    question = await add_question(
        golden,
        query="镜头卡锚定兼容性",
        category="fact",
        expected_paths=["vector"],
        relevant_chunk_ids=chunk_ids,
    )

    assert question.relevant_chunk_ids == tuple(chunk_ids)
    assert len(chunk_ids) == len(_SHOTS)


async def test_shot_cards_enter_layer1_recall(store, tmp_path) -> None:
    """fake 视频 KB → 镜头卡作为 chunk 进 L1 检索：recall@k 有数（spec §6）。"""
    _doc_id, chunk_ids = await _seed_video_kb(store)
    speech_card = chunk_ids[1]  # 口述型镜头卡（asr 主导）

    golden = tmp_path / "golden.jsonl"
    await add_question(
        golden,
        query="视频里讲师说的退休年龄怎么执行",
        category="fact",
        expected_paths=["vector"],
        relevant_chunk_ids=[speech_card],
    )

    await ondemand.run_layer1_for_kb(
        KB,
        golden_path=golden,
        searchers=_searchers_hitting(chunk_ids),
        generated_at=GENERATED_AT,
    )

    rows = await store.list_eval_runs(KB)
    assert len(rows) == 1
    assert rows[0].status == "completed"
    summary = rows[0].layer1_metrics["summary"]
    assert summary["question_count"] == 1
    # 口述型镜头卡被 vector 路命中 → recall@k / hit_rate 满分（有数，非 None/0）。
    assert summary["recall_at_k"] == 1.0
    assert summary["hit_rate"] == 1.0
    # 镜头卡走 vector 路命中且 expected_paths=["vector"] → path_accuracy 也计入。
    assert summary["path_accuracy"] == 1.0
