"""Offline regression for operator-configured image providers."""

import re
from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig


def _config(**image_generation):
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "test", "environment": {}},
            "image_generation": {
                "provider": "openai",
                "model": "synthetic-image-model",
                "base_url": "https://images.example/v1",
                "api_key": "synthetic-server-key",
                **image_generation,
            },
        }
    )


def test_typed_server_profile_is_usable_without_managed_catalog(tmp_path, monkeypatch):
    from deerflow.config.image_generation import resolve_server_image_profile

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = _config()
    profile = resolve_server_image_profile(config)
    assert profile is not None
    assert (profile.provider.value, profile.model, profile.usable()) == ("openai", "synthetic-image-model", True)


def test_typed_server_profile_loads_from_yaml_with_environment_key(tmp_path, monkeypatch):
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("SYNTHETIC_IMAGE_TEST_KEY", "synthetic-yaml-key")
    config = AppConfig._from_yaml_text(
        """sandbox:\n  use: test\nimage_generation:\n  provider: openai\n  model: synthetic-image-model\n  base_url: https://images.example/v1\n  api_key: $SYNTHETIC_IMAGE_TEST_KEY\n""",
        tmp_path / "config.yaml",
    )
    assert config.image_generation is not None
    assert config.image_generation.api_key.get_secret_value() == "synthetic-yaml-key"
    assert config.image_generation_environment["IMAGE_GENERATION_MODEL"] == "synthetic-image-model"


def test_legacy_server_profile_remains_available(tmp_path, monkeypatch):
    from deerflow.config.image_generation import resolve_server_image_profile

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": {"GEMINI_API_KEY": "synthetic-legacy-key", "GEMINI_IMAGE_MODEL": "legacy-image"}}})
    profile = resolve_server_image_profile(config)
    assert profile is not None
    assert (profile.provider.value, profile.model, profile.usable()) == ("gemini", "legacy-image", True)


def test_typed_minimax_default_uses_canonical_endpoint_identity(tmp_path, monkeypatch):
    from app.gateway.routers import image_generation as router

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = _config(provider="minimax", model="image-01", base_url=None)
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    server = next(item for item in router._list_profiles()["profiles"] if item["source"] == "config")
    assert server["base_url"] == "https://api.minimaxi.com"
    router._set_default(router.SetImageDefaultRequest(source="sandbox_environment", target_identity=server["identity"]))
    assert router._status()["source"] == "sandbox_environment"


def test_typed_and_legacy_server_profiles_cannot_compete():
    with pytest.raises(ValueError, match="image_generation.*sandbox.environment"):
        AppConfig.model_validate(
            {
                "sandbox": {"use": "test", "environment": {"GEMINI_API_KEY": "synthetic-legacy-key"}},
                "image_generation": {
                    "provider": "openai",
                    "model": "synthetic-image-model",
                    "base_url": "https://images.example/v1",
                    "api_key": "synthetic-server-key",
                },
            }
        )


def test_typed_server_and_web_profiles_remain_separate_choices(tmp_path, monkeypatch):
    from app.gateway.routers import image_generation as router
    from deerflow.config import image_generation as image_config
    from deerflow.config.image_generation import ManagedImageGenerationProfile

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = _config()
    web = ManagedImageGenerationProfile(
        name="synthetic-web",
        provider="openai",
        model="other-image-model",
        base_url="https://images.example/v1",
        api_key="synthetic-web-key",
        enabled=True,
        revision="synthetic-revision",
        server_model_at_enable="openai:synthetic-image-model",
    )
    monkeypatch.setattr(router, "get_app_config", lambda: config)

    def store():
        return SimpleNamespace(list=lambda: [web])

    monkeypatch.setattr(router, "ManagedImageGenerationProfileStore", store)
    monkeypatch.setattr(image_config, "ManagedImageGenerationProfileStore", store)
    listed = router._list_profiles()
    assert {item["source"] for item in listed["profiles"]} == {"config", "managed"}
    server = next(item for item in listed["profiles"] if item["source"] == "config")
    router._set_default(router.SetImageDefaultRequest(source="sandbox_environment", target_identity=server["identity"]))
    assert router._status()["source"] == "sandbox_environment"


def test_server_profile_can_be_probed_and_status_is_projected(tmp_path, monkeypatch):
    from app.gateway.routers import image_generation as router

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = _config()
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    calls = []

    def fake_probe(profile, operation):
        calls.append((profile.model, operation))
        return "success"

    monkeypatch.setattr(router, "probe_image_profile", fake_probe)
    before = router._list_profiles()
    server = next(item for item in before["profiles"] if item["source"] == "config")
    assert server["verified_generation"] is False
    result = router._test_server(SimpleNamespace(expected_identity=server["identity"]), "generation")
    assert result == {"ok": True, "message": "success"}
    assert calls == [("synthetic-image-model", "generation")]
    after = router._list_profiles()
    server = next(item for item in after["profiles"] if item["source"] == "config")
    assert server["verified_generation"] is True
    assert "synthetic-server-key" not in str(after)

    monkeypatch.setattr(router, "probe_image_profile", lambda _profile, _operation: "unreachable")
    assert router._test_server(SimpleNamespace(expected_identity=server["identity"]), "edit") == {"ok": False, "message": "unreachable"}
    assert router._status()["status"] == "unreachable"

    for changed in (_config(model="replacement-model"), _config(api_key="replacement-key")):
        monkeypatch.setattr(router, "get_app_config", lambda changed=changed: changed)
        stale = next(item for item in router._list_profiles()["profiles"] if item["source"] == "config")
        assert stale["verified_generation"] is False


@pytest.mark.asyncio
async def test_server_probe_requires_admin_and_rejects_stale_model(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from app.gateway.routers import image_generation as router

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(router, "get_app_config", _config)
    calls = []
    monkeypatch.setattr(router, "probe_image_profile", lambda *_args: calls.append(1) or "success")
    body = router.TestServerImageProfileRequest(expected_identity="stale")
    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))

    with pytest.raises(HTTPException) as denied:
        await router.test_server_image_profile(member, "generation", body)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as stale:
        await router.test_server_image_profile(admin, "generation", body)
    assert stale.value.status_code == 409
    assert calls == []


def test_server_probe_discards_result_after_key_rotation(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from app.gateway.routers import image_generation as router

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    current = [_config()]
    monkeypatch.setattr(router, "get_app_config", lambda: current[0])
    identity = next(item["identity"] for item in router._list_profiles()["profiles"] if item["source"] == "config")

    def rotating_probe(_profile, _operation):
        current[0] = _config(api_key="rotated-synthetic-key")
        return "success"

    monkeypatch.setattr(router, "probe_image_profile", rotating_probe)
    with pytest.raises(HTTPException) as changed:
        router._test_server(router.TestServerImageProfileRequest(expected_identity=identity), "generation")
    assert changed.value.status_code == 409
    assert router._status()["supports_generation"] is False


def test_typed_server_profile_reaches_local_aio_and_tool(tmp_path, monkeypatch):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_module
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins import image_generation_tool as image_tool

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    current = [_config()]
    monkeypatch.setattr(provider_module, "get_app_config", lambda: current[0])
    monkeypatch.setattr(image_tool, "get_app_config", lambda: current[0])
    provider = object.__new__(AioSandboxProvider)
    provider._backend = object.__new__(LocalContainerBackend)
    provider._config = {"command_timeout": 30}
    monkeypatch.setattr(provider, "_base_sandbox_id_for_thread", lambda *_args: "synthetic-base")
    monkeypatch.setattr(provider, "_managed_image_profile", lambda: None)
    monkeypatch.setattr(provider, "_get_extra_mounts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(provider, "_lark_integration_active", lambda *_args: False)
    monkeypatch.setattr(provider, "_lark_broker_active", lambda *_args: False)
    monkeypatch.setattr(provider, "_local_config_mount_exclusion_root", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider, "_replica_count", lambda: (3, 0))
    monkeypatch.setattr(provider_module, "wait_for_sandbox_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(provider, "_register_created_sandbox", lambda _thread, sandbox_id, _info, **_kwargs: sandbox_id)
    created = []

    def create(_thread, sandbox_id, **kwargs):
        created.append(kwargs)
        return provider_module.SandboxInfo(sandbox_id=sandbox_id, sandbox_url="http://synthetic-sandbox")

    provider._backend.create = create
    sandbox_id = provider._sandbox_id_for_thread("synthetic-thread", "synthetic-user")
    assert sandbox_id != "synthetic-base"
    assert provider._create_sandbox("synthetic-thread", sandbox_id, user_id="synthetic-user") == sandbox_id
    assert created[0]["extra_environment"]["IMAGE_GENERATION_API_KEY"] == "synthetic-server-key"

    sandbox = object.__new__(AioSandbox)
    sandbox._id = sandbox_id
    provider._bind_image_profile_context(sandbox, "synthetic-thread", "synthetic-user")
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: False)
    commands = []

    def execute(_sandbox, command, *, runtime, env, timeout):
        commands.append(env)
        return re.search(r"__DEERFLOW_IMAGE_OK_[a-f0-9]+__", command).group()

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", execute)
    args = (SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/image.png")
    assert image_tool.generate_image_tool.func(*args).startswith("Successfully generated")
    assert commands == [None]

    current[0] = _config(api_key="rotated-synthetic-key")
    assert provider._sandbox_id_for_thread("synthetic-thread", "synthetic-user") != sandbox_id
    assert "IMAGE_PROFILE_CHANGED" in image_tool.generate_image_tool.func(*args)
    assert commands == [None]
