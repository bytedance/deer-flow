"""Explicit ``reload_app_config(config_path)`` must pin that file for later reads.

Mirrors the ``_extensions_config_source`` contract: once an explicit path is
reloaded, ``get_app_config()`` (and therefore ``DeerFlowClient(config_path=...)``)
must keep following that file instead of ambient default resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import deerflow.config.app_config as app_config_module
from deerflow.client import DeerFlowClient
from deerflow.config.acp_config import load_acp_config_from_dict
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.app_config import (
    AppConfig,
    get_app_config,
    reload_app_config,
    reset_app_config,
    set_app_config,
)
from deerflow.config.checkpointer_config import load_checkpointer_config_from_dict
from deerflow.config.extensions_config import reset_extensions_config
from deerflow.config.guardrails_config import load_guardrails_config_from_dict
from deerflow.config.memory_config import load_memory_config_from_dict
from deerflow.config.stream_bridge_config import load_stream_bridge_config_from_dict
from deerflow.config.subagents_config import load_subagents_config_from_dict
from deerflow.config.summarization_config import load_summarization_config_from_dict
from deerflow.config.title_config import load_title_config_from_dict
from deerflow.config.tool_search_config import load_tool_search_config_from_dict
from deerflow.runtime.checkpointer import reset_checkpointer
from deerflow.runtime.store import reset_store
from deerflow.storage import reset_blob_store


def _reset_singletons() -> None:
    reset_extensions_config()
    load_title_config_from_dict({})
    load_summarization_config_from_dict({})
    load_memory_config_from_dict({})
    load_agents_api_config_from_dict({})
    load_subagents_config_from_dict({})
    load_tool_search_config_from_dict({})
    load_guardrails_config_from_dict({})
    load_checkpointer_config_from_dict(None)
    load_stream_bridge_config_from_dict(None)
    load_acp_config_from_dict({})
    reset_checkpointer()
    reset_store()
    reset_blob_store()
    reset_app_config()


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
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _model_names(config: AppConfig) -> list[str]:
    return [model.name for model in config.models]


@pytest.fixture
def isolated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point ambient resolution at an empty tmp project root (no config.yaml)."""
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    # Avoid legacy monorepo candidates finding the checkout's config.yaml.
    monkeypatch.setattr(
        app_config_module,
        "_legacy_config_candidates",
        lambda: (),
    )
    _reset_singletons()
    yield tmp_path
    _reset_singletons()


def test_get_app_config_follows_explicit_reload_without_ambient(isolated_project: Path) -> None:
    custom = isolated_project / "custom" / "config.yaml"
    custom.parent.mkdir()
    _write_config(custom, model_name="custom-model")

    reload_app_config(str(custom))
    cfg = get_app_config()
    assert _model_names(cfg) == ["custom-model"]


def test_client_config_path_overrides_sibling_default(isolated_project: Path) -> None:
    _write_config(isolated_project / "config.yaml", model_name="default-model")
    custom = isolated_project / "custom.yaml"
    _write_config(custom, model_name="custom-model")

    client = DeerFlowClient(config_path=str(custom))
    assert _model_names(client._app_config) == ["custom-model"]
    assert _model_names(get_app_config()) == ["custom-model"]


def test_client_config_path_works_with_no_default_config(isolated_project: Path) -> None:
    custom = isolated_project / "only-custom.yaml"
    _write_config(custom, model_name="custom-model")

    client = DeerFlowClient(config_path=str(custom))
    assert _model_names(client._app_config) == ["custom-model"]
    assert _model_names(get_app_config()) == ["custom-model"]


def test_explicit_pin_revalidates_edits_and_clears_on_reset(isolated_project: Path) -> None:
    custom = isolated_project / "pinned.yaml"
    _write_config(custom, model_name="first-model")
    reload_app_config(str(custom))
    assert _model_names(get_app_config()) == ["first-model"]

    _write_config(custom, model_name="edited-model")
    assert _model_names(get_app_config()) == ["edited-model"]

    other = isolated_project / "other.yaml"
    _write_config(other, model_name="other-model")
    reload_app_config(str(other))
    assert _model_names(get_app_config()) == ["other-model"]
    assert app_config_module._app_config_source == str(other)

    # Failed reload keeps the prior pin.
    missing = isolated_project / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        reload_app_config(str(missing))
    assert app_config_module._app_config_source == str(other)
    assert _model_names(get_app_config()) == ["other-model"]

    # Argument-less reload clears the pin (and fails here: no ambient file).
    with pytest.raises(FileNotFoundError):
        reload_app_config()
    assert app_config_module._app_config_source is None

    # Re-pin, then reset clears.
    reload_app_config(str(custom))
    assert app_config_module._app_config_source == str(custom)
    reset_app_config()
    assert app_config_module._app_config_source is None

    # set_app_config clears the pin.
    reload_app_config(str(custom))
    injected = AppConfig.from_file(str(custom))
    set_app_config(injected)
    assert app_config_module._app_config_source is None
    assert get_app_config() is injected
