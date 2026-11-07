"""Managed Kimi K3.1 contracts through real LangChain/OpenAI HTTP serialization.

Only HTTP transports are replaced; no provider credentials or network are used.
"""

import json
from copy import deepcopy
from types import MappingProxyType, SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel
from deerflow.models.factory import create_chat_model
from deerflow.models.patched_deepseek import PatchedChatDeepSeek
from deerflow.models.reasoning import resolve_reasoning_contract, resolve_reasoning_request

_MODELS = ("kimi-k3.1-pro", "kimi-k3.1-pro-highspeed")
_OMITTED = {"temperature", "top_p", "n", "presence_penalty", "frequency_penalty", "thinking"}
_TOOL = {"type": "function", "function": {"name": "inspect_image", "description": "Inspect the image", "parameters": {"type": "object", "properties": {}}}}
_IMAGE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7AAAAABJRU5ErkJggg=="


def _profile(model_id):
    return ManagedModel(name="kimi-test", provider="moonshot-cn", model=model_id, api_key="offline-test-key").runtime_config()


@pytest_asyncio.fixture
async def wire():
    state = SimpleNamespace(requests=[], tool_turn=False)

    def respond(request):
        body = json.loads(request.content)
        state.requests.append((request, body))
        message = {"role": "assistant", "content": "OK", "reasoning_content": "Checked the image."}
        finish = "stop"
        if state.tool_turn and body["messages"][-1]["role"] != "tool":
            message["content"] = ""
            message["tool_calls"] = [{"id": "call-image", "type": "function", "function": {"name": "inspect_image", "arguments": "{}"}}]
            finish = "tool_calls"
        common = {"id": "chat-moonshot", "created": 1, "model": body["model"]}
        if not body.get("stream"):
            return httpx.Response(200, json={**common, "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": finish}]})
        delta = deepcopy(message)
        for index, call in enumerate(delta.get("tool_calls", [])):
            call["index"] = index
        chunks = [
            {**common, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**common, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
        ]
        content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content.encode())

    with httpx.Client(transport=httpx.MockTransport(respond)) as sync_client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
            state.clients = {"http_client": sync_client, "http_async_client": async_client}
            yield state


def _model(wire, model_id=_MODELS[0], *, endpoint=None, **kwargs):
    profile = _profile(model_id)
    if endpoint is not None:
        profile.api_base = endpoint
    app_config = AppConfig.model_validate({"sandbox": {"use": "test"}, "models": [profile]})
    return create_chat_model(profile.name, app_config=app_config, attach_tracing=False, max_retries=0, **wire.clients, **kwargs)


async def _call(model, mode, messages=None, **kwargs):
    messages = messages or [HumanMessage(content="Hello")]
    if mode == "invoke":
        return model.invoke(messages, **kwargs)
    if mode == "ainvoke":
        return await model.ainvoke(messages, **kwargs)
    result = None
    if mode == "stream":
        for chunk in model.stream(messages, **kwargs):
            result = chunk if result is None else result + chunk
    else:
        async for chunk in model.astream(messages, **kwargs):
            result = chunk if result is None else result + chunk
    assert result is not None
    return result


@pytest.mark.parametrize("model_id", _MODELS)
def test_exact_presets_declare_required_thinking_and_native_effort(model_id):
    profile = _profile(model_id)
    assert profile.use == "deerflow.models.patched_deepseek:PatchedChatDeepSeek"
    assert profile.supports_vision and profile.supports_thinking and profile.supports_reasoning_effort
    contract = resolve_reasoning_contract(profile)
    assert (contract.thinking, contract.dialect, contract.history) == ("required", "none", "preserve")
    assert contract.effort.values == ("low", "high", "max")
    assert contract.effort.default == "max"
    assert dict(contract.effort.aliases) == {}
    resolved = resolve_reasoning_request(contract, thinking_enabled=False, reasoning_effort=None)
    assert resolved.thinking_enabled and resolved.reasoning_effort == "max"
    assert "thinking_forced_on" in resolved.adjustments
    assert profile.when_thinking_disabled is None


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", _MODELS)
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
async def test_all_public_paths_send_native_defaults(wire, model_id, mode):
    model = _model(wire, model_id, thinking_enabled=False)
    assert isinstance(model, PatchedChatDeepSeek)
    assert (await _call(model, mode)).content == "OK"
    assert len(wire.requests) == 1
    request, body = wire.requests[0]
    assert str(request.url) == "https://api.moonshot.cn/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer offline-test-key"
    assert body["model"] == model_id
    assert body["reasoning_effort"] == "max"
    assert _OMITTED.isdisjoint(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", _MODELS)
@pytest.mark.parametrize("effort,expected", [("low", "low"), ("high", "high"), ("max", "max"), ("minimal", "max"), ("medium", "max"), ("xhigh", "max")])
async def test_factory_effort_uses_native_vocabulary_and_contract_fallback(wire, model_id, effort, expected):
    model = _model(wire, model_id, reasoning_effort=effort)
    await _call(model, "ainvoke")
    assert wire.requests[0][1]["reasoning_effort"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "astream"])
@pytest.mark.parametrize("layer", ["factory", "bind", "invoke"])
async def test_fixed_provider_parameters_cannot_be_reintroduced(wire, mode, layer):
    overrides = {
        "temperature": 0.2,
        "top_p": 0.1,
        "n": 1,
        "presence_penalty": 1.0,
        "frequency_penalty": 1.0,
        "extra_body": {
            "temperature": 0.3,
            "top_p": 0.4,
            "n": 3,
            "presence_penalty": 0.9,
            "frequency_penalty": 0.8,
            "thinking": {"type": "disabled"},
            "metadata": {"fixture": "preserved"},
        },
    }
    original = deepcopy(overrides)
    model = _model(wire, model_overrides=overrides if layer == "factory" else None)
    if layer == "bind":
        model = model.bind(**overrides)
    await _call(model, mode, **(overrides if layer == "invoke" else {}))
    body = wire.requests[0][1]
    assert _OMITTED.isdisjoint(body)
    assert body["metadata"] == {"fixture": "preserved"}
    assert overrides == original


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking_type", ["enabled", "disabled", "keep"])
async def test_thinking_is_omitted_for_every_explicit_switch(wire, thinking_type):
    extra = {"thinking": {"type": thinking_type}}
    await _call(_model(wire), "ainvoke", extra_body=extra)
    assert "thinking" not in wire.requests[0][1]
    assert extra == {"thinking": {"type": thinking_type}}


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id,mode", [("kimi-k3.1-pro", "invoke"), ("kimi-k3.1-pro-highspeed", "astream")])
async def test_direct_adapter_constructor_and_model_kwargs_are_finalized(wire, model_id, mode):
    extra = {"temperature": 0.3, "n": 3, "thinking": {"type": "enabled"}, "metadata": {"fixture": "constructor"}}
    model_kwargs = {"thinking": {"type": "disabled"}, "max_completion_tokens": 128}
    original = deepcopy((extra, model_kwargs))
    model = PatchedChatDeepSeek(
        model=model_id,
        api_key="offline-test-key",
        api_base="https://api.moonshot.cn/v1",
        temperature=0.2,
        top_p=0.1,
        n=1,
        presence_penalty=0.9,
        frequency_penalty=0.8,
        extra_body=extra,
        model_kwargs=model_kwargs,
        max_retries=0,
        **wire.clients,
    )
    assert (await _call(model, mode)).content == "OK"
    body = wire.requests[0][1]
    assert _OMITTED.isdisjoint(body)
    assert body["metadata"] == {"fixture": "constructor"}
    assert body["max_completion_tokens"] == 128
    assert (extra, model_kwargs) == original


@pytest.mark.asyncio
async def test_immutable_extra_body_mapping_uses_effective_model_without_mutation(wire):
    values = {"model": "kimi-k3.1-pro-highspeed", "temperature": 0.2, "thinking": {"type": "disabled"}, "metadata": {"fixture": "mapping"}}
    original = deepcopy(values)
    await _call(_model(wire, "kimi-k2.5"), "ainvoke", extra_body=MappingProxyType(values))
    body = wire.requests[0][1]
    assert body["model"] == "kimi-k3.1-pro-highspeed"
    assert _OMITTED.isdisjoint(body)
    assert body["metadata"] == {"fixture": "mapping"}
    assert values == original


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["https://api.moonshot.cn/v1", "https://API.MOONSHOT.CN:443/v1/"])
async def test_official_endpoint_forms_share_finalization(wire, endpoint):
    await _call(_model(wire, endpoint=endpoint), "ainvoke", temperature=0.2)
    assert "temperature" not in wire.requests[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["https://proxy.example/v1", "http://api.moonshot.cn/v1", "https://api.moonshot.cn:8443/v1", "https://api.moonshot.cn/v2"])
async def test_nonofficial_endpoints_are_not_rewritten(wire, endpoint):
    await _call(_model(wire, endpoint=endpoint), "ainvoke", temperature=0.2, extra_body={"thinking": {"type": "disabled"}})
    body = wire.requests[0][1]
    assert body["temperature"] == 0.2
    assert body["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ["kimi-k2.5", "unknown", "kimi-k3.1-pro-preview"])
async def test_other_ids_keep_existing_capabilities_and_wire_settings(wire, model_id):
    profile = _profile(model_id)
    assert profile.reasoning.thinking == ("optional" if model_id == "kimi-k2.5" else "unsupported")
    assert profile.supports_vision == (model_id == "kimi-k2.5")
    await _call(_model(wire, model_id), "ainvoke", temperature=0.2)
    assert wire.requests[0][1]["temperature"] == 0.2


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,effective,normalized", [("kimi-k3.1-pro", "kimi-k2.5", False), ("kimi-k2.5", "kimi-k3.1-pro", True), ("kimi-k3.1-pro", "unknown", False)])
async def test_extra_body_model_override_determines_the_effective_contract(wire, configured, effective, normalized):
    extra = {"model": effective, "temperature": 0.2, "thinking": {"type": "disabled"}, "metadata": {"fixture": "unchanged"}}
    original = deepcopy(extra)
    await _call(_model(wire, configured), "ainvoke", extra_body=extra)
    body = wire.requests[0][1]
    assert body["model"] == effective
    assert body["metadata"] == {"fixture": "unchanged"}
    assert ("temperature" not in body) == normalized
    assert ("thinking" not in body) == normalized
    if normalized:
        assert body.get("reasoning_effort", "max") == "max"
    assert extra == original


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", _MODELS)
async def test_image_tool_followup_replays_real_reasoning(wire, model_id):
    wire.tool_turn = True
    model = _model(wire, model_id, reasoning_effort="low").bind_tools([_TOOL])
    messages = [HumanMessage(content=[{"type": "text", "text": "Inspect this image."}, {"type": "image_url", "image_url": {"url": _IMAGE}}])]
    original = deepcopy(messages)
    first = await _call(model, "astream", messages)
    assert first.additional_kwargs["reasoning_content"] == "Checked the image."
    assert first.tool_calls[0]["name"] == "inspect_image"
    history = [*messages, first, ToolMessage(content="One pixel", tool_call_id=first.tool_calls[0]["id"])]
    assert (await _call(model, "ainvoke", history)).content == "OK"
    assert len(wire.requests) == 2
    for _, body in wire.requests:
        assert body["messages"][0]["content"][1]["image_url"]["url"] == _IMAGE
        assert body["reasoning_effort"] == "low"
        assert _OMITTED.isdisjoint(body)
    assistant = wire.requests[1][1]["messages"][1]
    assert assistant["reasoning_content"] == "Checked the image."
    assert assistant["tool_calls"][0]["id"] == first.tool_calls[0]["id"]
    assert messages == original
