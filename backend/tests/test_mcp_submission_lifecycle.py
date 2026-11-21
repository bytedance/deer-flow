"""Deterministic delivery, abandonment and loop-lifetime races for submissions."""

import asyncio
import logging
import threading
from concurrent.futures import Future
from contextvars import ContextVar

import pytest

from app.mcp_tasks.submission import SubmissionOwner


async def _turn():
    reached = asyncio.Event()
    asyncio.get_running_loop().call_soon(reached.set)
    await reached.wait()


async def _finish(owner):
    owner.close(timeout=1)
    await owner.drain(deadline=asyncio.get_running_loop().time() + 1)
    assert not owner._submissions


@pytest.mark.asyncio
async def test_cancel_after_operation_finished_before_delivery_still_hands_off(monkeypatch):
    record = {"id": "newly-persisted"}
    handed_off = []
    completed = asyncio.Event()

    async def operation():
        return record

    async def abandon(result):
        handed_off.append(result)

    owner = SubmissionOwner(abandon)
    complete = owner._completed

    def cancel_before_delivery(submission):
        complete(submission)
        assert submission.task.done()
        assert submission.delivery.done()
        assert submission.receipt == "waiting"
        completed.set()
        caller.cancel()

    monkeypatch.setattr(owner, "_completed", cancel_before_delivery)
    caller = asyncio.create_task(owner.submit(operation, timeout=1))
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
        assert completed.is_set()
        assert handed_off == [record]
    finally:
        await _finish(owner)


@pytest.mark.asyncio
async def test_delivered_result_is_not_abandoned_by_later_stop():
    handed_off = []

    async def abandon(result):
        handed_off.append(result)

    async def operation():
        return {"id": "delivered"}

    owner = SubmissionOwner(abandon)
    assert await owner.submit(operation, timeout=1) == {"id": "delivered"}
    await _finish(owner)
    assert handed_off == []


@pytest.mark.asyncio
async def test_repeated_cancel_and_stop_share_one_handoff_and_deadline():
    entered = asyncio.Event()
    release = asyncio.Event()
    handoff_started = asyncio.Event()
    release_handoff = asyncio.Event()
    handed_off = []

    async def operation():
        entered.set()
        await release.wait()
        return {"id": "pending"}

    async def abandon(result):
        handed_off.append(result)
        handoff_started.set()
        await release_handoff.wait()

    owner = SubmissionOwner(abandon)
    caller = asyncio.create_task(owner.submit(operation, timeout=5))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        caller.cancel()
        await _turn()
        deadline = owner.close(timeout=0)
        assert owner.close(timeout=100) == deadline
        release.set()
        await asyncio.wait_for(handoff_started.wait(), timeout=5)
        caller.cancel()
        await _turn()
        assert not caller.done()
        assert handed_off == [{"id": "pending"}]
        release_handoff.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
    finally:
        release.set()
        release_handoff.set()
        await asyncio.wait_for(asyncio.gather(caller, return_exceptions=True), timeout=5)
        await _finish(owner)


@pytest.mark.asyncio
async def test_cancellation_before_admission_never_starts_remote_work(monkeypatch):
    queued = asyncio.Event()
    callbacks = []
    calls = []

    async def operation():
        calls.append("submit")
        return {"id": "unexpected"}

    async def abandon(_result):
        calls.append("cancel")

    owner = SubmissionOwner(abandon)
    admit = owner._admit

    def defer(*args):
        callbacks.append(args)
        queued.set()

    monkeypatch.setattr(owner, "_admit", defer)
    caller = asyncio.create_task(owner.submit(operation, timeout=0))
    try:
        await asyncio.wait_for(queued.wait(), timeout=5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
        assert len(callbacks) == 1
        admit(*callbacks.pop())
        await _turn()
        assert calls == []
    finally:
        for callback in callbacks:
            admit(*callback)
        await _finish(owner)


@pytest.mark.asyncio
async def test_old_queued_submission_cannot_enter_restarted_generation(monkeypatch):
    queued = asyncio.Event()
    callbacks = []
    calls = []

    async def operation():
        calls.append("submit")
        return {"id": "fresh"}

    async def abandon(_result):
        calls.append("cancel")

    owner = SubmissionOwner(abandon)
    assert owner.start()
    admit = owner._admit

    def defer(*args):
        callbacks.append(args)
        queued.set()

    monkeypatch.setattr(owner, "_admit", defer)
    caller = asyncio.create_task(owner.submit(operation, timeout=1))
    try:
        await asyncio.wait_for(queued.wait(), timeout=5)
        owner.close(timeout=0)
        assert owner.start()
        assert len(callbacks) == 1
        admit(*callbacks.pop())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
        assert calls == []
        monkeypatch.setattr(owner, "_admit", admit)
        assert await owner.submit(operation, timeout=1) == {"id": "fresh"}
        assert calls == ["submit"]
    finally:
        for callback in callbacks:
            admit(*callback)
        await _finish(owner)


@pytest.mark.asyncio
async def test_restart_stays_closed_until_abandoned_operation_and_handoff_settle():
    entered = asyncio.Event()
    release = asyncio.Event()
    handed_off = []

    async def operation():
        entered.set()
        await release.wait()
        return {"id": "pending"}

    async def abandon(result):
        handed_off.append(result)

    owner = SubmissionOwner(abandon)
    assert owner.start()
    caller = asyncio.create_task(owner.submit(operation, timeout=1))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        owner.close(timeout=0)
        assert not owner.start()
        with pytest.raises(RuntimeError, match="stopping"):
            await owner.submit(operation, timeout=1)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
        assert handed_off == [{"id": "pending"}]
        assert owner.start()
        assert await owner.submit(operation, timeout=1) == {"id": "pending"}
        assert len(handed_off) == 1
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(caller, return_exceptions=True), timeout=5)
        await _finish(owner)


@pytest.mark.asyncio
async def test_late_failure_is_observed_after_cancelled_caller_has_returned(caplog):
    entered = asyncio.Event()
    release = asyncio.Event()
    handed_off = []
    failure = RuntimeError("remote submission failed after abandonment")

    async def operation():
        entered.set()
        await release.wait()
        raise failure

    async def abandon(result):
        handed_off.append(result)

    owner = SubmissionOwner(abandon)
    caller = asyncio.create_task(owner.submit(operation, timeout=0))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        caller.cancel()
        with caplog.at_level(logging.WARNING), pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
        assert owner._submissions
        release.set()
        await _finish(owner)
        assert handed_off == []
        assert sum(record.exc_info is not None and record.exc_info[1] is failure for record in caplog.records) == 1
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(caller, return_exceptions=True), timeout=5)
        await _finish(owner)


@pytest.mark.asyncio
async def test_handoff_failure_is_observed_without_replacing_caller_cancellation(caplog):
    entered = asyncio.Event()
    release = asyncio.Event()
    failure = RuntimeError("cancellation intent storage unavailable")

    async def operation():
        entered.set()
        await release.wait()
        return {"id": "owned"}

    async def abandon(_result):
        raise failure

    owner = SubmissionOwner(abandon)
    caller = asyncio.create_task(owner.submit(operation, timeout=1))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        caller.cancel()
        release.set()
        with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=5)
        assert sum(record.exc_info is not None and record.exc_info[1] is failure for record in caplog.records) == 1
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(caller, return_exceptions=True), timeout=5)
        await _finish(owner)


@pytest.mark.asyncio
async def test_closed_caller_loop_cannot_cancel_owned_work_or_lose_context():
    owner_loop = asyncio.get_running_loop()
    request_context = ContextVar("mcp-submission-test-context", default=None)
    entered = asyncio.Event()
    release = asyncio.Event()
    ready = Future()
    stopped = Future()
    observed = []

    async def operation():
        observed.append(("submit", asyncio.get_running_loop(), request_context.get()))
        entered.set()
        await release.wait()
        return {"id": "cross-loop"}

    async def abandon(_result):
        observed.append(("cancel", asyncio.get_running_loop(), request_context.get()))

    owner = SubmissionOwner(abandon)
    assert owner.start()

    def thread_main():
        async def call():
            token = request_context.set("caller-context")
            try:
                task = asyncio.create_task(owner.submit(operation, timeout=0))
                ready.set_result((asyncio.get_running_loop(), task))
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                request_context.reset(token)

        try:
            asyncio.run(call())
        except BaseException as exc:
            stopped.set_exception(exc)
        else:
            stopped.set_result(None)

    thread = threading.Thread(target=thread_main, name="mcp-submission-short-lived-caller")
    thread.start()
    caller_loop = None
    try:
        caller_loop, caller = await asyncio.wait_for(asyncio.wrap_future(ready), timeout=5)
        await asyncio.wait_for(entered.wait(), timeout=5)
        caller_loop.call_soon_threadsafe(caller.cancel)
        await asyncio.wait_for(asyncio.wrap_future(stopped), timeout=5)
        assert caller_loop.is_closed()
        assert owner._submissions
        release.set()
        await _finish(owner)
        assert observed == [("submit", owner_loop, "caller-context"), ("cancel", owner_loop, "caller-context")]
        assert request_context.get() is None
    finally:
        release.set()
        if caller_loop is not None and not caller_loop.is_closed():
            caller_loop.call_soon_threadsafe(caller.cancel)
        await asyncio.to_thread(thread.join, 5)
        assert not thread.is_alive()
        await _finish(owner)


@pytest.mark.asyncio
async def test_closed_owner_loop_rejects_factory_without_creating_coroutine():
    calls = []

    async def abandon(_result):
        calls.append("cancel")

    async def bind():
        owner = SubmissionOwner(abandon)
        assert owner.start()
        return owner

    owner = await asyncio.to_thread(lambda: asyncio.run(bind()))

    def operation():
        calls.append("submit")
        raise AssertionError("closed-loop submission must not construct an operation")

    with pytest.raises(RuntimeError, match="closed"):
        await owner.submit(operation, timeout=0)
    assert calls == []
