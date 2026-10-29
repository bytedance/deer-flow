"""Deleting an operator-linked custom skill package must unlink, not fail.

The storage contract (``SkillStorage._is_external_skill_directory_symlink``)
accepts a one-level symlink under ``custom/`` that points at an externally
managed skill package. Every read path honors it, but ``delete_custom_skill``
called ``shutil.rmtree`` on the link, which refuses symlinks: the delete
raised ``OSError`` after the history record had already been appended, the
projection mutation cleared the user's skill view on the way out, and the
Gateway answered 500. The external tree is not ours to delete, so removing
the skill means removing the link.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from support.symlinks import symlink_or_skip

from deerflow.config.paths import Paths
from deerflow.skills.storage import get_or_new_skill_storage, reset_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


def _skill_content(name: str) -> str:
    return f"---\nname: {name}\ndescription: Linked skill\n---\n\n# {name}\n"


@pytest.fixture(autouse=True)
def _reset_storages():
    reset_skill_storage()
    yield
    reset_skill_storage()


def _plant_external_package(tmp_path: Path, name: str) -> Path:
    external = tmp_path / "operator-skills" / name
    external.mkdir(parents=True)
    (external / "SKILL.md").write_text(_skill_content(name), encoding="utf-8")
    (external / "references").mkdir()
    (external / "references" / "notes.md").write_text("keep me", encoding="utf-8")
    return external


def _assert_external_untouched(external: Path, name: str) -> None:
    assert (external / "SKILL.md").read_text(encoding="utf-8") == _skill_content(name)
    assert (external / "references" / "notes.md").read_text(encoding="utf-8") == "keep me"


def test_local_storage_unlinks_a_symlinked_package_and_leaves_the_target_alone(tmp_path: Path):
    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True)
    storage = get_or_new_skill_storage(skills_path=str(skills_root))
    external = _plant_external_package(tmp_path, "linked-skill")
    link = skills_root / "custom" / "linked-skill"
    symlink_or_skip(link, external, target_is_directory=True)
    assert storage.custom_skill_exists("linked-skill")

    storage.delete_custom_skill("linked-skill", history_meta={"action": "delete", "source": "test"})

    assert not link.exists() and not link.is_symlink()
    assert not storage.custom_skill_exists("linked-skill")
    _assert_external_untouched(external, "linked-skill")
    history = [json.loads(line) for line in storage.get_skill_history_file("linked-skill").read_text(encoding="utf-8").splitlines() if line]
    assert history[-1]["action"] == "delete"
    assert history[-1]["prev_content"] == _skill_content("linked-skill")


def test_user_scoped_storage_unlinks_a_symlinked_package_and_keeps_the_projection(tmp_path: Path):
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
    )
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=tmp_path)), patch("deerflow.config.paths._paths", None):
        storage = UserScopedSkillStorage("test-user", host_path=str(skills_root), app_config=config)
        storage.write_custom_skill("kept-skill", "SKILL.md", _skill_content("kept-skill"))
        external = _plant_external_package(tmp_path, "linked-skill")
        link = storage.get_user_custom_root() / "linked-skill"
        symlink_or_skip(link, external, target_is_directory=True)
        assert storage.custom_skill_exists("linked-skill")

        storage.delete_custom_skill("linked-skill")

        assert not link.exists() and not link.is_symlink()
        assert not storage.custom_skill_exists("linked-skill")
        _assert_external_untouched(external, "linked-skill")
        # The sibling skill is still there and still projected: a failed
        # mutation would have cleared the user's whole custom view.
        assert storage.custom_skill_exists("kept-skill")
        view = Paths(base_dir=tmp_path).base_dir / "users" / "test-user" / "skills_view" / "custom"
        assert (view / "kept-skill" / "SKILL.md").is_file()
        assert not (view / "linked-skill").exists()
