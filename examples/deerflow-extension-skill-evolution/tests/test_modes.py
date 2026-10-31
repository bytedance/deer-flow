"""Tests for the persisted evolution-mode switch (settings.json)."""

import json
from pathlib import Path

import pytest

from deerflow_extension_skill_evolution import modes
from deerflow_extension_skill_evolution.modes import (
    DEFAULT_MODE,
    KEY,
    MODE_APPEND,
    MODE_MODEL,
    MODES,
    read_evolution_mode,
    settings_path,
    write_evolution_mode,
)


def test_read_defaults_to_model_without_a_file(tmp_path) -> None:
    assert read_evolution_mode(path=tmp_path / "settings.json") == MODE_MODEL
    assert read_evolution_mode(path=tmp_path / "nested" / "settings.json") == DEFAULT_MODE


def test_write_then_read_roundtrips_the_enum(tmp_path) -> None:
    path = tmp_path / "settings.json"
    write_evolution_mode(MODE_APPEND, path=path)
    assert read_evolution_mode(path=path) == MODE_APPEND
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {KEY: MODE_APPEND}
    write_evolution_mode(MODE_MODEL, path=path)
    assert read_evolution_mode(path=path) == MODE_MODEL


def test_write_preserves_unrelated_keys(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({KEY: MODE_APPEND, "other": 42}), encoding="utf-8")
    write_evolution_mode(MODE_MODEL, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {KEY: MODE_MODEL, "other": 42}


def test_corrupt_or_invalid_values_fall_back_to_the_default(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_evolution_mode(path=path) == DEFAULT_MODE
    path.write_text(json.dumps([MODE_APPEND]), encoding="utf-8")
    assert read_evolution_mode(path=path) == DEFAULT_MODE
    path.write_text(json.dumps({KEY: "agent"}), encoding="utf-8")
    assert read_evolution_mode(path=path) == DEFAULT_MODE


def test_write_rejects_values_outside_the_enum(tmp_path) -> None:
    with pytest.raises(ValueError, match="evolution_mode"):
        write_evolution_mode("agent", path=tmp_path / "settings.json")
    with pytest.raises(ValueError, match="evolution_mode"):
        write_evolution_mode(None, path=tmp_path / "settings.json")


def test_the_settings_file_lives_beside_the_installed_package() -> None:
    assert settings_path().parent == Path(modes.__file__).resolve().parent
    assert settings_path().name == "settings.json"
    assert set(MODES) == {MODE_MODEL, MODE_APPEND}


def test_persistent_settings_migrate_legacy_and_survive_reinstall(tmp_path, monkeypatch):
    legacy = tmp_path / "install" / "settings.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({KEY: MODE_APPEND, "other": 42}), encoding="utf-8")
    monkeypatch.setattr(modes, "settings_path", lambda: legacy)
    database = tmp_path / "state" / "evolution.sqlite"
    state = modes.EvolutionModeSettings(str(database))
    assert state.path == database.with_name("evolution.sqlite.settings.json")
    assert state.read() == MODE_APPEND
    assert json.loads(state.path.read_text(encoding="utf-8"))["other"] == 42
    legacy.unlink()
    assert modes.EvolutionModeSettings(str(database)).read() == MODE_APPEND
    state.write(MODE_MODEL)
    assert state.read() == MODE_MODEL
    assert not legacy.exists()


def test_persistent_settings_take_precedence_and_are_store_scoped(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.json"
    write_evolution_mode(MODE_APPEND, path=legacy)
    monkeypatch.setattr(modes, "settings_path", lambda: legacy)
    first = modes.EvolutionModeSettings(str(tmp_path / "one.sqlite"))
    first.write(MODE_MODEL)
    assert modes.EvolutionModeSettings(str(tmp_path / "one.sqlite")).read() == MODE_MODEL
    assert modes.EvolutionModeSettings(str(tmp_path / "two.sqlite")).read() == MODE_APPEND
    assert first.read() == MODE_MODEL


def test_corrupt_persistent_settings_do_not_resurrect_legacy_choice(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.json"
    write_evolution_mode(MODE_APPEND, path=legacy)
    monkeypatch.setattr(modes, "settings_path", lambda: legacy)
    state = modes.EvolutionModeSettings(str(tmp_path / "store.sqlite"))
    state.path.write_text("broken", encoding="utf-8")
    assert modes.EvolutionModeSettings(str(tmp_path / "store.sqlite")).read() == MODE_MODEL


def test_pre_upgrade_migration_command_copies_from_old_install(tmp_path):
    legacy = tmp_path / "old-install" / "settings.json"
    write_evolution_mode(MODE_APPEND, path=legacy)
    database = tmp_path / "state" / "store.sqlite"
    assert modes.main(["--storage-path", str(database), "--legacy-settings", str(legacy)]) == 0
    legacy.unlink()
    assert modes.EvolutionModeSettings(str(database)).read() == MODE_APPEND


def test_pre_upgrade_migration_refuses_missing_source(tmp_path):
    with pytest.raises(SystemExit):
        modes.main(["--storage-path", str(tmp_path / "store.sqlite"), "--legacy-settings", str(tmp_path / "missing.json")])
