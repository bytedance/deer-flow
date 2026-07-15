from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.evaluation import EvaluationService
from app.gateway.deps import get_evaluation_repo, get_optional_user_from_request
from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

router = APIRouter(prefix="/api/evals", tags=["evals"])
_ADMIN_REQUIRED_DETAIL = "Evaluation APIs are only available to admin or internal callers"


class EvalCreateRequest(BaseModel):
    suite: dict[str, Any] = Field(..., description="Immutable eval suite snapshot")
    config: dict[str, Any] | None = None
    start_immediately: bool = Field(default=False, description="Run dispatcher once after create")


class EvalCreateResponse(BaseModel):
    eval_run_id: str
    status: str
    suite_name: str
    suite_digest: str
    total_items: int


async def _require_eval_operator(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    role = getattr(user, "system_role", None)
    if role not in {"admin", INTERNAL_SYSTEM_ROLE}:
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED_DETAIL)
    return str(getattr(user, "id", "internal"))


def _service(request: Request) -> EvaluationService:
    service = getattr(request.app.state, "evaluation_service", None)
    if service is not None:
        return service
    return EvaluationService(repository=get_evaluation_repo(request))


def _ensure_persistent_run_events(request: Request) -> None:
    run_events_config = getattr(request.app.state, "run_events_config", None)
    if getattr(run_events_config, "backend", None) == "memory":
        raise HTTPException(status_code=409, detail="Evaluation runs require persistent run_events backend (db or jsonl)")


def _response(row: dict[str, Any]) -> EvalCreateResponse:
    return EvalCreateResponse(
        eval_run_id=row["id"],
        status=row["status"],
        suite_name=row["suite_name"],
        suite_digest=row["suite_digest"],
        total_items=row["total_items"],
    )


@router.post("", response_model=EvalCreateResponse)
async def create_eval_run(
    body: EvalCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvalCreateResponse:
    owner_id = await _require_eval_operator(request)
    _ensure_persistent_run_events(request)
    row = await _service(request).create_eval_run(
        owner_id=owner_id,
        suite_data=body.suite,
        idempotency_key=idempotency_key,
        config=body.config,
    )
    if body.start_immediately:
        dispatcher = getattr(request.app.state, "evaluation_dispatcher", None)
        if dispatcher is not None:
            await dispatcher.run_once()
        else:
            await _service(request).run_eval(row["id"])
        row = await get_evaluation_repo(request).get_run(row["id"]) or row
    return _response(row)


@router.get("/{eval_run_id}")
async def get_eval_run(eval_run_id: str, request: Request) -> dict[str, Any]:
    await _require_eval_operator(request)
    row = await get_evaluation_repo(request).get_run(eval_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Eval run {eval_run_id} not found")
    return row


@router.get("/{eval_run_id}/items")
async def list_eval_items(eval_run_id: str, request: Request) -> dict[str, Any]:
    await _require_eval_operator(request)
    repo = get_evaluation_repo(request)
    if await repo.get_run(eval_run_id) is None:
        raise HTTPException(status_code=404, detail=f"Eval run {eval_run_id} not found")
    return {"items": await repo.list_items(eval_run_id)}


@router.post("/{eval_run_id}/cancel")
async def cancel_eval_run(eval_run_id: str, request: Request) -> dict[str, Any]:
    await _require_eval_operator(request)
    cancelled = await _service(request).cancel_eval(eval_run_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Eval run {eval_run_id} not found")
    return {"eval_run_id": eval_run_id, "status": "cancelled"}


@router.get("/{eval_run_id}/report", response_model=None)
async def get_eval_report(
    eval_run_id: str,
    request: Request,
    format: Literal["json", "markdown"] = "json",
) -> dict[str, Any] | PlainTextResponse:
    await _require_eval_operator(request)
    row = await get_evaluation_repo(request).get_run(eval_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Eval run {eval_run_id} not found")
    if format == "markdown":
        return PlainTextResponse(row.get("report_markdown") or "", media_type="text/markdown")
    return row.get("report_json") or {}


def _test_request(repo, *, user_id: str = "admin-1", role: str = "admin") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(evaluation_repo=repo)),
        state=SimpleNamespace(user=SimpleNamespace(id=user_id, system_role=role)),
        cookies={},
        headers={},
    )
