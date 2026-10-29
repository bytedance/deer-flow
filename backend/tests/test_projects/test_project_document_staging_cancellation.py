"""Cancelled shelf staging retains filesystem ownership until cleanup ends."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import call_unwrapped
from fastapi import Response

from deerflow.config.paths import Paths
from deerflow.projects import documents


@pytest.mark.asyncio
async def test_cancelled_chunk_stream_closes_and_removes_staging(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    waiting = asyncio.Event()
    never = asyncio.Event()
    handles = []
    real_open = documents._open_staging

    def observe_open(*args):
        handle = real_open(*args)
        handles.append(handle)
        return handle

    async def chunks():
        yield b"first chunk\n"
        waiting.set()
        await never.wait()

    monkeypatch.setattr(documents, "_open_staging", observe_open)
    task = asyncio.create_task(documents.stage_document_bytes(paths, user_id="u1", project_id="p1", chunks=chunks(), max_bytes=1024))
    try:
        await asyncio.wait_for(waiting.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert handles[0].closed, "cancelled staging retained its file descriptor"
        assert not list((paths.project_documents_dir("u1", "p1") / ".staging").iterdir())
        assert not never.is_set(), "cancellation must not drain a stalled incoming stream"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for handle in handles:
            handle.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["open", "write", "close", "cleanup"])
@pytest.mark.parametrize("worker_fails", [False, True], ids=["success", "failure"])
async def test_cancelled_staging_drains_file_operation(tmp_path, monkeypatch, operation, worker_fails):
    paths = Paths(tmp_path)
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started = asyncio.Event()
    finished = threading.Event()
    release = threading.Event()
    handles = []
    worker_threads = []
    cleanup_before_worker_finish = []
    real_open = documents._open_staging
    real_cleanup = documents._close_and_unlink
    real_file_io = documents.run_file_io

    def gated(call):
        worker_threads.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        try:
            if threading.get_ident() != loop_thread:
                assert release.wait(10), "file operation was not released"
            if worker_fails and operation != "cleanup":
                raise OSError("synthetic staging worker failure")
            return call()
        finally:
            finished.set()

    def observe_open(*args):
        def create():
            handle = real_open(*args)
            handles.append(handle)
            return handle

        handle = gated(create) if operation == "open" else create()
        if operation in {"write", "close"}:
            real_operation = getattr(handle, operation)
            first = True

            def observed_operation(*args):
                nonlocal first
                if first:
                    first = False
                    return gated(lambda: real_operation(*args))
                return real_operation(*args)

            setattr(handle, operation, observed_operation)
        elif operation == "cleanup" and worker_fails:
            real_close = handle.close

            def close_with_error():
                real_close()
                raise OSError("staging close failed after closing")

            handle.close = close_with_error
        return handle

    def observe_cleanup(*args):
        if operation == "cleanup":
            # Hold cleanup before the real close/unlink. The failure case
            # raises from close only after releasing its real descriptor.
            gated(lambda: None)
        return real_cleanup(*args)

    async def observe_file_io(func, *args, **kwargs):
        if func is observe_cleanup and operation in {"write", "close"}:
            cleanup_before_worker_finish.append(not finished.is_set())
        return await real_file_io(func, *args, **kwargs)

    monkeypatch.setattr(documents, "_open_staging", observe_open)
    monkeypatch.setattr(documents, "_close_and_unlink", observe_cleanup)
    monkeypatch.setattr(documents, "run_file_io", observe_file_io)
    limit = 1 if operation == "cleanup" else 1024
    task = asyncio.create_task(documents.stage_document_bytes(paths, user_id="u1", project_id="p1", chunks=[b"payload\n"], max_bytes=limit))
    try:
        await asyncio.wait_for(started.wait(), 10)
        assert len(worker_threads) == 1
        assert worker_threads[0] != loop_thread, "staging blocked the event loop"
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        for _ in range(10):
            await asyncio.sleep(0)
        assert not task.done(), "cancellation detached an admitted file operation"
        assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert finished.is_set()
        assert not any(cleanup_before_worker_finish), "cleanup started before its file operation finished"
        assert all(handle.closed for handle in handles)
        staging = paths.project_documents_dir("u1", "p1") / ".staging"
        assert not staging.exists() or not list(staging.iterdir())
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(finished.wait, 10)
        for handle in handles:
            if not handle.closed:
                handle.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True], ids=["list", "async-stream"])
async def test_completed_staging_keeps_exact_bytes_and_hash(tmp_path, streamed):
    paths = Paths(tmp_path)
    chunks = [b"UTF-8\n", "\u4f60\u597d\r\n".encode("utf-8"), b"\x00\xff"]

    async def stream():
        for chunk in chunks:
            yield chunk

    staged = await documents.stage_document_bytes(paths, user_id="u1", project_id="p1", chunks=stream() if streamed else chunks, max_bytes=1024)
    content = b"".join(chunks)
    assert staged.staging_path.read_bytes() == content
    assert staged.size_bytes == len(content)
    assert staged.sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["upload", "promotion"])
async def test_shelf_entry_cancellation_reclaims_staging_before_insert(tmp_path, monkeypatch, entry):
    """Both route consumers retain the real staging writer and worker pool."""
    from app.gateway.routers import project_documents as router

    paths = Paths(tmp_path)
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    loop = asyncio.get_running_loop()
    handles = []
    real_open = documents._open_staging
    insert = AsyncMock()
    source = paths.sandbox_outputs_dir("thread-1", user_id="u1") / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source bytes\n")

    def observe_open(*args):
        handle = real_open(*args)
        handles.append(handle)
        real_write = handle.write

        def paused_write(chunk):
            loop.call_soon_threadsafe(started.set)
            try:
                assert release.wait(10), "route staging writer was not released"
                return real_write(chunk)
            finally:
                finished.set()

        handle.write = paused_write
        return handle

    monkeypatch.setattr(documents, "_open_staging", observe_open)
    monkeypatch.setattr(router, "get_paths", lambda: paths)
    monkeypatch.setattr(router, "get_effective_user_id", lambda: "u1")
    monkeypatch.setattr(router, "_require_active_project", AsyncMock(return_value={"id": "p1", "status": "active"}))
    monkeypatch.setattr(router, "get_project_document_repo", lambda request: SimpleNamespace())
    monkeypatch.setattr(router, "get_thread_store", lambda request: SimpleNamespace(get=AsyncMock(return_value={"thread_id": "thread-1"})))
    monkeypatch.setattr(router, "add_staged_document", insert)

    if entry == "upload":
        file = SimpleNamespace(filename="source.txt", read=AsyncMock(side_effect=[b"source bytes\n", b""]))
        call = call_unwrapped(router.upload_project_document, "p1", request=SimpleNamespace(), response=Response(), file=file, name=None, config=SimpleNamespace(uploads={}))
    else:
        body = router.PromoteThreadFileRequest(thread_id="thread-1", kind="output", name="source.txt")
        call = call_unwrapped(router.promote_thread_file_to_shelf, "p1", body=body, request=SimpleNamespace(), response=Response(), config=SimpleNamespace(uploads={}))
    task = asyncio.create_task(call)
    try:
        await asyncio.wait_for(started.wait(), 10)
        task.cancel()
        for _ in range(10):
            await asyncio.sleep(0)
        assert not task.done(), "route abandoned its real staging writer"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert finished.is_set()
        assert handles[0].closed
        assert not list((paths.project_documents_dir("u1", "p1") / ".staging").iterdir())
        insert.assert_not_awaited()
        assert source.read_bytes() == b"source bytes\n"
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for handle in handles:
            if not handle.closed:
                handle.close()
