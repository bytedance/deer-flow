"""Attach-to-thread staging cleanup must not replace the caller's outcome.

``attach_project_document_to_thread`` stages a copy of a shelf document and
removes it in a ``finally``. When that removal fails — a worker still holds the
handle on Windows, an antivirus scanner intercepts it, the filesystem is
read-only — the raised ``PermissionError`` would replace whatever the endpoint
was about to return, and it would also skip ``service.aclose()`` because the
call sits after the removal in the same ``finally``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.gateway.routers import project_documents as mod


class _Request:
    """Minimal request stand-in; the permission decorators honor this bypass."""

    _deerflow_test_bypass_auth = True


class _StagedPath:
    """A staged path whose removal always fails."""

    def __init__(self) -> None:
        self.unlink_attempts = 0

    def unlink(self, missing_ok: bool = False) -> None:
        self.unlink_attempts += 1
        raise PermissionError(13, "The process cannot access the file", str(self))


class _FakeService:
    """Records the lifecycle calls the endpoint is expected to make."""

    instances: list[_FakeService] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.opened = False
        self.aclosed = False
        self.cleaned = False
        self.ingest_error: BaseException | None = None
        _FakeService.instances.append(self)

    async def open(self) -> None:
        self.opened = True

    async def ingest_chunks(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if self.ingest_error is not None:
            raise self.ingest_error
        return {
            "filename": "report.txt",
            "size": 4,
            "virtual_path": "/threads/t1/report.txt",
            "artifact_url": "/artifacts/report.txt",
        }

    async def finalize(self) -> None:
        return None

    async def cleanup_written(self) -> None:
        self.cleaned = True

    async def aclose(self) -> None:
        self.aclosed = True


def _patch_endpoint(monkeypatch: pytest.MonkeyPatch, staged_path: _StagedPath) -> type[_FakeService]:
    _FakeService.instances = []

    async def _require_project(_request: Any, _project_id: str) -> dict[str, Any]:
        return {"id": "p1"}

    async def _stage(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], Any]:
        return ({"name": "report.txt"}, staged_path)

    async def _chunks(*_args: Any, **_kwargs: Any):
        if False:  # pragma: no cover - keeps this an async generator
            yield b""

    async def _run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(mod, "_require_project", _require_project)
    monkeypatch.setattr(mod, "get_project_document_repo", lambda _request: object())
    monkeypatch.setattr(mod, "get_effective_user_id", lambda: "u1")
    monkeypatch.setattr(mod, "get_paths", lambda: object())
    monkeypatch.setattr(mod, "stage_document_copy_for_attach", _stage)
    monkeypatch.setattr(mod, "ThreadUploadIngestionService", _FakeService)
    monkeypatch.setattr(mod, "read_file_chunks", _chunks)
    monkeypatch.setattr(mod, "run_file_io", _run_inline)
    return _FakeService


def _call_endpoint() -> Any:
    return mod.attach_project_document_to_thread(
        project_id="p1",
        document_id="d1",
        thread_id="t1",
        request=_Request(),
        config=object(),
    )


def test_staging_cleanup_failure_keeps_the_response_and_closes_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged_path = _StagedPath()
    service_cls = _patch_endpoint(monkeypatch, staged_path)

    response = asyncio.run(_call_endpoint())

    assert response.filename == "report.txt"
    assert staged_path.unlink_attempts == 1
    assert len(service_cls.instances) == 1
    assert service_cls.instances[0].aclosed is True


def test_staging_cleanup_failure_keeps_the_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged_path = _StagedPath()
    service_cls = _patch_endpoint(monkeypatch, staged_path)
    original = HTTPException(status_code=409, detail="content_missing")

    def _make_service(*args: Any, **kwargs: Any) -> Any:
        service = _FakeService(*args, **kwargs)
        service.ingest_error = original
        return service

    monkeypatch.setattr(mod, "ThreadUploadIngestionService", _make_service)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(_call_endpoint())

    assert raised.value is original
    assert service_cls.instances[0].aclosed is True
    assert service_cls.instances[0].cleaned is True


class _ZeroSizeStaged:
    """A staged upload that turned out to be empty."""

    def __init__(self, staging_path: Any) -> None:
        self.size_bytes = 0
        self.staging_path = staging_path


def _patch_rejection_path(monkeypatch: pytest.MonkeyPatch, staged_path: _StagedPath) -> None:
    """Make ``stage_document_bytes`` return an empty staged upload."""

    async def _require_active_project(_request: Any, _project_id: str) -> dict[str, Any]:
        return {"id": "p1", "status": "active"}

    async def _stage(*_args: Any, **_kwargs: Any) -> _ZeroSizeStaged:
        return _ZeroSizeStaged(staged_path)

    async def _run_inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(mod, "_require_active_project", _require_active_project)
    monkeypatch.setattr(mod, "_require_project", _require_active_project)
    monkeypatch.setattr(mod, "get_effective_user_id", lambda: "u1")
    monkeypatch.setattr(mod, "get_paths", lambda: object())
    monkeypatch.setattr(mod, "_get_upload_limit", lambda *_args, **_kwargs: 1024)
    monkeypatch.setattr(mod, "stage_document_bytes", _stage)
    monkeypatch.setattr(mod, "run_file_io", _run_inline)


def test_empty_upload_rejection_survives_a_failing_staging_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup failure must not turn the mapped 400 into a raw 500."""

    staged_path = _StagedPath()
    _patch_rejection_path(monkeypatch, staged_path)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            mod.upload_project_document(
                project_id="p1",
                request=_Request(),
                response=object(),
                file=object(),
                name="report.txt",
                config=object(),
            )
        )

    assert raised.value.status_code == 400
    assert raised.value.detail == "Empty file"
    assert staged_path.unlink_attempts == 1


def test_empty_promotion_rejection_survives_a_failing_staging_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guarantee on the save-to-shelf path."""

    staged_path = _StagedPath()
    _patch_rejection_path(monkeypatch, staged_path)

    class _ThreadStore:
        async def get(self, _thread_id: str) -> dict[str, Any]:
            return {"thread_id": "t1"}

    monkeypatch.setattr(mod, "get_thread_store", lambda _request: _ThreadStore())
    monkeypatch.setattr(mod, "get_project_document_repo", lambda _request: object())
    monkeypatch.setattr(mod, "_resolve_thread_source", lambda *_args, **_kwargs: object())

    body = mod.PromoteThreadFileRequest(thread_id="t1", kind="upload", name="report.txt")

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            mod.promote_thread_file_to_shelf(
                project_id="p1",
                body=body,
                request=_Request(),
                response=object(),
                config=object(),
            )
        )

    assert raised.value.status_code == 400
    assert raised.value.detail == "Empty file"
    assert staged_path.unlink_attempts == 1
