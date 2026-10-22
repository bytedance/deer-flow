"""Async tracing owns fingerprint I/O and exporter cleanup without blocking its loop."""

import asyncio
import threading
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def selected_file_snapshot(tmp_path, monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import RunTracingSnapshot, current_monocle_fingerprint

    credentials = tmp_path / "fake-google-credentials.json"
    await asyncio.to_thread(credentials.write_text, '{"type":"test-only","private_key":"not-a-real-key"}', encoding="utf-8")
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "gcs")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credentials))
    for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    reset_tracing_config()
    fingerprint = await asyncio.to_thread(current_monocle_fingerprint)
    snapshot = RunTracingSnapshot(snapshot_id="selected-file", owner_user_id="alice", agent_name="lead_agent", mode="inherit", revision="1", providers=(), monocle_enabled=True, monocle_fingerprint=fingerprint)
    yield snapshot, credentials
    reset_tracing_config()


async def _entered(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 3), timeout=4)


def _block_selected_read(monkeypatch, credentials, loop_thread, entered, release):
    original = Path.read_bytes

    def read(path):
        if path == credentials:
            assert threading.get_ident() != loop_thread, "fingerprint read blocked the event-loop thread"
            entered.set()
            assert release.wait(5)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)


@pytest.mark.asyncio
async def test_fingerprint_read_and_close_are_off_loop_but_context_activation_stays_on_caller_task(selected_file_snapshot, monkeypatch):
    from deerflow.tracing import scoped

    snapshot, credentials = selected_file_snapshot
    loop_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    _block_selected_read(monkeypatch, credentials, loop_thread, entered, release)
    closed = []
    original_close = scoped.TracingSession.close

    def close(session):
        assert threading.get_ident() != loop_thread
        closed.append(scoped.get_current_snapshot())
        original_close(session)

    monkeypatch.setattr(scoped.TracingSession, "close", close)

    async def run():
        caller = asyncio.current_task()
        async with scoped.async_tracing_scope(snapshot):
            assert asyncio.current_task() is caller
            assert threading.get_ident() == loop_thread
            assert scoped.get_current_snapshot() is snapshot
        assert scoped.get_current_snapshot() is None

    task = asyncio.create_task(run())
    try:
        await _entered(entered)
        marker = asyncio.Event()
        asyncio.get_running_loop().call_soon(marker.set)
        await asyncio.wait_for(marker.wait(), 1)
        assert not task.done()
        assert scoped.get_current_snapshot() is None
    finally:
        release.set()
        await task
    assert closed == [None]


@pytest.mark.asyncio
async def test_cancelled_construction_is_drained_then_closes_the_unactivated_session(selected_file_snapshot, monkeypatch):
    from deerflow.tracing import scoped

    snapshot, credentials = selected_file_snapshot
    loop_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    _block_selected_read(monkeypatch, credentials, loop_thread, entered, release)
    closed = []
    original_close = scoped.TracingSession.close

    def close(session):
        assert threading.get_ident() != loop_thread
        assert scoped.get_current_snapshot() is None
        closed.append(session)
        original_close(session)

    monkeypatch.setattr(scoped.TracingSession, "close", close)

    async def run():
        async with scoped.async_tracing_scope(snapshot):
            pytest.fail("cancelled initialization must not enter the scope body")

    task = asyncio.create_task(run())
    try:
        await _entered(entered)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(closed) == 1 and closed[0]._closed
    assert scoped.get_current_snapshot() is None


@pytest.mark.asyncio
async def test_cancelled_close_keeps_ownership_until_its_worker_finishes(selected_file_snapshot, monkeypatch):
    from deerflow.tracing import scoped

    snapshot, _ = selected_file_snapshot
    loop_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()
    original_close = scoped.TracingSession.close
    closed = []

    def close(session):
        assert threading.get_ident() != loop_thread
        assert scoped.get_current_snapshot() is None
        entered.set()
        assert release.wait(5)
        original_close(session)
        closed.append(session)

    monkeypatch.setattr(scoped.TracingSession, "close", close)

    async def run():
        async with scoped.async_tracing_scope(snapshot):
            assert scoped.get_current_snapshot() is snapshot

    task = asyncio.create_task(run())
    try:
        await _entered(entered)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        marker = asyncio.Event()
        asyncio.get_running_loop().call_soon(marker.set)
        await asyncio.wait_for(marker.wait(), 1)
        assert not task.done()
        assert closed == []
        assert scoped.get_current_snapshot() is None
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(closed) == 1 and closed[0]._closed


@pytest.mark.asyncio
async def test_body_cancellation_restores_parent_context_before_offloaded_cleanup(selected_file_snapshot, monkeypatch):
    from deerflow.tracing import scoped

    parent, _ = selected_file_snapshot
    child = parent.model_copy(update={"snapshot_id": "nested-child"})
    body_entered = asyncio.Event()

    async def run():
        async with scoped.async_tracing_scope(parent):
            assert scoped.get_current_snapshot() is parent
            try:
                async with scoped.async_tracing_scope(child):
                    assert scoped.get_current_snapshot() is child
                    body_entered.set()
                    await asyncio.Event().wait()
            finally:
                assert scoped.get_current_snapshot() is parent

    task = asyncio.create_task(run())
    await asyncio.wait_for(body_entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert scoped.get_current_snapshot() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["worker", "compaction"])
async def test_async_entrypoints_keep_selected_credential_reads_off_loop(selected_file_snapshot, monkeypatch, entrypoint):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.tracing.scoped import get_current_snapshot

    snapshot, credentials = selected_file_snapshot
    entered, release = threading.Event(), threading.Event()
    _block_selected_read(monkeypatch, credentials, threading.get_ident(), entered, release)
    if entrypoint == "worker":
        from test_worker_trace_binding import _run

        from deerflow.runtime.runs import worker

        monkeypatch.setattr(worker, "restore_snapshot", lambda *args, **kwargs: snapshot)

        def callbacks():
            assert get_current_snapshot() is snapshot
            return []

        monkeypatch.setattr(worker, "build_tracing_callbacks", callbacks)

        async def run():
            config = await _run({"configurable": {"thread_id": "thread-trace-binding"}})
            assert config["metadata"]["deerflow_tracing_snapshot_id"] == snapshot.snapshot_id

    else:
        from deerflow.runtime import context_compaction

        monkeypatch.setattr(context_compaction, "restore_snapshot", lambda *args, **kwargs: snapshot)

        async def compact(*args, **kwargs):
            assert get_current_snapshot() is snapshot
            return "compacted"

        monkeypatch.setattr(context_compaction, "_compact_thread_context", compact)
        accessor = SimpleNamespace(aget=AsyncMock(return_value=SimpleNamespace(metadata={})))

        async def run():
            assert await context_compaction.compact_thread_context(accessor, "thread-1", app_config=SimpleNamespace()) == "compacted"

    task = asyncio.create_task(run())
    try:
        await _entered(entered)
        marker = asyncio.Event()
        asyncio.get_running_loop().call_soon(marker.set)
        await asyncio.wait_for(marker.wait(), 1)
        assert not task.done()
    finally:
        release.set()
        await task
    assert get_current_snapshot() is None
