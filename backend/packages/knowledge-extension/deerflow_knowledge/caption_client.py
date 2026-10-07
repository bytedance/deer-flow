"""The one outbound entry point for both caption legs.

These legs are hand-written HTTP rather than LangChain models, so the protocol is ours to
speak — and it follows the entry's provider, not a setting of its own (`VlmTarget.dialect`).
Two dialects today: the OpenAI shape (`POST {base}/chat/completions`, `Authorization`) and
Anthropic's Messages shape (`POST {base}/v1/messages`, `X-Api-Key`, `anthropic-version`).

Both legs call :func:`request_caption` so each shape is written once; the prompts and the
degradation semantics stay with the legs themselves. What carries "thinking off" to the
endpoint is the entry's declaration (spec 2026-10-02 D1=甲′), and an empty answer borrows
the reasoning draft before it degrades (D2=甲).
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Mapping, Sequence
from typing import Literal

import httpx

from deerflow_knowledge.vlm_target import VlmTarget

logger = logging.getLogger(__name__)

#: Sent on every Messages request. The SDK's own default value (`anthropic/_client.py:180`);
#: a module constant on purpose — bumping it is a code change, not a config knob.
ANTHROPIC_VERSION = "2023-06-01"

#: The one cap on concurrent caption requests within a leg run, shared by both legs
#: (spec 2026-10-03 D1=甲). A constant on purpose: the global total already scales with
#: ``worker_concurrency`` (this × the worker count), so the cap must not scale with it too.
_CAPTION_CONCURRENCY = 4

#: The output-budget floor while thinking is on (spec 2026-10-03 D2=甲): thinking tokens
#: draw from the same budget, so 1024 truncates the answer away (the empty-caption
#: post-mortem). A floor, not a value — a higher user budget is never cut.
_THINKING_MAX_TOKENS_FLOOR = 4096

Dialect = Literal["openai", "anthropic"]


def _url(target: VlmTarget) -> str:
    base = target.base_url.rstrip("/")
    return f"{base}/v1/messages" if target.dialect == "anthropic" else f"{base}/chat/completions"


def _data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _merge_shape(body: dict, shape: Mapping) -> None:
    """Deep-merge a declared shape into the body, unwrapping ``extra_body`` on the way.

    Shapes are written the way LangChain consumes them (``extra_body`` = "spread into the
    request body"); this leg speaks raw HTTP, so the wire body is the shape one level up.
    """
    for key, value in shape.items():
        if key == "extra_body" and isinstance(value, Mapping):
            _merge_shape(body, value)
        elif isinstance(value, Mapping) and isinstance(body.get(key), dict):
            _merge_shape(body[key], value)
        else:
            body[key] = value


def _apply_thinking_off(target: VlmTarget, body: dict) -> None:
    """Carry "thinking off" in the spelling this entry declares (spec 2026-10-02 D1=甲′).

    A declared ``when_thinking_disabled`` shape wins, and the two spellings are never both
    sent — stacking disable parameters is how the ``minimal`` request earned its 400. No
    shape and no declared effort support means nothing is added: an undeclared parameter is
    the sick request the capability gate exists to prevent.
    """
    if target.disable_shape:
        _merge_shape(body, target.disable_shape)
    elif target.supports_reasoning_effort:
        body["reasoning_effort"] = "none"


def _apply_thinking_on(target: VlmTarget, body: dict) -> None:
    """The symmetric half (spec 2026-10-03): "thinking on" in the declared spelling.

    Only a declared ``when_thinking_enabled`` shape is sent — undeclared means not sent, the
    same guard as the off half.
    """
    if target.enable_shape:
        _merge_shape(body, target.enable_shape)


def _openai_request(target: VlmTarget, prompt: str, images: Sequence[tuple[bytes, str]], *, max_tokens: int, temperature: float, thinking: bool = False) -> tuple[dict, dict]:
    content = [{"type": "image_url", "image_url": {"url": _data_url(data, media_type)}} for data, media_type in images]
    content.append({"type": "text", "text": prompt})
    body = {"model": target.model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": temperature}
    if thinking:
        _apply_thinking_on(target, body)
    else:
        _apply_thinking_off(target, body)
    headers = {"Authorization": f"Bearer {target.api_key or ''}", "Content-Type": "application/json"}
    return body, headers


def _anthropic_request(target: VlmTarget, prompt: str, images: Sequence[tuple[bytes, str]], *, max_tokens: int, temperature: float, thinking: bool = False) -> tuple[dict, dict]:
    content = [{"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode("ascii")}} for data, media_type in images]
    content.append({"type": "text", "text": prompt})
    # `max_tokens` is required by the Messages API; the value is the OpenAI leg's own.
    body = {"model": target.model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}], "temperature": temperature}
    if thinking:
        _apply_thinking_on(target, body)  # "off" stays absent: Messages thinking is opt-in (D1=甲′)
    headers = {"X-Api-Key": target.api_key or "", "anthropic-version": ANTHROPIC_VERSION, "Content-Type": "application/json"}
    return body, headers


def _openai_caption(payload: dict) -> str:
    message = (payload.get("choices") or [{}])[0].get("message") or {}
    # An empty answer borrows the reasoning draft (D2=甲): for a thinking model that draft
    # is often the whole transcription, and the alternative is a filename placeholder.
    return (message.get("content") or "").strip() or (message.get("reasoning_content") or "").strip()


def _anthropic_caption(payload: dict) -> str:
    """Concatenate every text block; a reply may interleave other kinds (e.g. thinking).

    Empty text borrows the thinking blocks' drafts (D2=甲) before giving up.
    """
    blocks = payload.get("content") or []
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()
    return text or "".join(block.get("thinking", "") for block in blocks if block.get("type") == "thinking").strip()


async def request_caption(
    client: httpx.AsyncClient,
    *,
    target: VlmTarget,
    prompt: str,
    images: Sequence[tuple[bytes, str]],
    max_tokens: int,
    temperature: float,
    thinking: bool = False,
) -> str:
    """Ask ``target`` to caption ``images`` and return the text, or raise.

    The three ways this can fail are the caller's to interpret: a non-2xx (``raise_for_status``),
    an empty answer (no text and no reasoning draft left to borrow), and any transport error.
    Both legs degrade on all three. The generation parameters come from the caller
    (``rag.caption_*``), so this module stays transport-only.

    ``thinking`` mirrors chat's entry gate (spec 2026-10-03): an entry that declares no
    thinking support is pressed back to "off" with the chat-side warning, never sent "on".
    While thinking is on, the effective ``max_tokens`` gets a 4096 floor (D2=甲) — a higher
    user budget is never cut.
    """
    if thinking and not target.supports_thinking:
        logger.warning("Thinking mode is enabled but model '%s' does not support it; fallback to non-thinking mode.", target.model)
        thinking = False
    if thinking:
        max_tokens = max(max_tokens, _THINKING_MAX_TOKENS_FLOOR)
    anthropic = target.dialect == "anthropic"
    if anthropic:
        body, headers = _anthropic_request(target, prompt, images, max_tokens=max_tokens, temperature=temperature, thinking=thinking)
    else:
        body, headers = _openai_request(target, prompt, images, max_tokens=max_tokens, temperature=temperature, thinking=thinking)

    response = await client.post(_url(target), headers=headers, json=body)
    response.raise_for_status()
    caption = _anthropic_caption(response.json()) if anthropic else _openai_caption(response.json())
    if not caption:
        raise ValueError("VLM returned an empty caption")
    return caption
