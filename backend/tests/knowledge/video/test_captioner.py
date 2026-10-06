"""Shot captioner leg tests (spec 2026-09-08 §2/§3, plan Task 6).

VLM 层用 httpx.MockTransport mock（对齐现有 captioner 测试先例 test_parser.py）；
配文目标用一条真实的 `models:` 条目（spec 2026-09-23 D10.3：钥匙从条目来，环境变量
兜底与裸 id 路径已退役）。核心契约：条目无钥匙 → 全镜头降级空 + degraded；
单镜头 VLM 失败 → 该镜头空、计入 failed；failed/total > 30% → degraded（对齐
graph 30% 规则，spec §2）。降级非硬依赖——caption 缺失时镜头卡仍含 asr+ocr。
"""

from __future__ import annotations

import json

import httpx
import pytest

from deerflow.knowledge.video.captioner import CaptionOutcome, caption_shots


def _vlm_transport(*, fail_first: int = 0, content: str = "镜头描述", recorded: list[httpx.Request] | None = None) -> httpx.MockTransport:
    """前 fail_first 次调用返回 500，其余返回固定 caption（并发下失败总数确定）。"""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if recorded is not None:
            recorded.append(request)
        index = state["n"]
        state["n"] += 1
        if index < fail_first:
            return httpx.Response(500, text="vlm boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


_FRAMES = {0: [b"\xff\xd8frame0"], 1: [b"\xff\xd8frame1"]}

#: The caption target these tests resolve: a real ``models:`` entry, because the caption legs
#: read the key from the entry now (spec 2026-09-23 D10.3/R14) — the env fallback and the
#: bare-id path are gone, so a bare id is not a target any more.
_VLM_ENTRY = {
    "name": "test-vlm",
    "use": "langchain_openai:ChatOpenAI",
    "model": "test-vlm-wire",
    "base_url": "https://vlm.example/v1",
    "api_key": "test-key",
    "supports_vision": True,
}


def _vlm_config(*, with_key: bool = True, rag: dict | None = None):
    """The entry-backed config; ``with_key=False`` leaves the entry keyless on purpose.

    ``rag`` overrides the section's own keys (A-4's caption knobs).
    """
    from deerflow.config.app_config import AppConfig

    entry = {key: value for key, value in _VLM_ENTRY.items() if with_key or key != "api_key"}
    return AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": [entry], "rag": {"vlm_model": "test-vlm", **(rag or {})}})


@pytest.fixture(autouse=True)
def _caption_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deerflow.knowledge.video.captioner.get_app_config", _vlm_config)


async def test_caption_shots_empty_input():
    assert await caption_shots({}) == CaptionOutcome(captions={}, failed=0, degraded=False)


async def test_caption_shots_all_success(monkeypatch):
    async with httpx.AsyncClient(transport=_vlm_transport(content="讲师讲解")) as client:
        outcome = await caption_shots(_FRAMES, client=client, model="test-vlm")
    assert outcome.captions == {0: "讲师讲解", 1: "讲师讲解"}
    assert outcome.failed == 0
    assert outcome.degraded is False


async def test_caption_shots_missing_key_degrades_all(monkeypatch):
    """api_key 缺失 → 不 outbound，全镜头空 caption + degraded（对齐现有 captioner 降级）。"""
    monkeypatch.setattr("deerflow.knowledge.video.captioner.get_app_config", lambda: _vlm_config(with_key=False))
    outcome = await caption_shots(_FRAMES, model="test-vlm")
    assert outcome.captions == {0: "", 1: ""}
    assert outcome.failed == 2
    assert outcome.degraded is True


async def test_caption_shots_partial_failure_below_threshold(monkeypatch):
    """1/5 失败 = 20% < 30% → 不 degraded。"""
    frames = {i: [b"f"] for i in range(5)}
    async with httpx.AsyncClient(transport=_vlm_transport(fail_first=1)) as client:
        outcome = await caption_shots(frames, client=client, model="test-vlm")
    assert outcome.failed == 1
    assert outcome.degraded is False
    assert sum(1 for c in outcome.captions.values() if c) == 4  # 4 个非空


async def test_caption_shots_failure_above_threshold(monkeypatch):
    """2/5 失败 = 40% > 30% → degraded（对齐 graph 30% 规则）。"""
    frames = {i: [b"f"] for i in range(5)}
    async with httpx.AsyncClient(transport=_vlm_transport(fail_first=2)) as client:
        outcome = await caption_shots(frames, client=client, model="test-vlm")
    assert outcome.failed == 2
    assert outcome.degraded is True


async def test_caption_shots_exactly_30_percent_not_degraded(monkeypatch):
    """3/10 失败 = 30%（非 >30%）→ 不 degraded（阈值严格大于）。"""
    frames = {i: [b"f"] for i in range(10)}
    async with httpx.AsyncClient(transport=_vlm_transport(fail_first=3)) as client:
        outcome = await caption_shots(frames, client=client, model="test-vlm")
    assert outcome.failed == 3
    assert outcome.degraded is False


async def test_caption_shots_no_frames_for_shot_is_empty_not_failed(monkeypatch):
    """无帧镜头（抽帧全失败）→ 空 caption，不计 VLM failed（无输入 ≠ 调用失败）。"""
    frames = {0: [], 1: [b"f"]}
    async with httpx.AsyncClient(transport=_vlm_transport(content="描述")) as client:
        outcome = await caption_shots(frames, client=client, model="test-vlm")
    assert outcome.captions[0] == ""
    assert outcome.captions[1] == "描述"
    assert outcome.failed == 0


async def test_shot_caption_request_carries_the_configured_generation_params(monkeypatch):
    """A-4: the two knobs reach the wire from ``rag.caption_*`` (spec 2026-09-30 D1/D2)."""
    monkeypatch.setattr("deerflow.knowledge.video.captioner.get_app_config", lambda: _vlm_config(rag={"caption_max_tokens": 2048, "caption_temperature": 0.7}))
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_vlm_transport(recorded=recorded)) as client:
        await caption_shots(_FRAMES, client=client, model="test-vlm")

    body = json.loads(recorded[0].content)
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.7


async def test_shot_caption_request_defaults_are_the_pre_change_values(monkeypatch):
    """The leg-level negative control: undeclared ⇒ 1024 / 0.15 on the wire (Task 0 capture)."""
    recorded: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_vlm_transport(recorded=recorded)) as client:
        await caption_shots(_FRAMES, client=client, model="test-vlm")

    body = json.loads(recorded[0].content)
    assert body["max_tokens"] == 1024
    assert body["temperature"] == 0.15
