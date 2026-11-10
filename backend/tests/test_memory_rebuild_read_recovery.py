"""A temporary canonical read failure must not publish an incomplete index."""

from __future__ import annotations

import errno
from pathlib import Path
from unittest.mock import Mock

import pytest

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem


@pytest.mark.parametrize("already_warmed", [False, True])
@pytest.mark.parametrize("read_errno", [errno.EACCES, errno.EIO])
def test_full_rebuild_recovers_after_canonical_read_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, already_warmed: bool, read_errno: int) -> None:
    config = {"storage_path": str(tmp_path), "token_counting": "char"}
    # Seed canonical files without a derived index, as on a fresh Gateway.
    writer = DeerMem(backend_config={**config, "retrieval_adapter": ""})
    try:
        _, primary_id = writer.create_fact("Primary database is PostgreSQL", user_id="alice", agent_name="researcher")
        _, backup_id = writer.create_fact("Backup database is SQLite", user_id="alice", agent_name="researcher")
        _, other_agent_id = writer.create_fact("Database for planning", user_id="alice", agent_name="planner")
        _, other_user_id = writer.create_fact("Database for Bob", user_id="bob", agent_name="researcher")
    finally:
        writer.close()

    blocked_path = next(tmp_path.rglob(f"{backup_id}.md"))
    canonical_bytes = {path: path.read_bytes() for path in tmp_path.rglob("*.md")}
    manager = DeerMem(backend_config=config)
    try:
        if already_warmed:
            assert manager.warm_retrieval()
        read_text = Path.read_text
        failed_reads: list[Path] = []

        def fail_one_fact(path: Path, *args, **kwargs):
            if path == blocked_path:
                failed_reads.append(path)
                raise OSError(read_errno, "temporary canonical read failure")
            return read_text(path, *args, **kwargs)

        with monkeypatch.context() as fault:
            fault.setattr(Path, "read_text", fail_one_fact)
            warmed = manager.warm_retrieval()
            assert failed_reads, "the warmup must attempt the actual canonical read"
            if already_warmed:
                # The previous complete index remains usable while the file is locked.
                assert {fact["id"] for fact in manager.search("database", top_k=10, user_id="alice", agent_name="researcher")} == {primary_id, backup_id}

        assert not warmed
        for _ in range(2):
            assert {fact["id"] for fact in manager.search("database", top_k=10, user_id="alice", agent_name="researcher")} == {primary_id, backup_id}
        assert [fact["id"] for fact in manager.search("database", user_id="alice", agent_name="planner")] == [other_agent_id]
        assert [fact["id"] for fact in manager.search("database", user_id="bob", agent_name="researcher")] == [other_user_id]
        assert {path: path.read_bytes() for path in canonical_bytes} == canonical_bytes
    finally:
        manager.close()


def test_full_rebuild_still_skips_malformed_facts_without_repeated_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    try:
        _, good_id = manager.create_fact("Healthy database preference", user_id="alice", agent_name="researcher")
        _, broken_id = manager.create_fact("Broken database preference", user_id="alice", agent_name="researcher")
        broken_path = next(tmp_path.rglob(f"{broken_id}.md"))
        broken_path.write_text("not a canonical fact", encoding="utf-8")

        assert manager.warm_retrieval()
        rebuild = Mock(wraps=manager._storage.rebuild_index)
        monkeypatch.setattr(manager._storage, "rebuild_index", rebuild)
        for _ in range(2):
            assert [fact["id"] for fact in manager.search("database", user_id="alice", agent_name="researcher")] == [good_id]
        rebuild.assert_not_called()
        assert broken_path.read_text(encoding="utf-8") == "not a canonical fact"
    finally:
        manager.close()
