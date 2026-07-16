"""Tests for the per-agent memory toggle on custom agents (issue #3626).

A custom agent can hand-author ``memory: {enabled: false}`` in its
``config.yaml`` to run without memory even when the deployment enables memory
globally. These tests pin:

* the ``memory:`` block parses on :class:`AgentConfig` and is ``None`` when
  omitted (so every existing agent loads unchanged),
* ``load_agent_config`` round-trips the block through YAML,
* the block survives ``preserve_non_managed_fields`` (the update surfaces never
  drop it),
* ``disabled_memory_config`` switches both the write and read sides off, and
* ``apply_agent_memory_override`` folds the opt-out into the effective app
  config only for an agent that disables memory — every other agent gets the
  same object back (narrow, no-op-by-default semantics).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deerflow.agents.lead_agent.agent import apply_agent_memory_override
from deerflow.config.agents_config import (
    MANAGED_AGENT_CONFIG_FIELDS,
    AgentConfig,
    AgentMemoryConfig,
    load_agent_config,
    preserve_non_managed_fields,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.memory_config import MemoryConfig, disabled_memory_config, should_use_memory_tools
from deerflow.config.sandbox_config import SandboxConfig


# --------------------------------------------------------------------------- #
# AgentConfig parsing
# --------------------------------------------------------------------------- #
def test_memory_field_defaults_to_none() -> None:
    # An omitted memory block inherits the global config, so every existing
    # agent continues to load unchanged.
    assert AgentConfig(name="solo").memory is None


def test_memory_block_disable_parses() -> None:
    cfg = AgentConfig(name="worker", memory={"enabled": False})
    assert isinstance(cfg.memory, AgentMemoryConfig)
    assert cfg.memory.enabled is False


def test_memory_block_enabled_parses() -> None:
    cfg = AgentConfig(name="worker", memory={"enabled": True})
    assert cfg.memory is not None
    assert cfg.memory.enabled is True


def test_memory_block_defaults_enabled_true() -> None:
    # A present-but-empty ``memory: {}`` block means "enabled" (the field default).
    assert AgentMemoryConfig().enabled is True


# --------------------------------------------------------------------------- #
# YAML round-trip via load_agent_config (mirrors the github-block tests)
# --------------------------------------------------------------------------- #
def _write_agent(base: Path, user_id: str, name: str, body: dict) -> None:
    agent_dir = base / "users" / user_id / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


def test_load_agent_config_reads_memory_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Reset the singleton so the new HOME is picked up.
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    _write_agent(tmp_path, "default", "stateless-worker", {"name": "stateless-worker", "memory": {"enabled": False}})
    cfg = load_agent_config("stateless-worker", user_id="default")
    assert cfg is not None
    assert cfg.memory is not None
    assert cfg.memory.enabled is False


def test_load_agent_config_without_memory_block_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    _write_agent(tmp_path, "default", "plain-agent", {"name": "plain-agent"})
    cfg = load_agent_config("plain-agent", user_id="default")
    assert cfg is not None
    assert cfg.memory is None


# --------------------------------------------------------------------------- #
# The block is hand-authored: the update surfaces must never drop it.
# --------------------------------------------------------------------------- #
def test_memory_is_not_a_managed_field() -> None:
    assert "memory" not in MANAGED_AGENT_CONFIG_FIELDS


def test_preserve_non_managed_fields_keeps_memory() -> None:
    cfg = AgentConfig(name="worker", model="fast", memory={"enabled": False})
    preserved = preserve_non_managed_fields(cfg)
    # ``model`` is managed (re-emitted by the updater); ``memory`` is
    # hand-authored and must be carried forward verbatim.
    assert "model" not in preserved
    assert preserved["memory"] == {"enabled": False}


# --------------------------------------------------------------------------- #
# disabled_memory_config (pure)
# --------------------------------------------------------------------------- #
def test_disabled_memory_config_turns_off_both_sides() -> None:
    base = MemoryConfig(enabled=True, injection_enabled=True, debounce_seconds=42)
    off = disabled_memory_config(base)
    assert off.enabled is False
    assert off.injection_enabled is False
    # Unrelated tuning is preserved so re-enabling later restores prior settings.
    assert off.debounce_seconds == 42
    # The input is not mutated.
    assert base.enabled is True
    assert base.injection_enabled is True


# --------------------------------------------------------------------------- #
# apply_agent_memory_override — the fold into the effective app config
# --------------------------------------------------------------------------- #
def _app_config(*, enabled: bool = True, injection: bool = True, mode: str = "middleware") -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        memory=MemoryConfig(enabled=enabled, injection_enabled=injection, mode=mode),
    )


def test_override_disables_memory_for_opted_out_agent() -> None:
    app_config = _app_config(enabled=True, injection=True)
    agent_config = AgentConfig(name="worker", memory={"enabled": False})

    effective = apply_agent_memory_override(app_config, agent_config)

    assert effective is not app_config  # a copy — original is untouched
    assert app_config.memory.enabled is True
    assert effective.memory.enabled is False
    assert effective.memory.injection_enabled is False


def test_override_disables_memory_tools_gate() -> None:
    # Even in tool mode, an opted-out agent gets no memory tools.
    app_config = _app_config(enabled=True, injection=True, mode="tool")
    agent_config = AgentConfig(name="worker", memory={"enabled": False})

    effective = apply_agent_memory_override(app_config, agent_config)

    assert should_use_memory_tools(app_config.memory) is True  # baseline: tools would be on
    assert should_use_memory_tools(effective.memory) is False  # override turns them off


def test_override_is_identity_without_agent_config() -> None:
    app_config = _app_config()
    assert apply_agent_memory_override(app_config, None) is app_config


def test_override_is_identity_when_memory_block_absent() -> None:
    app_config = _app_config()
    agent_config = AgentConfig(name="worker")  # no memory block
    assert apply_agent_memory_override(app_config, agent_config) is app_config


def test_override_enabled_true_is_identity() -> None:
    # ``memory: {enabled: true}`` never widens — it leaves the global config
    # exactly as-is (same object back).
    app_config = _app_config(enabled=True, injection=True)
    agent_config = AgentConfig(name="worker", memory={"enabled": True})
    effective = apply_agent_memory_override(app_config, agent_config)
    assert effective is app_config
    assert effective.memory.enabled is True


def test_override_cannot_force_memory_on_when_global_off() -> None:
    # Narrow semantics: an agent can't re-enable memory the operator disabled
    # globally. ``enabled: true`` is a no-op, so global-off stays off.
    app_config = _app_config(enabled=False, injection=False)
    agent_config = AgentConfig(name="worker", memory={"enabled": True})
    effective = apply_agent_memory_override(app_config, agent_config)
    assert effective is app_config
    assert effective.memory.enabled is False


# --------------------------------------------------------------------------- #
# build_middlewares — the opt-out folds through to the real chain
# --------------------------------------------------------------------------- #
def test_build_middlewares_folds_memory_opt_out_into_the_chain(monkeypatch) -> None:
    """End-to-end: the opt-out reaches the actual middleware chain.

    ``apply_agent_memory_override`` resolves the effective config once; then
    ``build_middlewares`` reads ``app_config.memory`` and hands it to
    ``MemoryMiddleware``, which self-gates on ``enabled`` (its hooks return early
    when disabled). So an opted-out agent's ``MemoryMiddleware`` is inert (present
    but short-circuits) with read-side injection off, while a normal agent's is
    active. This locks the ``risk:high`` wiring end-to-end rather than only the
    pure helpers.
    """
    from deerflow.agents.lead_agent import agent as lead_agent_module
    from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

    # Stub the heavy shared/summarization/todo parts so this exercises only the
    # lead-only assembly that decides on MemoryMiddleware.
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda *, app_config=None: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)

    runnable = {"configurable": {"is_plan_mode": False, "subagent_enabled": False}}

    def _memory_mw(mws):
        return next((m for m in mws if isinstance(m, MemoryMiddleware)), None)

    app_config = _app_config(enabled=True, injection=True)

    # Normal agent: MemoryMiddleware is present and active.
    normal = _memory_mw(lead_agent_module.build_middlewares(runnable, model_name="safe-model", app_config=app_config))
    assert normal is not None
    assert normal._memory_config.enabled is True

    # Opted-out agent: fold the override, rebuild -> MemoryMiddleware is inert.
    effective = apply_agent_memory_override(app_config, AgentConfig(name="worker", memory={"enabled": False}))
    assert effective.memory.enabled is False
    assert effective.memory.injection_enabled is False  # read side off too
    opted = _memory_mw(lead_agent_module.build_middlewares(runnable, model_name="safe-model", app_config=effective))
    assert opted is not None
    assert opted._memory_config.enabled is False
