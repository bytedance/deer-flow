"""Official GPT-6 presets must use the real SDK's Responses tool path."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel, ManagedModelStore, merge_managed_models
from deerflow.models.factory import create_chat_model

MODELS = ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-sol", "gpt-6-luna")
REQUIRED = {"gpt-6-astra", "gpt-6.1-sol"}
ADMIN = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
TOOL = {"type": "function", "function": {"name": "connection_check", "description": "Check connectivity", "parameters": {"type": "object", "properties": {}}}}


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    requests = []

    async def send(client, request, **kwargs):
        body = json.loads(request.content)
        requests.append((request, body))
        if request.url.path != "/v1/responses":
            return httpx.Response(400, request=request, json={"error": {"type": "invalid_request_error", "message": "Tools require Responses"}})
        final = any(item.get("type") == "function_call_output" for item in body["input"])
        item = (
            {"type": "message", "id": "msg-test", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "Connected.", "annotations": []}]}
            if final
            else {"type": "function_call", "id": "fc-test", "call_id": "call-test", "name": "connection_check", "arguments": "{}", "status": "completed"}
        )
        response = {
            "id": "resp-test",
            "object": "response",
            "created_at": 1,
            "model": body["model"],
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "output": [item],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
        }
        events = [
            {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0, "item": item if final else {**item, "arguments": ""}},
        ]
        events.append(
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "item_id": item["id"], "delta": "Connected."}
            if final
            else {"type": "response.function_call_arguments.delta", "output_index": 0, "item_id": item["id"], "delta": "{}"}
        )
        events.extend([{"type": "response.output_item.done", "output_index": 0, "item": item}, {"type": "response.completed", "response": response}])
        content = "".join(f"data: {json.dumps({**event, 'sequence_number': i})}\n\n" for i, event in enumerate(events))
        return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"}, content=content)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return requests


async def collect(model, messages):
    result = None
    async for chunk in model.astream(messages):
        result = chunk if result is None else result + chunk
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", MODELS)
async def test_web_probe_and_saved_chat_use_responses_with_tool_followup(wire, model_id):
    profile = ManagedModel(provider="openai", model=model_id, api_key="test-key")
    store = ManagedModelStore()
    assert await router.test_model(ADMIN, router.SaveModelRequest(config=profile)) == {"ok": True, "message": "success"}
    assert not store.path.exists()
    saved = store.save(profile, expected_revision=None)
    config = merge_managed_models(AppConfig.model_validate({"sandbox": {"use": "test"}}))
    model = create_chat_model(saved.name, app_config=config, attach_tracing=False)
    messages = [HumanMessage(content="Call connection_check.")]
    reply = await collect(model.bind_tools([TOOL], tool_choice="connection_check"), messages)
    assert reply.tool_calls[0]["name"] == "connection_check"
    final = await collect(model, [*messages, reply, ToolMessage(content="ok", tool_call_id=reply.tool_calls[0]["id"])])
    assert final.text == "Connected."
    assert len(wire) == 3
    for request, body in wire:
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-key"
        assert body["model"] == model_id
        assert body["reasoning"]["effort"] == ("medium" if model_id in REQUIRED else "none")
        assert "temperature" not in body
    assert wire[0][1]["max_output_tokens"] == (2048 if model_id in REQUIRED else 32)
    assert wire[0][1]["tool_choice"] == ("auto" if model_id in REQUIRED else {"type": "function", "name": "connection_check"})


@pytest.mark.parametrize("model_id", MODELS)
@pytest.mark.parametrize("effort,expected", [(None, "medium"), ("minimal", "low"), ("max", "max")])
def test_official_gpt6_reasoning_parameters(model_id, effort, expected):
    profile = ManagedModel(provider="openai", model=model_id, api_key="test-key")
    config = AppConfig.model_validate({"models": [profile.runtime_config()], "sandbox": {"use": "test"}})
    client = create_chat_model("connection-check", app_config=config, thinking_enabled=True, reasoning_effort=effort, attach_tracing=False)
    assert client.reasoning_effort == expected
    assert client.use_responses_api is True


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", ("gpt-6.1-terra", "gpt-6-sol", "gpt-6-luna"))
@pytest.mark.parametrize("effort", ["minimal", "low", "high"])
async def test_flash_mode_disables_reasoning_even_with_explicit_effort(wire, model_id, effort):
    profile = ManagedModel(provider="openai", model=model_id, api_key="test-key")
    config = AppConfig.model_validate({"models": [profile.runtime_config()], "sandbox": {"use": "test"}})
    model = create_chat_model("connection-check", app_config=config, thinking_enabled=False, reasoning_effort=effort, attach_tracing=False)

    await collect(model.bind_tools([TOOL]), [HumanMessage(content="Call connection_check.")])

    assert wire[0][1]["reasoning"]["effort"] == "none"


@pytest.mark.parametrize("provider,model_id", [("openai-compatible", "gpt-6.1-sol"), ("openai", "gpt-6-future"), ("openai", "gpt-4.1"), ("qwen-cn", "gpt-6.1-sol")])
def test_unrelated_routes_are_unchanged(provider, model_id):
    kwargs = {"base_url": "https://proxy.example.com/v1"} if provider == "openai-compatible" else {}
    config = ManagedModel(provider=provider, model=model_id, api_key="test-key", **kwargs).runtime_config()
    assert config.use_responses_api is None
    assert config.output_version is None


@pytest.mark.parametrize("model_id", MODELS)
def test_capability_override_keeps_official_responses_route(model_id):
    config = ManagedModel(provider="openai", model=model_id, api_key="test-key", reasoning={"thinking": "unsupported", "dialect": "none"}).runtime_config()
    assert config.use_responses_api is True
    assert not config.supports_thinking


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", MODELS)
@pytest.mark.parametrize(
    "reasoning",
    [
        {"thinking": "unsupported", "dialect": "none"},
        {"thinking": "optional", "dialect": "none"},
        {"thinking": "required", "dialect": "none"},
        {"thinking": "optional", "dialect": "none", "effort": {"values": ["high"], "default": "high"}},
        {"thinking": "optional", "dialect": "none", "effort": {"values": ["high"], "path": "extra_body.reasoning_effort"}},
    ],
)
async def test_explicit_contract_can_be_probed_saved_and_reloaded(wire, model_id, reasoning):
    profile = ManagedModel(provider="openai", model=model_id, api_key="test-key", reasoning=reasoning)
    assert await router.test_model(ADMIN, router.SaveModelRequest(config=profile)) == {"ok": True, "message": "success"}
    saved = ManagedModelStore().save(profile, expected_revision=None)
    loaded = merge_managed_models(AppConfig.model_validate({"sandbox": {"use": "test"}}))
    runtime = next(model for model in loaded.models if model.name == saved.name)
    expected = profile.reasoning.model_copy(deep=True)
    if expected.effort is not None:
        expected.effort.path = "reasoning_effort"
    assert runtime.reasoning == expected
    assert runtime.use_responses_api is True
    assert runtime.output_version == "responses/v1"
    if reasoning.get("effort", {}).get("default") == "high":
        assert wire[0][1]["reasoning"]["effort"] == "high"
    else:
        assert "reasoning" not in wire[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", MODELS)
@pytest.mark.parametrize("effort", ["none", "high"])
@pytest.mark.parametrize("path", ["extra_body.reasoning_effort", "output_config.effort", "effort"])
async def test_saved_legacy_effort_path_uses_responses_wire_format(wire, model_id, effort, path):
    profile = ManagedModel(
        provider="openai",
        model=model_id,
        api_key="test-key",
        reasoning={"thinking": "optional", "dialect": "none", "effort": {"values": ["none", "high"], "default": effort, "path": path}},
    )
    assert await router.test_model(ADMIN, router.SaveModelRequest(config=profile)) == {"ok": True, "message": "success"}
    saved = ManagedModelStore().save(profile, expected_revision=None)
    config = merge_managed_models(AppConfig.model_validate({"sandbox": {"use": "test"}}))
    model = create_chat_model(saved.name, app_config=config, attach_tracing=False)
    await collect(model.bind_tools([TOOL]), [HumanMessage(content="Call connection_check.")])
    for request, body in wire:
        assert request.url.path == "/v1/responses"
        assert body["reasoning"]["effort"] == effort
        assert "reasoning_effort" not in body
    # Runtime translation must not migrate the encrypted record or input object.
    assert ManagedModelStore().list()[0].reasoning == profile.reasoning
    assert profile.reasoning.effort.path == path


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", MODELS)
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("source", ["agent", "kwargs"])
async def test_sampling_follows_effective_reasoning_effort(wire, model_id, enabled, source):
    profile = ManagedModel(provider="openai", model=model_id, api_key="test-key")
    config = AppConfig.model_validate({"models": [profile.runtime_config()], "sandbox": {"use": "test"}})
    sampling = {"temperature": 0.4, "top_p": 0.8, "top_logprobs": 2}
    options = {"model_overrides": sampling} if source == "agent" else sampling
    model = create_chat_model("connection-check", app_config=config, thinking_enabled=enabled, reasoning_effort="high", attach_tracing=False, **options)
    await collect(model.bind_tools([TOOL]), [HumanMessage(content="Call connection_check.")])
    body = wire[0][1]
    expected_effort = "high" if enabled or model_id in REQUIRED else "none"
    assert body["reasoning"]["effort"] == expected_effort
    for key, value in sampling.items():
        if expected_effort == "none":
            assert body[key] == value
        else:
            assert key not in body
    assert sampling == {"temperature": 0.4, "top_p": 0.8, "top_logprobs": 2}
