"""Export cleanup must preserve cancellation, disconnects and completed transfers."""

import asyncio
import threading
from io import BytesIO

import pytest
from starlette.requests import ClientDisconnect, Request

from app.gateway import skill_export as service
from deerflow.skills.export import SkillExportArchive


class CloseFailure(BytesIO):
    def __init__(self, data, error_type=OSError):
        super().__init__(data)
        self.error_type = error_type

    def close(self):
        super().close()
        raise self.error_type("injected archive close failure")


@pytest.fixture
def slots(monkeypatch):
    # Private process budget: no other test can consume or release these slots.
    budget = threading.BoundedSemaphore(2)
    monkeypatch.setattr(service, "_slots", budget)
    yield budget
    assert budget.acquire(blocking=False), "an export slot leaked"
    assert budget.acquire(blocking=False), "an export slot leaked"
    assert not budget.acquire(blocking=False), "an export slot was released twice"


@pytest.fixture(params=[OSError, AttributeError], ids=["io-error", "non-io-error"])
def close_error(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["close-failure", "close-and-log-failure"])
def close_failure(request, monkeypatch, close_error):
    if request.param:

        def fail(*args, **kwargs):
            raise RuntimeError("injected logging failure")

        # This logger is used only by the new best-effort cleanup diagnostic.
        import logging

        monkeypatch.setattr(logging.getLogger(service.__name__), "warning", fail)
    return CloseFailure(b"zip", close_error)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "disconnect", "read-error", "cancel"])
async def test_response_cleanup_preserves_outcome(slots, close_failure, outcome):
    file = close_failure
    body_started = asyncio.Event()
    expected = RuntimeError("original read failure")
    if outcome == "read-error":

        def read(*args):
            raise expected

        file.read = read
    response = service.SkillExportResponse(SkillExportArchive(file, 3), "demo", service.ExportLease.acquire())
    messages = []

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)
        if outcome == "disconnect":
            raise OSError("original transport disconnect")
        if outcome == "cancel" and message["type"] == "http.response.body":
            body_started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
    try:
        if outcome == "cancel":
            await asyncio.wait_for(body_started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
        elif outcome == "disconnect":
            with pytest.raises(ClientDisconnect):
                await task
        elif outcome == "read-error":
            with pytest.raises(RuntimeError) as error:
                await task
            assert error.value is expected
        else:
            await task
            assert messages[0]["status"] == 200
            assert b"".join(m.get("body", b"") for m in messages) == b"zip"
            assert messages[-1]["more_body"] is False
        assert file.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        # Always close the real resource even if a pre-fix assertion fails.
        BytesIO.close(file)


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True], ids=["task-cancel", "client-disconnect"])
async def test_unclaimed_archive_cleanup_preserves_outcome(slots, close_failure, disconnect):
    started = asyncio.Event()
    disconnected = asyncio.Event()
    loop = asyncio.get_running_loop()

    def work(cancel):
        loop.call_soon_threadsafe(started.set)
        assert cancel.wait(3)
        return SkillExportArchive(close_failure, 3)

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    request = Request({"type": "http"}, receive) if disconnect else None
    task = asyncio.create_task(service.run_export_work(work, request))
    try:
        await asyncio.wait_for(started.wait(), 3)
        if disconnect:
            disconnected.set()
        else:
            task.cancel()
        error_type = service.ExportClientDisconnected if disconnect else asyncio.CancelledError
        with pytest.raises(error_type):
            await task
        assert task.cancelled() is (not disconnect)
        assert close_failure.closed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        BytesIO.close(close_failure)


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_release_slot_before_close_finishes(slots):
    loop = asyncio.get_running_loop()
    close_started = asyncio.Event()
    finish = threading.Event()

    class PausedClose(BytesIO):
        def close(self):
            loop.call_soon_threadsafe(close_started.set)
            assert finish.wait(3)
            super().close()
            raise OSError("injected close failure")

    file = PausedClose(b"zip")
    response = service.SkillExportResponse(SkillExportArchive(file, 3), "demo", service.ExportLease.acquire())
    blocked = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.body":
            blocked.set()
            await asyncio.Event().wait()

    async def receive():
        await asyncio.Event().wait()

    task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
    try:
        await asyncio.wait_for(blocked.wait(), 3)
        task.cancel()
        await asyncio.wait_for(close_started.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        second = service.ExportLease.acquire()
        try:
            with pytest.raises(Exception) as error:
                service.ExportLease.acquire()
            assert error.value.status_code == 429
        finally:
            second.release()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert file.closed
    finally:
        finish.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        BytesIO.close(file)


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["response", "unclaimed-worker"])
async def test_cleanup_diagnostic_identifies_skill(slots, caplog, boundary):
    file = CloseFailure(b"zip")
    archive = SkillExportArchive(file, 3)
    try:
        if boundary == "response":
            response = service.SkillExportResponse(archive, "demo", service.ExportLease.acquire())
            messages = []

            async def receive():
                await asyncio.Event().wait()

            async def send(message):
                messages.append(message)

            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
            assert messages[0]["status"] == 200
            assert b"".join(m.get("body", b"") for m in messages) == b"zip"
        else:
            started = asyncio.Event()
            loop = asyncio.get_running_loop()

            def work(cancel):
                loop.call_soon_threadsafe(started.set)
                assert cancel.wait(3)
                return archive

            task = asyncio.create_task(service.run_export_work(work, skill_name="demo"))
            try:
                await asyncio.wait_for(started.wait(), 3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.cancelled()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        records = [record for record in caplog.records if record.name == service.__name__]
        assert len(records) == 1
        assert "'demo'" in records[0].getMessage()
        assert isinstance(records[0].exc_info[1], OSError)
        assert file.closed
    finally:
        BytesIO.close(file)
