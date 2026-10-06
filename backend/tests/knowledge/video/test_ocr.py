"""屏幕文字腿的契约测试（spec 2026-09-08 §2/§8；2026-09-30 起走 `rag.vlm_model`）。

清洗拼接是纯函数；腿本身（目标解析 / 无钥匙 / 单镜头失败 / >30% ⇒ degraded）与 caption
腿**共用同一套骨架**（`run_shot_prompt`），所以这里用 `httpx.MockTransport` 覆盖调用与
降级，不打真实 VLM 端点。与 caption 腿的差别只有两点：提问的 prompt（要转录、不要描述）
与返回文本的清洗。
"""

from __future__ import annotations

import httpx
import pytest

from deerflow.knowledge.video.ocr import normalize_ocr_text, screen_text_shots

# ── normalize_ocr_text 纯函数 ────────────────────────────────────────────


def test_normalize_strips_and_joins_in_order():
    assert normalize_ocr_text(["  你好  ", "世界", "  "]) == "你好\n世界"


def test_normalize_empty_is_empty_string():
    assert normalize_ocr_text([]) == ""
    assert normalize_ocr_text(["   ", "\t"]) == ""


# ── screen_text_shots（VLM 路线）─────────────────────────────────────────


def _vlm_transport(*, fail_first: int = 0, content: str = "季度经营分析会\nQ3 Revenue 128.4M") -> httpx.MockTransport:
    """前 fail_first 次调用返回 500，其余返回固定文本（并发下失败总数确定）。"""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = state["n"]
        state["n"] += 1
        if index < fail_first:
            return httpx.Response(500, text="vlm boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


_FRAMES = {0: [b"\xff\xd8frame0"], 1: [b"\xff\xd8frame1"]}

#: 与 caption 腿同一套目标解析：屏幕文字读的也是 `rag.vlm_model` 指的那条 `models:` 条目
#: （spec 2026-09-30：不再有独立的 OCR 引擎，也没有 `video.ocr_lang`）。
_VLM_ENTRY = {
    "name": "test-vlm",
    "use": "langchain_openai:ChatOpenAI",
    "model": "test-vlm-wire",
    "base_url": "https://vlm.example/v1",
    "api_key": "test-key",
    "supports_vision": True,
}


def _vlm_config(*, with_key: bool = True):
    from deerflow.config.app_config import AppConfig

    entry = {key: value for key, value in _VLM_ENTRY.items() if with_key or key != "api_key"}
    return AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": [entry], "rag": {"vlm_model": "test-vlm"}})


@pytest.fixture(autouse=True)
def _vlm_target(monkeypatch: pytest.MonkeyPatch) -> None:
    # 骨架住在 captioner 里（两条腿共用），目标解析也发生在那里。
    monkeypatch.setattr("deerflow.knowledge.video.captioner.get_app_config", _vlm_config)


async def test_screen_text_shots_returns_the_transcription():
    async with httpx.AsyncClient(transport=_vlm_transport()) as client:
        outcome = await screen_text_shots(_FRAMES, client=client, model="test-vlm")

    assert outcome.captions == {0: "季度经营分析会\nQ3 Revenue 128.4M", 1: "季度经营分析会\nQ3 Revenue 128.4M"}
    assert outcome.failed == 0
    assert outcome.degraded is False


async def test_screen_text_shots_asks_for_a_transcript_not_a_description():
    """这一句 prompt 是它与 caption 腿唯一的语义差别：要转录、不要描述。"""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "屏幕上的字"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await screen_text_shots({0: [b"\xff\xd8frame"]}, client=client, model="test-vlm")

    assert "转录" in seen[0]
    assert "描述这个镜头" not in seen[0]


async def test_screen_text_shots_blank_lines_are_dropped():
    async with httpx.AsyncClient(transport=_vlm_transport(content="第一行\n\n  \n第二行")) as client:
        outcome = await screen_text_shots({0: [b"\xff\xd8frame"]}, client=client, model="test-vlm")

    assert outcome.captions == {0: "第一行\n第二行"}


async def test_screen_text_shots_empty_input():
    outcome = await screen_text_shots({})
    assert outcome.captions == {}
    assert outcome.failed == 0
    assert outcome.degraded is False


async def test_a_single_failed_shot_keeps_the_others_and_does_not_degrade():
    """1/4 失败 = 25% < 30%：那一个镜头空，其余照旧，腿不标 degraded。"""
    frames = {0: [b"f0"], 1: [b"f1"], 2: [b"f2"], 3: [b"f3"]}
    async with httpx.AsyncClient(transport=_vlm_transport(fail_first=1)) as client:
        outcome = await screen_text_shots(frames, client=client, model="test-vlm")

    assert outcome.failed == 1
    assert len([text for text in outcome.captions.values() if text]) == 3
    assert outcome.degraded is False


async def test_a_failure_rate_over_the_threshold_degrades_the_leg():
    frames = {0: [b"f0"], 1: [b"f1"], 2: [b"f2"]}
    async with httpx.AsyncClient(transport=_vlm_transport(fail_first=2)) as client:
        outcome = await screen_text_shots(frames, client=client, model="test-vlm")

    assert outcome.failed == 2
    assert outcome.degraded is True


async def test_frameless_shots_are_not_failures():
    """无帧镜头留空、不计失败（无输入 ≠ 调用失败）——与 caption 腿同一条规则。"""
    async with httpx.AsyncClient(transport=_vlm_transport()) as client:
        outcome = await screen_text_shots({0: [b"f0"], 1: []}, client=client, model="test-vlm")

    assert outcome.captions[1] == ""
    assert outcome.failed == 0
    assert outcome.degraded is False


async def test_a_keyless_target_degrades_without_a_call(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("deerflow.knowledge.video.captioner.get_app_config", lambda: _vlm_config(with_key=False))
    outcome = await screen_text_shots(_FRAMES, model="test-vlm")

    assert outcome.captions == {0: "", 1: ""}
    assert outcome.failed == 2
    assert outcome.degraded is True
