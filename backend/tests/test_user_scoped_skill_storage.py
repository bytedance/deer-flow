"""Tests for UserScopedSkillStorage: per-user isolation, fallback, and path safety."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.paths import Paths
from deerflow.skills.storage import reset_skill_storage, reset_user_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import SkillCategory


def _skill_content(name: str, description: str = "Demo skill") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


@pytest.fixture(autouse=True)
def _reset_storages():
    """Reset all skill storage caches between tests."""
    reset_skill_storage()
    yield
    reset_skill_storage()


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Provide a temp directory as the DeerFlow base_dir."""
    return tmp_path


@pytest.fixture
def paths(base_dir: Path) -> Paths:
    return Paths(base_dir=base_dir)


@pytest.fixture
def skills_root(base_dir: Path) -> Path:
    """Create the global skills root directory with public/ and custom/ subdirs."""
    root = base_dir / "skills"
    root.mkdir()
    (root / "public").mkdir()
    (root / "custom").mkdir()
    return root


@pytest.fixture
def config(skills_root):
    """Minimal app_config-like namespace for storage construction."""
    from types import SimpleNamespace

    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
    )


@pytest.fixture
def user_storage(base_dir: Path, skills_root, config) -> UserScopedSkillStorage:
    """Create a UserScopedSkillStorage for user 'test-user'."""
    with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
        with patch("deerflow.config.paths._paths", None):
            storage = UserScopedSkillStorage("test-user", host_path=str(skills_root), app_config=config)
    return storage


class TestPathRedirection:
    """Custom skill paths are redirected to per-user directories."""

    def test_custom_skill_dir_is_user_scoped(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        expected = base_dir / "users" / "test-user" / "skills" / "custom" / "demo-skill"
        assert user_storage.get_custom_skill_dir("demo-skill") == expected

    def test_custom_skill_file_is_user_scoped(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        expected = base_dir / "users" / "test-user" / "skills" / "custom" / "demo-skill" / "SKILL.md"
        assert user_storage.get_custom_skill_file("demo-skill") == expected

    def test_history_file_is_user_scoped(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        expected = base_dir / "users" / "test-user" / "skills" / "custom" / ".history" / "demo-skill.jsonl"
        assert user_storage.get_skill_history_file("demo-skill") == expected

    def test_public_skill_paths_still_use_global_root(self, user_storage: UserScopedSkillStorage, skills_root: Path):
        assert user_storage.get_skills_root_path() == skills_root

    def test_user_id_property(self, user_storage: UserScopedSkillStorage):
        assert user_storage.user_id == "test-user"


class TestWriteAndRead:
    """Writes go to user dir, reads from user dir when present."""

    def test_write_creates_file_in_user_dir(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        user_storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill"))
        user_file = base_dir / "users" / "test-user" / "skills" / "custom" / "demo-skill" / "SKILL.md"
        assert user_file.exists()
        assert user_file.read_text(encoding="utf-8") == _skill_content("demo-skill")

    def test_write_does_not_create_in_global_custom(self, user_storage: UserScopedSkillStorage, skills_root: Path, base_dir: Path):
        user_storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill"))
        global_file = skills_root / "custom" / "demo-skill" / "SKILL.md"
        assert not global_file.exists()

    def test_read_from_user_dir(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        user_storage.write_custom_skill("demo-skill", "SKILL.md", _skill_content("demo-skill"))
        content = user_storage.read_custom_skill("demo-skill")
        assert "demo-skill" in content

    def test_read_not_found_raises(self, user_storage: UserScopedSkillStorage):
        with pytest.raises(FileNotFoundError):
            user_storage.read_custom_skill("nonexistent")

    def test_write_makes_path_sandbox_readable(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        user_storage.write_custom_skill("demo-skill", "references/ref.md", "# ref")
        skill_dir = base_dir / "users" / "test-user" / "skills" / "custom" / "demo-skill"
        ref_dir = skill_dir / "references"
        assert stat.S_IMODE(skill_dir.stat().st_mode) & 0o055 == 0o055
        assert stat.S_IMODE(ref_dir.stat().st_mode) & 0o055 == 0o055


class TestSkillLoading:
    """Public skills from global, custom from user dir + fallback."""

    def test_public_skills_loaded_from_global(self, user_storage: UserScopedSkillStorage, skills_root: Path):
        public_dir = skills_root / "public" / "deep-research"
        public_dir.mkdir(parents=True)
        (public_dir / "SKILL.md").write_text(_skill_content("deep-research"), encoding="utf-8")

        skills = user_storage.load_skills(enabled_only=False)
        public_skills = [s for s in skills if s.category == SkillCategory.PUBLIC]
        assert len(public_skills) == 1
        assert public_skills[0].name == "deep-research"

    def test_public_skill_package_children_are_not_registered(self, user_storage: UserScopedSkillStorage, skills_root: Path):
        public_dir = skills_root / "public" / "reviewer"
        fixture_dir = public_dir / "evals" / "fixtures" / "injection"
        fixture_dir.mkdir(parents=True)
        (public_dir / "SKILL.md").write_text(_skill_content("reviewer"), encoding="utf-8")
        (fixture_dir / "SKILL.md").write_text(_skill_content("injection-example"), encoding="utf-8")

        names = {skill.name for skill in user_storage.load_skills(enabled_only=False)}

        assert names == {"reviewer"}

    def test_custom_skills_loaded_from_user_dir(self, user_storage: UserScopedSkillStorage, base_dir: Path):
        user_storage.write_custom_skill("my-skill", "SKILL.md", _skill_content("my-skill"))

        skills = user_storage.load_skills(enabled_only=False)
        custom_skills = [s for s in skills if s.category == SkillCategory.CUSTOM]
        assert len(custom_skills) == 1
        assert custom_skills[0].name == "my-skill"

    def test_fallback_to_global_custom_when_user_dir_empty(self, user_storage: UserScopedSkillStorage, skills_root: Path, base_dir: Path):
        # Put skill in global custom (NOT in user dir)
        global_dir = skills_root / "custom" / "global-skill"
        global_dir.mkdir(parents=True)
        (global_dir / "SKILL.md").write_text(_skill_content("global-skill"), encoding="utf-8")

        # User dir is empty → fallback loads from global custom as LEGACY
        skills = user_storage.load_skills(enabled_only=False)
        legacy_skills = [s for s in skills if s.category == SkillCategory.LEGACY]
        assert len(legacy_skills) == 1
        assert legacy_skills[0].name == "global-skill"

    def test_no_fallback_when_user_dir_has_content(self, user_storage: UserScopedSkillStorage, skills_root: Path, base_dir: Path):
        # Put skill in global custom
        global_dir = skills_root / "custom" / "global-skill"
        global_dir.mkdir(parents=True)
        (global_dir / "SKILL.md").write_text(_skill_content("global-skill"), encoding="utf-8")

        # Also put skill in user custom
        user_storage.write_custom_skill("user-skill", "SKILL.md", _skill_content("user-skill"))

        # User dir has content → no fallback, only user-level skill
        skills = user_storage.load_skills(enabled_only=False)
        custom_skills = [s for s in skills if s.category == SkillCategory.CUSTOM]
        assert len(custom_skills) == 1
        assert custom_skills[0].name == "user-skill"

    def test_mixed_public_and_custom(self, user_storage: UserScopedSkillStorage, skills_root: Path, base_dir: Path):
        # Create public skill
        public_dir = skills_root / "public" / "deep-research"
        public_dir.mkdir(parents=True)
        (public_dir / "SKILL.md").write_text(_skill_content("deep-research"), encoding="utf-8")

        # Create user custom skill
        user_storage.write_custom_skill("my-skill", "SKILL.md", _skill_content("my-skill"))

        skills = user_storage.load_skills(enabled_only=False)
        assert len(skills) == 2
        categories = {s.category for s in skills}
        assert categories == {SkillCategory.PUBLIC, SkillCategory.CUSTOM}


class TestIsolation:
    """Different users must see different custom skills."""

    def test_two_users_isolated(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                storage_a = UserScopedSkillStorage("alice", host_path=str(skills_root), app_config=config)
                storage_b = UserScopedSkillStorage("bob", host_path=str(skills_root), app_config=config)

                storage_a.write_custom_skill("skill-a", "SKILL.md", _skill_content("skill-a"))
                storage_b.write_custom_skill("skill-b", "SKILL.md", _skill_content("skill-b"))

                skills_a = [s for s in storage_a.load_skills(enabled_only=False) if s.category == SkillCategory.CUSTOM]
                skills_b = [s for s in storage_b.load_skills(enabled_only=False) if s.category == SkillCategory.CUSTOM]

                assert len(skills_a) == 1
                assert skills_a[0].name == "skill-a"
                assert len(skills_b) == 1
                assert skills_b[0].name == "skill-b"

    def test_delete_is_isolated(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                storage_a = UserScopedSkillStorage("alice", host_path=str(skills_root), app_config=config)
                storage_b = UserScopedSkillStorage("bob", host_path=str(skills_root), app_config=config)

                storage_a.write_custom_skill("skill-a", "SKILL.md", _skill_content("skill-a"))
                storage_b.write_custom_skill("skill-b", "SKILL.md", _skill_content("skill-b"))

                storage_a.delete_custom_skill("skill-a")

                # Alice has no custom skills, Bob still has theirs
                skills_a = [s for s in storage_a.load_skills(enabled_only=False) if s.category == SkillCategory.CUSTOM]
                skills_b = [s for s in storage_b.load_skills(enabled_only=False) if s.category == SkillCategory.CUSTOM]

                assert len(skills_a) == 0
                assert len(skills_b) == 1


class TestHistoryIsolation:
    """History files are per-user."""

    def test_history_per_user(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                storage_a = UserScopedSkillStorage("alice", host_path=str(skills_root), app_config=config)
                storage_a.write_custom_skill("shared-name", "SKILL.md", _skill_content("shared-name"))

                storage_a.append_history("shared-name", {"action": "create", "author": "alice"})

                history_file_a = base_dir / "users" / "alice" / "skills" / "custom" / ".history" / "shared-name.jsonl"
                assert history_file_a.exists()

    def test_history_does_not_leak_to_global(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                storage = UserScopedSkillStorage("alice", host_path=str(skills_root), app_config=config)
                storage.write_custom_skill("my-skill", "SKILL.md", _skill_content("my-skill"))
                storage.append_history("my-skill", {"action": "create"})

                global_history = skills_root / "custom" / ".history" / "my-skill.jsonl"
                assert not global_history.exists()


class TestPathSafety:
    """UserScopedSkillStorage inherits path-traversal guards from LocalSkillStorage."""

    def test_rejects_invalid_skill_name(self, user_storage: UserScopedSkillStorage):
        with pytest.raises(ValueError, match="hyphen-case"):
            user_storage.get_custom_skill_dir("../../escaped")

    def test_rejects_path_traversal_in_write(self, user_storage: UserScopedSkillStorage):
        with pytest.raises(ValueError, match="skill directory"):
            user_storage.write_custom_skill("demo-skill", "../../escaped.txt", "x")

    def test_rejects_empty_path_in_write(self, user_storage: UserScopedSkillStorage):
        with pytest.raises(ValueError, match="empty"):
            user_storage.write_custom_skill("demo-skill", "", "x")


class TestFactory:
    """get_or_new_user_skill_storage factory behavior."""

    def test_returns_same_instance_for_same_user(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                from deerflow.skills.storage import get_or_new_user_skill_storage

                s1 = get_or_new_user_skill_storage("alice", app_config=config)
                s2 = get_or_new_user_skill_storage("alice", app_config=config)
                assert s1 is s2

    def test_returns_different_instance_for_different_user(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                from deerflow.skills.storage import get_or_new_user_skill_storage

                s1 = get_or_new_user_skill_storage("alice", app_config=config)
                s2 = get_or_new_user_skill_storage("bob", app_config=config)
                assert s1 is not s2

    def test_reset_clears_specific_user(self, base_dir: Path, skills_root, config):
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                from deerflow.skills.storage import get_or_new_user_skill_storage

                s_alice = get_or_new_user_skill_storage("alice", app_config=config)
                s_bob = get_or_new_user_skill_storage("bob", app_config=config)

                reset_user_skill_storage("alice")

                # Alice's storage is gone; a new one is created
                s_alice_new = get_or_new_user_skill_storage("alice", app_config=config)
                assert s_alice_new is not s_alice

                # Bob's storage is still cached
                s_bob_cached = get_or_new_user_skill_storage("bob", app_config=config)
                assert s_bob_cached is s_bob


class TestSkillToggleIsolation:
    """Per-user enabled/disabled state isolation for same-named custom skills.

    When Alice and Bob each own a custom skill named 'report-gen', disabling
    Alice's copy must NOT affect Bob's.  The enabled state is stored in
    per-user ``_skill_states.json`` so same-named skills can be toggled
    independently across users.
    """

    def test_alice_disable_does_not_affect_bob(self, base_dir: Path, skills_root, config):
        from types import SimpleNamespace

        from deerflow.agents.lead_agent.prompt import clear_skills_system_prompt_cache, get_skills_prompt_section
        from deerflow.sandbox.tools import _is_disabled_skill_path
        from deerflow.skills.storage import get_or_new_user_skill_storage

        # Rich config that includes skill_evolution (required by
        # get_skills_prompt_section) while keeping the test skills root.
        rich_config = SimpleNamespace(
            skills=config.skills,
            skill_evolution=SimpleNamespace(enabled=False),
        )

        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base_dir)):
            with patch("deerflow.config.paths._paths", None):
                with patch("deerflow.config.get_app_config", return_value=rich_config):
                    # Use the factory so storages enter the cache — both
                    # _is_disabled_skill_path and get_skills_prompt_section
                    # call the factory internally.
                    storage_alice = get_or_new_user_skill_storage("alice", app_config=rich_config)
                    storage_bob = get_or_new_user_skill_storage("bob", app_config=rich_config)

                    # 1. Two users each create a custom skill named "report-gen"
                    storage_alice.write_custom_skill("report-gen", "SKILL.md", _skill_content("report-gen", "Alice report generator"))
                    storage_bob.write_custom_skill("report-gen", "SKILL.md", _skill_content("report-gen", "Bob report generator"))

                    # 2. Alice disables her "report-gen"
                    storage_alice.set_skill_enabled_state("report-gen", False)

                    # 3. Bob's "report-gen" stays enabled in load_skills()
                    bob_skills = storage_bob.load_skills(enabled_only=False)
                    bob_report = [s for s in bob_skills if s.name == "report-gen" and s.category == SkillCategory.CUSTOM]
                    assert len(bob_report) == 1
                    assert bob_report[0].enabled is True

                    # Complementary: Alice's "report-gen" is disabled
                    alice_skills = storage_alice.load_skills(enabled_only=False)
                    alice_report = [s for s in alice_skills if s.name == "report-gen" and s.category == SkillCategory.CUSTOM]
                    assert len(alice_report) == 1
                    assert alice_report[0].enabled is False

                    # enabled_only=True filtering is also isolated
                    bob_enabled = storage_bob.load_skills(enabled_only=True)
                    assert any(s.name == "report-gen" for s in bob_enabled)

                    alice_enabled = storage_alice.load_skills(enabled_only=True)
                    assert not any(s.name == "report-gen" for s in alice_enabled)

                    # 4. Bob's skill still appears in the prompt section
                    clear_skills_system_prompt_cache()
                    prompt = get_skills_prompt_section(user_id="bob", app_config=rich_config)
                    assert "report-gen" in prompt

                    # 5. _is_disabled_skill_path returns False for Bob's skill path
                    assert _is_disabled_skill_path("/mnt/skills/custom/report-gen/SKILL.md", user_id="bob") is False

                    # Complementary: Alice's skill path IS disabled
                    assert _is_disabled_skill_path("/mnt/skills/custom/report-gen/SKILL.md", user_id="alice") is True


class TestSkillStateAtomicWrite:
    """P2-2: ``_write_skill_states`` must be atomic so a crash mid-write
    cannot silently re-enable every skill the user had disabled.
    """

    def test_writes_via_tempfile_then_replace(self, user_storage: UserScopedSkillStorage, base_dir: Path) -> None:
        states = {"report-gen": {"enabled": False}}
        user_storage._write_skill_states(states)

        target = user_storage._skill_states_file
        assert target.exists()
        # No leftover .tmp files in the directory.
        leftovers = [p for p in base_dir.glob("users/*/skills/.skill_states_*.json.tmp") if p.exists()]
        assert not leftovers, f"temp file left behind: {leftovers}"
        import json as _json

        assert _json.loads(target.read_text(encoding="utf-8")) == states

    def test_failed_write_does_not_truncate_existing_file(self, user_storage: UserScopedSkillStorage) -> None:
        import json as _json

        # Seed a valid state file.
        target = user_storage._skill_states_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_json.dumps({"old-skill": {"enabled": False}}), encoding="utf-8")

        # Force the inner write to fail; ensure the existing file is intact.
        with patch("pathlib.Path.replace", side_effect=OSError("boom")):
            with pytest.raises(OSError):
                user_storage._write_skill_states({"new-skill": {"enabled": True}})

        # Pre-existing content must survive the failed replacement.
        assert target.exists()
        assert _json.loads(target.read_text(encoding="utf-8")) == {"old-skill": {"enabled": False}}

        # And no orphan temp file should be left around in the user skills dir.
        leftovers = list(target.parent.glob(".skill_states_*.json.tmp"))
        assert not leftovers, f"temp file leaked: {leftovers}"


class TestSkillStateFailClosed:
    """P1-2: ``_is_disabled_skill_path`` must fail CLOSED (return True)
    when the enabled state cannot be determined, so a corrupt
    ``_skill_states.json`` or mid-write race never lets the agent read a
    disabled skill's files.
    """

    def test_returns_true_when_state_lookup_raises(self) -> None:
        from deerflow.sandbox.tools import _is_disabled_skill_path

        def _boom(_skill_name: str) -> bool:
            raise OSError("storage unavailable")

        with patch("deerflow.skills.storage.user_scoped_skill_storage.UserScopedSkillStorage.get_skill_enabled_state", side_effect=_boom):
            assert _is_disabled_skill_path("/mnt/skills/custom/report-gen/SKILL.md", user_id="default") is True

    def test_returns_true_when_public_extensions_config_raises(self) -> None:
        from deerflow.sandbox.tools import _is_disabled_skill_path

        def _boom() -> bool:
            raise OSError("extensions_config.json unreadable")

        with patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", side_effect=_boom):
            assert _is_disabled_skill_path("/mnt/skills/public/bootstrap/SKILL.md", user_id="default") is True


class TestSkillLoadingRespectsGlobalDisable:
    """P2-1: when the global ``extensions_config.json`` disables a
    CUSTOM/LEGACY skill, ``load_skills`` must still report it as
    disabled even if the per-user state has no entry (defaulting to
    enabled otherwise). Without the AND, an admin's global "off" for a
    shared skill would be silently flipped to "on" the moment a new
    user touches the per-user storage.
    """

    def test_global_disable_wins_when_per_user_state_missing(self, tmp_path: Path) -> None:
        from types import SimpleNamespace

        from deerflow.config.paths import Paths
        from deerflow.skills.storage import get_or_new_user_skill_storage
        from deerflow.skills.types import SkillCategory

        base = tmp_path
        skills_root = base / "skills"
        skills_root.mkdir()
        (skills_root / "custom").mkdir()
        (skills_root / "custom" / "shared-skill").mkdir()
        (skills_root / "custom" / "shared-skill" / "SKILL.md").write_text(
            _skill_content("shared-skill"),
            encoding="utf-8",
        )

        # Per-user state is empty (no per-user override for "shared-skill").
        with patch("deerflow.config.paths.get_paths", return_value=Paths(base_dir=base)):
            with patch("deerflow.config.paths._paths", None):
                cfg = SimpleNamespace(
                    skills=SimpleNamespace(
                        get_skills_path=lambda: skills_root,
                        container_path="/mnt/skills",
                        use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
                    ),
                )
                with patch("deerflow.config.get_app_config", return_value=cfg):
                    # Global extensions_config reports the shared skill as disabled.
                    ext_cfg = SimpleNamespace(
                        skills={"shared-skill": SimpleNamespace(enabled=False)},
                        is_skill_enabled=lambda name, _cat: not (name == "shared-skill"),
                    )
                    # The function inside ``load_skills`` does a
                    # function-local ``from deerflow.config.extensions_config
                    # import get_extensions_config``, so patch the
                    # extension_config module symbol.
                    with patch("deerflow.config.extensions_config.get_extensions_config", return_value=ext_cfg):
                        storage = get_or_new_user_skill_storage("alice", app_config=cfg)
                        loaded = storage.load_skills(enabled_only=False)
                        shared = [s for s in loaded if s.name == "shared-skill" and s.category == SkillCategory.LEGACY]
                        assert len(shared) == 1
                        # AND-merge: per-user default True AND global False → False
                        assert shared[0].enabled is False


class TestEnabledSkillsByConfigCacheBounded:
    """P2-4: ``_enabled_skills_by_config_cache`` must be bounded so a
    long-running process cannot leak one entry per distinct
    (app_config, user_id) pair ever seen.
    """

    def test_evicts_least_recently_used_above_maxsize(self, monkeypatch) -> None:
        from collections import OrderedDict

        from deerflow.agents.lead_agent import prompt as prompt_module

        # Shrink the cap so the test stays fast.
        monkeypatch.setattr(prompt_module, "_ENABLED_SKILLS_BY_CONFIG_CACHE_MAXSIZE", 4)
        prompt_module._enabled_skills_by_config_cache = OrderedDict()

        class FakeConfig:
            def __init__(self, name: str) -> None:
                self.name = name

        class FakeStorage:
            def __init__(self) -> None:
                self.load_calls = 0

            def load_skills(self, *, enabled_only: bool = False):
                self.load_calls += 1
                return []

        configs = [FakeConfig(f"cfg-{i}") for i in range(6)]
        storages = [FakeStorage() for _ in range(6)]
        # Index by cfg id so the lookups below are deterministic.
        cfg_to_storage = {id(c): s for c, s in zip(configs, storages)}

        def _user_storage(user_id, *, app_config=None):
            return cfg_to_storage[id(app_config)]

        def _global_storage(*, app_config=None):
            return cfg_to_storage[id(app_config)]

        # Patch the *already-imported* references inside the prompt
        # module. ``from ... import`` binds the name at import time, so
        # patching the storage module has no effect.
        with patch.object(prompt_module, "get_or_new_user_skill_storage", side_effect=_user_storage), patch.object(prompt_module, "get_or_new_skill_storage", side_effect=_global_storage):
            for i, cfg in enumerate(configs):
                prompt_module.get_enabled_skills_for_config(app_config=cfg, user_id=f"user-{i}")

        # After 6 distinct (cfg, user) inserts with a cap of 4, the cache
        # must hold exactly the 4 most-recently-touched entries.
        assert len(prompt_module._enabled_skills_by_config_cache) == 4
        kept_keys = set(prompt_module._enabled_skills_by_config_cache.keys())
        # The two oldest (cfg-0/user-0, cfg-1/user-1) should have been evicted.
        assert (id(configs[0]), "user-0") not in kept_keys
        assert (id(configs[1]), "user-1") not in kept_keys
        # And the four newest must still be there.
        for i in range(2, 6):
            assert (id(configs[i]), f"user-{i}") in kept_keys

        # Touching an older key bumps it to MRU. ``configs[0]`` is no
        # longer in the cache, so this re-loads it; this also re-loads
        # ``storages[0]`` from disk (so its load_calls goes from 0 to 1).
        with patch.object(prompt_module, "get_or_new_user_skill_storage", side_effect=_user_storage), patch.object(prompt_module, "get_or_new_skill_storage", side_effect=_global_storage):
            prompt_module.get_enabled_skills_for_config(app_config=configs[0], user_id="user-0")
        # Now configs[0] is MRU. Insert a new (cfg-new, user-new) entry:
        # the LRU is configs[2] and must be evicted.
        new_cfg = FakeConfig("cfg-new")
        new_storage = FakeStorage()
        cfg_to_storage[id(new_cfg)] = new_storage
        with patch.object(prompt_module, "get_or_new_user_skill_storage", side_effect=_user_storage), patch.object(prompt_module, "get_or_new_skill_storage", side_effect=_global_storage):
            prompt_module.get_enabled_skills_for_config(app_config=new_cfg, user_id="user-new")

        kept = set(prompt_module._enabled_skills_by_config_cache.keys())
        assert (id(configs[0]), "user-0") in kept, "MRU touch should keep configs[0]"
        assert (id(new_cfg), "user-new") in kept
        assert (id(configs[2]), "user-2") not in kept, "LRU should have been evicted"
        assert len(prompt_module._enabled_skills_by_config_cache) == 4
