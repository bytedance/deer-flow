"""Tests for the proactive JSON-to-Markdown memory migration CLI."""

import json
from pathlib import Path

from deerflow.agents.memory.backends.deermem.deermem.core.paths import fact_file_path


def _legacy_memory(content: str) -> dict:
    return {
        "version": "1.0",
        "revision": 0,
        "lastUpdated": "2026-01-01T00:00:00Z",
        "user": {"workContext": {"summary": "keep me", "updatedAt": "2026-01-01T00:00:00Z"}},
        "history": {},
        "facts": [
            {
                "id": "fact_legacy",
                "content": content,
                "category": "context",
                "confidence": 0.9,
                "createdAt": "2026-01-01T00:00:00Z",
                "source": "manual",
            }
        ],
    }


def _seed_user(root: Path, user_bucket: str, content: str) -> Path:
    path = root / "users" / user_bucket / "memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_legacy_memory(content)), encoding="utf-8")
    return path


def test_cli_migrates_one_explicit_user(tmp_path: Path) -> None:
    from scripts.migrate_memory_markdown import main

    memory_path = _seed_user(tmp_path, "alice", "legacy alice fact")

    exit_code = main(["--storage-path", str(tmp_path), "--user-id", "alice"])

    assert exit_code == 0
    persisted = json.loads(memory_path.read_text(encoding="utf-8"))
    assert "facts" not in persisted
    assert persisted["user"]["workContext"]["summary"] == "keep me"
    assert fact_file_path(memory_path, "fact_legacy", agent_name="__default__").exists()


def test_cli_dry_run_reports_without_writing(tmp_path: Path, capsys) -> None:
    from scripts.migrate_memory_markdown import main

    memory_path = _seed_user(tmp_path, "alice", "legacy alice fact")
    original = memory_path.read_bytes()

    exit_code = main(["--storage-path", str(tmp_path), "--user-id", "alice", "--dry-run"])

    assert exit_code == 0
    assert memory_path.read_bytes() == original
    assert not (memory_path.parent / "agents" / "__default__" / "facts").exists()
    assert "would migrate" in capsys.readouterr().out


def test_cli_all_users_migrates_each_discovered_bucket(tmp_path: Path) -> None:
    from scripts.migrate_memory_markdown import main

    alice_path = _seed_user(tmp_path, "alice", "legacy alice fact")
    bob_path = _seed_user(tmp_path, "bob", "legacy bob fact")

    exit_code = main(["--storage-path", str(tmp_path), "--all-users"])

    assert exit_code == 0
    for memory_path in (alice_path, bob_path):
        assert "facts" not in json.loads(memory_path.read_text(encoding="utf-8"))
        assert fact_file_path(memory_path, "fact_legacy", agent_name="__default__").exists()


def test_cli_is_idempotent_and_reports_current_user(tmp_path: Path, capsys) -> None:
    from scripts.migrate_memory_markdown import main

    _seed_user(tmp_path, "alice", "legacy alice fact")
    arguments = ["--storage-path", str(tmp_path), "--user-id", "alice"]

    assert main(arguments) == 0
    capsys.readouterr()
    assert main(arguments) == 0

    assert "already current" in capsys.readouterr().out


def test_cli_requires_user_selection(tmp_path: Path) -> None:
    from scripts.migrate_memory_markdown import main

    try:
        main(["--storage-path", str(tmp_path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("CLI must require --all-users or --user-id")
