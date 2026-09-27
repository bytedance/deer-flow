"""DeepSeek managed-model regressions through real LangChain/OpenAI serialization.

Only the HTTP boundary is replaced. The fake provider enforces the documented
thinking/tool-choice restriction; the real SDK builds and parses every request.
No API credentials or network access are needed.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage, ToolMessage

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel, ManagedModelStore, merge_managed_models
from deerflow.models.factory import create_chat_model

_KEY = "diagnostic-only-not-a-real-key"
_ADMIN = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
_TOOL = {"type": "function", "function": {"name": "connection_check", "description": "Check the connection", "parameters": {"type": "object", "properties": {}}}}


def _profile(**overrides):
    return ManagedModel(**{"name": "flash", "model": "deepseek-flash", "base_url": "https://api.deepseek.com", "api_key": _KEY, **overrides})


def _base_config():
    return AppConfig.model_validate({"sandbox": {"use": "test"}, "models": []})


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    return ManagedModelStore()


@pytest.fixture
def provider(monkeypatch):
    """Inspect outbound HTTP and feed split SSE frames into the real SDK."""
    state = SimpleNamespace(requests=[], mode="tool", status=200, exception=None)

    async def send(client, request, **kwargs):
        body = json.loads(request.content)
        state.requests.append((request, body))
        if state.exception is not None:
            raise state.exception
        if state.status != 200:
            return httpx.Response(state.status, request=request, json={"error": {"message": f"Provider failure containing {_KEY}", "type": "invalid_request_error"}})
        if request.headers.get("authorization") != f"Bearer {_KEY}":
            return httpx.Response(401, request=request, json={"error": {"message": "Authentication failed", "type": "authentication_error"}})
        thinking = body.get("thinking", {}).get("type", "enabled") == "enabled"
        if request.url.host == "api.deepseek.com" and thinking and body.get("tool_choice") not in (None, "auto", "none"):
            return httpx.Response(400, request=request, json={"error": {"message": "Thinking mode does not support this tool_choice", "type": "invalid_request_error"}})
        deltas = [{"role": "assistant", "content": ""}]
        if thinking:
            deltas.extend([{"reasoning_content": "Checking "}, {"reasoning_content": "connection."}])
        finish = "stop"
        if body["messages"][-1]["role"] == "tool" or state.mode == "text":
            deltas.append({"content": "OK"})
        elif state.mode != "empty":
            name = "wrong_tool" if state.mode == "wrong_tool" else "connection_check"
            args = '{"unexpected":true}' if state.mode == "wrong_args" else "not-json" if state.mode == "malformed" else "{"
            deltas.append({"tool_calls": [{"index": 0, "id": "call-test", "type": "function", "function": {"name": name, "arguments": args}}]})
            if state.mode != "wrong_args":
                deltas.append({"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]})
            finish = "tool_calls"
        chunks = [{"id": "chat-test", "object": "chat.completion.chunk", "created": 1, "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
        chunks.append({"id": "chat-test", "object": "chat.completion.chunk", "created": 1, "model": body["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"}, content=content.encode())

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url", ["https://api.deepseek.com", "https://api.deepseek.com/v1/", "https://API.DEEPSEEK.COM:443"])
@pytest.mark.parametrize("model_id", ["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"])
async def test_probe_uses_non_thinking_bounded_streaming_tool_request(store, provider, base_url, model_id):
    draft = _profile(base_url=base_url, model=model_id, max_tokens=8192)
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=draft))
    assert result == {"ok": True, "message": "success"}
    assert len(provider.requests) == 1
    request, body = provider.requests[0]
    assert request.url == httpx.URL(base_url.rstrip("/") + "/chat/completions")
    assert body["model"] == model_id
    assert body["stream"] is True
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 32
    assert "max_completion_tokens" not in body
    assert body["tool_choice"] == {"type": "function", "function": {"name": "connection_check"}}
    assert request.extensions["timeout"]["read"] == 15
    assert draft.max_tokens == 8192
    assert "supports_thinking" not in draft.model_dump()
    assert not store.path.exists()
    assert not store.key_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "empty", "wrong_tool", "wrong_args", "malformed"])
async def test_probe_requires_the_expected_tool_and_empty_arguments(store, provider, mode):
    provider.mode = mode
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile()))
    assert result == {"ok": False, "message": "tool_call_missing"}
    assert len(provider.requests) == 1
    assert not store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_probe_does_not_retry_or_expose_provider_errors(store, provider, status):
    provider.status = status
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile()))
    assert result == {"ok": False, "message": "connection_failed"}
    assert _KEY not in json.dumps(result)
    assert len(provider.requests) == 1
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_probe_timeout_and_cancellation_are_distinct(store, provider):
    provider.exception = httpx.ReadTimeout("private provider detail")
    assert await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile())) == {"ok": False, "message": "connection_failed"}
    provider.exception = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile()))
    assert not store.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("key_mode", ["retained", "replacement", "cleared"])
async def test_probe_uses_draft_or_saved_key_without_persisting(store, provider, key_mode):
    saved = store.save(_profile(api_key="old-key" if key_mode == "replacement" else _KEY), expected_revision=None)
    original_catalog = store.path.read_bytes()
    draft = _profile(api_key={"retained": None, "replacement": _KEY, "cleared": ""}[key_mode])
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=draft, expected_revision=saved.revision))
    assert result == ({"ok": False, "message": "connection_failed"} if key_mode == "cleared" else {"ok": True, "message": "success"})
    assert len(provider.requests) == 1
    expected_key = "not-required" if key_mode == "cleared" else _KEY
    assert provider.requests[0][0].headers["authorization"] == f"Bearer {expected_key}"
    assert store.path.read_bytes() == original_catalog
    assert store.list()[0].revision == saved.revision
    assert (draft.api_key.get_secret_value() if draft.api_key is not None else None) == {"retained": None, "replacement": _KEY, "cleared": ""}[key_mode]


@pytest.mark.asyncio
async def test_stale_revision_is_rejected_before_provider_contact(store, provider):
    saved = store.save(_profile(), expected_revision=None)
    store.save(_profile(), expected_revision=saved.revision)
    with pytest.raises(HTTPException) as exc:
        await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile(api_key=None), expected_revision=saved.revision))
    assert exc.value.status_code == 409
    assert not provider.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [SimpleNamespace(user=SimpleNamespace(system_role="user")), SimpleNamespace(user=SimpleNamespace(system_role="admin"), auth_source="pat")])
async def test_probe_authorization_precedes_provider_contact(store, provider, state):
    with pytest.raises(HTTPException) as exc:
        await router.test_model(SimpleNamespace(state=state), router.SaveModelRequest(config=_profile()))
    assert exc.value.status_code == 403
    assert not provider.requests
    assert not store.path.exists()


async def _collect(model, messages):
    result = None
    async for chunk in model.astream(messages, config={"callbacks": []}):
        result = chunk if result is None else result + chunk
    assert result is not None
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [False, True])
async def test_saved_model_streaming_replays_reasoning_and_honors_token_limit(store, provider, thinking):
    saved = store.save(_profile(max_tokens=1536), expected_revision=None)
    original_catalog = store.path.read_bytes()
    base = _base_config()
    config = merge_managed_models(base)
    model_config = config.get_model_config(saved.name)
    model = create_chat_model(saved.name, thinking_enabled=thinking, reasoning_effort="high", app_config=config, attach_tracing=False)
    bound = model.bind_tools([_TOOL])
    history = [HumanMessage(content="Call connection_check, then say OK.")]
    first = await _collect(bound, history)
    assert first.tool_calls[0]["name"] == "connection_check"
    expected_reasoning = "Checking connection." if thinking else None
    assert first.additional_kwargs.get("reasoning_content") == expected_reasoning
    history.extend([first, ToolMessage(content="healthy", tool_call_id=first.tool_calls[0]["id"])])
    final = await _collect(bound, history)
    assert final.content == "OK"
    assert len(provider.requests) == 2
    for request, body in provider.requests:
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert body["thinking"] == {"type": "enabled" if thinking else "disabled"}
        assert body["max_tokens"] == 1536
        assert "max_completion_tokens" not in body
        if thinking:
            assert body["reasoning_effort"] == "high"
    assistant = provider.requests[1][1]["messages"][1]
    assert assistant["content"] == ""
    assert assistant.get("reasoning_content") == expected_reasoning
    assert store.path.read_bytes() == original_catalog
    assert base.models == []
    assert model_config.supports_thinking is True
    assert model_config.supports_reasoning_effort is True


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.deepseek.com.example.org/v1",
        "https://other.api.deepseek.com/v1",
        "https://api.deepseek.com/anthropic",
        "https://api.deepseek.com/proxy/v1",
        "https://api.deepseek.com:8443/v1",
        "https://openrouter.ai/api/v1",
        "http://localhost:8000/v1",
    ],
)
def test_other_endpoints_do_not_gain_deepseek_specific_parameters(store, base_url):
    saved = store.save(_profile(base_url=base_url), expected_revision=None)
    config = merge_managed_models(_base_config())
    model = create_chat_model(saved.name, app_config=config, attach_tracing=False)
    payload = model._get_request_payload([HumanMessage(content="Hello")])
    assert "thinking" not in payload
    assert not payload.get("extra_body")
    assert config.get_model_config(saved.name).supports_thinking is False
    assert str(model.openai_api_base).rstrip("/") == base_url.rstrip("/")


@pytest.mark.asyncio
async def test_generic_openai_probe_keeps_existing_request_contract(store, provider):
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile(base_url="https://example.com/v1")))
    assert result == {"ok": True, "message": "success"}
    body = provider.requests[0][1]
    assert "thinking" not in body
    assert body["max_completion_tokens"] == 32
    assert body["tool_choice"]["function"]["name"] == "connection_check"


@pytest.mark.asyncio
async def test_new_draft_without_key_does_not_use_environment_credentials(store, provider, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", _KEY)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile(api_key=None)))
    assert result == {"ok": False, "message": "connection_failed"}
    assert provider.requests[0][0].headers["authorization"] == "Bearer not-required"
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_stream_failure_after_valid_tool_chunks_is_not_success(store, provider, monkeypatch):
    send = httpx.AsyncClient.send

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield self.content
            raise httpx.ReadError("private upstream stream failure")

        def __init__(self, content):
            self.content = content

    async def interrupted(client, request, **kwargs):
        response = await send(client, request, **kwargs)
        if response.status_code == 200:
            content = response.content.replace(b"data: [DONE]\n\n", b"")
            return httpx.Response(200, request=request, headers=response.headers, stream=InterruptedStream(content))
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", interrupted)
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=_profile()))
    assert result == {"ok": False, "message": "connection_failed"}
    assert len(provider.requests) == 1
    assert not store.path.exists()
