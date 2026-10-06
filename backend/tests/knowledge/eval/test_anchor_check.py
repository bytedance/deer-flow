"""Anchor guard tests for the golden question write path (spec 2026-10-05 §2/§4).

写入口「锚定核验」：纯字符串比对（`sparse._tokenize` 分词集合交），零 LLM。
q008 形状 = 答案锚贴到不含答案术语的切片（贴错）⇒ 拦截并回显结构化明细；
人可带一次性确认标记（`anchor_ack`）放行术语级拦截——机器要求人看一眼，不否决人。
两条豁免钉死：无参考答案免术语核验（锚存在性照跑）、多片题只拦单片零命中。
"""

from __future__ import annotations

import json

import pytest

from deerflow.knowledge.eval.question_bank import add_question, load_questions

pytestmark = pytest.mark.asyncio

DOC = "e" * 32
GOOD_CHUNK = f"{DOC}#0001"
WRONG_CHUNK = f"{DOC}#0002"
WEAK_CHUNK = f"{DOC}#0003"
MISSING_CHUNK = f"{DOC}#0999"

CHUNK_TEXTS = {
    GOOD_CHUNK: "什么是自动拆箱/装箱？装箱：将基本数据类型转换为包装类型。拆箱：将包装类型转换为基本数据类型。",
    WRONG_CHUNK: "Integer 会缓存 -128 到 127 的对象，==比较的是引用地址。",
    WEAK_CHUNK: "装箱可以手工完成，也可以由编译器自动完成。",
}

REFERENCE = "装箱是把基本数据类型转成包装类型；拆箱是把包装类型转成基本数据类型。"


def _anchor_check():
    # 延迟导入：RED 期模块未建，逐用例报 ImportError 而非整文件收集失败。
    from deerflow.knowledge.eval import anchor_check

    return anchor_check


def _guard(texts: dict[str, str] | None = None):
    ac = _anchor_check()
    mapping = dict(CHUNK_TEXTS if texts is None else texts)

    async def fetch(chunk_ids):
        # store_fetch 同款契约：锚定片 + 同文档切片（找对照 B 用）。
        docs = {cid.rsplit("#", 1)[0] for cid in chunk_ids}
        return {cid: text for cid, text in mapping.items() if cid.rsplit("#", 1)[0] in docs}

    return ac.guard_from_fetch(fetch)


def _fields(**overrides) -> dict:
    fields = {
        "query": "什么是自动拆箱和装箱？",
        "category": "fact",
        "expected_paths": ("vector",),
        "relevant_chunk_ids": [WRONG_CHUNK],
        "relevant_entities": [],
        "reference_answer": REFERENCE,
    }
    fields.update(overrides)
    return fields


async def test_misanchored_question_is_blocked_with_structured_detail(tmp_path) -> None:
    ac = _anchor_check()
    path = tmp_path / "golden.jsonl"

    with pytest.raises(ac.AnchorMismatchError) as exc_info:
        await add_question(path, anchor_guard=_guard(), **_fields())

    detail = exc_info.value.detail
    assert detail["reason"] in ("mismatch", "zero_hit")
    assert "装箱" in detail["miss_terms"]
    assert detail["suggested_chunk"] == GOOD_CHUNK
    assert detail["hits"] < detail["best_hits"]
    # 拦截即不落盘——题库不留半成品。
    assert await load_questions(path) == []


async def test_ack_flag_lets_human_override_mismatch(tmp_path) -> None:
    path = tmp_path / "golden.jsonl"

    question = await add_question(path, anchor_guard=_guard(), anchor_ack=True, **_fields())

    assert [q.id for q in await load_questions(path)] == [question.id]


async def test_empty_answer_skips_term_check(tmp_path) -> None:
    path = tmp_path / "golden.jsonl"

    question = await add_question(path, anchor_guard=_guard(), **_fields(reference_answer=None))

    assert question.id


async def test_missing_chunk_is_not_bypassable_even_with_ack(tmp_path) -> None:
    ac = _anchor_check()
    path = tmp_path / "golden.jsonl"

    for answer in (REFERENCE, None):
        with pytest.raises(ac.AnchorMismatchError) as exc_info:
            await add_question(
                path,
                anchor_guard=_guard(),
                anchor_ack=True,
                **_fields(relevant_chunk_ids=[MISSING_CHUNK], reference_answer=answer),
            )
        assert exc_info.value.detail["reason"] == "missing_chunk"
    assert await load_questions(path) == []


async def test_multi_chunk_beaten_anchor_passes(tmp_path) -> None:
    # 多片题只拦"单片零命中"：WEAK_CHUNK 命中弱但 >0 ⇒ 被压制只作提示、放行。
    path = tmp_path / "golden.jsonl"

    question = await add_question(
        path,
        anchor_guard=_guard(),
        **_fields(relevant_chunk_ids=[GOOD_CHUNK, WEAK_CHUNK]),
    )

    assert question.id


async def test_multi_chunk_zero_hit_chunk_is_blocked(tmp_path) -> None:
    ac = _anchor_check()
    path = tmp_path / "golden.jsonl"

    with pytest.raises(ac.AnchorMismatchError) as exc_info:
        await add_question(
            path,
            anchor_guard=_guard(),
            **_fields(relevant_chunk_ids=[GOOD_CHUNK, WRONG_CHUNK]),
        )

    assert exc_info.value.detail["reason"] in ("mismatch", "zero_hit")
    assert await load_questions(path) == []


async def test_no_guard_keeps_today_behavior(tmp_path) -> None:
    # 零受害者钉：guard 默认关时既有调用形状不变（误锚照样入库）。
    path = tmp_path / "golden.jsonl"

    question = await add_question(path, **_fields())

    assert [q.id for q in await load_questions(path)] == [question.id]
    assert json.loads(path.read_text(encoding="utf-8").strip())["reference_answer"] == REFERENCE


async def test_verdict_names_suspicious_chunks_for_read_time_badges(tmp_path) -> None:
    """读时「存疑」徽章的疑片集（spec 2026-10-05 §2④）：判定层给出被疑的锚
    （单片贴错=该片、多片零命中=全部零命中片），``detail`` 五键 wire 契约不动。"""
    ac = _anchor_check()

    single = ac.check_anchor(reference_answer=REFERENCE, anchor_chunk_ids=[WEAK_CHUNK], chunk_texts=CHUNK_TEXTS)
    assert single.reason == "mismatch"
    assert single.chunk_ids == (WEAK_CHUNK,)
    assert set(single.detail) == {"reason", "miss_terms", "hits", "best_hits", "suggested_chunk"}

    multi = ac.check_anchor(reference_answer=REFERENCE, anchor_chunk_ids=[GOOD_CHUNK, WRONG_CHUNK], chunk_texts=CHUNK_TEXTS)
    assert multi.reason == "zero_hit"
    assert multi.chunk_ids == (WRONG_CHUNK,)

    ok = ac.check_anchor(reference_answer=REFERENCE, anchor_chunk_ids=[GOOD_CHUNK], chunk_texts=CHUNK_TEXTS)
    assert ok.chunk_ids == ()
