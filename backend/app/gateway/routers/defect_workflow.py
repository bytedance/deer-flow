"""Proxy APIs for EHM defect workflow closure tasks."""

from __future__ import annotations

import logging
import json
import os
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/defect-workflow", tags=["defect-workflow"])

DEFAULT_EHM_ORIGIN = "http://10.0.2.233"
DEFAULT_CLOSED_LOOP_PREFIX = "/closed-loop-api"
DEFAULT_WORKFLOW_PREFIX = "/workflow-api"
DEFAULT_TIMEOUT_SECONDS = 30.0


class ClaimTaskRequest(BaseModel):
    comment: str | None = None


class SubmitTaskRequest(BaseModel):
    action: str = Field(default="SUBMIT")
    formData: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _resolve_service_base_url(kind: str) -> str:
    """Resolve EHM service base URLs.

    `kind` is either `closed_loop` or `workflow`.
    """
    if kind == "closed_loop":
        explicit = os.environ.get("EHM_CLOSED_LOOP_BASE_URL", "").strip()
        if explicit:
            return _strip_trailing_slash(explicit)
        origin = _strip_trailing_slash(os.environ.get("EHM_BASE_ORIGIN", DEFAULT_EHM_ORIGIN).strip())
        prefix = os.environ.get("EHM_CLOSED_LOOP_API_PREFIX", DEFAULT_CLOSED_LOOP_PREFIX).strip() or DEFAULT_CLOSED_LOOP_PREFIX
        return f"{origin}/{prefix.strip('/')}"

    if kind == "workflow":
        explicit = os.environ.get("EHM_WORKFLOW_BASE_URL", "").strip()
        if explicit:
            return _strip_trailing_slash(explicit)
        origin = _strip_trailing_slash(os.environ.get("EHM_BASE_ORIGIN", DEFAULT_EHM_ORIGIN).strip())
        prefix = os.environ.get("EHM_WORKFLOW_API_PREFIX", DEFAULT_WORKFLOW_PREFIX).strip() or DEFAULT_WORKFLOW_PREFIX
        return f"{origin}/{prefix.strip('/')}"

    raise ValueError(f"Unknown EHM service kind: {kind}")


def _resolve_timeout_seconds() -> float:
    raw = os.environ.get("EHM_DEFECT_WORKFLOW_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1.0, min(float(raw), 300.0))
    except ValueError:
        logger.warning("Invalid EHM_DEFECT_WORKFLOW_TIMEOUT_SECONDS=%r; using default", raw)
        return DEFAULT_TIMEOUT_SECONDS


def _resolve_access_token(request: Request) -> str | None:
    """Extract the user's platform bearer token from the incoming request."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    cookie_token = request.cookies.get("access_token", "").strip()
    if cookie_token:
        return cookie_token

    state_user = getattr(getattr(request, "state", None), "user", None)
    if isinstance(state_user, dict):
        token = str(state_user.get("ins_base_token") or "").strip()
        if token:
            return token

    return None


def _build_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _join_url(base_url: str, path: str) -> str:
    return f"{_strip_trailing_slash(base_url)}/{path.lstrip('/')}"


def _safe_path_id(value: str | int) -> str:
    return quote(str(value), safe="")


def _normalize_upstream_error(status_code: int, payload: Any) -> HTTPException:
    if status_code in {401, 403, 404, 409, 422}:
        return HTTPException(status_code=status_code, detail=payload)
    if 400 <= status_code < 500:
        return HTTPException(status_code=status_code, detail=payload)
    return HTTPException(
        status_code=502,
        detail={
            "message": "EHM defect workflow service unavailable",
            "upstream_status": status_code,
            "upstream": payload,
        },
    )


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        try:
            return json.loads(response.text, strict=False)
        except ValueError:
            return {"message": response.text}


class DefectWorkflowProxyClient:
    def __init__(
        self,
        *,
        closed_loop_base_url: str | None = None,
        workflow_base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.closed_loop_base_url = closed_loop_base_url or _resolve_service_base_url("closed_loop")
        self.workflow_base_url = workflow_base_url or _resolve_service_base_url("workflow")
        self.timeout_seconds = timeout_seconds or _resolve_timeout_seconds()

    async def request(
        self,
        *,
        service: str,
        method: str,
        path: str,
        token: str,
        params: Iterable[tuple[str, str]] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        base_url = self.closed_loop_base_url if service == "closed_loop" else self.workflow_base_url
        url = _join_url(base_url, path)
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                headers=_build_headers(token),
                params=list(params or []),
                json=json_body,
            )
        payload = _response_payload(response)
        if response.status_code >= 400:
            raise _normalize_upstream_error(response.status_code, payload)
        return payload


def _client() -> DefectWorkflowProxyClient:
    return DefectWorkflowProxyClient()


def _token_or_401(request: Request) -> str:
    token = _resolve_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="User token not available for EHM defect workflow API")
    return token


@router.get("/tasks/todo")
async def list_defect_todos(request: Request) -> Any:
    token = _token_or_401(request)
    return await _client().request(
        service="closed_loop",
        method="GET",
        path="/api/v1/defects/tasks/todo",
        token=token,
        params=request.query_params.multi_items(),
    )


@router.get("/defects/{defect_id}")
async def get_defect_detail(defect_id: str, request: Request) -> Any:
    token = _token_or_401(request)
    return await _client().request(
        service="closed_loop",
        method="GET",
        path=f"/api/v1/defects/{_safe_path_id(defect_id)}",
        token=token,
    )


@router.get("/tasks/{task_id}/form-context")
async def get_task_form_context(task_id: str, request: Request) -> Any:
    token = _token_or_401(request)
    return await _client().request(
        service="workflow",
        method="GET",
        path=f"/task-forms/tasks/{_safe_path_id(task_id)}/context",
        token=token,
    )


@router.post("/defects/{defect_id}/workflow-tasks/{task_id}/claim")
async def claim_defect_task(
    defect_id: str,
    task_id: str,
    body: ClaimTaskRequest,
    request: Request,
) -> Any:
    token = _token_or_401(request)
    return await _client().request(
        service="closed_loop",
        method="POST",
        path=f"/api/v1/defects/{_safe_path_id(defect_id)}/workflow-tasks/{_safe_path_id(task_id)}/claim",
        token=token,
        json_body=body.model_dump(),
    )


@router.post("/defects/{defect_id}/workflow-tasks/{task_id}/submit")
async def submit_defect_task(
    defect_id: str,
    task_id: str,
    body: SubmitTaskRequest,
    request: Request,
) -> Any:
    token = _token_or_401(request)
    return await _client().request(
        service="closed_loop",
        method="POST",
        path=f"/api/v1/defects/{_safe_path_id(defect_id)}/workflow-tasks/{_safe_path_id(task_id)}/submit",
        token=token,
        json_body=body.model_dump(),
    )
