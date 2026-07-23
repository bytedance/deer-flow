"""Tests for the per-agent model-settings block on :class:`AgentConfig` (#4336).

Covers the new ``model_settings`` / ``thinking_enabled`` / ``reasoning_effort``
fields: validation bounds, YAML round-trip via ``load_agent_config``, backward
compatibility (absent = None), and that they are treated as managed fields by
``preserve_non_managed_fields``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.agents_config import (
    MANAGED_AGENT_CONFIG_FIELDS,
    MAX_AGENT_OUTPUT_TOKENS,
    AgentConfig,
    AgentModelSettings,
    load_agent_config,
    preserve_non_managed_fields,
)


def test_model_settings_default_to_none() -> None:
    cfg = AgentConfig(name="solo")
    assert cfg.model_settings is None
    assert cfg.thinking_enabled is None
    assert cfg.reasoning_effort is None


def test_model_settings_parse_full_shape() -> None:
    cfg = AgentConfig(
        name="researcher",
        model_settings={"temperature": 0.2, "max_tokens": 12000},
        thinking_enabled=True,
        reasoning_effort="high",
    )
    assert isinstance(cfg.model_settings, AgentModelSettings)
    assert cfg.model_settings.temperature == 0.2
    assert cfg.model_settings.max_tokens == 12000
    assert cfg.thinking_enabled is True
    assert cfg.reasoning_effort == "high"


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_temperature_out_of_range_rejected(temperature: float) -> None:
    with pytest.raises(ValidationError):
        AgentModelSettings(temperature=temperature)


def test_max_tokens_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AgentModelSettings(max_tokens=0)


def test_max_tokens_has_sane_upper_bound() -> None:
    with pytest.raises(ValidationError):
        AgentModelSettings(max_tokens=MAX_AGENT_OUTPUT_TOKENS + 1)


def test_model_settings_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        AgentModelSettings(top_p=0.9)  # type: ignore[call-arg]


def test_reasoning_effort_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(name="x", reasoning_effort="turbo")  # type: ignore[arg-type]


def test_reasoning_effort_rejects_codex_unsupported_minimal() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(name="x", reasoning_effort="minimal")  # type: ignore[arg-type]


def test_model_settings_are_managed_fields() -> None:
    # These are managed by the HTTP agent settings API, so the generic
    # preserve_non_managed_fields helper must not also carry them. Surfaces that
    # do not expose them directly, such as the harness update_agent tool, need a
    # dedicated carry-forward path instead.
    for field in ("model_settings", "thinking_enabled", "reasoning_effort"):
        assert field in MANAGED_AGENT_CONFIG_FIELDS


def test_preserve_non_managed_excludes_model_settings() -> None:
    cfg = AgentConfig(
        name="a",
        model_settings={"temperature": 0.5},
        thinking_enabled=True,
        github={"installation_id": 7},
    )
    preserved = preserve_non_managed_fields(cfg)
    assert "model_settings" not in preserved
    assert "thinking_enabled" not in preserved
    # github stays preserved (hand-authored, not managed by the update surfaces).
    assert "github" in preserved


def _write_agent(base: Path, user_id: str, name: str, body: dict) -> None:
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


def test_load_agent_config_round_trips_model_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    body = {
        "name": "researcher",
        "model": "claude-sonnet-4-6",
        "model_settings": {"temperature": 0.2, "max_tokens": 12000},
        "thinking_enabled": True,
        "reasoning_effort": "high",
    }
    _write_agent(tmp_path, "default", "researcher", body)

    cfg = load_agent_config("researcher", user_id="default")
    assert cfg is not None
    assert cfg.model_settings is not None
    assert cfg.model_settings.temperature == 0.2
    assert cfg.model_settings.max_tokens == 12000
    assert cfg.thinking_enabled is True
    assert cfg.reasoning_effort == "high"


def test_load_agent_config_without_model_settings_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    _write_agent(tmp_path, "default", "plain", {"name": "plain", "model": "gpt-4o"})

    cfg = load_agent_config("plain", user_id="default")
    assert cfg is not None
    assert cfg.model_settings is None
    assert cfg.thinking_enabled is None
    assert cfg.reasoning_effort is None
