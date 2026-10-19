"""Skill discovery must follow useful links without revisiting ancestors."""

from pathlib import Path

import pytest
from support.symlinks import symlink_or_skip

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


@pytest.fixture(params=[(kind, category) for kind in ("local", "user") for category in ("public", "custom", "integrations", "legacy")])
def storage_and_root(request, tmp_path, monkeypatch):
    kind, category = request.param
    host = tmp_path / "skills"
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path / "data"))
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: ExtensionsConfig())
    if kind == "local":
        storage = LocalSkillStorage(host_path=str(host))
        root = host / category
    else:
        storage = UserScopedSkillStorage("test-user", host_path=str(host))
        root = {
            "public": host / "public",
            "custom": storage._user_custom_root,
            "integrations": storage._integrations_root,
            "legacy": storage._global_custom_root,
        }[category]
    root.mkdir(parents=True)

    # Keep regressions deterministic and bounded, even on the unfixed scanner.
    # This delegates every entry and pruning decision to the real os.walk.
    import os

    real_walk = os.walk

    def bounded_walk(*args, **kwargs):
        for index, entry in enumerate(real_walk(*args, **kwargs)):
            assert index < 32, "skill discovery keeps revisiting a cyclic directory"
            yield entry

    monkeypatch.setattr(os, "walk", bounded_walk)
    return storage, root


def _write_skill(path: Path, name: str):
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Discovery regression\n---\n", encoding="utf-8")


@pytest.mark.parametrize("cycle", ["self", "ancestor", "branching"])
def test_load_skills_prunes_ancestor_cycles(storage_and_root, cycle):
    storage, root = storage_and_root
    namespace = root / "team"
    _write_skill(namespace / "helper", "helper")
    target = namespace if cycle == "self" else root
    symlink_or_skip(namespace / "a-loop", target, target_is_directory=True)
    if cycle == "branching":
        symlink_or_skip(namespace / "b-loop", target, target_is_directory=True)

    skills = storage.load_skills()

    assert [skill.name for skill in skills] == ["helper"]
    assert skills[0].relative_path == Path("team/helper")


def test_discovery_preserves_external_aliases_and_package_boundaries(storage_and_root, tmp_path):
    storage, root = storage_and_root
    external = tmp_path / "operator-skills"
    _write_skill(external / "helper", "helper")
    _write_skill(external / "helper" / "evals" / "nested", "not-a-runtime-skill")
    _write_skill(external / ".hidden", "hidden-skill")
    for alias in ("a-linked", "b-linked"):
        symlink_or_skip(root / alias, external, target_is_directory=True)

    files = [path.relative_to(category_root) for _, category_root, path in storage._iter_skill_files()]

    assert files == [Path("a-linked/helper/SKILL.md"), Path("b-linked/helper/SKILL.md")]
    assert [skill.name for skill in storage.load_skills()] == ["helper"]


def test_cycles_inside_external_namespaces_do_not_hide_aliases(storage_and_root, tmp_path):
    storage, root = storage_and_root
    external = tmp_path / "operator-skills"
    _write_skill(external / "helper", "helper")
    symlink_or_skip(external / "loop", external, target_is_directory=True)
    for alias in ("a-linked", "b-linked"):
        symlink_or_skip(root / alias, external, target_is_directory=True)

    files = [path.relative_to(category_root) for _, category_root, path in storage._iter_skill_files()]

    assert files == [Path("a-linked/helper/SKILL.md"), Path("b-linked/helper/SKILL.md")]
