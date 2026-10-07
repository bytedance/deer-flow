"""One cap for the caption leg (spec 2026-10-03 D1=甲).

The caption leg's concurrency cap is a single shared constant rather than a formula of
``worker_concurrency``. The pins run at W=1 and W=3, where such a formula would diverge,
and assert the cap does not scale with W.
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


async def _caption_cap_for(monkeypatch, *, worker_concurrency: int) -> int:
    """The cap the caption leg builds, at one worker count."""
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage

    config = _config(worker_concurrency)
    monkeypatch.setattr(captioner_module, "get_app_config", lambda: config)
    monkeypatch.setattr(asyncio, "Semaphore", _RecordingSemaphore)

    _RecordingSemaphore.built = []
    await caption_images([ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")], client=httpx.AsyncClient(transport=_transport()), model="vl-entry")
    return _RecordingSemaphore.built[-1]


@pytest.mark.asyncio
async def test_the_caption_leg_builds_the_cap(monkeypatch):
    assert await _caption_cap_for(monkeypatch, worker_concurrency=1) == 4


@pytest.mark.asyncio
async def test_the_cap_does_not_scale_with_worker_concurrency(monkeypatch):
    caps_at_one = await _caption_cap_for(monkeypatch, worker_concurrency=1)
    caps_at_three = await _caption_cap_for(monkeypatch, worker_concurrency=3)

    assert caps_at_one == caps_at_three
