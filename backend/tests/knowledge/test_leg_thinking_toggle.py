"""Per-leg thinking toggles: checked legs follow chat's treatment (spec 2026-10-03).

The caption legs read ``rag.vlm_thinking``; they are raw HTTP, so they mirror the
lead-agent entry gate (an entry that declares no thinking support is pressed back to
non-thinking with a warning) at the outbound door. The default is False: an unchecked
leg builds exactly the request it builds today.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from deerflow.config.app_config import AppConfig

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

ENABLED_SHAPE = {"extra_body": {"thinking": {"type": "enabled"}}}
DISABLED_SHAPE = {"extra_body": {"thinking": {"type": "disabled"}}}

#: A thinking-capable entry with both spellings declared (the D3 shape he configured).
THINKING_ENTRY = {
    "name": "think-entry",
    "use": "langchain_openai:ChatOpenAI",
    "model": "wire-think",
    "base_url": "https://think.example/v1",
    "api_key": "sk-think",
    "supports_thinking": True,
    "when_thinking_enabled": ENABLED_SHAPE,
    "when_thinking_disabled": DISABLED_SHAPE,
}

#: Same spellings, but the entry declares no thinking support — the gate's case.
UNSUPPORTED_ENTRY = {
    **THINKING_ENTRY,
    "name": "plain-entry",
    "model": "wire-plain",
    "supports_thinking": False,
}


def _config(models: list[dict] | None = None, rag: dict | None = None) -> AppConfig:
    return AppConfig.model_validate({"sandbox": SANDBOX, "models": models or [THINKING_ENTRY], "rag": rag or {}})


# ── the caption legs mirror the entry gate at the outbound door ─────────────


def _vlm_target(cfg, name: str):
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    return resolve_vlm_target(cfg, name)


def _caption_body(target, **kwargs):
    from deerflow.knowledge.caption_client import _openai_request

    return _openai_request(target, "Describe.", [(b"jpeg", "image/jpeg")], max_tokens=1024, temperature=0.15, **kwargs)[0]


def test_caption_checked_sends_the_declared_enable_shape():
    target = _vlm_target(_config([THINKING_ENTRY]), "think-entry")

    body = _caption_body(target, thinking=True)

    assert body["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in body


def test_caption_checked_without_a_declared_shape_adds_nothing():
    bare = {key: value for key, value in THINKING_ENTRY.items() if not key.startswith("when_thinking") and key != "supports_thinking"}
    target = _vlm_target(_config([bare]), "think-entry")

    body = _caption_body(target, thinking=True)

    assert "thinking" not in body and "reasoning_effort" not in body


def test_caption_default_still_sends_the_disable_shape():
    target = _vlm_target(_config([THINKING_ENTRY]), "think-entry")

    body = _caption_body(target)

    assert body["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_caption_checked_but_the_entry_declares_no_support_downgrades_with_a_warning(caplog):
    from deerflow.knowledge.caption_client import request_caption

    target = _vlm_target(_config([UNSUPPORTED_ENTRY]), "plain-entry")
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "一张图"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level(logging.WARNING):
            await request_caption(client, target=target, prompt="Describe.", images=[(b"jpeg", "image/jpeg")], max_tokens=1024, temperature=0.15, thinking=True)

    import json as _json

    body = _json.loads(recorded[0].content)
    assert body["thinking"] == {"type": "disabled"}  # pressed back to the off spelling
    # The caption door names the wire model (VlmTarget carries no entry name).
    assert "wire-plain" in caplog.text and "does not support" in caplog.text


# ── D2=甲: the output budget rises while thinking is on ───────────────────
#
# Thinking tokens draw from the same output budget (the truncation post-mortem), so the
# effective budget gets a 4096 floor when thinking is on — never cutting a higher user
# value, and never rising once the entry gate has pressed thinking back off.


async def _sent_max_tokens(entry_name: str, *, thinking: bool, user_budget: int) -> int:
    import json as _json

    from deerflow.knowledge.caption_client import request_caption

    target = _vlm_target(_config([THINKING_ENTRY if entry_name == "think-entry" else UNSUPPORTED_ENTRY]), entry_name)
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await request_caption(client, target=target, prompt="p", images=[(b"jpeg", "image/jpeg")], max_tokens=user_budget, temperature=0.15, thinking=thinking)
    return _json.loads(recorded[0].content)["max_tokens"]


@pytest.mark.asyncio
async def test_checked_caption_raises_the_budget_to_at_least_4096():
    assert await _sent_max_tokens("think-entry", thinking=True, user_budget=1024) == 4096


@pytest.mark.asyncio
async def test_checked_caption_keeps_a_higher_user_budget():
    assert await _sent_max_tokens("think-entry", thinking=True, user_budget=8192) == 8192


@pytest.mark.asyncio
async def test_unchecked_caption_keeps_the_user_budget():
    assert await _sent_max_tokens("think-entry", thinking=False, user_budget=1024) == 1024


@pytest.mark.asyncio
async def test_downgraded_caption_keeps_the_user_budget():
    """Ordering pin: the gate runs first, so a pressed-back request never earns the floor."""
    assert await _sent_max_tokens("plain-entry", thinking=True, user_budget=1024) == 1024
