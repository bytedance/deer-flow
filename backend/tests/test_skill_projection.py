"""Enabled-only filesystem projections exposed to sandbox providers."""

from __future__ import annotations

import errno
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig
from deerflow.config.paths import Paths
from deerflow.skills.projection import ensure_public_skill_projection, ensure_skill_projections, rebuild_skill_projections, skill_projection_mutation
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


def test_nested_skill_frontmatter_is_supporting_data_inside_parent_package(projection_env) -> None:
    env = projection_env
    parent_root = env.skills_root / "public" / "parent-skill"
    _write_skill(env.skills_root / "public", "parent-skill")
    nested = _write_skill(parent_root / "fixtures", "nested-skill")
    env.extensions.skills["nested-skill"] = SkillStateConfig(enabled=False)

    projected = rebuild_skill_projections(env.storage)
    nested_view = projected.public / nested.parent.relative_to(env.skills_root / "public")

    assert (projected.public / "parent-skill" / "SKILL.md").is_file()
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


def test_custom_content_write_keeps_unrelated_skill_visible_during_rebuild(projection_env, monkeypatch) -> None:
    env = projection_env
    env.storage.write_custom_skill("alpha", "SKILL.md", _skill_content("alpha"))
    env.storage.write_custom_skill("beta", "SKILL.md", _skill_content("beta", "before"))
    projected = rebuild_skill_projections(env.storage)
    alpha_view = projected.custom / "alpha" / "SKILL.md"

    from deerflow.skills import projection as projection_module

    real_stage_skill = projection_module._stage_skill
    staging_started = Event()
    release_staging = Event()

    def _delayed_stage_skill(*args, **kwargs):
        if not staging_started.is_set():
            staging_started.set()
            assert release_staging.wait(timeout=5)
        return real_stage_skill(*args, **kwargs)

    monkeypatch.setattr(projection_module, "_stage_skill", _delayed_stage_skill)

    with ThreadPoolExecutor(max_workers=1) as executor:
        write_future = executor.submit(env.storage.write_custom_skill, "beta", "SKILL.md", _skill_content("beta", "after"))
        assert staging_started.wait(timeout=5)
        unrelated_skill_remained_visible = alpha_view.is_file()
        release_staging.set()
        write_future.result(timeout=5)

    assert unrelated_skill_remained_visible
    assert "after" in (projected.custom / "beta" / "SKILL.md").read_text(encoding="utf-8")


def test_per_user_toggle_removes_custom_skill_before_returning(projection_env) -> None:
    env = projection_env
    env.storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill"))
    projected = rebuild_skill_projections(env.storage)
    assert (projected.custom / "demo-skill" / "SKILL.md").is_file()

    env.storage.set_skill_enabled_state("demo-skill", False)

    assert not (projected.custom / "demo-skill").exists()


def test_managed_integration_projection_is_filtered_per_user(projection_env) -> None:
    env = projection_env
    integration_root = env.paths.integration_skills_dir()
    _write_skill(integration_root / "lark-cli", "lark-doc")

    alice_projection = rebuild_skill_projections(env.storage)
    alice_skill = alice_projection.integrations / "lark-cli" / "lark-doc" / "SKILL.md"
    assert alice_skill.is_file()

    env.storage.set_skill_enabled_state("lark-doc", False)
    assert not alice_skill.exists()

    bob_storage = UserScopedSkillStorage("bob", host_path=str(env.skills_root), app_config=env.config)
    bob_projection = rebuild_skill_projections(bob_storage)
    assert (bob_projection.integrations / "lark-cli" / "lark-doc" / "SKILL.md").is_file()


def test_disabling_custom_skill_hides_only_target_while_rebuilding(projection_env, monkeypatch) -> None:
    env = projection_env
    env.storage.write_custom_skill("alpha", "SKILL.md", _skill_content("alpha"))
    env.storage.write_custom_skill("beta", "SKILL.md", _skill_content("beta"))
    projected = rebuild_skill_projections(env.storage)

    from deerflow.skills import projection as projection_module

    real_stage_skill = projection_module._stage_skill
    staging_started = Event()
    release_staging = Event()

    def _delayed_stage_skill(*args, **kwargs):
        if not staging_started.is_set():
            staging_started.set()
            assert release_staging.wait(timeout=5)
        return real_stage_skill(*args, **kwargs)

    monkeypatch.setattr(projection_module, "_stage_skill", _delayed_stage_skill)

    with ThreadPoolExecutor(max_workers=1) as executor:
        disable_future = executor.submit(env.storage.set_skill_enabled_state, "beta", False)
        assert staging_started.wait(timeout=5)
        alpha_remained_visible = (projected.custom / "alpha" / "SKILL.md").is_file()
        beta_was_hidden = not (projected.custom / "beta").exists()
        release_staging.set()
        disable_future.result(timeout=5)

    assert alpha_remained_visible
    assert beta_was_hidden


def test_disabling_namespaced_skill_hides_its_real_projection_path(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "custom" / "team", "helper")
    projected = rebuild_skill_projections(env.storage)
    target = projected.legacy / "team" / "helper"
    assert (target / "SKILL.md").is_file()

    with skill_projection_mutation(env.storage, "user", remove_names=("helper",)):
        env.storage._write_skill_states({"helper": {"enabled": False}})
        assert not target.exists()

    assert not target.exists()


def test_disabling_duplicate_namespaced_public_skills_hides_every_path(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public" / "team-a", "helper")
    _write_skill(env.skills_root / "public" / "team-b", "helper")
    projected = rebuild_skill_projections(env.storage)
    targets = [projected.public / team / "helper" for team in ("team-a", "team-b")]
    assert all((target / "SKILL.md").is_file() for target in targets)

    with skill_projection_mutation(env.storage, "public", remove_names=("helper",)):
        env.extensions.skills["helper"] = SkillStateConfig(enabled=False)
        assert all(not target.exists() for target in targets)

    assert all(not target.exists() for target in targets)


def test_mutation_failure_clears_projection_scope(projection_env) -> None:
    env = projection_env
    env.storage.write_custom_skill("alpha", "SKILL.md", _skill_content("alpha"))
    projected = rebuild_skill_projections(env.storage)
    manifest = projected.custom.parent / ".projection-manifest.json"
    assert (projected.custom / "alpha" / "SKILL.md").is_file()

    with pytest.raises(OSError, match="mutation failed"):
        with skill_projection_mutation(env.storage, "user"):
            raise OSError("mutation failed")

    assert list(projected.custom.iterdir()) == []
    assert list(projected.legacy.iterdir()) == []
    assert list(projected.integrations.iterdir()) == []
    assert not manifest.exists()


def test_targeted_removal_failure_clears_drifted_projection_scope(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public" / "team", "helper")
    projected = rebuild_skill_projections(env.storage)
    manifest = projected.public.parent / ".projection-manifest.json"
    namespace = projected.public / "team"
    shutil.rmtree(namespace)
    namespace.write_text("drifted file", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        with skill_projection_mutation(env.storage, "public", remove_names=("helper",)):
            env.extensions.skills["helper"] = SkillStateConfig(enabled=False)

    assert list(projected.public.iterdir()) == []
    assert not manifest.exists()


def test_targeted_removal_drift_check_raises_when_underlying_unlink_swallows_error(projection_env, monkeypatch) -> None:
    """Explicit drift check raises NotADirectoryError even if underlying unlink would swallow ENOENT (Windows semantics)."""
    env = projection_env
    _write_skill(env.skills_root / "public" / "team", "helper")
    projected = rebuild_skill_projections(env.storage)
    manifest = projected.public.parent / ".projection-manifest.json"
    namespace = projected.public / "team"
    shutil.rmtree(namespace)
    namespace.write_text("drifted file", encoding="utf-8")

    from deerflow.skills import projection as projection_module

    # Simulate Windows Path.unlink(missing_ok=True) semantics where file-in-path
    # returns ENOENT and is swallowed, so underlying removal would not raise ENOTDIR.
    monkeypatch.setattr(projection_module, "_remove_projection_entry", lambda _target: None)

    with pytest.raises(NotADirectoryError, match="Projection namespace drifted to a file"):
        with skill_projection_mutation(env.storage, "public", remove_names=("helper",)):
            env.extensions.skills["helper"] = SkillStateConfig(enabled=False)

    assert list(projected.public.iterdir()) == []
    assert not manifest.exists()


def test_user_custom_skill_replaces_legacy_projection(projection_env) -> None:
    env = projection_env
    _write_skill(env.skills_root / "custom", "legacy-skill")
    projected = rebuild_skill_projections(env.storage)
    assert (projected.legacy / "legacy-skill" / "SKILL.md").is_file()

    env.storage.write_custom_skill("custom-skill", "SKILL.md", _skill_content("custom-skill"))

    assert (projected.custom / "custom-skill" / "SKILL.md").is_file()
    assert list(projected.legacy.iterdir()) == []


@pytest.mark.parametrize("category", ["custom", "legacy"])
def test_ensure_user_projection_uses_fresh_global_state_across_workers(projection_env, category: str) -> None:
    env = projection_env
    skill_name = f"{category}-skill"
    source_root = env.storage.get_user_custom_root() if category == "custom" else env.skills_root / "custom"
    _write_skill(source_root, skill_name)
    projected = rebuild_skill_projections(env.storage)
    target = getattr(projected, category) / skill_name / "SKILL.md"
    manifest = projected.custom.parent / ".projection-manifest.json"
    assert target.is_file()
    assert manifest.is_file()

    fresh_extensions = ExtensionsConfig()
    fresh_extensions.skills[skill_name] = SkillStateConfig(enabled=False)
    with patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=fresh_extensions):
        ensure_skill_projections(env.storage)
        assert not target.exists()
        assert manifest.is_file()
        rebuilt_manifest = manifest.read_text(encoding="utf-8")

        # The rebuilt manifest must not mark the stale visible view as fresh.
        ensure_skill_projections(env.storage)
        assert not target.exists()
        assert manifest.read_text(encoding="utf-8") == rebuilt_manifest


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


def test_ensure_steady_state_public_signature_checks_do_not_serialize(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "demo-skill")
    rebuild_skill_projections(env.storage)

    from deerflow.skills import projection as projection_module

    real_source_signature = projection_module._source_signature
    public_signatures = Barrier(2, timeout=2)

    def _synchronized_source_signature(storage, scope):
        if scope == "public":
            public_signatures.wait()
        return real_source_signature(storage, scope)

    monkeypatch.setattr(projection_module, "_source_signature", _synchronized_source_signature)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ensure_skill_projections, env.storage) for _ in range(2)]
        for future in futures:
            future.result(timeout=5)


def test_unlocked_public_snapshot_detects_manifest_change_during_signature_scan(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "demo-skill")
    projected = rebuild_skill_projections(env.storage)
    manifest = projected.public.parent / ".projection-manifest.json"

    from deerflow.skills import projection as projection_module

    real_source_signature = projection_module._source_signature
    signature_read = Event()
    release_signature = Event()

    def _delayed_source_signature(storage, scope):
        signature = real_source_signature(storage, scope)
        if scope == "public":
            signature_read.set()
            assert release_signature.wait(timeout=5)
        return signature

    monkeypatch.setattr(projection_module, "_source_signature", _delayed_source_signature)

    with ThreadPoolExecutor(max_workers=1) as executor:
        ensure_future = executor.submit(ensure_skill_projections, env.storage)
        assert signature_read.wait(timeout=5)
        manifest.unlink()
        release_signature.set()
        ensure_future.result(timeout=5)

    assert manifest.is_file()


def test_concurrent_stale_public_ensure_rebuilds_once_after_lock_recheck(projection_env) -> None:
    env = projection_env
    source = _write_skill(env.skills_root / "public", "demo-skill", "before")
    rebuild_skill_projections(env.storage)

    replacement = source.with_suffix(".replacement")
    replacement.write_text(_skill_content("demo-skill", "after"), encoding="utf-8")
    replacement.replace(source)

    from deerflow.skills import projection as projection_module

    with patch.object(projection_module, "_rebuild_public_locked", wraps=projection_module._rebuild_public_locked) as rebuild:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(ensure_skill_projections, [env.storage] * 8))

    assert rebuild.call_count == 1


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


def test_boot_ensures_public_projection_without_scanning_known_users(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "public-skill")
    _write_skill(env.paths.user_custom_skills_dir("bob"), "custom-skill")

    def _unexpected_user_storage(*_args, **_kwargs):
        raise AssertionError("gateway boot must not enumerate user skill storage")

    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", _unexpected_user_storage)

    assert ensure_public_skill_projection(app_config=env.config) is True

    assert (env.paths.public_skills_view_dir / "public-skill" / "SKILL.md").is_file()
    assert not env.paths.user_custom_skills_view_dir("bob").exists()

    bob_storage = UserScopedSkillStorage("bob", host_path=str(env.skills_root), app_config=env.config)
    ensure_skill_projections(bob_storage)
    assert (env.paths.user_custom_skills_view_dir("bob") / "custom-skill" / "SKILL.md").is_file()


def test_boot_public_projection_failure_is_fail_closed_without_aborting(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "public-skill", "before")
    rebuild_skill_projections(env.storage, include_user=False)
    monkeypatch.setattr(
        "deerflow.skills.projection._source_signature",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("source unavailable")),
    )

    assert ensure_public_skill_projection(app_config=env.config) is False

    assert list(env.paths.public_skills_view_dir.iterdir()) == []


def test_boot_public_storage_factory_failure_is_fail_closed_without_aborting(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "public-skill")
    rebuild_skill_projections(env.storage, include_user=False)
    monkeypatch.setattr(
        "deerflow.skills.storage.get_or_new_skill_storage",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("storage init failed")),
    )

    assert ensure_public_skill_projection(app_config=env.config) is False
    assert list(env.paths.public_skills_view_dir.iterdir()) == []


def test_boot_factory_failure_cleanup_waits_for_concurrent_public_rebuild(projection_env, monkeypatch) -> None:
    env = projection_env
    _write_skill(env.skills_root / "public", "public-skill")
    from deerflow.skills import projection as projection_module

    before_manifest = Event()
    release_rebuild = Event()
    cleanup_finished = Event()
    real_write_manifest = projection_module._write_manifest

    def _delayed_write_manifest(scope_root, signature):
        before_manifest.set()
        assert release_rebuild.wait(timeout=5)
        real_write_manifest(scope_root, signature)

    monkeypatch.setattr(projection_module, "_write_manifest", _delayed_write_manifest)
    monkeypatch.setattr(
        "deerflow.skills.storage.get_or_new_skill_storage",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("storage init failed")),
    )

    def _rebuild() -> None:
        rebuild_skill_projections(env.storage, include_user=False)

    def _fail_boot_ensure() -> None:
        assert ensure_public_skill_projection(app_config=env.config) is False
        cleanup_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rebuild_future = executor.submit(_rebuild)
        assert before_manifest.wait(timeout=5)
        cleanup_future = executor.submit(_fail_boot_ensure)
        cleanup_waited_for_rebuild = not cleanup_finished.wait(timeout=0.2)
        release_rebuild.set()
        rebuild_future.result(timeout=5)
        cleanup_future.result(timeout=5)

    assert cleanup_waited_for_rebuild
    assert list(env.paths.public_skills_view_dir.iterdir()) == []
    assert not (env.paths.public_skills_view_dir.parent / ".projection-manifest.json").exists()


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
