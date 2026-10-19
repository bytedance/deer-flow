from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "load_memory_sample.py"
SPEC = importlib.util.spec_from_file_location("load_memory_sample", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
loader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loader)


def test_parse_args_requires_one_target_mode(tmp_path):
    with pytest.raises(SystemExit):
        loader.parse_args(tmp_path, [])


def test_parse_args_rejects_target_with_all_users(tmp_path):
    with pytest.raises(SystemExit):
        loader.parse_args(tmp_path, ["--target", "memory.json", "--all-users"])


def test_parse_args_accepts_all_users(tmp_path):
    args = loader.parse_args(tmp_path, ["--all-users"])

    assert args.all_users is True
    assert args.target is None


def test_load_sample_for_users_backs_up_every_user_before_import(tmp_path):
    events = []
    current = {
        "u1": {"facts": [{"id": "old-1"}]},
        "u2": {"facts": [{"id": "old-2"}]},
    }

    def load_memory(*, user_id):
        events.append(("load", user_id))
        return current[user_id]

    def import_memory(sample, *, user_id):
        assert (tmp_path / f"{user_id}.json").exists()
        assert all((tmp_path / f"{uid}.json").exists() for uid in current)
        events.append(("import", user_id))
        return sample

    count = loader.load_sample_for_users(
        {"facts": [{"id": "sample"}]},
        ["u1", "u2"],
        backup_root=tmp_path,
        no_backup=False,
        load_memory=load_memory,
        import_memory=import_memory,
    )

    assert count == 2
    assert events == [
        ("load", "u1"),
        ("load", "u2"),
        ("import", "u1"),
        ("import", "u2"),
    ]


def test_load_sample_for_users_with_no_users_is_a_noop(tmp_path):
    assert (
        loader.load_sample_for_users(
            {"facts": []},
            [],
            backup_root=tmp_path,
            no_backup=False,
            load_memory=lambda **_: pytest.fail("unexpected load"),
            import_memory=lambda *_args, **_kwargs: pytest.fail("unexpected import"),
        )
        == 0
    )


def test_load_sample_for_users_stops_after_import_failure(tmp_path):
    imported = []

    def fail_second(_sample, *, user_id):
        imported.append(user_id)
        if user_id == "u2":
            raise OSError("boom")

    with pytest.raises(OSError, match="boom"):
        loader.load_sample_for_users(
            {"facts": []},
            ["u1", "u2", "u3"],
            backup_root=tmp_path,
            no_backup=True,
            load_memory=lambda **_: {},
            import_memory=fail_second,
        )

    assert imported == ["u1", "u2"]


def test_load_sample_for_users_rejects_unpersisted_sample(tmp_path):
    with pytest.raises(OSError, match="not persisted for user u1"):
        loader.load_sample_for_users(
            {"facts": [{"id": "sample"}]},
            ["u1"],
            backup_root=tmp_path,
            no_backup=True,
            load_memory=lambda **_: {"facts": []},
            import_memory=lambda *_args, **_kwargs: {"facts": []},
        )


def test_load_sample_for_all_users_uses_runtime_config_resolution(monkeypatch, tmp_path):
    import asyncio

    import deerflow.config.app_config as app_config

    config_arguments = []

    def from_file(config_path=None):
        config_arguments.append(config_path)
        return SimpleNamespace(database=SimpleNamespace(backend="memory"))

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "review-config.yaml"))
    monkeypatch.setattr(app_config.AppConfig, "from_file", from_file)

    with pytest.raises(SystemExit, match="sqlite or postgres"):
        asyncio.run(
            loader.load_sample_for_all_users(SCRIPT_PATH.parents[1], {"facts": []}, no_backup=True),
        )

    assert config_arguments == [None]


def test_load_sample_for_all_users_uses_configured_memory_manager(monkeypatch, tmp_path):
    import asyncio

    import app.gateway.auth.repositories.sqlite as sqlite_repository
    import deerflow.agents.memory.manager as memory_manager
    import deerflow.config.app_config as app_config
    import deerflow.config.paths as config_paths
    import deerflow.persistence.engine as persistence_engine

    manager_factory_calls = 0
    loaded = []
    imported = []

    class FakeMemoryManager:
        def get_memory(self, *, user_id):
            loaded.append(user_id)
            return {"facts": [{"id": f"old-{user_id}"}]}

        def import_memory(self, sample, *, user_id):
            imported.append((user_id, sample))
            return sample

    manager = FakeMemoryManager()

    def get_memory_manager():
        nonlocal manager_factory_calls
        manager_factory_calls += 1
        return manager

    class FakeUserRepository:
        def __init__(self, _session_factory):
            pass

        async def list_user_ids(self):
            return ["u1", "u2"]

    async def init_engine_from_config(_database):
        pass

    async def close_engine():
        pass

    monkeypatch.setattr(memory_manager, "get_memory_manager", get_memory_manager)
    monkeypatch.setattr(sqlite_repository, "SQLiteUserRepository", FakeUserRepository)
    monkeypatch.setattr(
        app_config.AppConfig,
        "from_file",
        lambda *_args: SimpleNamespace(database=SimpleNamespace(backend="sqlite")),
    )
    monkeypatch.setattr(config_paths, "get_paths", lambda: SimpleNamespace(base_dir=tmp_path))
    monkeypatch.setattr(persistence_engine, "init_engine_from_config", init_engine_from_config)
    monkeypatch.setattr(persistence_engine, "get_session_factory", object)
    monkeypatch.setattr(persistence_engine, "close_engine", close_engine)

    sample = {"facts": [{"id": "sample"}]}
    count, backup_root = asyncio.run(
        loader.load_sample_for_all_users(SCRIPT_PATH.parents[1], sample, no_backup=False),
    )

    assert count == 2
    assert manager_factory_calls == 1
    assert loaded == ["u1", "u2"]
    assert imported == [("u1", sample), ("u2", sample)]
    assert backup_root is not None
    assert json.loads((backup_root / "u1.json").read_text())["facts"][0]["id"] == "old-u1"
    assert json.loads((backup_root / "u2.json").read_text())["facts"][0]["id"] == "old-u2"


def test_require_persistent_database_rejects_memory():
    with pytest.raises(SystemExit, match="sqlite or postgres"):
        loader.require_persistent_database("memory")


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_require_persistent_database_accepts_persistent_backends(backend):
    loader.require_persistent_database(backend)
