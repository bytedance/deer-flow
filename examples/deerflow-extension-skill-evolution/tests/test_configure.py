"""Tests for the page-driven grant configuration (target skills + models)."""

import asyncio
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import yaml

from deerflow_extension_skill_evolution import configure as configure_module
from deerflow_extension_skill_evolution.configure import SkillConfigurator, granted_model_roles

USER = "user-1"
OTHER = "user-2"

CONFIG = """\
plugins:
- name: skill-evolution
  package: deerflow-extension-skill-evolution
  use: deerflow_extension_skill_evolution:install
  enabled: true
  config:
    feedback_mode: agent
  host_access:
    evidence:
      owners:
      - user-1
    skill_mutations:
      owners:
      - user-1
      operations:
      - stage
      - commit
      target_skills:
      - demo-evolution
      topology: single_host_local
    model_invocation:
      roles:
        default: GLM-5-3
other_key: 1
"""

CATALOG = ["demo-evolution", "batch-rename-txt"]
MODELS = ["GLM-5-3", "GLM-5-4"]


def _ctx(user_id: str = USER) -> SimpleNamespace:
    return SimpleNamespace(principal=SimpleNamespace(user_id=user_id))


def _configurator(tmp_path: Path, *, text: str = CONFIG, mode_reader=None, mode_writer=None) -> SkillConfigurator:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(text, encoding="utf-8")
    return SkillConfigurator(
        config_locator=lambda: (config_path, tmp_path),
        catalog_loader=lambda user: list(CATALOG),
        model_loader=lambda: list(MODELS),
        mode_reader=mode_reader or (lambda: "model"),
        mode_writer=mode_writer or (lambda mode: None),
    )


def _install_fake_manager(monkeypatch) -> None:
    """A minimal stand-in for the host's extension-manager editor.

    The plugin reuses ``_manager_lock`` and ``_write_plugins_block`` lazily;
    the fake keeps the same call shapes so the entry-mutation logic runs
    end-to-end against a real file.
    """

    @contextmanager
    def lock(root):
        yield

    def write_block(path, original, plugins):
        root = yaml.safe_load(original) or {}
        root["plugins"] = plugins
        path.write_text(yaml.safe_dump(root, sort_keys=False, allow_unicode=True), encoding="utf-8")

    manager = types.ModuleType("deerflow.extensions.manager")
    manager._manager_lock = lock
    manager._write_plugins_block = write_block
    extensions = types.ModuleType("deerflow.extensions")
    extensions.manager = manager
    deerflow = types.ModuleType("deerflow")
    deerflow.extensions = extensions
    monkeypatch.setitem(sys.modules, "deerflow", deerflow)
    monkeypatch.setitem(sys.modules, "deerflow.extensions", extensions)
    monkeypatch.setitem(sys.modules, "deerflow.extensions.manager", manager)


def test_status_reports_the_current_grants(tmp_path) -> None:
    configurator = _configurator(tmp_path, mode_reader=lambda: "append")
    result = asyncio.run(configurator.status({}, _ctx()))
    assert result["ok"] is True
    assert result["config_available"] is True
    assert result["targets"] == ["demo-evolution"]
    assert result["evolution_roles"] == {"default": "GLM-5-3"}
    assert result["skill_catalog"] == CATALOG
    assert result["models"] == MODELS
    assert result["evolution_mode"] == "append"
    # A caller outside the owners grant may read, but never write.
    assert asyncio.run(configurator.status({}, _ctx(OTHER)))["can_write"] is False


def test_status_degrades_when_config_is_unavailable(tmp_path) -> None:
    configurator = SkillConfigurator(
        config_locator=lambda: None,
        catalog_loader=lambda user: list(CATALOG),
        model_loader=lambda: list(MODELS),
    )
    result = asyncio.run(configurator.status({}, _ctx()))
    assert result["ok"] is True
    assert result["config_available"] is False
    assert result["can_write"] is False
    assert result["targets"] == []
    assert result["evolution_roles"] == {}
    # The page still needs auth and a strict empty payload.
    assert asyncio.run(configurator.status({}, SimpleNamespace(principal=None))) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
    assert asyncio.run(configurator.status({"skill_name": "x"}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}


def test_write_rewrites_the_plugin_entry(tmp_path, monkeypatch) -> None:
    _install_fake_manager(monkeypatch)
    configurator = _configurator(tmp_path)
    result = asyncio.run(configurator.write({"skill_names": ["batch-rename-txt", "demo-evolution"]}, _ctx()))
    assert result["ok"] is True
    assert result["targets"] == ["batch-rename-txt", "demo-evolution"]
    assert result["restart_required"] is True
    assert result["reinstall_command"].startswith("make extension-upgrade")
    entry = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["plugins"][0]
    assert entry["host_access"]["skill_mutations"]["target_skills"] == ["batch-rename-txt", "demo-evolution"]
    # The model invocation grant is operator-owned configuration and is
    # deliberately left untouched: model choice is a per-launch selection.
    assert entry["host_access"]["model_invocation"]["roles"] == {"default": "GLM-5-3"}
    # Untouched neighbours survive the surgical plugins-block rewrite.
    assert yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["other_key"] == 1


def test_write_persists_the_evolution_mode(tmp_path, monkeypatch) -> None:
    _install_fake_manager(monkeypatch)
    written: list[str] = []
    configurator = _configurator(tmp_path, mode_writer=written.append)
    result = asyncio.run(configurator.write({"skill_names": ["demo-evolution"], "evolution_mode": "append"}, _ctx()))
    assert result["ok"] is True
    assert result["targets"] == ["demo-evolution"]
    assert result["evolution_mode"] == "append"
    assert result["restart_required"] is True
    assert written == ["append"]
    # A mode-only write skips config.yaml entirely: it is read per call on
    # the backend, so no reinstall or restart is needed.
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    result = asyncio.run(configurator.write({"evolution_mode": "model"}, _ctx()))
    assert result == {"ok": True, "evolution_mode": "model"}
    assert written == ["append", "model"]
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before


def test_write_validates_and_reports_mode_failures(tmp_path) -> None:
    configurator = _configurator(tmp_path)
    assert asyncio.run(configurator.write({"skill_names": ["demo-evolution"], "evolution_mode": "agent"}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(configurator.write({}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(configurator.write({"evolution_mode": "append"}, _ctx(OTHER))) == {"ok": False, "error": {"code": "FORBIDDEN"}}

    def _boom(mode):
        raise OSError("disk full")

    failing = _configurator(tmp_path, mode_writer=_boom)
    assert asyncio.run(failing.write({"evolution_mode": "append"}, _ctx())) == {"ok": False, "error": {"code": "WRITE_FAILED"}}


def test_write_rejects_unknown_or_unauthorized_requests(tmp_path) -> None:
    configurator = _configurator(tmp_path)
    # Unknown skills fail closed with the offending names.
    assert asyncio.run(configurator.write({"skill_names": ["ghost-skill"]}, _ctx())) == {"ok": False, "error": {"code": "UNKNOWN_SKILL", "skills": ["ghost-skill"]}}
    # Non-canonical names never reach the catalog check.
    assert asyncio.run(configurator.write({"skill_names": ["Bad_Name"]}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(configurator.write({"skill_names": []}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert asyncio.run(configurator.write({}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    # Evolution models are not part of the write contract any more.
    assert asyncio.run(configurator.write({"skill_names": ["demo-evolution"], "evolution_models": ["GLM-5-4"]}, _ctx())) == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    # Callers outside the skill_mutations owners grant may not write.
    assert asyncio.run(configurator.write({"skill_names": ["demo-evolution"]}, _ctx(OTHER))) == {"ok": False, "error": {"code": "FORBIDDEN"}}
    assert asyncio.run(configurator.write({"skill_names": ["demo-evolution"]}, SimpleNamespace(principal=None))) == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
    # Without config.yaml there is nothing to write.
    missing = SkillConfigurator(
        config_locator=lambda: None,
        catalog_loader=lambda user: list(CATALOG),
        model_loader=lambda: list(MODELS),
    )
    assert asyncio.run(missing.write({"skill_names": ["demo-evolution"]}, _ctx())) == {"ok": False, "error": {"code": "CONFIG_UNAVAILABLE"}}


def test_granted_model_roles_reads_config_yaml(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr(configure_module, "_locate_config", lambda: (config_path, tmp_path))
    assert granted_model_roles() == {"default": "GLM-5-3"}
    # An entry without the model grant simply has no roles; an unreadable
    # config yields None so evolution launches pass through to the host check.
    monkeypatch.setattr(configure_module, "_locate_config", lambda: None)
    assert granted_model_roles() is None
