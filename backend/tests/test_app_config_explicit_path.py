from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import deerflow.config.app_config as app_config_module
from deerflow.config.app_config import get_app_config, reload_app_config, reset_app_config, set_app_config
from deerflow.config.extensions_config import reset_extensions_config


def _write_extensions_config(path: Path) -> None:
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def _write_config(path: Path, *, model_name: str) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    """Isolate the config singletons and point ambient resolution at tmp_path.

    The default-resolution search reads the working directory, so the tests
    chdir into ``tmp_path`` and stage an ``extensions_config.json`` there; the
    ambient ``config.yaml`` is written per-test when a scenario needs one.
    """
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    reset_app_config()
    try:
        yield tmp_path
    finally:
        reset_extensions_config()
        reset_app_config()


def test_explicit_reload_overrides_a_sibling_ambient_default(config_env):
    """reload_app_config(config_path) pins the file; an ambient default cannot win.

    This is issue #7086 manifestation 1: the client configured a custom config
    that declared ``custom-model``, and the next ``get_app_config()`` reported
    the ambient default's model instead.
    """
    tmp_path = config_env
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    custom_config = custom_dir / "config.yaml"
    _write_config(custom_config, model_name="custom-model")
    _write_config(tmp_path / "config.yaml", model_name="default-model")

    reload_app_config(str(custom_config))
    cfg = get_app_config()

    assert cfg.models[0].name == "custom-model"


def test_get_app_config_follows_explicit_reload_without_an_ambient_default(config_env):
    """After an explicit reload, get_app_config() revalidates the pinned file.

    This is issue #7086 manifestation 2: with no ambient ``config.yaml``, the
    follow-up ``get_app_config()`` re-ran default resolution and raised
    ``FileNotFoundError`` for the very file the reload had just loaded.
    """
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")
    assert not (tmp_path / "config.yaml").exists()

    reload_app_config(str(custom_config))
    cfg = get_app_config()

    assert cfg.models[0].name == "custom-model"


def test_pinned_explicit_file_stays_hot_reloadable(config_env):
    """The pin keeps the freshness contract: edits to the pinned file reload."""
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")

    reload_app_config(str(custom_config))
    first = get_app_config()
    assert first.models[0].name == "custom-model"

    _write_config(custom_config, model_name="edited-model")
    second = get_app_config()
    assert second is not first
    assert second.models[0].name == "edited-model"


def test_reset_clears_the_explicit_source_pin(config_env):
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")

    reload_app_config(str(custom_config))
    assert app_config_module._app_config_source == str(custom_config)

    reset_app_config()
    assert app_config_module._app_config_source is None


def test_set_app_config_clears_the_explicit_source_pin(config_env):
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")

    reload_app_config(str(custom_config))
    assert app_config_module._app_config_source is not None

    set_app_config(object.__new__(type(get_app_config())))
    assert app_config_module._app_config_source is None


def test_argument_less_reload_falls_back_to_default_resolution(config_env):
    """An argument-less reload clears the pin; default resolution takes over."""
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")
    ambient = tmp_path / "config.yaml"
    _write_config(ambient, model_name="default-model")

    reload_app_config(str(custom_config))
    assert app_config_module._app_config_source is not None

    reload_app_config()
    assert app_config_module._app_config_source is None

    cfg = get_app_config()
    assert cfg.models[0].name == "default-model"


def test_explicit_env_config_path_is_not_pinned_as_explicit_source(config_env, monkeypatch):
    """The env var is already part of default resolution; it must not pin.

    ``reload_app_config()`` resolving ``DEER_FLOW_CONFIG_PATH`` stores no
    source pin, so a later change of the env var keeps working exactly as in
    ``test_get_app_config_reloads_when_config_path_changes``.
    """
    tmp_path = config_env
    env_config = tmp_path / "env-config.yaml"
    _write_config(env_config, model_name="env-model")

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(env_config))
    reset_app_config()

    reload_app_config()
    assert app_config_module._app_config_source is None

    cfg = get_app_config()
    assert cfg.models[0].name == "env-model"


def test_default_flow_get_app_config_records_no_pin(config_env, monkeypatch):
    """An internal re-cache inside get_app_config() must not create a pin.

    Regression for the review finding on this PR: the first re-cache passed
    the resolved path into ``_load_and_cache_app_config``, so an ambient or
    env-resolved path was recorded as if a caller had pinned it — freezing
    that path over later ``DEER_FLOW_CONFIG_PATH`` changes.
    """
    tmp_path = config_env
    env_a = tmp_path / "env-a.yaml"
    _write_config(env_a, model_name="model-a")

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(env_a))
    reset_app_config()

    # First load: triggers the internal re-cache path inside get_app_config().
    first = get_app_config()
    assert first.models[0].name == "model-a"
    assert app_config_module._app_config_source is None, "default-flow load must not record a pin"

    # The env-var contract keeps working after that re-cache.
    env_b = tmp_path / "env-b.yaml"
    _write_config(env_b, model_name="model-b")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(env_b))

    second = get_app_config()
    assert second.models[0].name == "model-b"
    assert app_config_module._app_config_source is None


def test_explicit_pin_survives_get_app_config_recache(config_env):
    """A real explicit pin must survive the re-cache inside get_app_config()."""
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")

    reload_app_config(str(custom_config))
    # Force a freshness-driven re-cache: bump the file's mtime.
    import os

    later = custom_config.stat().st_mtime + 5
    os.utime(custom_config, (later, later))
    cfg = get_app_config()

    assert cfg.models[0].name == "custom-model"
    assert app_config_module._app_config_source == str(custom_config)


def test_client_config_path_overrides_sibling_default_without_explicit_reload(config_env):
    """DeerFlowClient(config_path=...) keeps working through the pin.

    The client calls ``reload_app_config(config_path)`` once and then
    ``get_app_config()``; both now agree on the explicit file. This replays
    that exact pair of calls.
    """
    tmp_path = config_env
    custom_config = tmp_path / "custom" / "config.yaml"
    custom_config.parent.mkdir()
    _write_config(custom_config, model_name="custom-model")
    _write_config(tmp_path / "config.yaml", model_name="default-model")

    # The DeerFlowClient pair:
    reload_app_config(str(custom_config))
    cfg = get_app_config()

    assert cfg.models[0].name == "custom-model"
