"""The two caption request-body builders (A-4, spec 2026-09-30 D2).

The values used to live in module constants; they now arrive as parameters. The two
negative-control tests below compare against bodies captured on 2026-09-30 (Task 0,
HEAD ``075b3b5b``) *before* the move, canonicalised as sorted-key JSON — key order is
not part of the comparison, content is. The two positive tests pin that the parameters
are what the body carries, in both dialects.
"""

from __future__ import annotations

import json

import httpx
import pytest
from deerflow_knowledge.caption_client import _anthropic_request, _openai_request, request_caption
from deerflow_knowledge.vlm_target import VlmTarget

_PROMPT = "Describe this image."
_IMAGE = (b"\x89PNG\r\n\x1a\nfake-bytes", "image/png")

#: Task 0's capture of the pre-change OpenAI body (values then read from `_MAX_TOKENS` / `_TEMPERATURE`).
_CAPTURED_OPENAI = (
    '{"max_tokens":1024,"messages":[{"content":[{"image_url":{"url":"data:image/png;base64,iVBORw0KGgpmYWtlLWJ5dGVz"},"type":"image_url"},'
    '{"text":"Describe this image.","type":"text"}],"role":"user"}],"model":"probe-model","temperature":0.15}'
)

#: Task 0's capture of the pre-change Messages body.
_CAPTURED_ANTHROPIC = (
    '{"max_tokens":1024,"messages":[{"content":[{"source":{"data":"iVBORw0KGgpmYWtlLWJ5dGVz","media_type":"image/png","type":"base64"},"type":"image"},'
    '{"text":"Describe this image.","type":"text"}],"role":"user"}],"model":"probe-model","temperature":0.15}'
)


def _target(dialect: str) -> VlmTarget:
    return VlmTarget(model="probe-model", base_url="http://127.0.0.1:8899", api_key="sk-probe", dialect=dialect, source="model_entry")


def _canonical(body: dict) -> str:
    return json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def test_openai_body_is_byte_identical_to_the_pre_change_capture():
    body, _ = _openai_request(_target("openai"), _PROMPT, [_IMAGE], max_tokens=1024, temperature=0.15)

    assert _canonical(body) == _CAPTURED_OPENAI


def test_anthropic_body_is_byte_identical_to_the_pre_change_capture():
    body, _ = _anthropic_request(_target("anthropic"), _PROMPT, [_IMAGE], max_tokens=1024, temperature=0.15)

    assert _canonical(body) == _CAPTURED_ANTHROPIC


def test_openai_body_carries_the_given_values():
    body, _ = _openai_request(_target("openai"), _PROMPT, [_IMAGE], max_tokens=2048, temperature=0.7)

    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.7


def test_anthropic_body_carries_the_given_values():
    body, _ = _anthropic_request(_target("anthropic"), _PROMPT, [_IMAGE], max_tokens=2048, temperature=0.7)

    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.7


# ── thinking-off dispatch (D1=甲′) and the empty-answer fallback (D2=甲) ────
#
# Both live at this one outbound door. What carries "thinking off" is the entry's own
# declaration, never a constant: a declared `when_thinking_disabled` shape wins and the two
# spellings are never both sent (the `minimal` 400 is the precedent for stacking parameters),
# an entry that declares effort support gets `reasoning_effort:"none"`, and the Anthropic
# dialect gets nothing at all — thinking is opt-in on Messages. An empty answer borrows the
# reasoning draft before it degrades; failing to borrow keeps today's failure semantics.


def _declared_target(**overrides) -> VlmTarget:
    fields = {"model": "probe-model", "base_url": "http://127.0.0.1:8899", "api_key": "sk-probe", "dialect": "openai", "source": "model_entry"}
    fields.update(overrides)
    return VlmTarget(**fields)


_SHAPE = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def test_an_entry_declaring_effort_support_gets_effort_none():
    body, _ = _openai_request(_declared_target(supports_reasoning_effort=True), _PROMPT, [_IMAGE], max_tokens=1024, temperature=0.15)

    assert body["reasoning_effort"] == "none"


def test_a_declared_disable_shape_wins_and_is_never_doubled_with_effort():
    body, _ = _openai_request(_declared_target(supports_reasoning_effort=True, disable_shape=_SHAPE), _PROMPT, [_IMAGE], max_tokens=1024, temperature=0.15)

    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in body


def test_an_entry_declaring_nothing_gets_no_thinking_parameters():
    """The guard row: `reasoning_effort` to an entry that declares no effort support is the
    sick request the capability gate exists to prevent — undeclared means not sent."""
    body, _ = _openai_request(_target("openai"), _PROMPT, [_IMAGE], max_tokens=1024, temperature=0.15)

    assert "reasoning_effort" not in body
    assert "chat_template_kwargs" not in body
    assert "extra_body" not in body


def test_anthropic_body_gets_no_thinking_parameters_even_when_the_entry_declares_them():
    body, _ = _anthropic_request(_declared_target(dialect="anthropic", supports_reasoning_effort=True, disable_shape={"extra_body": {"thinking": {"type": "disabled"}}}), _PROMPT, [_IMAGE], max_tokens=1024, temperature=0.15)

    assert "reasoning_effort" not in body
    assert "thinking" not in body
    assert "extra_body" not in body


def _reply_transport(payload: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


async def _caption_of(payload: dict, target: VlmTarget) -> str:
    async with httpx.AsyncClient(transport=_reply_transport(payload)) as client:
        return await request_caption(client, target=target, prompt=_PROMPT, images=[_IMAGE], max_tokens=1024, temperature=0.15)


@pytest.mark.asyncio
async def test_an_empty_openai_answer_borrows_the_reasoning_draft():
    caption = await _caption_of({"choices": [{"message": {"content": "", "reasoning_content": "  草稿：界面文字逐字转录  "}}]}, _declared_target())

    assert caption == "草稿：界面文字逐字转录"


@pytest.mark.asyncio
async def test_an_openai_answer_with_neither_text_nor_draft_still_raises():
    with pytest.raises(ValueError):
        await _caption_of({"choices": [{"message": {"content": "", "reasoning_content": ""}}]}, _declared_target())


@pytest.mark.asyncio
async def test_an_empty_anthropic_answer_borrows_the_thinking_block():
    target = _declared_target(dialect="anthropic")
    caption = await _caption_of({"content": [{"type": "thinking", "thinking": "草稿"}]}, target)

    assert caption == "草稿"


@pytest.mark.asyncio
async def test_anthropic_text_still_wins_over_the_thinking_block():
    target = _declared_target(dialect="anthropic")
    caption = await _caption_of({"content": [{"type": "thinking", "thinking": "草稿"}, {"type": "text", "text": "正文"}]}, target)

    assert caption == "正文"
