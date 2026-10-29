# SPDX-License-Identifier: MIT
"""Custom-skill writers keep the original save error when temporary cleanup fails."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.paths import Paths
from deerflow.skills.storage import get_or_new_skill_storage, reset_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


@pytest.fixture(autouse=True)
def _reset_storages():
    reset_skill_storage()
    yield
    reset_skill_storage()


@pytest.fixture()
def storage(tmp_path):
    return get_or_new_skill_storage(skills_path=str(tmp_path))


@pytest.fixture()
def user_storage(tmp_path):
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)):
        with patch("deerflow.config.paths._paths", None):
            created = UserScopedSkillStorage("test-user", host_path=str(tmp_path))
    return created


def _failing_replace(real_replace, destination_name: str, primary: BaseException, staged: list[Path]):
    def replace(path, destination):
        if Path(destination).name == destination_name and path.name != destination_name:
            staged.append(path)
            raise primary
        return real_replace(path, destination)

    return replace


@pytest.mark.parametrize("storage_kind", ["local", "user"])
@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_write_custom_skill_preserves_replace_error_when_cleanup_fails(tmp_path, monkeypatch, caplog, storage, user_storage, storage_kind, failure):
    selected = storage if storage_kind == "local" else user_storage
    skill_dir = selected.get_custom_skill_dir("demo-skill")
    target = skill_dir / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("previous", encoding="utf-8")

    primary = OSError("replace failed")
    staged: list[Path] = []
    real_replace = Path.replace
    real_unlink = Path.unlink
    monkeypatch.setattr(Path, "replace", _failing_replace(real_replace, "SKILL.md", primary, staged))
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if staged and path == staged[0]:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(OSError) as raised:
                selected.write_custom_skill("demo-skill", "SKILL.md", "replacement")
        assert raised.value is primary
        assert target.read_text(encoding="utf-8") == "previous"
        assert len(staged) == 1
        if failure == "none":
            assert not staged[0].exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert staged[0].exists()
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(staged[0]) in caplog.text
                assert "temporary unlink failed" in caplog.text
    finally:
        for path in staged:
            real_unlink(path, missing_ok=True)


@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_skill_states_preserve_save_error_when_cleanup_fails(monkeypatch, caplog, user_storage, failure):
    target = user_storage._skill_states_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"old-skill": {"enabled": false}}\n', encoding="utf-8")

    primary = OSError("replace failed")
    staged: list[Path] = []
    real_replace = Path.replace
    real_unlink = Path.unlink

    def replace(path, destination):
        if destination == target and path != target:
            staged.append(path)
            raise primary
        return real_replace(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if staged and path == staged[0]:
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(OSError) as raised:
                user_storage._write_skill_states({"new-skill": {"enabled": True}})
        assert raised.value is primary
        assert target.read_text(encoding="utf-8") == '{"old-skill": {"enabled": false}}\n'
        assert len(staged) == 1
        if failure == "none":
            assert not staged[0].exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert staged[0].read_text(encoding="utf-8").strip().startswith("{")
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(staged[0]) in caplog.text
    finally:
        for path in staged:
            real_unlink(path, missing_ok=True)


@pytest.mark.parametrize("failure", ["none", "unlink", "logging"])
def test_skill_states_keyboard_interrupt_still_cleans(monkeypatch, caplog, user_storage, failure):
    target = user_storage._skill_states_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"old-skill": {"enabled": false}}\n', encoding="utf-8")

    primary = KeyboardInterrupt()
    staged: list[Path] = []
    cleanup_unlinks: list[Path] = []
    real_replace = Path.replace
    real_unlink = Path.unlink

    monkeypatch.setattr(Path, "replace", _failing_replace(real_replace, target.name, primary, staged))
    if failure in {"unlink", "logging"}:

        def unlink(path, *args, **kwargs):
            if staged and path == staged[0]:
                cleanup_unlinks.append(path)
                raise OSError("temporary unlink failed")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
    if failure == "logging":

        def boom_log(*args, **kwargs):
            raise RuntimeError("log handler failed")

        monkeypatch.setattr("deerflow.utils.atomic_write.logger.warning", boom_log)

    try:
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.atomic_write"):
            with pytest.raises(KeyboardInterrupt) as raised:
                user_storage._write_skill_states({"new-skill": {"enabled": True}})
        assert raised.value is primary
        assert target.read_text(encoding="utf-8") == '{"old-skill": {"enabled": false}}\n'
        assert len(staged) == 1
        if failure == "none":
            assert not staged[0].exists()
            assert "Failed to remove temporary output file" not in caplog.text
        else:
            assert staged[0].exists()
            assert cleanup_unlinks == [staged[0]]
            if failure == "unlink":
                assert "Failed to remove temporary output file" in caplog.text
                assert str(staged[0]) in caplog.text
                assert "temporary unlink failed" in caplog.text
    finally:
        for path in staged:
            real_unlink(path, missing_ok=True)
