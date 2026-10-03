"""Bind scheduler operations to one authenticated owner and originating run."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field

from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION, get_auth_disabled_user, is_auth_disabled
from app.gateway.authz import resolve_route_permissions
from app.gateway.deps import get_config, get_local_provider, get_scheduled_task_repo, get_scheduled_task_run_repo, get_scheduled_task_service, get_thread_store
from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE
from app.gateway.scheduled_task_validation import validate_scheduled_task_create
from deerflow.agents.interaction_policy import RunInteractionMode, RunInteractionPolicy
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict
from deerflow.scheduler.runtime import SchedulerCapabilityMode, SchedulerRunCapability, scheduler_tools_enabled

_MANAGE_PERMISSIONS = {
    "create": frozenset({"threads:write", "runs:create"}),
    "list": frozenset({"threads:read"}),
    "pause": frozenset({"threads:write"}),
    "delete": frozenset({"threads:write"}),
    "note": frozenset({"threads:write"}),
    "trial": frozenset({"threads:write", "runs:create"}),
}
_CREATE_FIELDS = frozenset({"title", "prompt", "schedule_type", "schedule_spec", "timezone", "context_mode", "goal_objective", "max_runs", "end_at"})
_PUBLIC_FIELDS = ("id", "title", "status", "context_mode", "goal_objective", "schedule_type", "schedule_spec", "timezone", "next_run_at", "max_runs", "end_at", "standing_notes")
_STOP_INSTRUCTIONS = "Pause on the scheduled tasks page, or ask to stop this task in the conversation where it was created."


class _TaskBounds(BaseModel):
    goal_objective: str | None = Field(default=None, min_length=1)
    max_runs: int | None = Field(default=None, ge=1, strict=True)
    end_at: AwareDatetime | None = None


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {**{key: task.get(key) for key in _PUBLIC_FIELDS}, "stop_instructions": _STOP_INSTRUCTIONS}


def _error(exc: HTTPException) -> dict[str, Any]:
    return {"error": exc.detail, "status_code": exc.status_code}


async def _owner(owner_id: str, token_version: int, *, auth_disabled_owner: bool) -> Any | None:
    if auth_disabled_owner:
        user = get_auth_disabled_user() if is_auth_disabled() and owner_id == AUTH_DISABLED_USER_ID else None
    else:
        user = await get_local_provider().get_user(owner_id)
    if user is None or str(user.id) != owner_id or getattr(user, "token_version", 0) != token_version or getattr(user, "needs_setup", False) or getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        return None
    return user


@dataclass(frozen=True, repr=False)
class _SchedulerCapability:
    mode: SchedulerCapabilityMode
    _owner_id: str
    _token_version: int
    _auth_disabled_owner: bool
    _permission_ceiling: frozenset[str]
    _origin_thread_id: str
    _run_id: str
    _assistant_id: str
    _original_user_text: str
    _task_repo: Any
    _task_run_repo: Any
    _thread_store: Any
    _service: Any
    _task_id: str | None = None
    _occurrence_id: str | None = None

    async def _require(self, permissions: frozenset[str], *, check_origin: bool = True) -> None:
        if not scheduler_tools_enabled(await asyncio.to_thread(get_config)):
            raise HTTPException(status_code=503, detail="Conversation schedule tools are disabled")
        user = await _owner(self._owner_id, self._token_version, auth_disabled_owner=self._auth_disabled_owner)
        if user is None:
            raise HTTPException(status_code=401, detail="Schedule authority is no longer authenticated")
        effective = frozenset(await resolve_route_permissions(user, is_internal=False)) & self._permission_ceiling
        if not permissions <= effective:
            raise HTTPException(status_code=403, detail="Permission denied for this scheduled task action")
        if check_origin:
            origin = await self._thread_store.get(self._origin_thread_id, user_id=self._owner_id)
            if origin is None or origin.get("user_id") != self._owner_id:
                raise HTTPException(status_code=404, detail="Originating conversation not found")

    async def _task(self, task_id: Any) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id:
            raise HTTPException(status_code=422, detail="task_id is required")
        task = await self._task_repo.get(task_id, user_id=self._owner_id)
        if task is None or task.get("user_id") != self._owner_id or task.get("origin_thread_id") != self._origin_thread_id:
            raise HTTPException(status_code=404, detail="Scheduled task not found")
        return task

    async def manage(self, *, action: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            if self.mode != "interactive":
                raise HTTPException(status_code=403, detail="Schedule management requires an interactive run")
            if action not in _MANAGE_PERMISSIONS:
                raise HTTPException(status_code=422, detail="Unsupported scheduled task action")
            await self._require(_MANAGE_PERMISSIONS[action])
            if action == "create":
                return await self._create(request)
            allowed = {"task_id", "note"} if action == "note" else {"task_id"} if action != "list" else set()
            if not isinstance(request, dict) or request.keys() - allowed:
                raise HTTPException(status_code=422, detail="Unsupported scheduled task fields")
            if action == "list":
                tasks = await self._task_repo.list_by_origin_thread(self._owner_id, self._origin_thread_id)
                return {"tasks": [_public_task(task) for task in tasks if task.get("user_id") == self._owner_id and task.get("origin_thread_id") == self._origin_thread_id]}
            task = await self._task(request.get("task_id"))
            task_id = task["id"]
            if action == "note":
                note = request.get("note")
                if not isinstance(note, str) or not note.strip() or len(note) > 500 or note not in self._original_user_text:
                    raise HTTPException(status_code=422, detail="A standing note must be the current user's explicit words verbatim, at most 500 characters")
                updated = await self._task_repo.append_standing_note(task_id, user_id=self._owner_id, origin_thread_id=self._origin_thread_id, note=note)
                if updated is None:
                    raise HTTPException(status_code=404, detail="Scheduled task not found")
                return _public_task(updated)
            if action == "trial":
                if not self._original_user_text.strip():
                    raise HTTPException(status_code=403, detail="A trial requires an explicit request in the current user turn")
                result = await self._service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
                status = {"not_found": 404, "conflict": 409, "failed": 502}.get(result.get("outcome"))
                if status is not None:
                    raise HTTPException(status_code=status, detail=result.get("error") or "Scheduled task trial could not be dispatched")
                return {"id": task_id, "triggered": True, "outcome": result.get("outcome"), "run_id": result.get("run_id")}
            if action == "pause" and task.get("status") == "running":
                raise HTTPException(status_code=409, detail="Scheduled task is currently running; retry after the active execution finishes")
            operation = self._task_repo.pause_with_queue_cancellation if action == "pause" else self._task_repo.delete_with_queue_cancellation
            outcome = await operation(task_id, user_id=self._owner_id, error=f"scheduled task was {('paused' if action == 'pause' else 'deleted')} while queued", now=datetime.now(UTC))
            if outcome == "not_found":
                raise HTTPException(status_code=404, detail="Scheduled task not found")
            if outcome == "executing":
                raise HTTPException(status_code=409, detail="Scheduled task is already launching or running; retry after the active execution finishes")
            return {"id": task_id, "paused" if action == "pause" else "deleted": True}
        except HTTPException as exc:
            return _error(exc)
        except ActiveScheduledTaskMutationConflict as exc:
            return {"error": f"Scheduled task has an active {exc.status} occurrence; retry after it finishes", "status_code": 409}
        except ValueError as exc:
            return {"error": str(exc), "status_code": 422}

    async def _create(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.gateway.routers.scheduled_tasks import ScheduledTaskCreateRequest, resolve_scheduled_task_assistant_id

        if not isinstance(request, dict) or request.keys() - _CREATE_FIELDS:
            raise HTTPException(status_code=422, detail="Unsupported scheduled task fields")
        bounds = _TaskBounds.model_validate(request)
        if bounds.goal_objective is not None and not bounds.goal_objective.strip():
            raise HTTPException(status_code=422, detail="goal_objective must not be blank")
        body = ScheduledTaskCreateRequest(
            **{key: value for key, value in request.items() if key not in {"goal_objective", "max_runs", "end_at"}},
            assistant_id=self._assistant_id,
            thread_id=self._origin_thread_id if request.get("context_mode") == "reuse_thread" else None,
        )
        reference = datetime.now(UTC)
        config = await asyncio.to_thread(get_config)
        definition = await validate_scheduled_task_create(body, user_id=self._owner_id, thread_store=self._thread_store, scheduler_config=config.scheduler, assistant_resolver=resolve_scheduled_task_assistant_id, now=reference)
        if bounds.goal_objective is not None and body.context_mode != "fresh_thread_per_run":
            raise HTTPException(status_code=422, detail="goal-backed schedules require fresh_thread_per_run")
        if bounds.end_at is not None and bounds.end_at <= reference:
            raise HTTPException(status_code=422, detail="end_at must be in the future")
        frequent = body.schedule_type == "interval" and definition["schedule_spec"]["every_seconds"] < 3600
        if body.schedule_type == "cron":
            frequent = not definition["schedule_spec"]["cron"].split()[0].isascii() or not definition["schedule_spec"]["cron"].split()[0].isdigit()
        if frequent and bounds.max_runs is None and bounds.end_at is None:
            raise HTTPException(status_code=422, detail="Schedules more frequent than hourly require max_runs or end_at")
        if bounds.end_at is not None and definition["next_run_at"] is not None and bounds.end_at <= definition["next_run_at"]:
            raise HTTPException(status_code=422, detail="end_at must allow at least one scheduled occurrence")
        task = await self._task_repo.create(
            task_id=f"task-{uuid.uuid4().hex}", user_id=self._owner_id, origin_thread_id=self._origin_thread_id, goal_objective=bounds.goal_objective, max_runs=bounds.max_runs, end_at=bounds.end_at, standing_notes=None, **definition
        )
        return _public_task(task)

    async def stop_current_schedule(self) -> dict[str, Any]:
        try:
            if self.mode != "scheduled" or not self._task_id or not self._occurrence_id:
                raise HTTPException(status_code=403, detail="This run has no own-schedule stop authority")
            await self._require(frozenset({"threads:write"}), check_origin=False)
            task = await self._task_repo.get(self._task_id, user_id=self._owner_id)
            if task is None or task.get("user_id") != self._owner_id or task.get("origin_thread_id") != self._origin_thread_id:
                raise HTTPException(status_code=404, detail="Scheduled task not found")
            requested = await self._task_run_repo.request_stop(self._occurrence_id, task_id=self._task_id, run_id=self._run_id, user_id=self._owner_id)
            if not requested:
                raise HTTPException(status_code=409, detail="The scheduled occurrence is no longer active or does not match this run")
            return {"id": self._task_id, "stop_requested": True, "message": "The current occurrence continues; its schedule will pause when this occurrence finishes."}
        except HTTPException as exc:
            return _error(exc)


async def prepare_scheduler_capability(
    request: Request,
    *,
    user: Any,
    thread_id: str,
    run_id: str,
    assistant_id: str,
    original_user_text: str,
    interaction_policy: RunInteractionPolicy,
    scheduled_task_runtime: Mapping[str, Any] | None = None,
) -> SchedulerRunCapability | None:
    """Bind private host authority; do not retain the Request or internal user."""
    source = getattr(getattr(request, "state", None), "auth_source", None)
    if source not in {AUTH_SOURCE_SESSION, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_AUTH_DISABLED} or user is None or getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        return None
    if not scheduler_tools_enabled(await asyncio.to_thread(get_config)):
        return None
    owner_id = str(user.id)
    auth_disabled_owner = owner_id == AUTH_DISABLED_USER_ID and is_auth_disabled()
    if source == AUTH_SOURCE_AUTH_DISABLED and not auth_disabled_owner:
        return None
    token_version = getattr(user, "token_version", 0)
    current = await _owner(owner_id, token_version, auth_disabled_owner=auth_disabled_owner)
    if current is None:
        return None
    ceiling = frozenset(await resolve_route_permissions(current, is_internal=False))
    if source != AUTH_SOURCE_INTERNAL:
        auth = getattr(request.state, "auth", None)
        request_user = getattr(request.state, "user", None)
        if auth is None or not auth.is_authenticated or request_user is None or str(request_user.id) != owner_id or str(auth.user.id) != owner_id:
            return None
        ceiling &= frozenset(auth.permissions)
    try:
        repo = get_scheduled_task_repo(request)
        occurrences = get_scheduled_task_run_repo(request)
        threads = get_thread_store(request)
        service = get_scheduled_task_service(request)
    except HTTPException:
        return None
    mode = interaction_policy.mode
    task_id = occurrence_id = None
    if mode is RunInteractionMode.INTERACTIVE:
        origin_thread_id = thread_id
        origin = await threads.get(origin_thread_id, user_id=owner_id)
        if origin is None or origin.get("user_id") != owner_id:
            return None
    elif mode is RunInteractionMode.SCHEDULED and source == AUTH_SOURCE_INTERNAL and isinstance(scheduled_task_runtime, Mapping):
        task_id = scheduled_task_runtime.get("task_id")
        occurrence_id = scheduled_task_runtime.get("occurrence_id")
        if scheduled_task_runtime.get("user_id") != owner_id or not isinstance(task_id, str) or not isinstance(occurrence_id, str):
            return None
        task = await repo.get(task_id, user_id=owner_id)
        if task is None or task.get("user_id") != owner_id or not isinstance(task.get("origin_thread_id"), str) or not task["origin_thread_id"]:
            return None
        origin_thread_id = task["origin_thread_id"]
    else:
        return None
    return _SchedulerCapability(
        mode=mode.value,
        _owner_id=owner_id,
        _token_version=token_version,
        _auth_disabled_owner=auth_disabled_owner,
        _permission_ceiling=ceiling,
        _origin_thread_id=origin_thread_id,
        _run_id=run_id,
        _assistant_id=assistant_id,
        _original_user_text=original_user_text if isinstance(original_user_text, str) else "",
        _task_repo=repo,
        _task_run_repo=occurrences,
        _thread_store=threads,
        _service=service,
        _task_id=task_id,
        _occurrence_id=occurrence_id,
    )
