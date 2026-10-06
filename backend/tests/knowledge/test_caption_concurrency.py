"""One cap for both caption legs (spec 2026-10-03 D1=甲).

The two legs used to build their concurrency caps from two formulas — the image leg a
hard 4, the video leg ``worker_concurrency × 2`` (which double-counts W: W=2 makes both
come out at 4 and hides the split). The pins run at W=1 and W=3, where the old formulas
diverge, and assert both legs build one shared value that does not scale with W.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from deerflow.config.app_config import AppConfig

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

VL_ENTRY = {
    "name": "vl-entry",
    "use": "langchain_openai:ChatOpenAI",
    "model": "wire-vl",
    "base_url": "https://vl.example/v1",
    "api_key": "sk-vl",
    "supports_vision": True,
}


def _config(worker_concurrency: int) -> AppConfig:
    return AppConfig.model_validate({"sandbox": SANDBOX, "models": [VL_ENTRY], "rag": {"worker_concurrency": worker_concurrency}})


def _transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "一张图"}}]}))


class _RecordingSemaphore(asyncio.Semaphore):
    built: list[int] = []

    def __init__(self, value: int = 1) -> None:
        super().__init__(value)
        type(self).built.append(value)


async def _caps_for(monkeypatch, *, worker_concurrency: int) -> tuple[int, int]:
    """The cap each leg builds, at one worker count."""
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage
    from deerflow.knowledge.video import captioner as video_captioner_module
    from deerflow.knowledge.video.captioner import caption_shots

    config = _config(worker_concurrency)
    monkeypatch.setattr(captioner_module, "get_app_config", lambda: config)
    monkeypatch.setattr(video_captioner_module, "get_app_config", lambda: config)
    monkeypatch.setattr(asyncio, "Semaphore", _RecordingSemaphore)

    _RecordingSemaphore.built = []
    await caption_images([ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")], client=httpx.AsyncClient(transport=_transport()), model="vl-entry")
    image_cap = _RecordingSemaphore.built[-1]

    _RecordingSemaphore.built = []
    await caption_shots({0: [b"frame"]}, client=httpx.AsyncClient(transport=_transport()), model="vl-entry")
    video_cap = _RecordingSemaphore.built[-1]
    return image_cap, video_cap


@pytest.mark.asyncio
async def test_both_legs_build_the_same_cap(monkeypatch):
    image_cap, video_cap = await _caps_for(monkeypatch, worker_concurrency=1)

    assert image_cap == video_cap == 4


@pytest.mark.asyncio
async def test_the_cap_does_not_scale_with_worker_concurrency(monkeypatch):
    caps_at_one = await _caps_for(monkeypatch, worker_concurrency=1)
    caps_at_three = await _caps_for(monkeypatch, worker_concurrency=3)

    assert caps_at_one == caps_at_three
