"""Provider registration tests use real configuration and encrypted persistence."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import SecretStr, ValidationError

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config, set_app_config
from deerflow.config.managed_model_providers import PROVIDERS
from deerflow.config.managed_models import ManagedModel, ManagedModelInputError, ManagedModelStore, merge_managed_models
from deerflow.models.factory import create_chat_model


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return ManagedModelStore()


@pytest.mark.parametrize(
    "provider,endpoint,adapter",
    [
        ("openai", "https://api.openai.com/v1", "langchain_openai:ChatOpenAI"),
        ("anthropic", "https://api.anthropic.com", "langchain_anthropic:ChatAnthropic"),
        ("deepseek", "https://api.deepseek.com", "deerflow.models.patched_deepseek:PatchedChatDeepSeek"),
        ("qwen-cn", "https://dashscope.aliyuncs.com/compatible-mode/v1", "deerflow.models.patched_deepseek:PatchedChatDeepSeek"),
        ("doubao", "https://ark.cn-beijing.volces.com/api/v3", "deerflow.models.patched_deepseek:PatchedChatDeepSeek"),
        ("moonshot-cn", "https://api.moonshot.cn/v1", "deerflow.models.patched_deepseek:PatchedChatDeepSeek"),
        ("zai", "https://api.z.ai/api/paas/v4", "deerflow.models.patched_deepseek:PatchedChatDeepSeek"),
        ("minimax", "https://api.minimax.io/v1", "deerflow.models.patched_minimax:PatchedChatMiniMax"),
    ],
)
def test_preset_routing_and_conservative_unknown_capabilities(provider, endpoint, adapter):
    profile = ManagedModel(provider=provider, model="unknown/model 名称", api_key="test-key")
    config = profile.runtime_config()
    assert config.use == adapter
    assert (config.model_extra.get("base_url") or config.model_extra.get("api_base")) == endpoint
    assert not config.supports_thinking
    assert not config.supports_reasoning_effort
    assert not config.supports_vision
    assert config.context_window is None


def test_automatic_names_are_valid_unique_and_stable(store):
    for model in ["a/b c 中文", "中" * 200, "same", "same"]:
        saved = store.save(ManagedModel(provider="openai", model=model, api_key="test"), expected_revision=None)
        assert 0 < len(saved.name) <= 100
        assert saved.name.isascii()
        updated = store.save(saved.model_copy(update={"model": "changed", "api_key": None}), expected_revision=saved.revision)
        assert updated.name == saved.name
    assert len({m.name for m in store.list()}) == 4


_ADMIN = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
_TOOL = {"type": "function", "function": {"name": "connection_check", "description": "Check the connection", "parameters": {"type": "object", "properties": {}}}}


@pytest.mark.parametrize("field,value", [("base_url", "https://evil.invalid/v1"), ("base_url", None), ("use", "evil:Code"), ("protocol", "other"), ("api_base", "https://evil.invalid")])
def test_preset_drafts_reject_route_overrides(field, value):
    with pytest.raises(ValidationError):
        router.SaveModelRequest.model_validate({"config": {"provider": "openai", "model": "any", "api_key": "private-test-key", field: value}})


@pytest.mark.parametrize("provider", ["unknown", "OPENAI", "", "openai/../../"])
def test_unknown_provider_rejected(provider):
    with pytest.raises(ValidationError):
        ManagedModel(provider=provider, model="any", api_key="test")


def test_key_requirements_and_switching_do_not_reuse_credentials(store):
    original = store.save(ManagedModel(provider="openai", model="any", api_key="old"), expected_revision=None)
    before = store.path.read_bytes()
    with pytest.raises(ManagedModelInputError, match="API key"):
        store.save(original.model_copy(update={"provider": "anthropic", "api_key": None}), expected_revision=original.revision)
    assert store.path.read_bytes() == before
    updated = store.save(original.model_copy(update={"provider": "anthropic", "api_key": SecretStr("new")}), expected_revision=original.revision)
    assert updated.name == original.name
    assert updated.api_key.get_secret_value() == "new"
    with pytest.raises(ManagedModelInputError):
        store.save(updated.model_copy(update={"api_key": SecretStr("")}), expected_revision=updated.revision)
    cleared = store.save(updated.model_copy(update={"api_key": SecretStr(""), "enabled": False}), expected_revision=updated.revision)
    assert not cleared.public()["has_api_key"]
    assert merge_managed_models(AppConfig.model_validate({"sandbox": {"use": "test"}})).models == []


def test_old_catalog_is_compatible_without_rewriting_and_preserves_snapshot(store):
    from cryptography.fernet import Fernet

    store.path.parent.mkdir(parents=True)
    key = Fernet.generate_key()
    store.key_path.write_bytes(key)
    old = {
        "name": "old-proxy",
        "provider": "openai-compatible",
        "model": "deepseek-v4-pro",
        "display_name": "Old",
        "base_url": "https://proxy.example.com/v1",
        "api_key": "secret-old",
        "enabled": True,
        "supports_vision": False,
        "context_window": 32768,
        "max_tokens": 100,
        "revision": "legacy",
    }
    encrypted = Fernet(key).encrypt(json.dumps([old]).encode())
    store.path.write_bytes(encrypted)
    base = AppConfig.model_validate({"sandbox": {"use": "test"}})
    snapshot = merge_managed_models(base)
    assert snapshot.models[0].use == "langchain_openai:ChatOpenAI"
    assert snapshot.models[0].api_key == "secret-old"
    assert store.path.read_bytes() == encrypted
    saved = store.save(store.list()[0].model_copy(update={"model": "new", "api_key": None}), expected_revision="legacy")
    assert saved.name == "old-proxy"
    assert saved.api_key.get_secret_value() == "secret-old"
    assert snapshot.models[0].model == "deepseek-v4-pro"
    assert merge_managed_models(base).models[0].model == "new"


def test_auto_names_are_allocated_inside_cross_writer_lock(store):
    def save(_):
        return store.save(ManagedModel(provider="openai", model="重复/name", api_key="test"), expected_revision=None).name

    with ThreadPoolExecutor(max_workers=4) as workers:
        names = list(workers.map(save, range(12)))
    assert len(set(names)) == len(store.list()) == 12


def test_preset_overrides_and_injected_config_remain_authoritative(store):
    saved = store.save(ManagedModel(provider="openai", model="unknown", api_key="test", supports_vision=True, context_window=12345, max_tokens=123), expected_revision=None)
    base = AppConfig.model_validate({"sandbox": {"use": "test"}})
    merged = merge_managed_models(base)
    assert merged.models[0].context_window == 12345
    assert merged.models[0].supports_vision is True
    set_app_config(base)
    try:
        assert get_app_config() is base
        assert get_app_config().models == []
    finally:
        reset_app_config()
    assert store.list()[0].name == saved.name


@pytest.mark.asyncio
async def test_provider_metadata_requires_admin():
    catalog = await router.list_model_providers(_ADMIN)
    assert {p["id"] for p in catalog["providers"]} == {p.id for p in PROVIDERS}
    assert all(set(p) == {"id", "display_name", "requires_api_key", "custom_endpoint"} for p in catalog["providers"])
    with pytest.raises(HTTPException) as exc:
        await router.list_model_providers(SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user"))))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_http_validation_never_echoes_draft_keys():
    app = FastAPI()
    app.include_router(router.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for config in [
            {"provider": "openai", "model": "x", "base_url": "https://evil.invalid"},
            {"provider": "unknown", "model": "x"},
            {"provider": "openai", "model": "x", "api_key": "**********"},
            {"provider": "openai", "model": "x", "use": "evil"},
        ]:
            config.setdefault("api_key", "private-test-key")
            response = await client.put("/api/managed-models", json={"config": config})
            assert response.status_code == 422
            assert "private-test-key" not in response.text
            assert "**********" not in response.text
            assert "evil" not in response.text


@pytest.fixture
def wire(monkeypatch):
    """Only replace HTTP transport; run the real adapters and vendor SDKs."""
    state = SimpleNamespace(requests=[], status=200, mode="tool")

    async def send(client, request, **kwargs):
        body = json.loads(request.content)
        state.requests.append((request, body))
        if state.status != 200:
            return httpx.Response(state.status, request=request, json={"error": {"type": "authentication_error", "message": "secret-test-key private provider body"}})
        if request.url.host == "api.anthropic.com":
            events = [
                (
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {"id": "msg-test", "type": "message", "role": "assistant", "content": [], "model": body["model"], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}},
                    },
                ),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "call-test", "name": "connection_check", "input": {}}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            content = "".join(f"event: {event}\ndata: {json.dumps(data)}\n\n" for event, data in events)
        else:
            delta = {"role": "assistant", "content": ""}
            if state.mode == "tool":
                delta["tool_calls"] = [{"index": 0, "id": "call-test", "type": "function", "function": {"name": "connection_check", "arguments": "{}"}}]
            else:
                delta["content"] = "x" * (20000 if state.mode == "huge" else 2)
            chunk = {"id": "chat-test", "object": "chat.completion.chunk", "created": 1, "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": "tool_calls" if state.mode == "tool" else "stop"}]}
            content = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"}, content=content.encode())

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [p.id for p in PROVIDERS if p.endpoint])
async def test_probe_and_chat_share_real_sdk_protocol_and_auth(store, wire, provider):
    profile = ManagedModel(provider=provider, model="unlisted-model", api_key="secret-test-key")
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=profile))
    assert result == {"ok": True, "message": "success"}
    assert not store.path.exists()
    saved = store.save(profile, expected_revision=None)
    app_config = merge_managed_models(AppConfig.model_validate({"sandbox": {"use": "test"}}))
    model = create_chat_model(saved.name, app_config=app_config, attach_tracing=False, model_overrides={"max_tokens": 64})
    response = None
    async for chunk in model.bind_tools([_TOOL], tool_choice="connection_check").astream([HumanMessage(content="Call connection_check.")]):
        response = chunk if response is None else response + chunk
    assert response.tool_calls[0]["name"] == "connection_check"
    assert len(wire.requests) == 2
    probe_request, probe_body = wire.requests[0]
    chat_request, chat_body = wire.requests[1]
    assert probe_request.url == chat_request.url
    assert probe_request.extensions["timeout"]["read"] == 15
    assert "thinking" not in probe_body
    assert "reasoning_effort" not in probe_body
    if provider == "anthropic":
        assert str(probe_request.url) == "https://api.anthropic.com/v1/messages"
        assert probe_request.headers["x-api-key"] == "secret-test-key"
        assert "authorization" not in probe_request.headers
        assert probe_body["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
        assert probe_body["tool_choice"] == {"type": "tool", "name": "connection_check"}
        assert probe_body["max_tokens"] == 32
        assert chat_body["max_tokens"] == 64
        assert "stream_options" not in probe_body
    else:
        assert str(probe_request.url).endswith("/chat/completions")
        assert probe_request.headers["authorization"] == "Bearer secret-test-key"
        if provider == "openai":
            assert probe_body["tool_choice"]["function"]["name"] == "connection_check"
        else:
            assert probe_body["tool_choice"] == "auto"
        token_field = "max_completion_tokens" if provider == "openai" else "max_tokens"
        assert probe_body[token_field] == 32
        assert chat_body[token_field] == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model", [("deepseek", "deepseek-v4-flash"), ("anthropic", "claude-sonnet-4-5-20250929"), ("minimax", "MiniMax-M3"), ("moonshot-cn", "kimi-k2.5")])
async def test_known_optional_thinking_disabled_only_for_probe(store, wire, provider, model):
    profile = ManagedModel(provider=provider, model=model, api_key="secret-test-key")
    config = profile.runtime_config()
    assert config.supports_thinking
    assert await router.test_model(_ADMIN, router.SaveModelRequest(config=profile)) == {"ok": True, "message": "success"}
    assert wire.requests[0][1]["thinking"] == {"type": "disabled"}
    assert config.when_thinking_enabled
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_required_thinking_uses_auto_selection_and_bounded_budget(store, wire):
    profile = ManagedModel(provider="minimax", model="MiniMax-M2.7", api_key="secret-test-key")
    assert await router.test_model(_ADMIN, router.SaveModelRequest(config=profile)) == {"ok": True, "message": "success"}
    body = wire.requests[0][1]
    assert body["tool_choice"] == "auto"
    assert "thinking" not in body
    assert body["max_tokens"] == 2048


@pytest.mark.asyncio
@pytest.mark.parametrize("status,message", [(401, "authentication_failed"), (403, "authentication_failed"), (500, "connection_failed")])
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_native_and_compatible_errors_are_redacted_and_not_retried(store, wire, provider, status, message):
    wire.status = status
    assert await router.test_model(_ADMIN, router.SaveModelRequest(config=ManagedModel(provider=provider, model="x", api_key="secret-test-key"))) == {"ok": False, "message": message}
    assert len(wire.requests) == 1
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_missing_preset_key_never_contacts_provider(store, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Missing credentials must not make a network request")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    result = await router.test_model(_ADMIN, router.SaveModelRequest(config=ManagedModel(provider="openai", model="x")))
    assert result == {"ok": False, "message": "missing_api_key"}
    assert not store.path.exists()


@pytest.mark.asyncio
async def test_revision_credential_retention_and_provider_switch(store, wire):
    saved = store.save(ManagedModel(provider="openai", model="x", api_key="secret-test-key"), expected_revision=None)
    body = router.SaveModelRequest(config=saved.model_copy(update={"api_key": None}), expected_revision=saved.revision)
    assert await router.test_model(_ADMIN, body) == {"ok": True, "message": "success"}
    switched = body.model_copy(update={"config": body.config.model_copy(update={"provider": "anthropic"})})
    assert await router.test_model(_ADMIN, switched) == {"ok": False, "message": "missing_api_key"}
    stale = body.model_copy(update={"expected_revision": "stale"})
    with pytest.raises(HTTPException) as exc:
        await router.test_model(_ADMIN, stale)
    assert exc.value.status_code == 409
    assert len(wire.requests) == 1
    assert store.list()[0].revision == saved.revision


@pytest.mark.asyncio
async def test_probe_limits_response_size(store, wire):
    wire.mode = "huge"
    assert await router.test_model(_ADMIN, router.SaveModelRequest(config=ManagedModel(provider="openai", model="x", api_key="secret-test-key"))) == {"ok": False, "message": "response_limit"}


def test_generated_name_collision_with_yaml_is_retried(store, monkeypatch):
    from deerflow.config import managed_models

    tokens = iter(["a" * 32, "b" * 32, "c" * 32])
    monkeypatch.setattr(managed_models, "uuid4", lambda: SimpleNamespace(hex=next(tokens)))
    saved = store.save(ManagedModel(provider="openai", model="x", api_key="test"), expected_revision=None, reserved_names={"openai-x-" + "a" * 12})
    assert saved.name == "openai-x-" + "b" * 12
    assert saved.revision == "c" * 32


@pytest.mark.asyncio
async def test_preset_api_save_refresh_yaml_conflict_and_disable(store, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from app.gateway.routers import models as models_router

    path = tmp_path / "config.yaml"
    original = "sandbox:\n  use: test\nmodels:\n  - name: operator\n    model: yaml-model\n    use: langchain_openai:ChatOpenAI\n    api_key: $MANAGED_TEST_YAML_KEY\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("MANAGED_TEST_YAML_KEY", "yaml-test-key")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(path))
    monkeypatch.delenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", raising=False)
    reset_app_config()
    app = FastAPI()
    app.include_router(router.router)
    app.include_router(models_router.router)
    app.middleware("http")(_admin_request)

    async def current_config():
        return await asyncio.to_thread(get_app_config)

    app.dependency_overrides[models_router.get_config] = current_config
    monkeypatch.setattr(models_router, "get_optional_user_from_request", AsyncMock(return_value=None))
    snapshot = get_app_config()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            create = await client.put("/api/managed-models", json={"config": {"provider": "openai", "model": "org/新 模型", "api_key": "private-test-key"}})
            assert create.status_code == 200
            saved = create.json()
            assert saved["enabled"] and saved["has_api_key"]
            assert "private-test-key" not in create.text
            listing = await client.get("/api/models")
            assert [item["name"] for item in listing.json()["models"]] == ["operator", saved["name"]]
            assert "private-test-key" not in listing.text and "yaml-test-key" not in listing.text
            next_snapshot = get_app_config()
            assert snapshot.models[0].api_key == "yaml-test-key"
            assert len(snapshot.models) == 1
            assert len(next_snapshot.models) == 2
            edit = {"config": {"name": saved["name"], "provider": "openai", "model": "new-model"}, "expected_revision": saved["revision"]}
            changed = await client.put("/api/managed-models", json=edit)
            assert changed.status_code == 200
            assert changed.json()["name"] == saved["name"]
            assert get_app_config().models[1].model == "new-model"
            assert next_snapshot.models[1].model == "org/新 模型"
            assert (await client.put("/api/managed-models", json=edit)).status_code == 409
            edit["expected_revision"] = changed.json()["revision"]
            edit["config"]["enabled"] = False
            assert (await client.put("/api/managed-models", json=edit)).status_code == 200
            assert len((await client.get("/api/models")).json()["models"]) == 1
            conflict = await client.put("/api/managed-models", json={"config": {"name": "operator", "provider": "openai", "model": "x", "api_key": "test"}})
            assert conflict.status_code == 409
        assert path.read_text(encoding="utf-8") == original
    finally:
        reset_app_config()


async def _admin_request(request, call_next):
    request.state.user = _ADMIN.state.user
    return await call_next(request)


@pytest.mark.parametrize("path", ["api_key", "base_url", "api_base", "use", "default_headers.Authorization", "model"])
def test_reasoning_cannot_override_preset_routing_or_credentials(path):
    with pytest.raises(ValidationError):
        ManagedModel(provider="openai", model="x", api_key="secret-test-key", reasoning={"thinking": "required", "effort": {"values": ["high"], "default": "high", "path": path}})


def test_reasoning_contract_override_is_preserved_and_validated(store):
    profile = ManagedModel(provider="deepseek", model="deepseek-v4-pro", api_key="test", reasoning={"thinking": "unsupported", "dialect": "none"}, supports_vision=False)
    saved = store.save(profile, expected_revision=None)
    runtime = saved.runtime_config()
    assert not runtime.supports_thinking
    assert not runtime.supports_reasoning_effort
    assert not runtime.supports_vision
    assert runtime.when_thinking_enabled is None
    assert runtime.when_thinking_disabled == {"extra_body": {"thinking": {"type": "disabled"}}}
    assert store.list()[0].reasoning.thinking == "unsupported"
