from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.infra.storage import ThreadMetaStorage
from store.repositories.contracts import (
    FeedbackRepositoryProtocol,
    RunRepositoryProtocol,
    ThreadMetaRepositoryProtocol,
)


def _require_state(request: Request, attr: str, label: str):
    value = getattr(request.app.state, attr, None)
    if value is None:
        raise HTTPException(status_code=503, detail=f"{label} not available")
    return value


def get_run_repository(request: Request) -> RunRepositoryProtocol:
    return _require_state(request, "run_store", "Run store")


def get_thread_meta_repository(request: Request) -> ThreadMetaRepositoryProtocol:
    return _require_state(request, "thread_meta_repo", "Thread metadata store")


def get_thread_meta_storage(request: Request) -> ThreadMetaStorage:
    return _require_state(request, "thread_meta_storage", "Thread metadata storage")


def get_feedback_repository(request: Request) -> FeedbackRepositoryProtocol:
    return _require_state(request, "feedback_repo", "Feedback")


CurrentRunRepository = Annotated[RunRepositoryProtocol, Depends(get_run_repository)]
CurrentThreadMetaRepository = Annotated[ThreadMetaRepositoryProtocol, Depends(get_thread_meta_repository)]
CurrentThreadMetaStorage = Annotated[ThreadMetaStorage, Depends(get_thread_meta_storage)]
CurrentFeedbackRepository = Annotated[FeedbackRepositoryProtocol, Depends(get_feedback_repository)]
