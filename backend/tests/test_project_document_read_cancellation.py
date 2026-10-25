"""Cancelled document reads retain and close handles opened by file workers."""

from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.projects import documents


@pytest.mark.asyncio
async def test_cancelled_read_closes_handle_after_open_worker_returns(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"source bytes")
    open_returned = threading.Event()
    release_open = threading.Event()
    handles = []
    real_run_file_io = documents.run_file_io

    async def observe_file_io(func, *args, **kwargs):
        if getattr(func, "__name__", None) == "_open":

            def open_then_pause():
                handle = func(*args, **kwargs)
                handles.append(handle)
                open_returned.set()
                assert release_open.wait(10), "test did not release the open worker"
                return handle

            return await real_run_file_io(open_then_pause)
        return await real_run_file_io(func, *args, **kwargs)

    monkeypatch.setattr(documents, "run_file_io", observe_file_io)

    async def consume():
        async for _chunk in documents.read_file_chunks(source, chunk_size=4):
            pass

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(open_returned.wait, 10), "open worker did not return a handle"
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done(), "cancellation detached the admitted open operation"
        release_open.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert handles[0].closed, "cancelled read retained its file descriptor"
    finally:
        release_open.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for handle in handles:
            if not handle.closed:
                handle.close()


@pytest.mark.asyncio
async def test_cancelled_read_drains_read_worker_before_close(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"source bytes")
    read_started = threading.Event()
    release_read = threading.Event()
    read_finished = threading.Event()
    close_started = threading.Event()
    release_close = threading.Event()
    close_before_read_finish = []
    handles = []
    real_run_file_io = documents.run_file_io

    async def observe_file_io(func, *args, **kwargs):
        if getattr(func, "__name__", None) == "_open":

            def open_and_wrap():
                handle = func(*args, **kwargs)
                handles.append(handle)
                real_read = handle.read
                real_close = handle.close

                def gated_read(*read_args, **read_kwargs):
                    read_started.set()
                    assert release_read.wait(10), "test did not release the read worker"
                    try:
                        return real_read(*read_args, **read_kwargs)
                    finally:
                        read_finished.set()

                def observed_close(*close_args, **close_kwargs):
                    close_started.set()
                    assert release_close.wait(10), "test did not release the close worker"
                    close_before_read_finish.append(not read_finished.is_set())
                    return real_close(*close_args, **close_kwargs)

                handle.read = gated_read
                handle.close = observed_close
                return handle

            return await real_run_file_io(open_and_wrap)
        return await real_run_file_io(func, *args, **kwargs)

    monkeypatch.setattr(documents, "run_file_io", observe_file_io)

    async def consume():
        async for _chunk in documents.read_file_chunks(source, chunk_size=4):
            pass

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(read_started.wait, 10), "read worker did not start"
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not await asyncio.to_thread(close_started.wait, 1), "close raced an admitted read worker"
        release_read.set()
        assert await asyncio.to_thread(read_finished.wait, 10), "read worker did not settle"
        release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert read_finished.is_set(), "cancellation escaped before the read worker settled"
        assert close_before_read_finish == [False], "close raced an admitted read worker"
        assert handles[0].closed, "cancelled read retained its file descriptor"
    finally:
        release_read.set()
        release_close.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for handle in handles:
            if not handle.closed:
                handle.close()


@pytest.mark.asyncio
async def test_cancelled_read_drains_close_worker(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"source bytes")
    first_chunk_ready = asyncio.Event()
    hold_consumer = asyncio.Event()
    close_started = threading.Event()
    release_close = threading.Event()
    close_finished = threading.Event()
    handles = []
    real_run_file_io = documents.run_file_io

    async def observe_file_io(func, *args, **kwargs):
        if getattr(func, "__name__", None) == "_open":

            def open_and_wrap():
                handle = func(*args, **kwargs)
                handles.append(handle)
                real_close = handle.close

                def gated_close(*close_args, **close_kwargs):
                    close_started.set()
                    assert release_close.wait(10), "test did not release the close worker"
                    try:
                        return real_close(*close_args, **close_kwargs)
                    finally:
                        close_finished.set()

                handle.close = gated_close
                return handle

            return await real_run_file_io(open_and_wrap)
        return await real_run_file_io(func, *args, **kwargs)

    monkeypatch.setattr(documents, "run_file_io", observe_file_io)

    async def consume_one():
        iterator = documents.read_file_chunks(source, chunk_size=4)
        try:
            await anext(iterator)
            first_chunk_ready.set()
            await hold_consumer.wait()
        finally:
            await iterator.aclose()

    task = asyncio.create_task(consume_one())
    try:
        await asyncio.wait_for(first_chunk_ready.wait(), 10)
        task.cancel()
        assert await asyncio.to_thread(close_started.wait, 10), "close worker did not start"
        assert not close_finished.is_set(), "close worker was not held by the test"
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation escaped before the close worker settled"
        release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert close_finished.is_set()
        assert handles[0].closed, "cancelled read retained its file descriptor"
    finally:
        release_close.set()
        hold_consumer.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for handle in handles:
            if not handle.closed:
                handle.close()
