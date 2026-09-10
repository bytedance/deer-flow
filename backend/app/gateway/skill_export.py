"""Request-owned export workers and responses; slots follow temporary-file lifetime."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse

from deerflow.skills.export import SkillExportArchive, SkillExportError
from deerflow.utils.file_io import run_file_io

# Slots are shared across all users in this Gateway process.
_slots = threading.BoundedSemaphore(2)
TRANSFER_TIMEOUT_SECONDS = 120.0


class ExportClientDisconnected(Exception):
    """A peer disconnect, distinct from cancellation of the server task."""


class SkillExportNotice(BaseModel):
    code: str
    message: str
    path: str | None = None


class SkillExportFile(BaseModel):
    path: str
    type: Literal["file", "directory"]
    size: int
    executable: bool


class SkillExportSecret(BaseModel):
    name: str
    optional: bool


class SkillExportRequirements(BaseModel):
    compatibility: str | None
    allowed_tools: list[str] | None
    required_secrets: list[SkillExportSecret] | None


class SkillExportManifestResponse(BaseModel):
    skill_name: str
    revision: str | None
    can_export: bool
    file_count: int
    directory_count: int
    total_bytes: int
    files: list[SkillExportFile]
    requirements: SkillExportRequirements
    warnings: list[SkillExportNotice]
    blockers: list[SkillExportNotice]


class ExportLease:
    def __init__(self) -> None:
        self._released = False

    @classmethod
    def acquire(cls) -> ExportLease:
        if not _slots.acquire(blocking=False):
            raise HTTPException(429, detail={"code": "skill_export_busy", "message": "Both export slots in this Gateway process are in use across all users. Retry after an export finishes."})
        return cls()

    def release(self) -> None:
        if not self._released:
            self._released = True
            _slots.release()


async def _drain(task: asyncio.Task) -> None:
    # Cancelling an asyncio future never stops its file-I/O worker. Repeated
    # cancellations must not release the slot or close a file still in use.
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break


async def _finish_io(func: Callable, *args):
    task = asyncio.create_task(run_file_io(func, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _drain(task)
        if not task.cancelled():
            task.exception()
        raise


async def _disconnected(request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def run_export_work(work: Callable[[threading.Event], Any], request: Request | None = None) -> tuple[Any, ExportLease]:
    """Transfer a successful result AND lease, or drain/clean them before raising."""
    lease = ExportLease.acquire()
    cancel_event = threading.Event()
    task = asyncio.create_task(run_file_io(work, cancel_event))
    disconnected = asyncio.create_task(_disconnected(request)) if request is not None else None
    try:
        if disconnected is not None:
            done, _ = await asyncio.wait((task, disconnected), return_when=asyncio.FIRST_COMPLETED)
            if disconnected in done:
                raise ExportClientDisconnected
        return await asyncio.shield(task), lease
    except BaseException:
        cancel_event.set()
        await _drain(task)
        try:
            if not task.cancelled():
                try:
                    result = task.result()
                except BaseException:
                    pass
                else:
                    if isinstance(result, SkillExportArchive):
                        await _finish_io(result.close)
        finally:
            lease.release()
        raise
    finally:
        if disconnected is not None:
            disconnected.cancel()
            await _drain(disconnected)


class SkillExportResponse(StreamingResponse):
    """Own cleanup even if ASGI fails before it starts iterating the body."""

    def __init__(self, archive: SkillExportArchive, name: str, lease: ExportLease) -> None:
        self.archive, self.lease = archive, lease
        super().__init__(
            self._chunks(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{name}.skill"',
                "Content-Length": str(archive.size),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def _chunks(self):
        while chunk := await _finish_io(self.archive.file.read, 1024 * 1024):
            yield chunk

    async def __call__(self, scope, receive, send) -> None:
        try:
            try:
                async with asyncio.timeout(TRANSFER_TIMEOUT_SECONDS):
                    await super().__call__(scope, receive, send)
            except TimeoutError:
                # Headers may already be sent. Abort the incomplete transfer;
                # never report success or append JSON to a partial ZIP.
                raise ClientDisconnect from None
        finally:
            try:
                await _finish_io(self.archive.close)
            finally:
                self.lease.release()


def export_http_error(error: SkillExportError) -> HTTPException:
    detail = {"code": error.code, "message": error.message}
    if error.path is not None:
        detail["path"] = error.path
    return HTTPException(error.status, detail=detail)
