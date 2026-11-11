"""Completed fact edits must survive overlapping retrieval publications."""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem


@pytest.mark.parametrize("publication", ["refresh", "install", "delta"])
@pytest.mark.parametrize("mutation", ["delete", "update"])
def test_search_after_completed_write_ignores_stale_publication(tmp_path: Path, publication: str, mutation: str) -> None:
    def pod(index: str) -> DeerMem:
        return DeerMem(backend_config={"storage_path": str(tmp_path / "home"), "retrieval_index_path": str(tmp_path / index), "token_counting": "char"})

    pod_a, pod_b = pod("index-a"), pod("index-b")
    scope = {"user_id": "alice", "agent_name": "agent-a"}
    at_old, allow_old = threading.Event(), threading.Event()
    at_freshness, allow_freshness = threading.Event(), threading.Event()
    installed, allow_publication, queried = threading.Event(), threading.Event(), threading.Event()
    errors: list[BaseException] = []
    observed: list[dict] = []
    workers: list[threading.Thread] = []

    def start(name, function):
        def body():
            try:
                function()
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=body, name=name, daemon=True)
        workers.append(worker)
        worker.start()
        return worker

    try:
        _, keep_id = pod_a.create_fact("alpha deployment remains", **scope)
        _, deleted_id = pod_a.create_fact("beta retired deployment", **scope)
        assert deleted_id and keep_id
        assert pod_a.warm_retrieval() and pod_b.warm_retrieval()
        real_load = pod_a._storage.load
        real_upsert = pod_a._storage._retrieval.upsert
        real_signature = pod_a._storage._scope_signature
        real_rebuild = pod_a._storage._retrieval.rebuild
        real_search = pod_a._storage._retrieval.search

        def held_load(*args, **kwargs):
            document = real_load(*args, **kwargs)
            if publication != "delta" and threading.current_thread().name == "old-publication":
                at_old.set()
                assert allow_old.wait(10), "stalled before old index install"
            return document

        def held_upsert(*args, **kwargs):
            if publication == "delta" and threading.current_thread().name == "old-publication":
                at_old.set()
                assert allow_old.wait(10), "stalled before old delta replay"
            return real_upsert(*args, **kwargs)

        def held_signature(*args, **kwargs):
            signature = real_signature(*args, **kwargs)
            if threading.current_thread().name == "target-search":
                at_freshness.set()
                assert allow_freshness.wait(10), "stalled after live signature read"
            return signature

        def held_rebuild(*args, **kwargs):
            real_rebuild(*args, **kwargs)
            if publication == "install" and threading.current_thread().name == "old-publication":
                installed.set()
                assert allow_publication.wait(10), "stalled after row installation"

        def observed_search(*args, **kwargs):
            results = real_search(*args, **kwargs)
            if threading.current_thread().name == "target-search":
                queried.set()
            return results

        with (
            patch.object(pod_a._storage, "load", side_effect=held_load),
            patch.object(pod_a._storage._retrieval, "upsert", side_effect=held_upsert),
            patch.object(pod_a._storage, "_scope_signature", side_effect=held_signature),
            patch.object(pod_a._storage._retrieval, "rebuild", side_effect=held_rebuild),
            patch.object(pod_a._storage._retrieval, "search", side_effect=observed_search),
        ):
            if publication != "delta":
                pod_b.update_fact(keep_id, content="alpha current deployment", **scope)
                stale = start("old-publication", lambda: pod_a.reload_memory(**scope))
            else:
                stale = start("old-publication", lambda: pod_a.update_fact(deleted_id, content="beta delayed older update", **scope))
            assert at_old.wait(10)
            # The public peer write completes, then A demonstrably sees it.
            if mutation == "delete":
                pod_b.delete_fact(deleted_id, **scope)
            else:
                pod_b.update_fact(deleted_id, content="gamma replacement deployment", **scope)
            assert pod_a.search("beta", **scope) == []
            target = start("target-search", lambda: observed.extend(pod_a.search("beta", **scope)))
            assert at_freshness.wait(10)
            allow_old.set()
            if publication == "install":
                assert installed.wait(10)
                allow_freshness.set()
                assert queried.wait(10)
                allow_publication.set()
            else:
                stale.join(10)
                assert not stale.is_alive()
                allow_freshness.set()
            stale.join(10)
            assert not stale.is_alive()
            target.join(10)
            assert not target.is_alive()
        assert not errors
        assert at_old.is_set() and at_freshness.is_set(), "both scheduling gates must fire"
        canonical = pod_a._storage.get_fact(deleted_id, **scope)
        if mutation == "delete":
            assert canonical is None
        else:
            assert canonical["content"] == "gamma replacement deployment"
        subsequent = pod_a.search("beta", **scope)
        assert subsequent == []
        assert [fact["id"] for fact in pod_a.search("alpha", **scope)] == [keep_id]
        if mutation == "update":
            assert [fact["id"] for fact in pod_a.search("gamma", **scope)] == [deleted_id]
        assert observed == [], "search started after completed write returned a stale indexed fact"
    finally:
        allow_old.set()
        allow_freshness.set()
        allow_publication.set()
        for worker in workers:
            worker.join(10)
            assert not worker.is_alive(), "worker did not finish during cleanup"
        pod_a.close()
        pod_b.close()


@pytest.mark.parametrize("mutation", ["delete", "update"])
def test_search_during_an_unpublished_delta_uses_canonical_facts(tmp_path: Path, mutation: str) -> None:
    def pod(index: str) -> DeerMem:
        return DeerMem(backend_config={"storage_path": str(tmp_path / "home"), "retrieval_index_path": str(tmp_path / index), "token_counting": "char"})

    pod_a, pod_b = pod("index-a"), pod("index-b")
    scope = {"user_id": "alice", "agent_name": "agent-a"}
    before, allow_mutation = threading.Event(), threading.Event()
    after, allow_publication = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    worker = None
    try:
        _, fact_id = pod_a.create_fact("beta old deployment", **scope)
        assert fact_id and pod_a.warm_retrieval() and pod_b.warm_retrieval()
        real_upsert = pod_a._storage._retrieval.upsert

        def held_upsert(*args, **kwargs):
            before.set()
            assert allow_mutation.wait(10), "stalled before adapter mutation"
            real_upsert(*args, **kwargs)
            after.set()
            assert allow_publication.wait(10), "stalled before signature publication"

        def update():
            try:
                pod_a.update_fact(fact_id, content="beta pending old deployment", **scope)
            except BaseException as exc:
                errors.append(exc)

        with patch.object(pod_a._storage._retrieval, "upsert", side_effect=held_upsert):
            worker = threading.Thread(target=update, daemon=True)
            worker.start()
            assert before.wait(10)
            if mutation == "delete":
                pod_b.delete_fact(fact_id, **scope)
            else:
                pod_b.update_fact(fact_id, content="gamma replacement deployment", **scope)
            assert pod_a.search("beta", **scope) == []
            allow_mutation.set()
            assert after.wait(10)
            # The stale row is now installed, but its dispatcher cannot finish.
            # This search must finish with canonical data without waiting for it.
            observed = pod_a.search("beta", **scope)
            if mutation == "update":
                assert [fact["id"] for fact in pod_a.search("gamma", **scope)] == [fact_id]
            allow_publication.set()
            worker.join(10)
            assert not worker.is_alive() and not errors
        assert before.is_set() and after.is_set()
        assert observed == [], "an in-flight old delta was mistaken for the fresh index"
    finally:
        allow_mutation.set()
        allow_publication.set()
        if worker is not None:
            worker.join(10)
            assert not worker.is_alive(), "worker did not finish during cleanup"
        pod_a.close()
        pod_b.close()


@pytest.mark.parametrize("user_id,agent_name", [("alice", "agent-b"), ("bob", "agent-a")])
def test_pending_notification_does_not_degrade_another_scope(tmp_path: Path, user_id: str, agent_name: str) -> None:
    memory = DeerMem(backend_config={"storage_path": str(tmp_path / "home"), "token_counting": "char"})
    scope = {"user_id": user_id, "agent_name": agent_name}
    entered, release = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    worker = None
    try:
        _, pending_id = memory.create_fact("beta source deployment", user_id="alice", agent_name="agent-a")
        _, wanted_id = memory.create_fact("alpha target deployment", **scope)
        assert pending_id and wanted_id and memory.warm_retrieval()
        real_upsert = memory._storage._retrieval.upsert

        def held_upsert(*args, **kwargs):
            real_upsert(*args, **kwargs)
            entered.set()
            assert release.wait(10), "stalled before notification publication"

        def update():
            try:
                memory.update_fact(pending_id, content="beta changed deployment", user_id="alice", agent_name="agent-a")
            except BaseException as exc:
                errors.append(exc)

        with patch.object(memory._storage._retrieval, "upsert", side_effect=held_upsert):
            worker = threading.Thread(target=update, daemon=True)
            worker.start()
            assert entered.wait(10)
            # An advanced FTS query has no literal substring match, so this
            # also detects an unnecessary fallback caused by the other scope.
            assert [fact["id"] for fact in memory.search("alpha OR omega", **scope)] == [wanted_id]
            release.set()
            worker.join(10)
            assert not worker.is_alive() and not errors
    finally:
        release.set()
        if worker is not None:
            worker.join(10)
            assert not worker.is_alive(), "worker did not finish during cleanup"
        memory.close()
