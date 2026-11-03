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


@pytest.mark.parametrize("provider,model_id", [("openai-compatible", "gpt-6.1-sol"), ("openai", "gpt-6-future"), ("openai", "gpt-4.1"), ("qwen-cn", "gpt-6.1-sol")])
def test_unrelated_routes_are_unchanged(provider, model_id):
    kwargs = {"base_url": "https://proxy.example.com/v1"} if provider == "openai-compatible" else {}
    config = ManagedModel(provider=provider, model=model_id, api_key="test-key", **kwargs).runtime_config()
    assert config.use_responses_api is None
    assert config.output_version is None


def test_capability_override_keeps_official_responses_route():
    config = ManagedModel(provider="openai", model="gpt-6.1-sol", api_key="test-key", reasoning={"thinking": "unsupported", "dialect": "none"}).runtime_config()
    assert config.use_responses_api is True
    assert not config.supports_thinking
