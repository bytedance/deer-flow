from __future__ import annotations

import importlib.util
from pathlib import Path

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

    def import_memory(_sample, *, user_id):
        assert (tmp_path / f"{user_id}.json").exists()
        assert all((tmp_path / f"{uid}.json").exists() for uid in current)
        events.append(("import", user_id))

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


def test_require_persistent_database_rejects_memory():
    with pytest.raises(SystemExit, match="sqlite or postgres"):
        loader.require_persistent_database("memory")


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_require_persistent_database_accepts_persistent_backends(backend):
    loader.require_persistent_database(backend)
