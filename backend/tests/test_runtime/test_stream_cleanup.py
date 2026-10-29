from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.stream_cleanup import AgentStreamCloseCancelledError, close_agent_stream


class _BlockingStream:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_cancelled = False

    async def aclose(self) -> None:
        self.close_started.set()
        try:
            await self.allow_close.wait()
        except asyncio.CancelledError:
            self.close_cancelled = True
            raise
        self.closed.set()


class _FailingCloseStream(_BlockingStream):
    async def aclose(self) -> None:
        self.close_started.set()
        try:
            await self.allow_close.wait()
        except asyncio.CancelledError:
            self.close_cancelled = True
            raise
        raise RuntimeError("close failed")


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_interrupt_stream_close() -> None:
    stream = _BlockingStream()
    running = asyncio.Event()
    first_cancellation: asyncio.CancelledError | None = None

    async def run_until_cancelled() -> None:
        nonlocal first_cancellation
        try:
            running.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            first_cancellation = exc
            await close_agent_stream(stream)
            raise

    task = asyncio.create_task(run_until_cancelled())
    await running.wait()
    task.cancel("first")
    await stream.close_started.wait()

    task.cancel("second")
    await asyncio.sleep(0)
    task.cancel("third")
    await asyncio.sleep(0)

    assert not task.done()
    assert not stream.close_cancelled
    assert not stream.closed.is_set()

    stream.allow_close.set()
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task

    assert exc_info.value is first_cancellation
    assert exc_info.value.args == ("first",)
    assert stream.closed.is_set()
    assert not stream.close_cancelled


@pytest.mark.asyncio
async def test_cancellation_pending_before_first_wait_is_deferred() -> None:
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    close_cancelled = False

    class CancelBeforeAwaitStream:
        def aclose(self):
            caller = asyncio.current_task()
            assert caller is not None
            caller.cancel("pending-before-wait")

            async def drain() -> None:
                nonlocal close_cancelled
                close_started.set()
                try:
                    await allow_close.wait()
                except asyncio.CancelledError:
                    close_cancelled = True
                    raise

            return drain()

    task = asyncio.create_task(close_agent_stream(CancelBeforeAwaitStream()))
    await close_started.wait()
    await asyncio.sleep(0)

    assert not task.done()
    assert not close_cancelled

    allow_close.set()
    with pytest.raises(asyncio.CancelledError, match="pending-before-wait"):
        await task

    assert not close_cancelled


@pytest.mark.asyncio
async def test_pre_wait_cancellation_does_not_replace_active_stream_error() -> None:
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    close_cancelled = False
    original_error = RuntimeError("stream failed")

    class CancelBeforeAwaitStream:
        def aclose(self):
            caller = asyncio.current_task()
            assert caller is not None
            caller.cancel("pending-before-wait")

            async def drain() -> None:
                nonlocal close_cancelled
                close_started.set()
                try:
                    await allow_close.wait()
                except asyncio.CancelledError:
                    close_cancelled = True
                    raise

            return drain()

    async def fail_then_close() -> None:
        try:
            raise original_error
        finally:
            await close_agent_stream(CancelBeforeAwaitStream())

    task = asyncio.create_task(fail_then_close())
    await close_started.wait()
    await asyncio.sleep(0)

    assert not task.done()
    assert not close_cancelled

    allow_close.set()
    with pytest.raises(RuntimeError, match="stream failed") as exc_info:
        await task

    assert exc_info.value is original_error
    assert not close_cancelled
    assert task.cancelling() == 0


@pytest.mark.asyncio
async def test_pre_entry_cancellation_does_not_replace_active_stream_error() -> None:
    stream = _BlockingStream()
    original_error = RuntimeError("stream failed")

    async def cancel_fail_then_close() -> None:
        caller = asyncio.current_task()
        assert caller is not None
        caller.cancel("pending-before-entry")
        try:
            raise original_error
        finally:
            await close_agent_stream(stream)

    task = asyncio.create_task(cancel_fail_then_close())
    await stream.close_started.wait()
    await asyncio.sleep(0)

    assert not task.done()
    assert not stream.close_cancelled

    stream.allow_close.set()
    with pytest.raises(RuntimeError, match="stream failed") as exc_info:
        await task

    assert exc_info.value is original_error
    assert stream.closed.is_set()
    assert not stream.close_cancelled
    assert task.cancelling() == 1


@pytest.mark.asyncio
async def test_pre_entry_and_synchronous_close_cancellations_are_balanced() -> None:
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    original_error = RuntimeError("stream failed")

    class CancelAgainBeforeAwaitStream:
        def aclose(self):
            caller = asyncio.current_task()
            assert caller is not None
            caller.cancel("during-close")

            async def drain() -> None:
                close_started.set()
                await allow_close.wait()

            return drain()

    async def cancel_fail_then_close() -> None:
        caller = asyncio.current_task()
        assert caller is not None
        caller.cancel("before-entry")
        try:
            raise original_error
        finally:
            await close_agent_stream(CancelAgainBeforeAwaitStream())

    task = asyncio.create_task(cancel_fail_then_close())
    await close_started.wait()
    await asyncio.sleep(0)

    assert not task.done()

    allow_close.set()
    with pytest.raises(RuntimeError, match="stream failed") as exc_info:
        await task

    assert exc_info.value is original_error
    assert task.cancelling() == 1


@pytest.mark.asyncio
async def test_delivered_cancellation_count_is_preserved_while_active_error_wins() -> None:
    original_error = RuntimeError("stream failed")

    class ImmediateStream:
        async def aclose(self) -> None:
            return None

    async def cancel_then_fail() -> None:
        caller = asyncio.current_task()
        assert caller is not None
        caller.cancel("already delivered")
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        try:
            raise original_error
        finally:
            await close_agent_stream(ImmediateStream())

    task = asyncio.create_task(cancel_then_fail())
    with pytest.raises(RuntimeError, match="stream failed") as exc_info:
        await task

    assert exc_info.value is original_error
    assert task.cancelling() == 1


@pytest.mark.asyncio
async def test_delivered_cancellation_count_survives_a_new_deferred_cancellation() -> None:
    stream = _BlockingStream()
    old_cancellation_delivered = asyncio.Event()

    async def cancel_then_close() -> None:
        caller = asyncio.current_task()
        assert caller is not None
        caller.cancel("already delivered")
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            old_cancellation_delivered.set()
        await close_agent_stream(stream)

    task = asyncio.create_task(cancel_then_close())
    await old_cancellation_delivered.wait()
    await stream.close_started.wait()

    task.cancel("deferred")
    await asyncio.sleep(0)

    assert not task.done()
    assert task.cancelling() == 2
    assert not stream.close_cancelled

    stream.allow_close.set()
    with pytest.raises(asyncio.CancelledError, match="deferred"):
        await task

    assert task.cancelling() == 2
    assert stream.closed.is_set()


@pytest.mark.asyncio
async def test_close_failure_is_preserved_as_cancellation_cause() -> None:
    stream = _FailingCloseStream()
    task = asyncio.create_task(close_agent_stream(stream))
    await stream.close_started.wait()

    task.cancel("close-cancelled")
    await asyncio.sleep(0)
    stream.allow_close.set()

    with pytest.raises(asyncio.CancelledError, match="close-cancelled") as exc_info:
        await task

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "close failed"
    assert not stream.close_cancelled


@pytest.mark.asyncio
async def test_host_cancellation_during_close_does_not_replace_active_stream_error() -> None:
    stream = _BlockingStream()
    original_error = RuntimeError("stream failed")

    async def fail_then_close() -> None:
        try:
            raise original_error
        finally:
            await close_agent_stream(stream)

    task = asyncio.create_task(fail_then_close())
    await stream.close_started.wait()
    task.cancel("host cancel")
    await asyncio.sleep(0)

    assert not task.done()
    assert not stream.close_cancelled

    stream.allow_close.set()
    with pytest.raises(RuntimeError, match="stream failed") as exc_info:
        await task

    assert exc_info.value is original_error
    assert stream.closed.is_set()
    assert not stream.close_cancelled


@pytest.mark.asyncio
async def test_stream_originated_cancellation_is_reported_as_close_failure() -> None:
    class SelfCancellingStream:
        async def aclose(self) -> None:
            raise asyncio.CancelledError("stream cancelled itself")

    with pytest.raises(AgentStreamCloseCancelledError, match="cancelled its own close operation") as exc_info:
        await close_agent_stream(SelfCancellingStream())

    assert isinstance(exc_info.value.__cause__, asyncio.CancelledError)
    assert exc_info.value.__cause__.args == ("stream cancelled itself",)
    assert exc_info.value.__suppress_context__ is True
    task = asyncio.current_task()
    assert task is not None
    assert task.cancelling() == 0


@pytest.mark.asyncio
async def test_synchronous_stream_close_cancellation_is_reported_as_failure() -> None:
    class SyncSelfCancellingStream:
        def aclose(self) -> None:
            raise asyncio.CancelledError("sync stream close cancellation")

    with pytest.raises(AgentStreamCloseCancelledError, match="cancelled its own close operation") as exc_info:
        await close_agent_stream(SyncSelfCancellingStream())

    assert isinstance(exc_info.value.__cause__, asyncio.CancelledError)
    assert exc_info.value.__cause__.args == ("sync stream close cancellation",)
    assert exc_info.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_cancellation_during_normal_close_is_deferred_until_close_finishes() -> None:
    stream = _BlockingStream()
    task = asyncio.create_task(close_agent_stream(stream))
    await stream.close_started.wait()

    task.cancel("close-cancelled")
    await asyncio.sleep(0)

    assert not task.done()
    assert not stream.close_cancelled

    stream.allow_close.set()
    with pytest.raises(asyncio.CancelledError, match="close-cancelled"):
        await task

    assert stream.closed.is_set()
    assert not stream.close_cancelled
