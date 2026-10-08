"""DeerMem retrieval-index placement and cross-instance freshness.

Several Gateway instances (Kubernetes Pods) can share one ``storage_path`` on a
ReadWriteMany home volume. The derived SQLite FTS5 index used to be pinned to
``{storage_path}/.retrieval``: one WAL database that every instance opened over
the network filesystem, emptied and refilled at every start, and deleted from
under its peers on any instance's corruption recovery. An instance also never
learned that a peer had written a user's facts, so its index served stale
results. These tests pin ``memory.backend_config.retrieval_index_path`` and the
manifest-signature re-sync that makes a peer's write visible on the next search
without rebuilding a scope this process wrote itself.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.retrieval import FTS5RetrievalAdapter, create_fts5_retrieval
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage, MemoryStorageCorruption, create_empty_memory

INDEX_FILENAME = "memory-fts5.sqlite3"
SCOPE = {"userId": "alice", "agentName": "agent-a"}


def _fact(fact_id: str, content: str) -> dict:
    return {
        "id": fact_id,
        "content": content,
        "category": "context",
        "confidence": 0.8,
        "createdAt": "2026-10-01T00:00:00Z",
        "source": {"type": "test", "threadId": None},
    }


def _ids(results: list[dict]) -> list[str]:
    return [item["fact"]["id"] for item in results]


def _instance(storage_root: Path, index_dir: Path) -> FileMemoryStorage:
    """One Gateway instance: shared canonical storage, its own derived index."""
    index_dir.mkdir(parents=True, exist_ok=True)
    return FileMemoryStorage(DeerMemConfig(storage_path=str(storage_root)), retrieval=FTS5RetrievalAdapter(index_dir / INDEX_FILENAME))


# ── retrieval_index_path ─────────────────────────────────────────────────────


def test_absolute_retrieval_index_path_places_the_index_outside_storage_path(tmp_path: Path) -> None:
    storage_root = tmp_path / "home"
    index_dir = tmp_path / "pod-local-index"
    adapter = create_fts5_retrieval(DeerMemConfig(storage_path=str(storage_root), retrieval_index_path=str(index_dir)))
    assert adapter is not None
    try:
        assert (index_dir / INDEX_FILENAME).is_file()
        assert not (storage_root / ".retrieval").exists()
    finally:
        adapter.close()


def test_relative_retrieval_index_path_resolves_against_storage_path(tmp_path: Path) -> None:
    adapter = create_fts5_retrieval(DeerMemConfig(storage_path=str(tmp_path), retrieval_index_path="index/local"))
    assert adapter is not None
    try:
        assert (tmp_path / "index" / "local" / INDEX_FILENAME).is_file()
        assert not (tmp_path / ".retrieval").exists()
    finally:
        adapter.close()


def test_default_retrieval_index_path_is_unchanged(tmp_path: Path) -> None:
    adapter = create_fts5_retrieval(DeerMemConfig(storage_path=str(tmp_path)))
    assert adapter is not None
    try:
        assert (tmp_path / ".retrieval" / INDEX_FILENAME).is_file()
    finally:
        adapter.close()


def test_corruption_recovery_touches_only_the_configured_index(tmp_path: Path) -> None:
    """A Pod recreating its own corrupt index must not delete files a peer holds open."""
    storage_root = tmp_path / "home"
    index_dir = tmp_path / "pod-local-index"
    index_dir.mkdir()
    (index_dir / INDEX_FILENAME).write_bytes(b"not a sqlite database")
    shared_index = storage_root / ".retrieval" / INDEX_FILENAME
    shared_index.parent.mkdir(parents=True)
    shared_index.write_bytes(b"a peer's file, must survive")

    adapter = create_fts5_retrieval(DeerMemConfig(storage_path=str(storage_root), retrieval_index_path=str(index_dir)))

    assert adapter is not None
    try:
        assert shared_index.read_bytes() == b"a peer's file, must survive"
        adapter.upsert(_fact("recovered", "recreated local index"), scope=SCOPE, path="")
        assert _ids(adapter.search("recreated", scopes=[SCOPE], top_k=5, mode="fts5", filters=None)) == ["recovered"]
    finally:
        adapter.close()


# ── cross-instance freshness ─────────────────────────────────────────────────


def test_search_sees_facts_a_peer_instance_wrote(tmp_path: Path) -> None:
    """Two Pods, one storage_path, one Pod-local index each: a write lands in the other Pod's next search."""
    storage_root = tmp_path / "home"
    pod_a = _instance(storage_root, tmp_path / "index-a")
    pod_b = _instance(storage_root, tmp_path / "index-b")
    try:
        assert pod_a.rebuild_index()["failed"] == 0  # startup warm-up on both Pods
        assert pod_b.rebuild_index()["failed"] == 0

        pod_a.upsert_fact(_fact("one", "alpha written on pod a"), user_id="alice", agent_name="agent-a")
        assert _ids(pod_b.search_facts("alpha", scopes=[SCOPE])) == ["one"]

        pod_b.upsert_fact(_fact("two", "beta written on pod b"), user_id="alice", agent_name="agent-a")
        assert _ids(pod_a.search_facts("beta", scopes=[SCOPE])) == ["two"]
        assert _ids(pod_a.search_facts("alpha", scopes=[SCOPE])) == ["one"]
    finally:
        pod_a.close()
        pod_b.close()


def test_search_drops_facts_a_peer_instance_deleted(tmp_path: Path) -> None:
    storage_root = tmp_path / "home"
    pod_a = _instance(storage_root, tmp_path / "index-a")
    pod_b = _instance(storage_root, tmp_path / "index-b")
    try:
        pod_a.upsert_fact(_fact("one", "alpha written on pod a"), user_id="alice", agent_name="agent-a")
        assert pod_b.rebuild_index()["failed"] == 0
        assert _ids(pod_b.search_facts("alpha", scopes=[SCOPE])) == ["one"]

        pod_a.delete_fact("one", user_id="alice", agent_name="agent-a")

        assert pod_b.search_facts("alpha", scopes=[SCOPE]) == []
    finally:
        pod_a.close()
        pod_b.close()


def test_own_writes_do_not_rebuild_a_scope_this_instance_indexed(tmp_path: Path) -> None:
    """Incremental notifications already cover this process's writes; only a peer's write costs a rebuild."""
    storage_root = tmp_path / "home"
    pod = _instance(storage_root, tmp_path / "index-a")
    try:
        pod.upsert_fact(_fact("one", "alpha indexed before warm-up"), user_id="alice", agent_name="agent-a")
        assert pod.rebuild_index()["failed"] == 0

        with patch.object(pod, "rebuild_index", wraps=pod.rebuild_index) as rebuild:
            assert _ids(pod.search_facts("alpha", scopes=[SCOPE])) == ["one"]
            pod.upsert_fact(_fact("two", "beta written here"), user_id="alice", agent_name="agent-a")
            assert _ids(pod.search_facts("beta", scopes=[SCOPE])) == ["two"]
            # Summary updates and writes to another agent bump the shared user manifest too.
            summaries = create_empty_memory()
            summaries["user"]["workContext"]["summary"] = "works on deployments"
            assert pod.save(summaries, user_id="alice")
            pod.upsert_fact(_fact("three", "gamma for another agent"), user_id="alice", agent_name="agent-b")
            assert _ids(pod.search_facts("alpha", scopes=[SCOPE])) == ["one"]
            pod.delete_fact("two", user_id="alice", agent_name="agent-a")
            assert pod.search_facts("beta", scopes=[SCOPE]) == []

        assert rebuild.call_count == 0
    finally:
        pod.close()


def test_peer_write_between_own_sync_and_own_write_still_rebuilds(tmp_path: Path) -> None:
    """An own write must not paper over a peer write that landed since this instance last synced."""
    storage_root = tmp_path / "home"
    pod_a = _instance(storage_root, tmp_path / "index-a")
    pod_b = _instance(storage_root, tmp_path / "index-b")
    try:
        assert pod_a.rebuild_index()["failed"] == 0
        assert pod_b.rebuild_index()["failed"] == 0
        pod_a.upsert_fact(_fact("one", "alpha written on pod a"), user_id="alice", agent_name="agent-a")
        pod_b.upsert_fact(_fact("two", "beta written on pod b"), user_id="alice", agent_name="agent-a")

        assert set(_ids(pod_b.search_facts("alpha OR beta", scopes=[SCOPE], mode="fts5"))) == {"one", "two"}
    finally:
        pod_a.close()
        pod_b.close()


def test_deermem_instances_with_pod_local_indexes_see_each_other(tmp_path: Path) -> None:
    storage_root = tmp_path / "home"

    def pod(index_name: str) -> DeerMem:
        return DeerMem(backend_config={"storage_path": str(storage_root), "retrieval_index_path": str(tmp_path / index_name), "token_counting": "char"})

    pod_a = pod("index-a")
    pod_b = pod("index-b")
    try:
        assert pod_a.warm_retrieval()
        assert pod_b.warm_retrieval()

        _, fact_id = pod_a.create_fact("pod a remembers the deployment region", user_id="alice")
        assert [fact["id"] for fact in pod_b.search("deployment region", user_id="alice")] == [fact_id]

        assert (tmp_path / "index-a" / INDEX_FILENAME).is_file()
        assert (tmp_path / "index-b" / INDEX_FILENAME).is_file()
        assert not (storage_root / ".retrieval").exists()
    finally:
        pod_a.close()
        pod_b.close()


@pytest.mark.parametrize("no_op", ["unchanged_patch", "identical_save"])
def test_no_op_commit_after_a_peer_delete_does_not_mask_the_deletion(tmp_path: Path, no_op: str) -> None:
    """A commit that changes nothing must not advance the synced signature past a peer's write.

    Pod A indexed f1/f2 at revision r; Pod B deleted f2 (r+1); A then applies a
    supported update to f1 that turns out to be a no-op. The commit helper hands
    back the unchanged manifest, so inferring "previous revision = r" from it
    would mark A's stale index as in sync at r+1 and keep returning f2 forever.
    """
    storage_root = tmp_path / "home"
    pod_a = _instance(storage_root, tmp_path / "index-a")
    pod_b = _instance(storage_root, tmp_path / "index-b")
    try:
        pod_a.apply_changes({"upserts": [_fact("f1", "alpha stays"), _fact("f2", "beta goes away")]}, user_id="alice", agent_name="agent-a")
        assert pod_a.rebuild_index()["failed"] == 0
        assert _ids(pod_a.search_facts("beta", scopes=[SCOPE])) == ["f2"]

        pod_b.delete_fact("f2", user_id="alice", agent_name="agent-a")

        if no_op == "unchanged_patch":
            stored = pod_a.get_fact("f1", user_id="alice", agent_name="agent-a")
            assert stored is not None
            result = pod_a.upsert_fact(stored, user_id="alice", agent_name="agent-a", expected_fact_revision=stored["revision"])
            assert result["upsertedFacts"] == [], "the unchanged-value patch must be a no-op commit"
        else:
            assert pod_a.save(pod_a.load("agent-a", user_id="alice"), "agent-a", user_id="alice")

        assert pod_a.search_facts("beta", scopes=[SCOPE]) == []
        assert _ids(pod_a.search_facts("alpha", scopes=[SCOPE])) == ["f1"]
    finally:
        pod_a.close()
        pod_b.close()


def test_scoped_resync_indexes_every_fact_of_a_large_scope(tmp_path: Path) -> None:
    """The re-sync must read the whole scope, not the first page of 100 facts.

    With 150 facts (max_facts allows up to 500) both Pods start complete. A
    peer's summary-only save changes the manifest signature; A's next search
    rebuilds the scope and must still hold all 150 facts afterwards.
    """
    storage_root = tmp_path / "home"
    config = DeerMemConfig(storage_path=str(storage_root), max_facts=200)
    (tmp_path / "index-a").mkdir()
    (tmp_path / "index-b").mkdir()
    pod_a = FileMemoryStorage(config, retrieval=FTS5RetrievalAdapter(tmp_path / "index-a" / INDEX_FILENAME))
    pod_b = FileMemoryStorage(config, retrieval=FTS5RetrievalAdapter(tmp_path / "index-b" / INDEX_FILENAME))
    try:
        facts = [_fact(f"fact-{index:03d}", f"zeta common memory number {index:03d} unique{index:03d}") for index in range(1, 151)]
        pod_a.apply_changes({"upserts": facts}, user_id="alice", agent_name="agent-a")
        assert pod_a.rebuild_index()["failed"] == 0
        assert pod_b.rebuild_index()["failed"] == 0
        assert _ids(pod_a.search_facts("unique150", scopes=[SCOPE])) == ["fact-150"]

        summaries = create_empty_memory()
        summaries["user"]["workContext"]["summary"] = "peer summary refresh"
        assert pod_b.save(summaries, user_id="alice")

        assert _ids(pod_a.search_facts("unique150", scopes=[SCOPE])) == ["fact-150"]
        assert _ids(pod_a.search_facts("unique001", scopes=[SCOPE])) == ["fact-001"]
        assert len(pod_a.search_facts("zeta", scopes=[SCOPE], top_k=200)) == 150
    finally:
        pod_a.close()
        pod_b.close()


class _PausableAdapter:
    """FTS5 adapter whose next bulk install and every remove can be held at a chosen point.

    With ``pause_after_next_install`` armed, ``rebuild`` performs the real
    install, signals ``installed`` and waits for ``allow_publish`` before
    returning, which holds the owning rebuild between its row replacement and
    its signature publication (one call; later rebuilds run unpaused).
    ``remove`` performs the real removal, signals ``removed`` and waits for
    ``allow_promote`` before returning, which holds the owning write after its
    adapter notification and before its signature promotion.
    """

    def __init__(self, inner: FTS5RetrievalAdapter) -> None:
        self._inner = inner
        self.pause_after_next_install = False
        self.installed = threading.Event()
        self.allow_publish = threading.Event()
        self.removed = threading.Event()
        self.allow_promote = threading.Event()

    def rebuild(self, records, *, scopes):
        self._inner.rebuild(records, scopes=scopes)
        if self.pause_after_next_install:
            self.pause_after_next_install = False
            self.installed.set()
            assert self.allow_publish.wait(10), "test orchestration stalled before the signature publication"

    def remove(self, fact_id, *, scope):
        self._inner.remove(fact_id, scope=scope)
        self.removed.set()
        assert self.allow_promote.wait(10), "test orchestration stalled before the signature promotion"

    def release(self) -> None:
        self.allow_publish.set()
        self.allow_promote.set()

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class _ReadHold:
    """Hold one scoped refresh after it has read the scope's facts and before it installs them.

    The scoped ``rebuild_index`` captures the manifest signature, reads the
    facts through ``load()`` and only then replaces the index rows, so holding
    here models a refresh that carries a snapshot taken before later writes.
    """

    def __init__(self, storage: FileMemoryStorage) -> None:
        self.at_read = threading.Event()
        self.allow_install = threading.Event()
        self.armed = True
        real_load = storage.load

        def load(*args, **kwargs):
            document = real_load(*args, **kwargs)
            if self.armed:
                self.armed = False
                self.at_read.set()
                assert self.allow_install.wait(10), "test orchestration stalled before the index install"
            return document

        storage.load = load  # type: ignore[method-assign]


def _run(target: Callable[[], object], errors: list[BaseException]) -> threading.Thread:
    def body() -> None:
        try:
            target()
        except BaseException as exc:  # noqa: BLE001 - surfaced through the errors list
            errors.append(exc)

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def _join(thread: threading.Thread, errors: list[BaseException]) -> None:
    thread.join(10)
    assert not thread.is_alive(), "worker thread did not finish"
    assert errors == []


def _racing_pods(tmp_path: Path) -> tuple[FileMemoryStorage, _PausableAdapter, FileMemoryStorage, _ReadHold]:
    """Warmed Pod A with a pausable index, peer Pod B, and A's next scoped refresh held after its fact read."""
    storage_root = tmp_path / "home"
    (tmp_path / "index-a").mkdir()
    adapter = _PausableAdapter(FTS5RetrievalAdapter(tmp_path / "index-a" / INDEX_FILENAME))
    pod_a = FileMemoryStorage(DeerMemConfig(storage_path=str(storage_root)), retrieval=adapter)  # type: ignore[arg-type]
    pod_b = _instance(storage_root, tmp_path / "index-b")
    pod_a.apply_changes({"upserts": [_fact("f1", "alpha stays"), _fact("f2", "beta goes away")]}, user_id="alice", agent_name="agent-a")
    assert pod_a.rebuild_index()["failed"] == 0
    summaries = create_empty_memory()
    summaries["user"]["workContext"]["summary"] = "peer summary refresh"
    assert pod_b.save(summaries, user_id="alice")  # r+1 on the shared manifest: A's next search re-syncs
    return pod_a, adapter, pod_b, _ReadHold(pod_a)


def test_promotion_is_fenced_against_a_refresh_that_installs_in_between(tmp_path: Path) -> None:
    """Reviewer interleaving: refresh reads f1/f2, own delete removes f2, refresh installs, delete promotes.

    The refresh captured the r+1 signature and the facts before the deletion
    committed r+2. Its install resurrects f2; promoting the deletion's r+2
    signature afterwards would declare that stale index in sync with the live
    manifest and keep returning f2 until the next manifest change.
    """
    pod_a, adapter, pod_b, hold = _racing_pods(tmp_path)
    errors: list[BaseException] = []
    try:
        refresh = _run(lambda: pod_a.search_facts("alpha", scopes=[SCOPE]), errors)
        assert hold.at_read.wait(10)  # refresh holds f1/f2 read at r+1, not yet installed

        deletion = _run(lambda: pod_a.delete_fact("f2", user_id="alice", agent_name="agent-a"), errors)
        assert adapter.removed.wait(10)  # r+2 committed, index row removed, promotion pending

        hold.allow_install.set()  # stale install resurrects f2 and records the r+1 signature
        _join(refresh, errors)
        adapter.allow_promote.set()  # the deletion must not stamp that index as r+2
        _join(deletion, errors)

        assert pod_a.search_facts("beta", scopes=[SCOPE]) == []
        assert _ids(pod_a.search_facts("alpha", scopes=[SCOPE])) == ["f1"]
    finally:
        hold.allow_install.set()
        adapter.release()
        pod_a.close()
        pod_b.close()


def test_stale_refresh_installing_after_a_promotion_is_caught_by_the_next_search(tmp_path: Path) -> None:
    """Mirrored order: the promotion lands first, then a stale refresh installs f1/f2.

    The stale refresh records the r+1 signature it captured, so the next search
    sees it differ from the live r+2 manifest and rebuilds the scope.
    """
    pod_a, adapter, pod_b, hold = _racing_pods(tmp_path)
    errors: list[BaseException] = []
    try:
        stale_refresh = _run(lambda: pod_a.search_facts("alpha", scopes=[SCOPE]), errors)
        assert hold.at_read.wait(10)
        assert pod_a.rebuild_index([SCOPE])["failed"] == 0  # a second, unpaused refresh syncs the scope at r+1

        adapter.allow_promote.set()
        pod_a.delete_fact("f2", user_id="alice", agent_name="agent-a")  # r+2: removes the row and promotes r+1 -> r+2
        assert pod_a.search_facts("beta", scopes=[SCOPE]) == []

        hold.allow_install.set()  # the stale install resurrects f2 under its own r+1 signature
        _join(stale_refresh, errors)

        assert pod_a.search_facts("beta", scopes=[SCOPE]) == []
        assert _ids(pod_a.search_facts("alpha", scopes=[SCOPE])) == ["f1"]
    finally:
        hold.allow_install.set()
        adapter.release()
        pod_a.close()
        pod_b.close()


def test_rebuild_publication_stays_ordered_with_row_replacement(tmp_path: Path) -> None:
    """Reviewer interleaving: two refreshes install in one order and would publish in the other.

    R1 captures r+1 with f1/f2 and is held before installing. A peer deletes f2
    (r+2). R2 captures r+2, installs f1 only and is held before publishing. R1
    then installs its stale f1/f2 and publishes r+1; R2 publishes r+2 last.
    Without serializing install+publish, R2's live-matching signature certifies
    R1's stale rows and the deleted f2 is returned until the manifest changes.
    """
    pod_a, adapter, pod_b, hold = _racing_pods(tmp_path)
    errors: list[BaseException] = []
    try:
        first = _run(lambda: pod_a.search_facts("alpha", scopes=[SCOPE]), errors)
        assert hold.at_read.wait(10)  # R1 holds f1/f2 read at r+1

        pod_b.delete_fact("f2", user_id="alice", agent_name="agent-a")  # r+2

        adapter.pause_after_next_install = True
        second = _run(lambda: pod_a.search_facts("alpha", scopes=[SCOPE]), errors)
        assert adapter.installed.wait(10)  # R2 installed f1 at r+2, publication pending

        hold.allow_install.set()  # R1 proceeds: with install+publish serialized it waits for R2; unfixed, it installs f1/f2 and publishes r+1 now
        first.join(1.5)
        adapter.allow_publish.set()  # R2 publishes r+2
        _join(second, errors)
        _join(first, errors)

        assert pod_a.search_facts("beta", scopes=[SCOPE]) == []
        assert _ids(pod_a.search_facts("alpha", scopes=[SCOPE])) == ["f1"]
    finally:
        hold.allow_install.set()
        adapter.release()
        pod_a.close()
        pod_b.close()


def test_full_rebuild_reads_each_manifest_once(tmp_path: Path) -> None:
    """Every agent bucket of a user shares one memory.json; the startup scan must not re-read it per bucket."""
    pod = _instance(tmp_path / "home", tmp_path / "index-a")
    try:
        for agent in ("agent-a", "agent-b", "agent-c"):
            pod.upsert_fact(_fact(f"{agent}-fact", f"fact for {agent}"), user_id="alice", agent_name=agent)
        pod.upsert_fact(_fact("bob-fact", "fact for bob"), user_id="bob", agent_name="agent-a")

        with patch.object(pod, "_load_memory_file", wraps=pod._load_memory_file) as manifest_reads:
            result = pod.rebuild_index()

        assert result == {"supported": True, "indexed": 4, "failed": 0}
        read_paths = sorted({call.args[0] for call in manifest_reads.call_args_list})
        assert read_paths == [pod._get_memory_file_path(user_id="alice"), pod._get_memory_file_path(user_id="bob")]
        assert manifest_reads.call_count == 2, "one manifest read per user, not per agent bucket"
        for agent in ("agent-a", "agent-b", "agent-c"):
            assert _ids(pod.search_facts(f"{agent}", scopes=[{"userId": "alice", "agentName": agent}])) == [f"{agent}-fact"]
    finally:
        pod.close()


@pytest.mark.parametrize("failure", [OSError("stale NFS handle"), MemoryStorageCorruption("malformed memory.json")])
def test_manifest_read_failure_during_the_freshness_compare_serves_the_local_index(tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: Exception) -> None:
    """The Pod-local index exists to decouple search from the shared volume.

    A transient read error or a corrupt manifest during the per-search compare
    must log and serve the current index, leave the recorded signature alone
    (no dirty mark: a rebuild would hit the same read), and let the next search
    compare normally.
    """
    storage_root = tmp_path / "home"
    pod_a = _instance(storage_root, tmp_path / "index-a")
    pod_b = _instance(storage_root, tmp_path / "index-b")
    key = ("alice", "agent-a")
    try:
        pod_a.upsert_fact(_fact("one", "alpha indexed locally"), user_id="alice", agent_name="agent-a")
        assert pod_a.rebuild_index()["failed"] == 0
        synced_before = pod_a._retrieval_synced_signatures[key]

        with patch.object(pod_a, "_load_memory_file", side_effect=failure), patch.object(pod_a, "rebuild_index", wraps=pod_a.rebuild_index) as rebuild, caplog.at_level(logging.WARNING):
            assert _ids(pod_a.search_facts("alpha", scopes=[SCOPE])) == ["one"]

        assert rebuild.call_count == 0
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING and "agent-a" in record.getMessage()]
        assert warnings, "the skipped compare must be visible to operators"
        assert pod_a._retrieval_synced_signatures[key] == synced_before
        assert key not in pod_a._retrieval_dirty_scopes

        pod_b.upsert_fact(_fact("two", "beta written on pod b"), user_id="alice", agent_name="agent-a")
        assert _ids(pod_a.search_facts("beta", scopes=[SCOPE])) == ["two"]  # the compare works again and re-syncs
    finally:
        pod_a.close()
        pod_b.close()
