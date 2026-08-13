"""End-to-end tests for enabled-only skill mounts across sandbox providers.

Verifies that public, per-user custom, legacy global-custom, and managed
integration skills all resolve to correct container paths that the sandbox
providers actually mount — covering ``LocalSandboxProvider`` and
``AioSandboxProvider`` (DooD / local-backend path).

Includes a full-pipeline test that exercises the actual path the model
takes: ``UserScopedSkillStorage`` category assignment → ``Skill.get_container_file_path()`` → ``sandbox.read_file()``.
"""

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig
from deerflow.config.paths import Paths
from deerflow.sandbox.local.local_sandbox import PathMapping
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider
from deerflow.sandbox.tools import read_file_tool
from deerflow.skills.projection import rebuild_skill_projections
from deerflow.skills.storage import reset_user_skill_storage
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow.skills.types import SKILL_MD_FILE, Skill, SkillCategory

_AIO_MODULE = "deerflow.community.aio_sandbox.aio_sandbox_provider"
_AIO_GET_CONFIG = f"{_AIO_MODULE}.get_app_config"


def _write_skill(base: Path, name: str, description: str = "test skill") -> Path:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / SKILL_MD_FILE
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_md


def _build_config(skills_root: Path):
    from deerflow.config.sandbox_config import SandboxConfig

    return SimpleNamespace(
        skills=SimpleNamespace(
            container_path="/mnt/skills",
            get_skills_path=lambda sk=skills_root: sk,
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        ),
        sandbox=SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            mounts=[],
        ),
    )


def _local_mounts(provider: LocalSandboxProvider, thread_id: str, user_id: str) -> dict[str, PathMapping]:
    mappings = list(provider._path_mappings) + provider._build_thread_path_mappings(thread_id, user_id=user_id)
    return {m.container_path: m for m in mappings}


@pytest.fixture
def skills_fs(tmp_path: Path) -> dict:
    root = tmp_path / "skills"
    pub = root / "public"
    legacy = root / "custom"
    users_dir = tmp_path / "users"
    user_custom = users_dir / "user-1" / "skills" / "custom"
    integrations = tmp_path / "integrations" / "skills" / "demo-provider"

    return {
        "root": root,
        "public": pub,
        "legacy_global": legacy,
        "user_custom": user_custom,
        "users_dir": users_dir,
        "pub_skill": _write_skill(pub, "pub-skill", "public skill"),
        "legacy_skill": _write_skill(legacy, "leg-skill", "legacy skill"),
        "user_skill": _write_skill(user_custom, "usr-skill", "user custom skill"),
        "integration_skill": _write_skill(integrations, "int-skill", "integration skill"),
    }


@pytest.fixture
def aio_mod():
    return importlib.import_module(_AIO_MODULE)


class TestThreeWayMountEndToEnd:
    # ── LocalSandboxProvider: mount structure ──────────────────────────

    def test_local_public_skill_mounted(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            idx = _local_mounts(provider, "thread-1", user_id="user-1")
        assert "/mnt/skills/public" in idx
        assert idx["/mnt/skills/public"].read_only is True
        assert Path(idx["/mnt/skills/public"].local_path) == paths.public_skills_view_dir

    def test_local_acquire_recovers_public_mount_after_initial_projection_failure(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        projection = SimpleNamespace(
            public=paths.public_skills_view_dir,
            custom=paths.user_custom_skills_view_dir("user-1"),
            legacy=paths.user_legacy_skills_view_dir("user-1"),
            integrations=paths.user_integration_skills_view_dir("user-1"),
        )
        for root in (projection.public, projection.custom, projection.legacy, projection.integrations):
            root.mkdir(parents=True, exist_ok=True)

        with (
            patch("deerflow.config.get_app_config", return_value=cfg),
            patch("deerflow.config.paths.get_paths", return_value=paths),
            patch.object(LocalSandboxProvider, "_ensure_skills_projection", side_effect=[OSError("transient"), projection]),
        ):
            provider = LocalSandboxProvider()
            sandbox_id = provider.acquire("thread-1", user_id="user-1")
            sandbox = provider.get(sandbox_id)

        mappings = {mapping.container_path: mapping for mapping in sandbox.path_mappings}
        assert Path(mappings["/mnt/skills/public"].local_path) == projection.public
        assert mappings["/mnt/skills/public"].read_only is True

    def test_local_per_user_custom_skill_mounted(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            idx = _local_mounts(provider, "thread-1", user_id="user-1")
        assert "/mnt/skills/custom" in idx
        assert Path(idx["/mnt/skills/custom"].local_path) == paths.user_custom_skills_view_dir("user-1")

    def test_local_managed_integrations_use_per_user_projection(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            idx = _local_mounts(provider, "thread-1", user_id="user-1")
        assert "/mnt/skills/integrations" in idx
        assert Path(idx["/mnt/skills/integrations"].local_path) == paths.user_integration_skills_view_dir("user-1")
        assert idx["/mnt/skills/integrations"].read_only is True

    def test_local_legacy_mounted_for_user_without_custom(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            idx = _local_mounts(provider, "thread-1", user_id="noob")
        assert "/mnt/skills/legacy" in idx
        assert Path(idx["/mnt/skills/legacy"].local_path) == paths.user_legacy_skills_view_dir("noob")

    def test_local_legacy_not_mounted_when_user_has_custom(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            idx = _local_mounts(provider, "thread-1", user_id="user-1")
        assert "/mnt/skills/legacy" in idx
        assert list(Path(idx["/mnt/skills/legacy"].local_path).iterdir()) == []

    def test_local_legacy_still_mounted_when_user_has_only_non_skill_subdir(self, skills_fs):
        (skills_fs["users_dir"] / "ghost" / "skills" / "custom" / "dangling-dir").mkdir(parents=True, exist_ok=True)
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            idx = _local_mounts(provider, "thread-1", user_id="ghost")
        assert "/mnt/skills/legacy" in idx

    # ── LocalSandboxProvider: read_file on container paths ─────────────

    def test_local_read_file_resolves_public_and_custom(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            sid = provider.acquire("thread-1", user_id="user-1")
        sandbox = provider.get(sid)
        assert "pub-skill" in sandbox.read_file("/mnt/skills/public/pub-skill/SKILL.md")
        assert "usr-skill" in sandbox.read_file("/mnt/skills/custom/usr-skill/SKILL.md")

    def test_local_read_file_resolves_legacy_skill(self, skills_fs):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            sid = provider.acquire("thread-1", user_id="noob")
        sandbox = provider.get(sid)
        assert "leg-skill" in sandbox.read_file("/mnt/skills/legacy/leg-skill/SKILL.md")

    def test_read_file_tool_uses_enabled_projection_for_every_skill_category(self, skills_fs, monkeypatch):
        """Exercise the model-visible tool through real provider mappings.

        The runtime identity deliberately differs from the ambient ContextVar.
        Acquire-time ``PathMapping`` must remain authoritative for both full and
        ranged reads; the tool layer must never reconstruct a raw host path.
        """
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        extensions = ExtensionsConfig()
        reset_user_skill_storage()

        with (
            patch("deerflow.config.get_app_config", return_value=cfg),
            patch("deerflow.config.paths.get_paths", return_value=paths),
            patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=extensions),
            patch("deerflow.config.extensions_config.get_extensions_config", return_value=extensions),
        ):
            provider = LocalSandboxProvider()
            sandbox_ids = {
                "user-1": provider.acquire("thread-user", user_id="user-1"),
                "noob": provider.acquire("thread-noob", user_id="noob"),
            }

            def _sandbox_for(runtime):
                return provider.get(runtime.state["sandbox"]["sandbox_id"])

            def _must_not_pre_resolve(_path: str) -> str:
                raise AssertionError("skill paths must stay virtual until the sandbox provider")

            monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", _sandbox_for)
            monkeypatch.setattr("deerflow.sandbox.tools._resolve_skills_path", _must_not_pre_resolve)

            token = set_current_user(SimpleNamespace(id="wrong-context-user"))
            try:
                cases = [
                    ("user-1", "thread-user", "/mnt/skills/public/pub-skill/SKILL.md", "pub-skill"),
                    ("user-1", "thread-user", "/mnt/skills/custom/usr-skill/SKILL.md", "usr-skill"),
                    ("noob", "thread-noob", "/mnt/skills/legacy/leg-skill/SKILL.md", "leg-skill"),
                    ("user-1", "thread-user", "/mnt/skills/integrations/demo-provider/int-skill/SKILL.md", "int-skill"),
                ]
                for user_id, thread_id, virtual_path, skill_name in cases:
                    runtime = SimpleNamespace(
                        state={
                            "sandbox": {"sandbox_id": sandbox_ids[user_id]},
                            "thread_data": {
                                "workspace_path": str(paths.sandbox_work_dir(thread_id, user_id=user_id)),
                                "uploads_path": str(paths.sandbox_uploads_dir(thread_id, user_id=user_id)),
                                "outputs_path": str(paths.sandbox_outputs_dir(thread_id, user_id=user_id)),
                            },
                        },
                        context={"thread_id": thread_id, "user_id": user_id},
                    )

                    full = read_file_tool.func(runtime=runtime, description="read skill", path=virtual_path)
                    ranged = read_file_tool.func(
                        runtime=runtime,
                        description="read skill name",
                        path=virtual_path,
                        start_line=2,
                        end_line=2,
                    )

                    assert f"# {skill_name}" in full
                    assert ranged == f"name: {skill_name}"
            finally:
                reset_current_user(token)
                reset_user_skill_storage()

    # ── Full pipeline: registry → container path → sandbox read ────────

    def test_registry_to_sandbox_full_pipeline(self, skills_fs):
        """Model's exact path: storage category → get_container_file_path → sandbox.read_file."""
        from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)

        with patch("deerflow.config.get_app_config", return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            provider = LocalSandboxProvider()
            sid_user = provider.acquire("t1", user_id="user-1")
            sid_noob = provider.acquire("t2", user_id="noob")
        sandbox_user = provider.get(sid_user)
        sandbox_noob = provider.get(sid_noob)

        # user-1 storage: sees public + custom, no legacy
        with patch("deerflow.config.paths.get_paths", return_value=paths):
            storage = UserScopedSkillStorage(user_id="user-1", host_path=str(skills_fs["root"]))
            skills = list(storage._iter_skill_files())
        by_name = {sf.parent.name: (cat, sf) for cat, _root, sf in skills}

        # public
        assert "pub-skill" in by_name
        cat, _ = by_name["pub-skill"]
        assert cat == SkillCategory.PUBLIC
        s = Skill(name="pub-skill", description="p", license=None, skill_dir=skills_fs["public"] / "pub-skill", skill_file=skills_fs["pub_skill"], relative_path=Path("pub-skill"), category=cat)
        cp = s.get_container_file_path("/mnt/skills")
        assert cp == "/mnt/skills/public/pub-skill/SKILL.md"
        assert "pub-skill" in sandbox_user.read_file(cp)

        # custom
        assert "usr-skill" in by_name
        cat, _ = by_name["usr-skill"]
        assert cat == SkillCategory.CUSTOM
        s = Skill(name="usr-skill", description="u", license=None, skill_dir=skills_fs["user_custom"] / "usr-skill", skill_file=skills_fs["user_skill"], relative_path=Path("usr-skill"), category=cat)
        cp = s.get_container_file_path("/mnt/skills")
        assert cp == "/mnt/skills/custom/usr-skill/SKILL.md"
        assert "usr-skill" in sandbox_user.read_file(cp)

        # noob storage: sees public + legacy (no per-user custom)
        with patch("deerflow.config.paths.get_paths", return_value=paths):
            storage = UserScopedSkillStorage(user_id="noob", host_path=str(skills_fs["root"]))
            skills = list(storage._iter_skill_files())
        by_name = {sf.parent.name: (cat, sf) for cat, _root, sf in skills}

        assert "leg-skill" in by_name
        cat, _ = by_name["leg-skill"]
        assert cat == SkillCategory.LEGACY
        s = Skill(name="leg-skill", description="l", license=None, skill_dir=skills_fs["legacy_global"] / "leg-skill", skill_file=skills_fs["legacy_skill"], relative_path=Path("leg-skill"), category=cat)
        cp = s.get_container_file_path("/mnt/skills")
        assert cp == "/mnt/skills/legacy/leg-skill/SKILL.md"
        assert "leg-skill" in sandbox_noob.read_file(cp)

    def test_local_tools_observe_toggle_without_sandbox_recreation(self, tmp_path, monkeypatch):
        skills_root = tmp_path / "skills"
        _write_skill(skills_root / "public", "secret-skill", "SECRET_PROCEDURE")
        paths = Paths(base_dir=tmp_path)
        cfg = _build_config(skills_root)
        extensions = ExtensionsConfig(skills={"secret-skill": SkillStateConfig(enabled=False)})

        with (
            patch("deerflow.config.get_app_config", return_value=cfg),
            patch("deerflow.config.paths.get_paths", return_value=paths),
            patch("deerflow.config.extensions_config.ExtensionsConfig.from_file", return_value=extensions),
            patch("deerflow.config.extensions_config.get_extensions_config", return_value=extensions),
        ):
            storage = UserScopedSkillStorage("user-1", host_path=str(skills_root), app_config=cfg)
            rebuild_skill_projections(storage)
            provider = LocalSandboxProvider()
            sandbox_id = provider.acquire("thread-1", user_id="user-1")
            sandbox = provider.get(sandbox_id)
            assert sandbox is not None
            runtime = SimpleNamespace(
                state={
                    "sandbox": {"sandbox_id": sandbox_id},
                    "thread_data": {
                        "workspace_path": str(paths.sandbox_work_dir("thread-1", user_id="user-1")),
                        "uploads_path": str(paths.sandbox_uploads_dir("thread-1", user_id="user-1")),
                        "outputs_path": str(paths.sandbox_outputs_dir("thread-1", user_id="user-1")),
                    },
                },
                context={"thread_id": "thread-1", "user_id": "user-1"},
            )
            monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda _runtime: sandbox)
            virtual_path = "/mnt/skills/public/secret-skill/SKILL.md"

            disabled = sandbox.execute_command(f"cat {virtual_path}")
            assert "SECRET_PROCEDURE" not in disabled
            structured_disabled = read_file_tool.func(runtime=runtime, description="read disabled skill", path=virtual_path)
            assert "SECRET_PROCEDURE" not in structured_disabled
            assert "disabled" in structured_disabled.lower()
            assert not (paths.public_skills_view_dir / "secret-skill").exists()
            assert (skills_root / "public" / "secret-skill" / "SKILL.md").is_file()

            extensions.skills["secret-skill"] = SkillStateConfig(enabled=True)
            rebuild_skill_projections(storage)
            enabled = sandbox.execute_command(f"cat {virtual_path}")
            assert "SECRET_PROCEDURE" in enabled
            assert "SECRET_PROCEDURE" in read_file_tool.func(runtime=runtime, description="read enabled skill", path=virtual_path)
            assert provider.acquire("thread-1", user_id="user-1") == sandbox_id

            extensions.skills["secret-skill"] = SkillStateConfig(enabled=False)
            rebuild_skill_projections(storage)
            disabled_again = sandbox.execute_command(f"cat {virtual_path}")
            assert "SECRET_PROCEDURE" not in disabled_again
            structured_disabled_again = read_file_tool.func(runtime=runtime, description="read disabled skill", path=virtual_path)
            assert "SECRET_PROCEDURE" not in structured_disabled_again
            assert "disabled" in structured_disabled_again.lower()

    # ── AioSandboxProvider ──────────────────────────────────────────────

    def test_aio_public_skill_mount(self, skills_fs, aio_mod):
        cfg = _build_config(skills_fs["root"])
        with patch(_AIO_GET_CONFIG, return_value=cfg):
            mounts = aio_mod.AioSandboxProvider._get_skills_mounts(user_id="user-1")
        idx = {m[1]: m for m in mounts}
        assert "/mnt/skills/public" in idx
        host, _, _ = idx["/mnt/skills/public"]
        assert "skills_view/public" in host.replace("\\", "/")

    def test_aio_per_user_custom_skill_mount(self, skills_fs, aio_mod, monkeypatch):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
        with patch(_AIO_GET_CONFIG, return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            mounts = aio_mod.AioSandboxProvider._get_skills_mounts(user_id="user-1")
        idx = {m[1]: m for m in mounts}
        assert "/mnt/skills/custom" in idx
        host, _, _ = idx["/mnt/skills/custom"]
        assert "users/user-1/skills_view/custom" in host.replace("\\", "/")

    def test_aio_legacy_mounted_for_user_without_custom(self, skills_fs, aio_mod, monkeypatch):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
        with patch(_AIO_GET_CONFIG, return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            mounts = aio_mod.AioSandboxProvider._get_skills_mounts(user_id="noob")
        idx = {m[1]: m for m in mounts}
        assert "/mnt/skills/legacy" in idx

    def test_aio_legacy_not_mounted_when_user_has_custom(self, skills_fs, aio_mod, monkeypatch):
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
        with patch(_AIO_GET_CONFIG, return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            mounts = aio_mod.AioSandboxProvider._get_skills_mounts(user_id="user-1")
        idx = {m[1]: m for m in mounts}
        assert "/mnt/skills/legacy" in idx

    def test_aio_legacy_still_mounted_when_user_has_only_non_skill_subdir(self, skills_fs, aio_mod, monkeypatch):
        (skills_fs["users_dir"] / "ghost" / "skills" / "custom" / "dangling-dir").mkdir(parents=True, exist_ok=True)
        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)
        with patch(_AIO_GET_CONFIG, return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            mounts = aio_mod.AioSandboxProvider._get_skills_mounts(user_id="ghost")
        idx = {m[1]: m for m in mounts}
        assert "/mnt/skills/legacy" in idx

    # ── AIO → Docker --mount translation ───────────────────────────────

    def test_aio_extra_mounts_translate_to_docker_bind_mounts(self, skills_fs, aio_mod, monkeypatch):
        """extra_mounts → _format_container_mount → correct Docker --mount args."""
        from deerflow.community.aio_sandbox.local_backend import _format_container_mount

        cfg = _build_config(skills_fs["root"])
        paths = Paths(base_dir=skills_fs["users_dir"].parent)
        monkeypatch.setattr(aio_mod, "get_paths", lambda: paths)

        with patch(_AIO_GET_CONFIG, return_value=cfg), patch("deerflow.config.paths.get_paths", return_value=paths):
            extra = aio_mod.AioSandboxProvider._get_extra_mounts(
                aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider),
                "thread-1",
                user_id="noob",
            )

        # extra includes thread mounts + skills mounts
        docker_args: list[str] = []
        mount_entries: dict[str, str] = {}
        for host, container, ro in extra:
            args = _format_container_mount("docker", host, container, ro)
            docker_args.extend(args)
            if args[0] == "--mount":
                mount_entries[container] = args[1]

        assert "--mount" in docker_args
        # Skills mounts must be present
        assert "/mnt/skills/public" in mount_entries
        assert "dst=/mnt/skills/public" in mount_entries["/mnt/skills/public"]
        assert "readonly" in mount_entries["/mnt/skills/public"]

        assert "/mnt/skills/custom" in mount_entries
        assert "dst=/mnt/skills/custom" in mount_entries["/mnt/skills/custom"]
        assert "users/noob/skills_view/custom" in mount_entries["/mnt/skills/custom"]

        assert "/mnt/skills/integrations" in mount_entries
        assert "dst=/mnt/skills/integrations" in mount_entries["/mnt/skills/integrations"]
        assert "users/noob/skills_view/integrations" in mount_entries["/mnt/skills/integrations"]

        # noob has no per-user custom → legacy is mounted
        assert "/mnt/skills/legacy" in mount_entries
        assert "dst=/mnt/skills/legacy" in mount_entries["/mnt/skills/legacy"]

    # ── Path alignment ──────────────────────────────────────────────────

    def test_skill_container_paths_match_expected_mounts(self, skills_fs):
        cr = "/mnt/skills"
        assert (
            Skill(
                name="p",
                description="",
                license=None,
                skill_dir=skills_fs["public"] / "pub-skill",
                skill_file=skills_fs["pub_skill"],
                relative_path=Path("pub-skill"),
                category=SkillCategory.PUBLIC,
            ).get_container_path(cr)
            == "/mnt/skills/public/pub-skill"
        )

        assert (
            Skill(
                name="u",
                description="",
                license=None,
                skill_dir=skills_fs["user_custom"] / "usr-skill",
                skill_file=skills_fs["user_skill"],
                relative_path=Path("usr-skill"),
                category=SkillCategory.CUSTOM,
            ).get_container_path(cr)
            == "/mnt/skills/custom/usr-skill"
        )

        assert (
            Skill(
                name="l",
                description="",
                license=None,
                skill_dir=skills_fs["legacy_global"] / "leg-skill",
                skill_file=skills_fs["legacy_skill"],
                relative_path=Path("leg-skill"),
                category=SkillCategory.LEGACY,
            ).get_container_path(cr)
            == "/mnt/skills/legacy/leg-skill"
        )
