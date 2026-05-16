from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import deerflow.config.app_config as app_config_module
from deerflow.config.acp_config import load_acp_config_from_dict
from deerflow.config.agents_api_config import get_agents_api_config, load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config
from deerflow.config.checkpointer_config import get_checkpointer_config, load_checkpointer_config_from_dict
from deerflow.config.guardrails_config import get_guardrails_config, load_guardrails_config_from_dict
from deerflow.config.memory_config import get_memory_config, load_memory_config_from_dict
from deerflow.config.stream_bridge_config import get_stream_bridge_config, load_stream_bridge_config_from_dict
from deerflow.config.subagents_config import get_subagents_app_config, load_subagents_config_from_dict
from deerflow.config.summarization_config import get_summarization_config, load_summarization_config_from_dict
from deerflow.config.title_config import get_title_config, load_title_config_from_dict
from deerflow.config.tool_search_config import get_tool_search_config, load_tool_search_config_from_dict
from deerflow.runtime.checkpointer import get_checkpointer, reset_checkpointer
from deerflow.runtime.store import get_store, reset_store


def _reset_config_singletons() -> None:
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
    reset_app_config()


def _write_config(path: Path, *, model_name: str, supports_thinking: bool) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": supports_thinking,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_config_with_agents_api(
    path: Path,
    *,
    model_name: str,
    supports_thinking: bool,
    agents_api: dict | None = None,
) -> None:
    config = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": model_name,
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
                "supports_thinking": supports_thinking,
            }
        ],
    }
    if agents_api is not None:
        config["agents_api"] = agents_api

    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_config_with_sections(path: Path, sections: dict | None = None) -> None:
    config = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": "first-model",
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
            }
        ],
    }
    if sections:
        config.update(sections)

    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_extensions_config(path: Path) -> None:
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def test_app_config_defaults_missing_database_to_sqlite(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.database.backend == "sqlite"
    assert config.database.sqlite_dir == ".deer-flow/data"


def test_app_config_defaults_empty_database_to_sqlite(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "database": {},
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.database.backend == "sqlite"
    assert config.database.sqlite_dir == ".deer-flow/data"


def test_get_app_config_reloads_when_file_changes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].supports_thinking is False

        _write_config(config_path, model_name="first-model", supports_thinking=True)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded.models[0].supports_thinking is True
        assert reloaded is not initial
    finally:
        reset_app_config()


def test_get_app_config_reloads_when_config_path_changes(tmp_path, monkeypatch):
    config_a = tmp_path / "config-a.yaml"
    config_b = tmp_path / "config-b.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_a, model_name="model-a", supports_thinking=False)
    _write_config(config_b, model_name="model-b", supports_thinking=True)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_a))
    reset_app_config()

    try:
        first = get_app_config()
        assert first.models[0].name == "model-a"

        monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_b))
        second = get_app_config()
        assert second.models[0].name == "model-b"
        assert second is not first
    finally:
        reset_app_config()


def test_get_app_config_resets_agents_api_config_when_section_removed(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_agents_api(
        config_path,
        model_name="first-model",
        supports_thinking=False,
        agents_api={"enabled": True},
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].name == "first-model"
        assert get_agents_api_config().enabled is True

        _write_config_with_agents_api(
            config_path,
            model_name="first-model",
            supports_thinking=False,
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded is not initial
        assert get_agents_api_config().enabled is False
    finally:
        reset_app_config()


def test_get_app_config_resets_singleton_configs_when_sections_removed(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(
        config_path,
        {
            "title": {"enabled": False, "max_words": 3},
            "summarization": {"enabled": True},
            "memory": {"enabled": False, "max_facts": 50},
            "subagents": {"timeout_seconds": 42, "agents": {"reviewer": {"max_turns": 2}}},
            "tool_search": {"enabled": True},
            "guardrails": {"enabled": True, "fail_closed": False},
            "checkpointer": {"type": "memory"},
            "stream_bridge": {"type": "memory", "queue_maxsize": 12},
        },
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        get_app_config()
        assert get_title_config().enabled is False
        assert get_summarization_config().enabled is True
        assert get_memory_config().enabled is False
        assert get_subagents_app_config().timeout_seconds == 42
        assert get_tool_search_config().enabled is True
        assert get_guardrails_config().enabled is True
        assert get_checkpointer_config() is not None
        assert get_stream_bridge_config() is not None

        _write_config_with_sections(config_path)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        get_app_config()
        assert get_title_config().enabled is True
        assert get_summarization_config().enabled is False
        assert get_memory_config().enabled is True
        assert get_subagents_app_config().timeout_seconds == 900
        assert get_tool_search_config().enabled is False
        assert get_guardrails_config().enabled is False
        assert get_checkpointer_config() is None
        assert get_stream_bridge_config() is None
    finally:
        _reset_config_singletons()


def test_get_app_config_resets_persistence_runtime_singletons_when_checkpointer_removed(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(config_path, {"checkpointer": {"type": "memory"}})

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_checkpointer()
    reset_store()
    reset_app_config()

    try:
        get_app_config()
        initial_checkpointer = get_checkpointer()
        initial_store = get_store()

        _write_config_with_sections(config_path)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        get_app_config()

        assert get_checkpointer_config() is None
        assert get_checkpointer() is not initial_checkpointer
        assert get_store() is not initial_store
    finally:
        _reset_config_singletons()


def test_get_app_config_keeps_persistence_runtime_singletons_when_checkpointer_unchanged(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(
        config_path,
        {
            "title": {"enabled": False},
            "checkpointer": {"type": "memory"},
        },
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    _reset_config_singletons()

    try:
        get_app_config()
        initial_checkpointer = get_checkpointer()
        initial_store = get_store()

        _write_config_with_sections(
            config_path,
            {
                "title": {"enabled": True},
                "checkpointer": {"type": "memory"},
            },
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        get_app_config()

        assert get_checkpointer() is initial_checkpointer
        assert get_store() is initial_store
    finally:
        _reset_config_singletons()


def test_get_app_config_does_not_mutate_singletons_when_reload_validation_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_sections(
        config_path,
        {
            "title": {"enabled": False},
            "tool_search": {"enabled": True},
            "checkpointer": {"type": "memory"},
        },
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    _reset_config_singletons()

    try:
        previous_app_config = get_app_config()
        initial_checkpointer = get_checkpointer()
        initial_store = get_store()

        _write_config_with_sections(
            config_path,
            {
                "title": False,
                "tool_search": False,
                "checkpointer": {"type": "memory"},
            },
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        with pytest.raises(ValidationError):
            get_app_config()

        assert app_config_module._app_config is previous_app_config
        assert get_title_config().enabled is False
        assert get_tool_search_config().enabled is True
        assert get_checkpointer_config() is not None
        assert get_checkpointer() is initial_checkpointer
        assert get_store() is initial_store
    finally:
        _reset_config_singletons()
