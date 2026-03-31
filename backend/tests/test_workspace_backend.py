"""Unit tests for WorkspaceConfig and LocalWorkspaceBackend."""

import asyncio
from pathlib import Path

import pytest

from deerflow.identity.agent_identity import AgentIdentity


# ── WorkspaceConfig ────────────────────────────────────────────────────────────

class TestWorkspaceConfig:
    def test_default_backend_is_local(self):
        from deerflow.config.workspace_config import WorkspaceConfig

        cfg = WorkspaceConfig()
        assert cfg.backend == "local"
        assert cfg.minio is None

    def test_minio_backend(self):
        from deerflow.config.workspace_config import WorkspaceConfig, MinioConfig

        cfg = WorkspaceConfig(
            backend="minio",
            minio=MinioConfig(endpoint="localhost:9000", bucket="test", access_key="key", secret_key="secret"),
        )
        assert cfg.backend == "minio"
        assert cfg.minio.bucket == "test"

    def test_get_set_workspace_config(self):
        from deerflow.config.workspace_config import get_workspace_config, set_workspace_config, WorkspaceConfig

        original = get_workspace_config()
        try:
            new_cfg = WorkspaceConfig(backend="local")
            set_workspace_config(new_cfg)
            assert get_workspace_config().backend == "local"
        finally:
            set_workspace_config(original)

    def test_load_from_dict(self):
        from deerflow.config.workspace_config import load_workspace_config_from_dict, get_workspace_config, WorkspaceConfig

        original = get_workspace_config()
        try:
            load_workspace_config_from_dict({"backend": "local"})
            assert get_workspace_config().backend == "local"
        finally:
            from deerflow.config.workspace_config import set_workspace_config
            set_workspace_config(original)


# ── LocalWorkspaceBackend ──────────────────────────────────────────────────────

class TestLocalWorkspaceBackend:
    def test_sync_down_noop_when_no_persistent_workspace(self, tmp_path):
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            identity = AgentIdentity(dept_id="d", user_id="u", agent_name="a")
            local_dir = tmp_path / "thread-workspace"
            local_dir.mkdir()

            backend = LocalWorkspaceBackend()
            asyncio.run(backend.sync_down(identity, local_dir))
            # No persistent workspace exists → local_dir untouched (no files added)
            assert list(local_dir.iterdir()) == []
        finally:
            paths_module.get_paths = orig

    def test_sync_down_copies_files(self, tmp_path):
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            identity = AgentIdentity(dept_id="d", user_id="u", agent_name="a")

            # Create persistent workspace with a file
            workspace = paths_obj.identity_workspace_dir(identity)
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "notes.txt").write_text("hello", encoding="utf-8")

            local_dir = tmp_path / "thread-workspace"
            local_dir.mkdir()

            backend = LocalWorkspaceBackend()
            asyncio.run(backend.sync_down(identity, local_dir))
            assert (local_dir / "notes.txt").read_text(encoding="utf-8") == "hello"
        finally:
            paths_module.get_paths = orig

    def test_sync_up_persists_files(self, tmp_path):
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            identity = AgentIdentity(dept_id="d", user_id="u", agent_name="a")

            local_dir = tmp_path / "thread-workspace"
            local_dir.mkdir()
            (local_dir / "output.txt").write_text("result", encoding="utf-8")

            backend = LocalWorkspaceBackend()
            asyncio.run(backend.sync_up(identity, local_dir))

            workspace = paths_obj.identity_workspace_dir(identity)
            assert (workspace / "output.txt").read_text(encoding="utf-8") == "result"
        finally:
            paths_module.get_paths = orig

    def test_sync_up_noop_without_agent(self, tmp_path):
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            # No agent → identity_workspace_dir returns None → sync_up is a no-op
            identity = AgentIdentity(dept_id="d", user_id="u")  # no agent_name

            local_dir = tmp_path / "thread-workspace"
            local_dir.mkdir()
            (local_dir / "file.txt").write_text("data", encoding="utf-8")

            backend = LocalWorkspaceBackend()
            # Should not raise; no persistent directory should be created
            asyncio.run(backend.sync_up(identity, local_dir))

            workspace = paths_obj.identity_workspace_dir(identity)
            assert workspace is None
        finally:
            paths_module.get_paths = orig

    def test_round_trip(self, tmp_path):
        """Files written by sync_up are correctly restored by sync_down."""
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths
        try:
            paths_module.get_paths = lambda: paths_obj
            identity = AgentIdentity(dept_id="d", user_id="u", agent_name="a")
            backend = LocalWorkspaceBackend()

            # Session 1: write a file and sync_up
            session1_dir = tmp_path / "session1"
            session1_dir.mkdir()
            (session1_dir / "data.csv").write_text("col1,col2\n1,2\n", encoding="utf-8")
            asyncio.run(backend.sync_up(identity, session1_dir))

            # Session 2: start fresh local_dir, sync_down should restore the file
            session2_dir = tmp_path / "session2"
            session2_dir.mkdir()
            asyncio.run(backend.sync_down(identity, session2_dir))
            assert (session2_dir / "data.csv").read_text(encoding="utf-8") == "col1,col2\n1,2\n"
        finally:
            paths_module.get_paths = orig


# ── SandboxMiddleware identity wiring ─────────────────────────────────────────

class TestSandboxMiddlewareWorkspace:
    def test_no_workspace_backend_without_agent(self):
        from deerflow.sandbox.middleware import SandboxMiddleware

        identity = AgentIdentity(dept_id="d", user_id="u")  # no agent
        mw = SandboxMiddleware(identity=identity)
        assert mw._get_workspace_backend() is None

    def test_no_workspace_backend_without_identity(self):
        from deerflow.sandbox.middleware import SandboxMiddleware

        mw = SandboxMiddleware()
        assert mw._get_workspace_backend() is None

    def test_local_backend_returned_for_agent_identity(self):
        from deerflow.sandbox.middleware import SandboxMiddleware
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend

        identity = AgentIdentity(dept_id="d", user_id="u", agent_name="a")
        mw = SandboxMiddleware(identity=identity)
        backend = mw._get_workspace_backend()
        assert isinstance(backend, LocalWorkspaceBackend)
