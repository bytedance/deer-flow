"""Unit tests for ``deerflow_knowledge.dimension_probe`` (spec 2026-09-26 §3 探针实现).

The probe answers "which dimensions does this embedding model accept" from a handful of real
calls, and the whole design rests on one criterion: **a candidate passes only when the answer
is ``200`` *and* the returned width equals what was asked** — the 2026-09-27 live run caught
``qwen3.7-text-embedding-flash`` answering ``200`` while silently clamping 1536/2048/2560 back
to 1024 (see ``pr-build/rag-embedding-probe-2026-09-27/``). These tests drive an
``httpx.MockTransport`` whose answer is a function of the asked dimension, so every branch
(three types, the no-param width call, verify-then-list, zero-tier fallback, misjudged range)
is pinned without a network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from deerflow_knowledge.dimension_probe import (
    CANDIDATE_DIMENSIONS,
    WILD_DIMENSION,
    DimensionProbeError,
    probe_dimensions,
)

PROBE_TEXT = "probe"
TIMEOUT = 5.0

SHAPES = {
    "generic": "openai-compatible",
    "dashscope": "dashscope",
    "ark": "volcengine-ark",
}


def _asked_dimension(shape: str, body: dict[str, Any]) -> int | None:
    """Which dimension the outgoing request asks for (None = the no-param call)."""
    if shape == "generic":
        return body.get("dimensions")
    if shape == "dashscope":
        return (body.get("parameters") or {}).get("dimension")
    if shape == "ark":
        return body.get("dimensions")
    raise AssertionError(shape)


def _ok_response(shape: str, width: int) -> httpx.Response:
    vector = [0.0] * width
    if shape == "generic":
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})
    if shape == "dashscope":
        return httpx.Response(200, json={"output": {"embeddings": [{"text_index": 0, "embedding": vector}]}})
    return httpx.Response(200, json={"data": {"embedding": vector}})


class _Stub:
    """An endpoint whose answer is a function of the asked dimension.

    ``answer(asked) -> (status, width)``; ``asked`` is ``None`` for the no-param call. The stub
    records every asked dimension and every raw body so a test can assert *what was sent*.
    """

    def __init__(self, shape: str, answer) -> None:
        self.shape = shape
        self.answer = answer
        self.asked: list[int | None] = []
        self.bodies: list[dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            asked = _asked_dimension(self.shape, body)
            self.asked.append(asked)
            self.bodies.append(body)
            status, width = self.answer(asked)
            if status != 200:
                return httpx.Response(status, json={"error": "refused"})
            return _ok_response(self.shape, width)

        return httpx.MockTransport(handler)


async def _run(shape: str, answer, *, base_url: str = "http://stub.local"):
    stub = _Stub(shape, answer)
    async with httpx.AsyncClient(transport=stub.transport()) as client:
        result = await probe_dimensions(
            provider=SHAPES[shape],
            model="stub-model",
            base_url=base_url,
            api_key="stub-key",
            text=PROBE_TEXT,
            timeout=TIMEOUT,
            client=client,
        )
    return result, stub


# ── 三型定性 ────────────────────────────────────────────────────────────────


async def test_range_measures_native_without_param_and_verifies_upper_bound():
    """② 型：333 被接受 ⇒ 原生宽度必须另发一发"不带参数"的，再验一次上界（3 发、不跑候选表）。"""
    result, stub = await _run("generic", lambda asked: (200, asked if asked is not None else 1536))

    assert result.type == "range"
    assert result.native == 1536
    assert result.values == [1536]
    assert stub.asked == [WILD_DIMENSION, None, 1536], "定性 + 量宽 + 上界验证，没有候选表请求"


async def test_tiered_lists_only_candidates_that_answer_with_the_asked_width():
    """① 型：333 被拒 ⇒ 逐档并发探；原生 1024 在表内 ⇒ 不补验。"""
    passing = {256, 512, 768, 1024}
    result, stub = await _run(
        "generic",
        lambda asked: (200, 1024) if asked is None else ((200, asked) if asked in passing else (400, 0)),
    )

    assert result.type == "tiered"
    assert result.native == 1024
    assert result.values == [256, 512, 768, 1024]
    assert sorted(stub.asked, key=lambda value: -1 if value is None else value) == sorted([WILD_DIMENSION, None, *CANDIDATE_DIMENSIONS], key=lambda value: -1 if value is None else value)


async def test_fixed_type_reuses_the_qualitative_answer_and_sends_one_call():
    """③ 型：参数被忽略 ⇒ 定性那发的宽度就是原生，不再多发。"""
    result, stub = await _run("generic", lambda asked: (200, 768))

    assert result.type == "fixed"
    assert result.native == 768
    assert result.values == [768]
    assert stub.asked == [WILD_DIMENSION]


# ── 三腿请求形状 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("shape", ["generic", "dashscope", "ark"])
async def test_three_legs_speak_their_own_request_shape(shape: str):
    """同一套判定换三种请求形状：发出去的参数名/形状必须与该腿客户端一致。"""
    result, stub = await _run(
        shape,
        lambda asked: (200, 1024) if asked is None else ((200, asked) if asked == 1024 else (400, 0)),
    )

    assert result.type == "tiered"
    qualitative = stub.bodies[0]
    if shape == "generic":
        assert qualitative["dimensions"] == WILD_DIMENSION and qualitative["input"] == [PROBE_TEXT]
    elif shape == "dashscope":
        assert qualitative["parameters"]["dimension"] == WILD_DIMENSION
        assert qualitative["parameters"]["output_type"] == "dense&sparse"
        assert qualitative["input"]["texts"] == [PROBE_TEXT]
    else:
        assert qualitative["dimensions"] == WILD_DIMENSION
        assert qualitative["input"] == [{"type": "text", "text": PROBE_TEXT}], "ark 一次只收一条 content"


# ── 回退与补验 ──────────────────────────────────────────────────────────────


async def test_zero_tier_fallback_keeps_the_measured_native_with_empty_values():
    """① 型一档都没过 ⇒ values 空、但 native 仍是实测默认宽度（上层据此渲染回退）。"""
    result, _ = await _run("generic", lambda asked: (200, 1024) if asked is None else (400, 0))

    assert result.type == "tiered"
    assert result.values == []
    assert result.native == 1024


async def test_offtable_native_is_verified_before_it_joins_the_list():
    """原生 ∉ 候选表 ⇒ 补一发 `dimensions: <原生>`；通过与不通过都不撒谎。"""

    def answer(asked):
        if asked is None:
            return 200, 640
        if asked == 640:
            return 200, 640
        return 400, 0

    result, stub = await _run("generic", answer)
    assert result.values == [640]
    assert stub.asked.count(640) == 1

    def clamped(asked):
        if asked is None:
            return 200, 640
        if asked == 640:
            return 200, 1024  # 200 但宽度不等于所求 ⇒ 不算通过
        return 400, 0

    result, _ = await _run("generic", clamped)
    assert result.values == []

    def in_table(asked):
        if asked is None:
            return 200, 1024
        return (200, asked) if asked == 1024 else (400, 0)

    result, stub = await _run("generic", in_table)
    assert result.values == [1024]
    assert stub.asked.count(1024) == 1, "原生在表内 ⇒ 不补验（逐档那一发已经问过）"


async def test_clamped_200_is_not_a_pass_in_any_of_the_three_places():
    """复刻 flash：1536 回 200 但宽度被钳成 1024 ⇒ 不列（① 逐档处按宽度相等判）。"""

    def answer(asked):
        if asked is None:
            return 200, 1024
        if asked == 1536:
            return 200, 1024
        return (200, asked) if asked in {256, 512, 768, 1024} else (400, 0)

    result, _ = await _run("generic", answer)

    assert result.values == [256, 512, 768, 1024]
    assert 1536 not in result.values


# ── ② 的上界验证与判歪 ─────────────────────────────────────────────────────


async def test_fake_range_with_unsettable_native_degrades_to_tiered():
    """真 ① 收 333 ⇒ 被判 ②；上界那一发失败 ⇒ 当场降级跑候选表、values = 真档位。"""

    def answer(asked):
        if asked is None:
            return 200, 1024
        if asked == WILD_DIMENSION:
            return 200, WILD_DIMENSION
        if asked == 1024:
            return 400, 0  # 上界要不到 ⇒ 判歪
        return (200, asked) if asked == 512 else (400, 0)

    result, stub = await _run("generic", answer)

    assert result.type == "tiered"
    assert result.values == [512]
    assert stub.asked.count(1024) >= 1, "降级后按候选表重问（1024 是候选之一）"


async def test_fake_range_with_settable_native_is_caught_nowhere_and_stays_range():
    """常见分支：真 ① 收 333 且原生可设 ⇒ 上界通过 ⇒ 不降级（退化为未验提示 + 保存期兜底）。"""

    def answer(asked):
        if asked is None:
            return 200, 1024
        if asked == WILD_DIMENSION:
            return 200, WILD_DIMENSION
        if asked == 1024:
            return 200, 1024
        return 400, 0

    result, _ = await _run("generic", answer)

    assert result.type == "range"
    assert result.values == [1024]


# ── 失败形态 ────────────────────────────────────────────────────────────────


async def test_refused_credentials_raise_a_probe_error():
    """探不出 = 抛 `DimensionProbeError`（端点把它渲染成"未探明"，不是 500）。"""
    with pytest.raises(DimensionProbeError):
        await _run("generic", lambda asked: (401, 0))
