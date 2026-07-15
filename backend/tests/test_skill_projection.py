"""Enabled-only filesystem projections exposed to sandbox providers."""

from __future__ import annotations

import errno
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig
from deerflow.config.paths import Paths
from deerflow.skills.projection import ensure_skill_projections, rebuild_all_skill_projections, rebuild_skill_projections
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


def _skill_content(name: str, marker: str = "v1") -> str:
    return f"---\nname: {name}\ndescription: {marker}\n---\n\n# {name}\n\n{marker}\n"


def _write_skill(root: Path, name: str, marker: str = "v1") -> Path:
    target = root / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_skill_content(name, marker), encoding="utf-8")
    return target


@pytest.fixture
def projection_env(tmp_path: Path):
    skills_root = tmp_path / "skills"
    (skills_root / "public").mkdir(parents=True)
    (skills_root / "custom").mkdir()
    paths = Paths(base_dir=tmp_path)
    config = SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )
    extensions = ExtensionsConfig()

    with (
        patch("deerflow.config.paths.get_paths", return_value=paths),
        patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=extensions),
        patch("deerflow.config.extensions_config.get_extensions_config", return_value=extensions),
    ):
        storage = UserScopedSkillStorage("alice", host_path=str(skills_root), app_config=config)
        yield SimpleNamespace(
            root=tmp_path,
            skills_root=skills_root,
            paths=paths,
            config=config,
            extensions=extensions,
            storage=storage,
        )


def test_projection_contains_only_enabled_skills(projection_env) -> None:
    env = projection_env
    enabled = _write_skill(env.skills_root / "public", "enabled-skill")
    _write_skill(env.skills_root / "public", "disabled-skill")
    env.extensions.skills["disabled-skill"] = SkillStateConfig(enabled=False)

    projected = rebuild_skill_projections(env.storage)

    enabled_view = projected.public / "enabled-skill" / "SKILL.md"
    assert enabled_view.read_text(encoding="utf-8") == enabled.read_text(encoding="utf-8")
    assert not (projected.public / "disabled-skill").exists()


def test_projection_rebuild_removes_newly_disabled_skill(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "demo-skill")
    projected = rebuild_skill_projections(env.storage)
    assert (projected.public / "demo-skill" / "SKILL.md").is_file()

    env.extensions.skills["demo-skill"] = SkillStateConfig(enabled=False)
    rebuild_skill_projections(env.storage)

    assert not (projected.public / "demo-skill").exists()


def test_disabled_nested_skill_is_not_copied_with_enabled_parent(projection_env) -> None:
    env = projection_env
    parent_root = env.skills_root / "public" / "parent-skill"
    _write_skill(env.skills_root / "public", "parent-skill")
    nested = _write_skill(parent_root / "fixtures", "nested-skill")
    env.extensions.skills["nested-skill"] = SkillStateConfig(enabled=False)

    projected = rebuild_skill_projections(env.storage)
    nested_view = projected.public / nested.parent.relative_to(env.skills_root / "public")

    assert (projected.public / "parent-skill" / "SKILL.md").is_file()
    assert not nested_view.exists()

    env.extensions.skills["nested-skill"] = SkillStateConfig(enabled=True)
    rebuild_skill_projections(env.storage)
    assert (nested_view / "SKILL.md").is_file()


def test_projection_falls_back_to_copy_when_hardlink_is_unavailable(projection_env, monkeypatch) -> None:
    env = projection_env
    source = _write_skill(env.skills_root / "public", "demo-skill")

    def _cross_device_link(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr("deerflow.skills.projection.os.link", _cross_device_link)
    projected = rebuild_skill_projections(env.storage)
    target = projected.public / "demo-skill" / "SKILL.md"

    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert target.stat().st_ino != source.stat().st_ino


def test_atomic_custom_skill_rewrite_refreshes_projection(projection_env) -> None:
    env = projection_env
    env.storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill", "before"))
    projected = rebuild_skill_projections(env.storage)
    target = projected.custom / "demo-skill" / "SKILL.md"
    old_inode = target.stat().st_ino

    env.storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill", "after"))

    assert "after" in target.read_text(encoding="utf-8")
    assert target.stat().st_ino != old_inode


def test_per_user_toggle_removes_custom_skill_before_returning(projection_env) -> None:
    env = projection_env
    env.storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill"))
    projected = rebuild_skill_projections(env.storage)
    assert (projected.custom / "demo-skill" / "SKILL.md").is_file()

    env.storage.set_skill_enabled_state("demo-skill", False)

    assert not (projected.custom / "demo-skill").exists()


def test_user_custom_skill_replaces_legacy_projection(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "custom", "legacy-skill")
    projected = rebuild_skill_projections(env.storage)
    assert (projected.legacy / "legacy-skill" / "SKILL.md").is_file()

    env.storage.write_custom_skill("custom-skill", "SKILL.md", _skill_content("custom-skill"))

    assert (projected.custom / "custom-skill" / "SKILL.md").is_file()
    assert list(projected.legacy.iterdir()) == []


def test_ensure_repairs_direct_atomic_source_replacement(projection_env) -> None:
    env = projection_env
    source = _write_skill(env.skills_root / "public", "demo-skill", "before")
    projected = rebuild_skill_projections(env.storage)
    target = projected.public / "demo-skill" / "SKILL.md"
    old_projected_inode = target.stat().st_ino

    replacement = source.with_suffix(".replacement")
    replacement.write_text(_skill_content("demo-skill", "after"), encoding="utf-8")
    replacement.replace(source)
    ensure_skill_projections(env.storage)

    assert "after" in target.read_text(encoding="utf-8")
    assert target.stat().st_ino != old_projected_inode


def test_ensure_without_source_changes_keeps_projected_inode(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "demo-skill")
    projected = rebuild_skill_projections(env.storage)
    target = projected.public / "demo-skill" / "SKILL.md"
    projected_inode = target.stat().st_ino

    ensure_skill_projections(env.storage)

    assert target.stat().st_ino == projected_inode


def test_rebuild_keeps_category_root_inode_stable(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "demo-skill")
    projected = rebuild_skill_projections(env.storage)
    root_inode = projected.public.stat().st_ino

    env.extensions.skills["demo-skill"] = SkillStateConfig(enabled=False)
    rebuild_skill_projections(env.storage)

    assert projected.public.stat().st_ino == root_inode


def test_rebuild_failure_clears_old_projection(projection_env, monkeypatch) -> None:
    env = projection_env
    source = _write_skill(env.skills_root / "public", "demo-skill", "before")
    projected = rebuild_skill_projections(env.storage)
    assert (projected.public / "demo-skill" / "SKILL.md").is_file()

    replacement = source.with_suffix(".replacement")
    replacement.write_text(_skill_content("demo-skill", "after"), encoding="utf-8")
    replacement.replace(source)
    monkeypatch.setattr("deerflow.skills.projection._stage_skill", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        ensure_skill_projections(env.storage)

    assert list(projected.public.iterdir()) == []


def test_signature_failure_clears_old_projection_and_manifest(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "demo-skill")
    projected = rebuild_skill_projections(env.storage)
    manifest = projected.public.parent / ".projection-manifest.json"
    assert (projected.public / "demo-skill" / "SKILL.md").is_file()
    assert manifest.is_file()

    monkeypatch.setattr(
        "deerflow.skills.projection._source_signature",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("source metadata unavailable")),
    )

    with pytest.raises(PermissionError, match="source metadata unavailable"):
        ensure_skill_projections(env.storage)

    assert list(projected.public.iterdir()) == []
    assert not manifest.exists()


def test_boot_rebuild_restores_public_and_known_user_views(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "public-skill")
    _write_skill(env.paths.user_custom_skills_dir("bob"), "custom-skill")

    rebuilt_users = rebuild_all_skill_projections(app_config=env.config)

    assert rebuilt_users == 1
    assert (env.paths.public_skills_view_dir / "public-skill" / "SKILL.md").is_file()
    assert (env.paths.user_custom_skills_view_dir("bob") / "custom-skill" / "SKILL.md").is_file()


def test_boot_rebuild_isolates_one_users_failure_from_the_rest(projection_env, monkeypatch) -> None:
    """A broken user directory (bad permissions, corrupted state file, ...)
    must fail closed for that user's scope only — not abort gateway boot for
    public skills or for other users' projections."""
    env = projection_env
    _write_skill(env.skills_root / "public", "public-skill")
    _write_skill(env.paths.user_custom_skills_dir("alice-broken"), "alice-skill")
    _write_skill(env.paths.user_custom_skills_dir("bob-ok"), "bob-skill")

    from deerflow.skills import projection as projection_module

    real_rebuild = projection_module.rebuild_skill_projections

    def _flaky_rebuild(storage, **kwargs):
        if getattr(storage, "user_id", None) == "alice-broken":
            raise OSError("simulated disk failure for alice-broken")
        return real_rebuild(storage, **kwargs)

    monkeypatch.setattr(projection_module, "rebuild_skill_projections", _flaky_rebuild)

    rebuilt_users = rebuild_all_skill_projections(app_config=env.config)

    assert rebuilt_users == 1
    assert (env.paths.public_skills_view_dir / "public-skill" / "SKILL.md").is_file()
    assert (env.paths.user_custom_skills_view_dir("bob-ok") / "bob-skill" / "SKILL.md").is_file()
    assert not env.paths.user_custom_skills_view_dir("alice-broken").exists() or list(env.paths.user_custom_skills_view_dir("alice-broken").iterdir()) == []


@pytest.mark.anyio
async def test_archive_install_is_projected_before_return(projection_env, monkeypatch, tmp_path) -> None:
    from deerflow.skills.security_scanner import ScanResult

    env = projection_env
    archive = tmp_path / "archive-skill.skill"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("archive-skill/SKILL.md", _skill_content("archive-skill"))
        bundle.writestr("archive-skill/references/guide.md", "# Guide\n")

    async def _allow_scan(*_args, **_kwargs):
        return ScanResult(decision="allow", reason="test")

    monkeypatch.setattr("deerflow.skills.installer.scan_skill_content", _allow_scan)

    result = await env.storage.ainstall_skill_from_archive(archive)

    projected = env.paths.user_custom_skills_view_dir("alice") / "archive-skill"
    assert result["success"] is True
    assert (projected / "SKILL.md").is_file()
    assert (projected / "references" / "guide.md").read_text(encoding="utf-8") == "# Guide\n"


def test_concurrent_custom_skill_writes_do_not_lose_projected_entries(projection_env) -> None:
    env = projection_env
    names = [f"skill-{index}" for index in range(8)]

    def _write(name: str) -> None:
        env.storage.write_custom_skill(name, "SKILL.md", _skill_content(name))

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(_write, names))

    projected_names = {path.name for path in env.paths.user_custom_skills_view_dir("alice").iterdir()}
    assert projected_names == set(names)


def test_concurrent_custom_skill_toggles_do_not_lose_state(projection_env) -> None:
    env = projection_env
    names = ("skill-a", "skill-b")
    for name in names:
        env.storage.write_custom_skill(name, "SKILL.md", _skill_content(name))

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda name: env.storage.set_skill_enabled_state(name, False), names))

    assert env.storage._read_skill_states() == {
        "skill-a": {"enabled": False},
        "skill-b": {"enabled": False},
    }
    assert list(env.paths.user_custom_skills_view_dir("alice").iterdir()) == []
