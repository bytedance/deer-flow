from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "checkpoint_storage.py"
_SPEC = importlib.util.spec_from_file_location("checkpoint_storage", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
checkpoint_storage = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checkpoint_storage)


def _create_checkpoint_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            CREATE TABLE writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                blob BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            );
            CREATE TABLE checkpoint_blobs (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL,
                version TEXT NOT NULL,
                type TEXT,
                blob BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
            );
            CREATE TABLE threads_meta (
                thread_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO checkpoints VALUES (?, '', ?, ?, 'msgpack', ?, ?)",
            [
                ("thread-a", "0001", None, b"small", b"{}"),
                ("thread-a", "0002", "0001", b"large" * 20, b"{}"),
                ("thread-b", "0001", None, b"orphan" * 5, b"{}"),
            ],
        )
        conn.executemany(
            "INSERT INTO writes VALUES (?, '', ?, ?, ?, 'messages', 'msgpack', ?)",
            [
                ("thread-a", "0001", "task-a", 0, b"pending"),
                ("thread-a", "0002", "task-a", 0, b"pending" * 10),
                ("thread-b", "0001", "task-b", 0, b"pending" * 3),
            ],
        )
        conn.executemany(
            "INSERT INTO checkpoint_blobs VALUES (?, '', 'messages', ?, 'msgpack', ?)",
            [
                ("thread-a", "0001", b"blob-a"),
                ("thread-b", "0001", b"blob-b" * 4),
            ],
        )
        conn.execute("INSERT INTO threads_meta(thread_id, user_id) VALUES ('thread-a', 'user-1')")
        conn.commit()
    finally:
        conn.close()


def _create_app_db(path: Path, thread_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE threads_meta (
                thread_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO threads_meta(thread_id, user_id) VALUES (?, 'user-1')",
            [(thread_id,) for thread_id in thread_ids],
        )
        conn.commit()
    finally:
        conn.close()


def test_inspect_checkpoint_storage_redacts_thread_ids_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "deerflow.db"
    _create_checkpoint_db(db_path)

    report = checkpoint_storage.inspect_checkpoint_storage(
        db_path,
        top=2,
        keep=1,
        include_thread_ids=False,
    )

    assert report["checkpoint_thread_count"] == 2
    assert report["app_thread_count"] == 1
    assert report["orphan_checkpoint_thread_count"] == 1
    assert "checkpoint_thread_ids" not in report
    assert "thread_id" not in report["top_threads"][0]
    assert report["retention_estimate"]["keep"] == 1
    assert report["retention_estimate"]["removable_checkpoint_rows"] == 1
    assert report["retention_estimate"]["removable_write_rows"] == 1


def test_inspect_checkpoint_storage_can_show_thread_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "deerflow.db"
    _create_checkpoint_db(db_path)

    report = checkpoint_storage.inspect_checkpoint_storage(
        db_path,
        top=2,
        include_thread_ids=True,
    )

    assert report["checkpoint_thread_ids"] == ["thread-a", "thread-b"]
    assert report["orphan_checkpoint_thread_ids"] == ["thread-b"]
    assert {entry["thread_id"] for entry in report["top_threads"]} == {
        "thread-a",
        "thread-b",
    }


def test_cli_report_json_uses_explicit_db(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "deerflow.db"
    _create_checkpoint_db(db_path)

    exit_code = checkpoint_storage.main(["report", "--db", str(db_path), "--json", "--keep", "1"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["source"] == "explicit"
    assert payload["tables"]["checkpoints"]["rows"] == 3
    assert payload["orphan_checkpoint_thread_count"] == 1
    assert "thread_id" not in payload["top_threads"][0]


def test_cli_report_human_can_show_thread_ids(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "deerflow.db"
    _create_checkpoint_db(db_path)

    exit_code = checkpoint_storage.main(["report", "--db", str(db_path), "--show-thread-ids", "--top", "1"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Checkpoint storage report" in captured.out
    assert "thread-a" in captured.out or "thread-b" in captured.out


def test_cli_report_resolves_legacy_checkpointer_and_separate_app_db(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    checkpoint_db = tmp_path / ".deer-flow" / "checkpoints.db"
    checkpoint_db.parent.mkdir(parents=True)
    _create_checkpoint_db(checkpoint_db)
    _create_app_db(
        tmp_path / ".deer-flow" / "data" / "deerflow.db",
        ["thread-a", "thread-b"],
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
checkpointer:
  type: sqlite
  connection_string: checkpoints.db
database:
  backend: sqlite
  sqlite_dir: .deer-flow/data
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = checkpoint_storage.main(["report", "--config", str(config_path), "--json", "--top", "1"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["source"] == "legacy checkpointer"
    assert payload["app_thread_count"] == 2
    assert payload["orphan_checkpoint_thread_count"] == 0
