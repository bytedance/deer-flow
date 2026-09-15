"""Regression coverage for DeerMem's #4279 RetrievalPort integration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.retrieval import (
    FTS5Retrieval,
    FTS5RetrievalAdapter,
    _is_advanced_query,
    _jieba_available,
    create_fts5_retrieval,
)
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage


def _fact(fact_id: str, content: str, *, category: str = "context") -> dict:
    return {
        "id": fact_id,
        "content": content,
        "category": category,
        "confidence": 0.8,
        "createdAt": "2026-07-21T00:00:00Z",
        "source": {"type": "test", "threadId": None},
    }


def test_natural_language_hyphens_are_not_treated_as_fts5_syntax() -> None:
    assert not _is_advanced_query("real-time co-pilot node -js +python")


@pytest.mark.skipif(not _jieba_available, reason="install the optional memory-zh extra")
def test_chinese_subphrase_search_uses_jieba_tokenization(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    scope = {"userId": "alice", "agentName": "agent-a"}
    try:
        adapter.upsert(_fact("zh", "中文检索支持验证"), scope=scope, path="")
        results = adapter.search("检索", scopes=[scope], top_k=5, mode="fts5", filters=None)
        assert [item["fact"]["id"] for item in results] == ["zh"]
    finally:
        adapter.close()


def test_score_time_decay_and_advanced_phrase_query(tmp_path: Path) -> None:
    engine = FTS5Retrieval(tmp_path / "facts.sqlite3")
    try:
        assert engine._compute_final_score(1.0, 0.5, "2026-07-21T00:00:00Z") > engine._compute_final_score(1.0, 0.5, "2020-01-01T00:00:00Z")
        engine.index_fact("phrase", "alpha beta", scope_user='"alice"', scope_agent='"agent-a"')
        assert engine.search('"alpha beta"', scope_user='"alice"', scope_agent='"agent-a"')
    finally:
        engine.close()


def test_warm_retrieval_rebuilds_the_complete_index(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    _, fact_id = manager.create_fact("warm retrieval fact", user_id="alice")
    assert manager.warm_retrieval()
    assert any(fact["id"] == fact_id for fact in manager.search("warm", user_id="alice"))


def test_warm_retrieval_accepts_partial_fact_failures(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    manager._storage.rebuild_index = lambda scopes=None: {"supported": True, "indexed": 2, "failed": 1}  # type: ignore[method-assign]

    assert manager.warm_retrieval()
    assert manager._retrieval_fully_warmed


def test_warm_retrieval_retries_after_fatal_rebuild_failure(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    manager._storage.rebuild_index = lambda scopes=None: {"supported": True, "indexed": 0, "failed": 1, "fatal": True}  # type: ignore[method-assign]

    assert not manager.warm_retrieval()
    assert not manager._retrieval_fully_warmed


def test_lazy_warm_rebuilds_each_requested_scope(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    calls: list[list[dict[str, str | None]]] = []
    manager._storage.rebuild_index = lambda scopes=None: calls.append(scopes or []) or {"supported": True, "failed": 0}  # type: ignore[method-assign]
    scopes = [{"userId": "alice", "agentName": "a"}, {"userId": "bob", "agentName": "b"}]
    manager._ensure_retrieval_scopes(scopes)
    assert calls == [[scopes[0]], [scopes[1]]]


def test_lazy_warm_does_not_retry_partial_fact_failures(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    rebuild = MagicMock(return_value={"supported": True, "indexed": 2, "failed": 1})
    manager._storage.rebuild_index = rebuild  # type: ignore[method-assign]
    scopes = [{"userId": "alice", "agentName": "a"}]

    manager._ensure_retrieval_scopes(scopes)
    manager._ensure_retrieval_scopes(scopes)

    rebuild.assert_called_once_with(scopes)


def test_deermem_close_releases_retrieval_connection(tmp_path: Path) -> None:
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "token_counting": "char"})
    close_storage = MagicMock()
    manager._storage.close = close_storage  # type: ignore[attr-defined]

    manager.close()

    close_storage.assert_called_once_with()


def test_file_storage_close_releases_retrieval_connection(tmp_path: Path) -> None:
    retrieval = MagicMock()
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=retrieval)

    storage.close()

    retrieval.close.assert_called_once_with()


def test_factory_recreates_corrupt_persistent_index(tmp_path: Path) -> None:
    index_dir = tmp_path / ".retrieval"
    index_dir.mkdir()
    db_path = index_dir / "memory-fts5.sqlite3"
    db_path.write_bytes(b"not a sqlite database")

    adapter = create_fts5_retrieval(DeerMemConfig(storage_path=str(tmp_path)))

    assert adapter is not None
    try:
        adapter.upsert(
            _fact("recovered", "recreated derived index"),
            scope={"userId": "alice", "agentName": "agent-a"},
            path="",
        )
        assert adapter.search(
            "recreated",
            scopes=[{"userId": "alice", "agentName": "agent-a"}],
            top_k=5,
            mode="fts5",
            filters=None,
        )
    finally:
        adapter.close()


def test_adapter_isolates_scopes_even_when_fact_ids_repeat(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    try:
        adapter.upsert(_fact("same", "Alice private alpha"), scope={"userId": "alice", "agentName": "__default__"}, path="")
        adapter.upsert(_fact("same", "Bob private beta"), scope={"userId": "bob", "agentName": "__default__"}, path="")

        alice = adapter.search("alpha", scopes=[{"userId": "alice", "agentName": "__default__"}], top_k=5, mode="hybrid", filters=None)
        bob = adapter.search("alpha", scopes=[{"userId": "bob", "agentName": "__default__"}], top_k=5, mode="hybrid", filters=None)

        assert [item["fact"]["content"] for item in alice] == ["Alice private alpha"]
        assert bob == []
    finally:
        adapter.close()


def test_adapter_persists_across_restart_and_supports_category_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite3"
    scope = {"userId": "alice", "agentName": "agent-a"}
    first = FTS5RetrievalAdapter(db_path)
    first.upsert(_fact("one", "Python deployment preference", category="preference"), scope=scope, path="")
    first.upsert(_fact("two", "Python deployment context", category="context"), scope=scope, path="")
    first.close()

    second = FTS5RetrievalAdapter(db_path)
    try:
        results = second.search("Python deployment", scopes=[scope], top_k=5, mode="hybrid", filters={"category": "preference"})
        assert [item["fact"]["id"] for item in results] == ["one"]
        assert results[0]["matchType"] == "fts5"
    finally:
        second.close()


def test_file_storage_incremental_notifications_update_and_remove_index(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=adapter)
    scope = {"userId": "alice", "agentName": "agent-a"}
    try:
        storage.upsert_fact(_fact("one", "initial searchable value"), user_id="alice", agent_name="agent-a", expected_manifest_revision=0)
        assert storage.search_facts("initial", scopes=[scope])[0]["fact"]["id"] == "one"

        updated = storage.get_fact("one", user_id="alice", agent_name="agent-a")
        assert updated is not None
        updated["content"] = "replacement searchable value"
        storage.upsert_fact(
            updated,
            user_id="alice",
            agent_name="agent-a",
            expected_manifest_revision=1,
            expected_fact_revision=updated["revision"],
        )
        assert storage.search_facts("replacement", scopes=[scope])[0]["fact"]["id"] == "one"
        assert storage.search_facts("initial", scopes=[scope]) == []

        storage.delete_fact("one", user_id="alice", agent_name="agent-a")
        assert storage.search_facts("replacement", scopes=[scope]) == []
    finally:
        adapter.close()


def test_full_rebuild_removes_stale_rows_after_markdown_delete(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=adapter)
    scope = {"userId": "alice", "agentName": "agent-a"}
    try:
        storage.upsert_fact(_fact("one", "stale markdown value"), user_id="alice", agent_name="agent-a", expected_manifest_revision=0)
        memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
        fact_path = next(memory_path.parent.glob("agents/agent-a/facts/**/*.md"))
        fact_path.unlink()

        result = storage.rebuild_index()
        assert result == {"supported": True, "indexed": 0, "failed": 0}
        assert storage.search_facts("stale", scopes=[scope]) == []
    finally:
        adapter.close()


def test_reload_rebuilds_index_after_out_of_band_markdown_edit(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=adapter)
    scope = {"userId": "alice", "agentName": "agent-a"}
    try:
        storage.upsert_fact(_fact("one", "original markdown value"), user_id="alice", agent_name="agent-a", expected_manifest_revision=0)
        memory_path = storage._get_memory_file_path("agent-a", user_id="alice")
        fact_path = next(memory_path.parent.glob("agents/agent-a/facts/**/*.md"))
        raw = fact_path.read_text(encoding="utf-8").replace("original markdown value", "edited markdown value")
        fact_path.write_text(raw, encoding="utf-8")

        storage.reload("agent-a", user_id="alice")
        assert storage.search_facts("edited", scopes=[scope])[0]["fact"]["id"] == "one"
        assert storage.search_facts("original", scopes=[scope]) == []
    finally:
        adapter.close()


def test_failed_notification_marks_scope_dirty_and_rebuilds_on_search(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)), retrieval=adapter)
    original_upsert = adapter.upsert
    failed_once = True

    def fail_once(fact, *, scope, path):
        nonlocal failed_once
        if failed_once:
            failed_once = False
            raise RuntimeError("simulated index outage")
        original_upsert(fact, scope=scope, path=path)

    adapter.upsert = fail_once  # type: ignore[method-assign]
    try:
        storage.upsert_fact(_fact("one", "recoverable indexed value"), user_id="alice", agent_name="agent-a", expected_manifest_revision=0)
        results = storage.search_facts("recoverable", scopes=[{"userId": "alice", "agentName": "agent-a"}])
        assert results[0]["fact"]["id"] == "one"
    finally:
        adapter.close()


def test_concurrent_upserts_are_searchable(tmp_path: Path) -> None:
    adapter = FTS5RetrievalAdapter(tmp_path / "facts.sqlite3")
    scope = {"userId": "alice", "agentName": "agent-a"}
    try:

        def write(index: int) -> None:
            adapter.upsert(_fact(f"fact-{index}", f"concurrent memory item {index}"), scope=scope, path="")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(20)))
        results = adapter.search("concurrent memory", scopes=[scope], top_k=20, mode="hybrid", filters=None)
        assert {item["fact"]["id"] for item in results} == {f"fact-{index}" for index in range(20)}
    finally:
        adapter.close()


def test_deermem_create_and_restart_use_retrieval_adapter(tmp_path: Path) -> None:
    config = {"storage_path": str(tmp_path), "token_counting": "char"}
    manager = DeerMem(backend_config=config)
    _, fact_id = manager.create_fact("BM25 retrieval survives restart", category="knowledge", user_id="alice")
    assert fact_id is not None
    assert any(fact["id"] == fact_id for fact in manager.search("retrieval BM25", user_id="alice"))

    restarted = DeerMem(backend_config=config)
    assert any(fact["id"] == fact_id for fact in restarted.search("restart retrieval", user_id="alice"))
