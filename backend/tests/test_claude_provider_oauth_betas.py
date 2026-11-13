"""OAuth beta header on Claude requests that send their own ``betas``."""

import json

import httpx
import pytest

from deerflow.models.claude_provider import ClaudeChatModel
from deerflow.models.credential_loader import OAUTH_ANTHROPIC_BETAS

OAUTH_BETAS = OAUTH_ANTHROPIC_BETAS.split(",")
CONTEXT_1M_BETA = "context-1m-2025-08-07"

_MESSAGE = {
    "id": "msg-test",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "ok"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}

_STREAM_EVENTS = [
    {"type": "message_start", "message": {**_MESSAGE, "content": [], "stop_reason": None, "usage": {"input_tokens": 1, "output_tokens": 0}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}},
    {"type": "message_stop"},
]


def _respond(request: httpx.Request) -> httpx.Response:
    if json.loads(request.content).get("stream"):
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in _STREAM_EVENTS)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())
    return httpx.Response(200, json=_MESSAGE)


async def _sent_beta_header(model: ClaudeChatModel, mode: str, **call_kwargs) -> str | None:
    """Send one request through the model's own SDK client and return its ``anthropic-beta`` header."""
    headers: list[str | None] = []

    def respond(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("anthropic-beta"))
        return _respond(request)

    transport = httpx.MockTransport(respond)
    if mode == "invoke":
        model._client = model._client.with_options(http_client=httpx.Client(transport=transport), max_retries=0)
        assert model.invoke("hi", **call_kwargs).content == "ok"
    else:
        model._async_client = model._async_client.with_options(http_client=httpx.AsyncClient(transport=transport), max_retries=0)
        if mode == "ainvoke":
            assert (await model.ainvoke("hi", **call_kwargs)).content == "ok"
        else:
            assert "".join([chunk.text async for chunk in model.astream("hi", **call_kwargs)]) == "ok"
    assert len(headers) == 1
    return headers[0]


def _oauth_model(**kwargs) -> ClaudeChatModel:
    model = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-oat01-fake-token", max_tokens=2048, **kwargs)
    assert model._is_oauth
    return model


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "astream"])
async def test_configured_betas_keep_oauth_betas(mode):
    model = _oauth_model(betas=[CONTEXT_1M_BETA])

    assert await _sent_beta_header(model, mode) == ",".join([*OAUTH_BETAS, CONTEXT_1M_BETA])
    assert model.betas == [CONTEXT_1M_BETA]


@pytest.mark.asyncio
async def test_empty_betas_keep_oauth_betas():
    assert await _sent_beta_header(_oauth_model(betas=[]), "ainvoke") == OAUTH_ANTHROPIC_BETAS


@pytest.mark.asyncio
async def test_configured_oauth_beta_is_not_repeated():
    model = _oauth_model(betas=["interleaved-thinking-2025-05-14", CONTEXT_1M_BETA])

    assert await _sent_beta_header(model, "ainvoke") == ",".join([*OAUTH_BETAS, CONTEXT_1M_BETA])


@pytest.mark.asyncio
async def test_call_time_betas_keep_oauth_betas():
    assert await _sent_beta_header(_oauth_model(), "ainvoke", betas=[CONTEXT_1M_BETA]) == ",".join([*OAUTH_BETAS, CONTEXT_1M_BETA])


@pytest.mark.asyncio
async def test_server_tool_beta_keeps_oauth_betas():
    """langchain-anthropic adds a beta for some server tools without any configured ``betas``."""
    model = _oauth_model().bind_tools([{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1}])

    assert await _sent_beta_header(model.bound, "ainvoke", **model.kwargs) == ",".join([*OAUTH_BETAS, "web-fetch-2025-09-10"])


@pytest.mark.asyncio
async def test_oauth_request_without_betas_uses_default_header():
    assert await _sent_beta_header(_oauth_model(), "ainvoke") == OAUTH_ANTHROPIC_BETAS


@pytest.mark.asyncio
async def test_api_key_betas_are_sent_unchanged():
    model = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-api03-fake-key", max_tokens=2048, betas=[CONTEXT_1M_BETA])
    assert not model._is_oauth

    assert await _sent_beta_header(model, "ainvoke") == CONTEXT_1M_BETA


@pytest.mark.asyncio
async def test_configured_extra_beta_header_keeps_oauth_betas():
    """An ``anthropic-beta`` in ``extra_headers`` replaces both the default header and the ``betas`` header."""
    model_kwargs = {"extra_headers": {"anthropic-beta": CONTEXT_1M_BETA, "x-trace": "1"}}
    model = _oauth_model(model_kwargs=model_kwargs)

    assert await _sent_beta_header(model, "ainvoke") == ",".join([*OAUTH_BETAS, CONTEXT_1M_BETA])
    assert model_kwargs == {"extra_headers": {"anthropic-beta": CONTEXT_1M_BETA, "x-trace": "1"}}


@pytest.mark.asyncio
async def test_call_time_extra_beta_header_keeps_oauth_betas():
    call_kwargs = {"betas": ["files-api-2025-04-14"], "extra_headers": {"anthropic-beta": f"{CONTEXT_1M_BETA}, oauth-2025-04-20"}}

    assert await _sent_beta_header(_oauth_model(), "ainvoke", **call_kwargs) == ",".join([*OAUTH_BETAS, CONTEXT_1M_BETA])


def test_extra_beta_header_name_is_case_insensitive():
    payload = {"extra_headers": {"Anthropic-Beta": CONTEXT_1M_BETA}}

    ClaudeChatModel._apply_oauth_betas(payload)

    assert payload == {"extra_headers": {"Anthropic-Beta": ",".join([*OAUTH_BETAS, CONTEXT_1M_BETA])}}


@pytest.mark.asyncio
async def test_api_key_extra_beta_header_is_sent_unchanged():
    model = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-api03-fake-key", max_tokens=2048, model_kwargs={"extra_headers": {"anthropic-beta": CONTEXT_1M_BETA}})
    assert not model._is_oauth

    assert await _sent_beta_header(model, "ainvoke") == CONTEXT_1M_BETA
