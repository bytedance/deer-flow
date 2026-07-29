"""Contract tests for the run-launcher anti-corruption layer.

The `RunLauncher` port allows exactly two exceptions to escape -- `ThreadBusyError`
and `LaunchFailedError` -- and the domain branches on the difference: a busy
thread on a scheduled dispatch is a *skipped* occurrence, a genuine failure is a
*recorded* one. Everything the Gateway can raise is therefore classified here,
and this file is what pins that classification.

That translation is the whole point of the adapter: it is what lets
`app/scheduler/service.py`'s `from fastapi import HTTPException` disappear
without the busy/failed distinction disappearing with it.

There is deliberately no `isinstance(launcher, RunLauncher)` assertion. The
adapter inherits the port explicitly, which makes that check trivially true --
and worse than useless: inheritance is exactly what turns a misspelled method
into a silent inherited `...` body returning `None`. Calling every port method
and asserting on what it returns, as this file does, is what actually catches
that.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.adapters.schedule.run_launcher import GatewayRunLauncher
from deerflow.domain.schedule.exceptions import LaunchFailedError, ThreadBusyError
from deerflow.domain.schedule.ports import LaunchedRun
from deerflow.runtime import ConflictError

LAUNCH_KWARGS = {
    "thread_id": "thread-1",
    "assistant_id": "assistant-1",
    "prompt": "do the thing",
    "owner_user_id": "user-1",
    "metadata": {"scheduled_task_id": "task-1", "scheduled_task_run_id": "rec-1", "scheduled_trigger": "scheduled"},
}


def _launcher_returning(payload):
    async def launch_run(**kwargs):
        launch_run.calls.append(kwargs)
        return payload

    launch_run.calls = []
    return GatewayRunLauncher(launch_run), launch_run


def _launcher_raising(exc):
    async def launch_run(**kwargs):
        raise exc

    return GatewayRunLauncher(launch_run)


class TestSuccessfulLaunch:
    @pytest.mark.asyncio
    async def test_returns_what_the_gateway_reported(self):
        launcher, _ = _launcher_returning({"run_id": "run-9", "thread_id": "thread-other"})
        result = await launcher.launch(**LAUNCH_KWARGS)
        assert result == LaunchedRun(run_id="run-9", thread_id="thread-other")

    @pytest.mark.asyncio
    async def test_echoes_the_gateways_thread_not_the_requested_one(self):
        """`LaunchedRun.thread_id` is documented as what actually ran, so the
        adapter must not substitute the thread it asked for."""
        launcher, _ = _launcher_returning({"run_id": "run-9", "thread_id": "thread-substituted"})
        result = await launcher.launch(**LAUNCH_KWARGS)
        assert result.thread_id == "thread-substituted"

    @pytest.mark.asyncio
    async def test_carries_every_argument_through_untouched(self):
        launcher, spy = _launcher_returning({"run_id": "r", "thread_id": "t"})
        await launcher.launch(**LAUNCH_KWARGS)
        assert spy.calls == [LAUNCH_KWARGS]

    @pytest.mark.asyncio
    async def test_a_malformed_gateway_payload_is_a_launch_failure(self):
        """A missing id is not a busy thread -- it is the run path breaking its
        own contract, which the domain records as a failure."""
        launcher, _ = _launcher_returning({"thread_id": "t"})
        with pytest.raises(LaunchFailedError):
            await launcher.launch(**LAUNCH_KWARGS)


class TestBusyThreadTranslation:
    @pytest.mark.asyncio
    async def test_conflict_error_becomes_thread_busy(self):
        launcher = _launcher_raising(ConflictError("thread already has an active run"))
        with pytest.raises(ThreadBusyError):
            await launcher.launch(**LAUNCH_KWARGS)

    @pytest.mark.asyncio
    async def test_http_409_becomes_thread_busy(self):
        """`start_run` rejects a busy thread as an HTTP 409 rather than a
        ConflictError on some paths; both mean the same thing here."""
        launcher = _launcher_raising(HTTPException(status_code=409, detail="thread is busy"))
        with pytest.raises(ThreadBusyError):
            await launcher.launch(**LAUNCH_KWARGS)

    @pytest.mark.asyncio
    async def test_the_cause_survives_in_the_message(self):
        launcher = _launcher_raising(ConflictError("thread already has an active run"))
        with pytest.raises(ThreadBusyError, match="thread already has an active run"):
            await launcher.launch(**LAUNCH_KWARGS)

    @pytest.mark.asyncio
    async def test_http_409_message_is_the_detail_not_the_repr(self):
        launcher = _launcher_raising(HTTPException(status_code=409, detail="thread is busy"))
        with pytest.raises(ThreadBusyError, match="^thread is busy$"):
            await launcher.launch(**LAUNCH_KWARGS)


class TestFailureTranslation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 404, 422, 500, 502])
    async def test_any_other_http_error_is_a_launch_failure(self, status_code):
        launcher = _launcher_raising(HTTPException(status_code=status_code, detail="nope"))
        with pytest.raises(LaunchFailedError):
            await launcher.launch(**LAUNCH_KWARGS)

    @pytest.mark.asyncio
    async def test_an_arbitrary_exception_is_a_launch_failure(self):
        launcher = _launcher_raising(RuntimeError("database is on fire"))
        with pytest.raises(LaunchFailedError, match="database is on fire"):
            await launcher.launch(**LAUNCH_KWARGS)

    @pytest.mark.asyncio
    async def test_the_original_exception_is_chained(self):
        """The domain only needs the two categories, but an operator reading a
        log needs the real traceback."""
        original = RuntimeError("database is on fire")
        launcher = _launcher_raising(original)
        with pytest.raises(LaunchFailedError) as caught:
            await launcher.launch(**LAUNCH_KWARGS)
        assert caught.value.__cause__ is original


class TestCancellationIsNotSwallowed:
    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """`CancelledError` is shutdown control flow, not a launch outcome.
        Translating it to LaunchFailedError would record a spurious failure and
        break cooperative cancellation of the poll loop."""
        launcher = _launcher_raising(asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await launcher.launch(**LAUNCH_KWARGS)
