"""Tests for migrate_memory_to_store.py."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.migrate_memory_to_store import (
    find_memory_files,
    load_memory_file,
    migrate_memory_to_store,
)


class TestLoadMemoryFile:
    """Tests for load_memory_file()."""

    def test_load_valid_json(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        data = {"version": "1.0", "facts": ["fact1"]}
        mem_file.write_text(json.dumps(data), encoding="utf-8")

        result = load_memory_file(mem_file)
        assert result is not None
        assert result["version"] == "1.0"
        assert result["facts"] == ["fact1"]

    def test_load_nonexistent_file(self, tmp_path: Path):
        result = load_memory_file(tmp_path / "nope.json")
        assert result is None

    def test_load_invalid_json(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        mem_file.write_text("{bad json", encoding="utf-8")
        result = load_memory_file(mem_file)
        assert result is None

    def test_load_empty_file(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        mem_file.write_text("", encoding="utf-8")
        result = load_memory_file(mem_file)
        assert result is None


class TestFindMemoryFiles:
    """Tests for find_memory_files()."""

    def test_empty_directory(self, tmp_path: Path):
        results = find_memory_files(tmp_path)
        assert results == []

    def test_tenant_level_memory(self, tmp_path: Path):
        mem_file = tmp_path / "memory.json"
        mem_file.write_text("{}", encoding="utf-8")

        results = find_memory_files(tmp_path)
        assert len(results) == 1
        assert results[0] == (mem_file, "default", None)

    def test_tenant_level_agents(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "researcher"
        agent_dir.mkdir(parents=True)
        mem_file = agent_dir / "memory.json"
        mem_file.write_text("{}", encoding="utf-8")

        results = find_memory_files(tmp_path)
        assert len(results) == 1
        assert results[0][1] == "default"
        assert results[0][2] == "researcher"

    def test_per_user_memory(self, tmp_path: Path):
        user_dir = tmp_path / "users" / "alice"
        user_dir.mkdir(parents=True)
        mem_file = user_dir / "memory.json"
        mem_file.write_text("{}", encoding="utf-8")

        results = find_memory_files(tmp_path)
        assert len(results) == 1
        assert results[0][1] == "alice"
        assert results[0][2] is None

    def test_per_user_agent_memory(self, tmp_path: Path):
        agent_dir = tmp_path / "users" / "alice" / "agents" / "coder"
        agent_dir.mkdir(parents=True)
        mem_file = agent_dir / "memory.json"
        mem_file.write_text("{}", encoding="utf-8")

        results = find_memory_files(tmp_path)
        assert len(results) == 1
        assert results[0][1] == "alice"
        assert results[0][2] == "coder"

    def test_mixed_layout(self, tmp_path: Path):
        (tmp_path / "memory.json").write_text("{}", encoding="utf-8")

        user_dir = tmp_path / "users" / "bob"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text("{}", encoding="utf-8")

        agent_dir = user_dir / "agents" / "writer"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.json").write_text("{}", encoding="utf-8")

        results = find_memory_files(tmp_path)
        assert len(results) == 3

        user_ids = {r[1] for r in results}
        assert user_ids == {"default", "bob"}

    def test_skips_non_directory_users(self, tmp_path: Path):
        users_dir = tmp_path / "users"
        users_dir.mkdir()
        (users_dir / "readme.txt").write_text("not a dir", encoding="utf-8")

        results = find_memory_files(tmp_path)
        assert results == []


def _make_memory_data(version: str = "1.0") -> dict:
    return {
        "version": version,
        "lastUpdated": "2026-01-01T00:00:00Z",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


class _FakeStoreCtx:
    """Context manager that yields a mock store."""

    def __init__(self, store: MagicMock):
        self._store = store

    def __enter__(self):
        return self._store

    def __exit__(self, *args):
        return False


def _patch_postgres_store(mock_store: MagicMock):
    """Patch sys.modules so the lazy import inside migrate_memory_to_store
    picks up our mock PostgresStore."""
    mock_pg_module = types.ModuleType("langgraph.store.postgres")
    mock_pg_cls = MagicMock()
    mock_pg_cls.from_conn_string.return_value = _FakeStoreCtx(mock_store)
    mock_pg_cls.PostgresStore = mock_pg_cls
    mock_pg_module.PostgresStore = mock_pg_cls
    return patch.dict(sys.modules, {"langgraph.store.postgres": mock_pg_module})


class TestMigrateMemoryToStore:
    """Tests for migrate_memory_to_store()."""

    def test_dry_run_does_not_write(self, tmp_path: Path):
        user_dir = tmp_path / "users" / "alice"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text(
            json.dumps(_make_memory_data()), encoding="utf-8"
        )

        mock_store = MagicMock()
        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
                dry_run=True,
            )

        assert result is True
        mock_store.put.assert_not_called()

    def test_no_files_returns_true(self, tmp_path: Path):
        mock_store = MagicMock()
        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
            )

        assert result is True

    def test_migrates_user_memory(self, tmp_path: Path):
        user_dir = tmp_path / "users" / "alice"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text(
            json.dumps(_make_memory_data()), encoding="utf-8"
        )

        mock_store = MagicMock()
        mock_store.get.return_value = None

        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
                tenant_id="test-tenant",
            )

        assert result is True
        mock_store.setup.assert_called_once()
        mock_store.put.assert_called_once()

        call_args = mock_store.put.call_args
        ns = call_args[0][0]
        assert ns == ("memory", "test-tenant", "alice", "default")
        assert call_args[0][1] == "data"
        assert call_args[0][2]["version"] == "1.0"

    def test_migrates_agent_memory(self, tmp_path: Path):
        agent_dir = tmp_path / "users" / "bob" / "agents" / "coder"
        agent_dir.mkdir(parents=True)
        (agent_dir / "memory.json").write_text(
            json.dumps(_make_memory_data()), encoding="utf-8"
        )

        mock_store = MagicMock()
        mock_store.get.return_value = None

        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
            )

        assert result is True
        ns = mock_store.put.call_args[0][0]
        assert ns == ("memory", "default", "bob", "coder")

    def test_skips_existing_records(self, tmp_path: Path):
        user_dir = tmp_path / "users" / "alice"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text(
            json.dumps(_make_memory_data()), encoding="utf-8"
        )

        mock_existing_item = MagicMock()
        mock_existing_item.value = {"version": "1.0"}

        mock_store = MagicMock()
        mock_store.get.return_value = mock_existing_item

        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
            )

        assert result is True
        mock_store.put.assert_not_called()

    def test_failed_load_counts_as_failure(self, tmp_path: Path):
        user_dir = tmp_path / "users" / "alice"
        user_dir.mkdir(parents=True)
        (user_dir / "memory.json").write_text(
            "{broken json", encoding="utf-8"
        )

        mock_store = MagicMock()
        mock_store.get.return_value = None

        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
            )

        assert result is False
        mock_store.put.assert_not_called()

    def test_tenant_level_memory_migrates(self, tmp_path: Path):
        (tmp_path / "memory.json").write_text(
            json.dumps(_make_memory_data()), encoding="utf-8"
        )

        mock_store = MagicMock()
        mock_store.get.return_value = None

        with _patch_postgres_store(mock_store):
            result = migrate_memory_to_store(
                "postgresql://fake/db",
                base_dir=tmp_path,
                tenant_id="my-tenant",
            )

        assert result is True
        ns = mock_store.put.call_args[0][0]
        assert ns == ("memory", "my-tenant", "default", "default")
