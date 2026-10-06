"""Bind scheduler operations to one authenticated owner and originating run."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request

from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION, get_auth_disabled_user, is_auth_disabled
from app.gateway.authz import resolve_route_permissions
from app.gateway.deps import get_config, get_local_provider, get_scheduled_task_repo, get_scheduled_task_run_repo, get_scheduled_task_service, get_thread_store
from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE
from app.gateway.scheduled_task_errors import repository_error, scheduler_error, tool_error_payload
from app.gateway.scheduled_task_validation import validate_scheduled_task_create
from deerflow.agents.interaction_policy import RunInteractionMode, RunInteractionPolicy
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict
from deerflow.scheduler.host_notes import RUN_ERROR_DELETED_WHILE_QUEUED, RUN_ERROR_PAUSED_WHILE_QUEUED
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


def _has_explicit_trial_request(user_text: str, task: Mapping[str, Any]) -> bool:
    """Accept bounded direct-run turns, never a keyword in arbitrary user text.

    This is deliberately not a general intent parser. Quoted, conditional,
    compound or bare-confirmation turns require a new direct user request.
    """
    if not user_text or len(user_text) > 500:
        return False
    command = " ".join(user_text.strip().rstrip(".!。！").split()).casefold()
    for prefix in ("yes, please ", "yes, ", "please ", "可以，请", "可以，", "好，", "请"):
        if command.startswith(prefix):
            command = command[len(prefix) :].strip()
            break
    targets = {"it", "this task"}
    # Titles are arbitrary prose and may contain quoted/conditional clauses.
    # Only an opaque selector can safely be interpolated into a direct request.
    task_id = task.get("id")
    if isinstance(task_id, str) and 5 < len(task_id) <= 64 and task_id.startswith("task-") and task_id.isascii() and task_id.replace("-", "").replace("_", "").isalnum():
        targets.add(task_id.casefold())
    direct_requests = {f"run {target} {timing}" for target in targets for timing in ("now", "once", "once now")}
    direct_requests.update({"run a trial now", "先跑一次", "现在跑一次", "先试跑一次", "现在试跑一次", "先运行一次", "现在运行一次"})
    for target in targets - {"it", "this task"}:
        direct_requests.update({f"先试跑{target}", f"现在试跑{target}", f"先运行{target}一次", f"现在运行{target}一次"})
    return command in direct_requests


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {**{key: task.get(key) for key in _PUBLIC_FIELDS}, "stop_instructions": _STOP_INSTRUCTIONS}


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
    # The conversation that manages tasks (interactive); scheduled runs bind
    # only their task and occurrence, so this is None for them.
    _origin_thread_id: str | None
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
            raise scheduler_error(503, "scheduler_tools_disabled", "Conversation schedule tools are disabled")
        user = await _owner(self._owner_id, self._token_version, auth_disabled_owner=self._auth_disabled_owner)
        if user is None:
            raise scheduler_error(401, "authority_expired", "Schedule authority is no longer authenticated")
        effective = frozenset(await resolve_route_permissions(user, is_internal=False)) & self._permission_ceiling
        if not permissions <= effective:
            raise scheduler_error(403, "permission_denied", "Permission denied for this scheduled task action")
        if check_origin:
            origin = await self._thread_store.get(self._origin_thread_id, user_id=self._owner_id) if self._origin_thread_id else None
            if origin is None or origin.get("user_id") != self._owner_id:
                raise scheduler_error(404, "conversation_not_found", "Originating conversation not found")

    async def _task(self, task_id: Any) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id:
            raise scheduler_error(422, "task_id_required", "task_id is required")
        task = await self._task_repo.get(task_id, user_id=self._owner_id)
        if task is None or task.get("user_id") != self._owner_id or task.get("origin_thread_id") != self._origin_thread_id:
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        return task

    async def manage(self, *, action: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            if self.mode != "interactive":
                raise scheduler_error(403, "interactive_run_required", "Schedule management requires an interactive run")
            if action not in _MANAGE_PERMISSIONS:
                raise scheduler_error(422, "unsupported_action", "Unsupported scheduled task action")
            await self._require(_MANAGE_PERMISSIONS[action])
            if action == "create":
                return await self._create(request)
            allowed = {"task_id", "note"} if action == "note" else {"task_id"} if action != "list" else set()
            if not isinstance(request, dict) or request.keys() - allowed:
                raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
            if action == "list":
                tasks = await self._task_repo.list_by_origin_thread(self._owner_id, self._origin_thread_id)
                return {"tasks": [_public_task(task) for task in tasks if task.get("user_id") == self._owner_id and task.get("origin_thread_id") == self._origin_thread_id]}
            task = await self._task(request.get("task_id"))
            task_id = task["id"]
            if action == "note":
                note = request.get("note")
                if not isinstance(note, str) or not note.strip() or len(note) > 500 or note not in self._original_user_text:
                    raise scheduler_error(422, "note_not_verbatim", "A standing note must be the current user's explicit words verbatim, at most 500 characters")
                # _task() above already authorized this task for the conversation.
                updated = await self._task_repo.append_standing_note(task_id, user_id=self._owner_id, note=note)
                if updated is None:
                    raise scheduler_error(404, "task_not_found", "Scheduled task not found")
                return _public_task(updated)
            if action == "trial":
                if not _has_explicit_trial_request(self._original_user_text, task):
                    raise scheduler_error(403, "trial_requires_direct_request", "A trial requires a direct request in the current user turn, such as 'Run this task now' or '先跑一次'; a task mention or bare confirmation is insufficient")
                result = await self._service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
                outcome = result.get("outcome")
                error = result.get("error") or "Scheduled task trial could not be dispatched"
                if outcome == "not_found":
                    raise scheduler_error(404, "task_not_found", error)
                if outcome == "conflict":
                    raise scheduler_error(409, "task_changed" if error == "scheduled task changed before trigger admission" else "task_running", error)
                if outcome == "failed":
                    raise scheduler_error(502, "trigger_failed", error)
                return {"id": task_id, "triggered": True, "outcome": result.get("outcome"), "run_id": result.get("run_id")}
            if action == "pause" and task.get("status") == "running":
                raise scheduler_error(409, "task_running", "Scheduled task is currently running; retry after the active execution finishes")
            operation = self._task_repo.pause_with_queue_cancellation if action == "pause" else self._task_repo.delete_with_queue_cancellation
            outcome = await operation(task_id, user_id=self._owner_id, error=RUN_ERROR_PAUSED_WHILE_QUEUED if action == "pause" else RUN_ERROR_DELETED_WHILE_QUEUED, now=datetime.now(UTC))
            if outcome == "not_found":
                raise scheduler_error(404, "task_not_found", "Scheduled task not found")
            if outcome == "executing":
                raise scheduler_error(409, "task_running", "Scheduled task is already launching or running; retry after the active execution finishes")
            if outcome == "finished":
                raise scheduler_error(409, "task_finished", "Scheduled task has finished; resume it to run again")
            return {"id": task_id, "paused" if action == "pause" else "deleted": True}
        except HTTPException as exc:
            return tool_error_payload(exc)
        except (ActiveScheduledTaskMutationConflict, ValueError) as exc:
            return tool_error_payload(repository_error(exc))

    async def _create(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.gateway.routers.scheduled_tasks import ScheduledTaskCreateRequest, resolve_scheduled_task_assistant_id

        if not isinstance(request, dict) or request.keys() - _CREATE_FIELDS:
            raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
        # Same model and validation as REST create (identical codes), plus the
        # chat-only rule that sub-hourly schedules need a safety cap.
        body = ScheduledTaskCreateRequest(
            **request,
            assistant_id=self._assistant_id,
            thread_id=self._origin_thread_id if request.get("context_mode") == "reuse_thread" else None,
        )
        config = await asyncio.to_thread(get_config)
        definition = await validate_scheduled_task_create(
            body,
            user_id=self._owner_id,
            thread_store=self._thread_store,
            scheduler_config=config.scheduler,
            assistant_resolver=resolve_scheduled_task_assistant_id,
            now=datetime.now(UTC),
            conversation_rules=True,
        )
        task = await self._task_repo.create(task_id=f"task-{uuid.uuid4().hex}", user_id=self._owner_id, origin_thread_id=self._origin_thread_id, standing_notes=None, **definition)
        return _public_task(task)

    async def stop_current_schedule(self) -> dict[str, Any]:
        try:
            if self.mode != "scheduled" or not self._task_id or not self._occurrence_id:
                raise scheduler_error(403, "no_stop_authority", "This run has no own-schedule stop authority")
            await self._require(frozenset({"threads:write"}), check_origin=False)
            # Own-stop is bound to this occurrence's task, whether a chat or
            # the tasks page created it; it never reaches another task.
            task = await self._task_repo.get(self._task_id, user_id=self._owner_id)
            if task is None or task.get("user_id") != self._owner_id or task.get("id") != self._task_id:
                raise scheduler_error(404, "task_not_found", "Scheduled task not found")
            requested = await self._task_run_repo.request_stop(self._occurrence_id, task_id=self._task_id, run_id=self._run_id, user_id=self._owner_id)
            if not requested:
                raise scheduler_error(409, "occurrence_not_active", "The scheduled occurrence is no longer active or does not match this run")
            return {"id": self._task_id, "stop_requested": True, "message": "The current occurrence continues; its schedule will pause when this occurrence finishes."}
        except HTTPException as exc:
            return tool_error_payload(exc)


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
        if task is None or task.get("user_id") != owner_id:
            return None
        # Bind the task and occurrence only: page-created tasks (no origin
        # conversation) get the same own-schedule stop as chat-created ones.
        origin_thread_id = None
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
