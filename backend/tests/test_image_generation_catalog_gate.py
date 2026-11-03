"""Deployment switch for the optional web-managed image catalog."""

import re
from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = tmp_path / "config.yaml"
    config.write_text("sandbox:\n  use: test\n", encoding="utf-8")
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    return tmp_path


def _config():
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "test"},
            "image_generation": {
                "provider": "openai",
                "model": "synthetic-server-image",
                "base_url": "https://images.example/v1",
                "api_key": "synthetic-server-key",
            },
        }
    )


def test_disabled_catalog_unmounts_management_routes_and_keeps_server_model(isolated_home, monkeypatch):
    import app.gateway.app as app_module
    from deerflow.config import image_generation as image_config

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "false")
    config = _config()
    monkeypatch.setattr(app_module, "get_app_config", lambda: config)
    app = app_module.create_app()
    assert app.state.image_generation_management_enabled is False
    assert not any(route.path.startswith("/api/image-generation") for route in app.routes)

    def forbidden_catalog_read(_self):
        pytest.fail("disabled runtime read the web image catalog")

    monkeypatch.setattr(image_config.EncryptedCatalog, "read", forbidden_catalog_read)
    profile, source, managed = image_config.resolve_image_generation_profile(config.image_generation_environment)
    assert (profile.model, source, managed) == ("synthetic-server-image", "sandbox_environment", None)
    assert image_config.image_profile_choice_needed(config.image_generation_environment) is False


def test_disabled_catalog_server_model_reaches_mocked_image_command(isolated_home, monkeypatch):
    from deerflow.config import image_generation as image_config
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins import image_generation_tool as image_tool

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "false")
    monkeypatch.setattr(image_tool, "get_app_config", _config)
    monkeypatch.setattr(image_config.EncryptedCatalog, "read", lambda _self: pytest.fail("web catalog was read"))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: object())
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: False)
    captured = {}

    def fake_command(_sandbox, command, *, runtime, env, timeout):
        captured.update(command=command, env=env)
        return re.search(r"__DEERFLOW_IMAGE_OK_[a-f0-9]+__", command).group()

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", fake_command)
    result = image_tool.generate_image_tool.func(
        SimpleNamespace(context={}),
        "/mnt/user-data/workspace/prompt.json",
        "/mnt/user-data/outputs/image.png",
    )
    assert result.startswith("Successfully generated")
    assert captured["command"].startswith('python -I -c "')
    assert captured["env"]["IMAGE_GENERATION_MODEL"] == "synthetic-server-image"
    assert captured["env"]["IMAGE_GENERATION_API_KEY"] == "synthetic-server-key"


def test_enabled_catalog_keeps_management_routes(isolated_home, monkeypatch):
    import app.gateway.app as app_module

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "true")
    monkeypatch.setattr(app_module, "get_app_config", _config)
    app = app_module.create_app()
    assert app.state.image_generation_management_enabled is True
    assert any(route.path == "/api/image-generation/profiles" for route in app.routes)


def test_disabled_catalog_ignores_existing_web_profile_without_deleting_it(isolated_home, monkeypatch):
    from deerflow.config.image_generation import (
        ImageConfigurationError,
        ImageGenerationDefaultStore,
        ManagedImageGenerationProfile,
        ManagedImageGenerationProfileStore,
        bind_image_generation_source,
        effective_image_generation_source,
        resolve_image_generation_profile,
    )

    store = ManagedImageGenerationProfileStore()
    web = ManagedImageGenerationProfile(
        name="synthetic-web",
        provider="openai",
        model="synthetic-web-image",
        base_url="https://images.example/v1",
        api_key="synthetic-web-key",
    )
    store.save(web, expected_revision=None)
    environment = _config().image_generation_environment
    assert resolve_image_generation_profile(environment)[1] == "managed"

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "false")
    assert resolve_image_generation_profile(environment)[1] == "sandbox_environment"
    assert store.list() == []
    with bind_image_generation_source("managed"):
        assert effective_image_generation_source(environment) is None
        assert resolve_image_generation_profile(environment)[1] == "sandbox_environment"
    with pytest.raises(ImageConfigurationError, match="disabled"):
        store.save(web, expected_revision=None)
    with pytest.raises(ImageConfigurationError, match="disabled"):
        ImageGenerationDefaultStore().save(
            "sandbox_environment",
            target_identity="synthetic",
            expected_revision=None,
            environment=environment,
        )
    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "true")
    assert resolve_image_generation_profile(environment)[1] == "managed"


def test_invalid_deployment_switch_rejects_gateway_startup(isolated_home, monkeypatch):
    import app.gateway.app as app_module
    from deerflow.config.image_generation import ImageConfigurationError

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "sometimes")
    monkeypatch.setattr(app_module, "get_app_config", _config)
    with pytest.raises(ImageConfigurationError, match="must be true or false"):
        app_module.create_app()


@pytest.mark.asyncio
@pytest.mark.parametrize(("switch", "expected_location"), [("false", "config.yaml"), ("true", "Settings > Models > Image models")])
@pytest.mark.parametrize("environment", [{}, {"IMAGE_GENERATION_PROVIDER": "openai"}])
async def test_image_tool_configuration_errors_point_to_available_settings(isolated_home, monkeypatch, switch, expected_location, environment):
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins import image_generation_tool as image_tool

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", switch)
    monkeypatch.setattr(image_tool, "get_app_config", lambda: SimpleNamespace(image_generation_environment=environment))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: pytest.fail("sandbox was acquired"))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized_async", lambda _runtime: pytest.fail("sandbox was acquired"))

    args = (SimpleNamespace(), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    results = (
        image_tool.check_image_generation_tool.func(SimpleNamespace(context={})),
        image_tool.generate_image_tool.func(*args),
        await image_tool.generate_image_tool.coroutine(*args),
    )
    for result in results:
        assert result.startswith("Error: IMAGE_PROVIDER_")
        assert expected_location in result


@pytest.mark.asyncio
async def test_feature_reports_deployment_switch(isolated_home, monkeypatch):
    from app.gateway.routers.features import list_features

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "false")
    result = await list_features(request, _config())
    assert result.image_generation_management.enabled is False

    monkeypatch.setenv("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "true")
    result = await list_features(request, _config())
    assert result.image_generation_management.enabled is True
