"""Bind scheduler operations to one authenticated owner and conversation.

An interactive turn manages the tasks created in its conversation and the
tasks whose run that conversation is. A scheduled run binds only its own task
and occurrence, and may only pause its own schedule. Results are small,
JSON-safe projections for the model and the web chat card: no ISO times, user,
lease or origin fields.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION, get_auth_disabled_user, is_auth_disabled
from app.gateway.authz import resolve_route_permissions
from app.gateway.deps import get_config, get_local_provider, get_scheduled_task_repo, get_scheduled_task_run_repo, get_scheduled_task_service, get_thread_store
from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE
from app.gateway.scheduled_task_errors import active_occurrence_error, repository_error, scheduler_error, tool_error_payload
from app.gateway.scheduled_task_validation import prepare_resume_updates, validate_scheduled_task_create, validate_scheduled_task_update
from app.scheduler.service import TASK_CHANGED_ERROR
from deerflow.agents.interaction_policy import RunInteractionMode, RunInteractionPolicy
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict
from deerflow.scheduler import host_notes
from deerflow.scheduler.runtime import SchedulerCapabilityMode, SchedulerRunCapability, scheduler_tools_enabled

_MANAGE_PERMISSIONS = {
    "create": frozenset({"threads:write", "runs:create"}),
    "update": frozenset({"threads:write", "runs:create"}),
    "resume": frozenset({"threads:write", "runs:create"}),
    "list": frozenset({"threads:read"}),
    "pause": frozenset({"threads:write"}),
    "delete": frozenset({"threads:write"}),
    "note": frozenset({"threads:write"}),
    "trial": frozenset({"threads:write", "runs:create"}),
}
_CREATE_FIELDS = frozenset({"title", "prompt", "stop_condition", "schedule_type", "schedule_spec", "timezone", "context_mode", "goal_objective", "max_runs", "end_at"})
_UPDATE_FIELDS = frozenset({"task_id", "title", "prompt", "stop_condition", "schedule_type", "schedule_spec", "timezone", "goal_objective", "max_runs", "end_at", "clear_fields"})
_RESUME_FIELDS = frozenset({"task_id", "max_runs", "end_at", "clear_fields"})
_UPDATE_CLEARABLE = frozenset({"goal_objective", "max_runs", "end_at", "stop_condition"})
_RESUME_CLEARABLE = frozenset({"max_runs", "end_at"})
# Errors where "now" in the task's zone helps the agent pick a new time.
_TIME_ERROR_CODES = frozenset({"timezone_required", "once_in_past", "once_too_soon", "once_time_passed", "end_at_in_past", "end_at_before_first_run"})
# Host-written run errors, reported to the agent by a short key instead of the English note.
_HOST_RUN_ERROR_KEYS = {
    host_notes.RUN_ERROR_RESTARTED: "restarted",
    host_notes.RUN_ERROR_LEASE_LOST: "lease_lost",
    host_notes.RUN_ERROR_QUEUE_TIMEOUT: "queue_timeout",
    host_notes.RUN_ERROR_PAUSED_WHILE_QUEUED: "paused_while_queued",
    host_notes.RUN_ERROR_DELETED_WHILE_QUEUED: "deleted_while_queued",
    host_notes.RUN_ERROR_END_REACHED: "end_reached",
    host_notes.RUN_ERROR_INTERRUPTED: "interrupted",
}
_REASON_CODE = re.compile(r"[a-z_]+(:[a-z_]+)?")
_ZONE_ERRORS = (ValueError, KeyError, OSError, TypeError)

# --- Trial consent -----------------------------------------------------------

_TRIAL_TRAILING_PUNCTUATION = ".!。！~～…"
_TRIAL_ACK_SEPARATORS = ",，、 "
_TRIAL_ACKS = tuple(sorted(("yes please", "yes", "sure", "ok", "okay", "please", "go ahead and", "alright", "好的", "好", "可以", "行", "嗯", "那就", "请", "麻烦"), key=len, reverse=True))
_TRIAL_PARTICLES = (" please", "吧", "呗", "啊", "呀", "哈", "看看")
_TRIAL_VERBS = ("run", "try", "test")
_TRIAL_TARGETS = ("it", "this task", "the task", "this")
_TRIAL_TIMINGS = ("now", "once", "once now", "right now", "now please")
_TRIAL_PHRASES = frozenset(
    {f"{verb} {target} {timing}" for verb in _TRIAL_VERBS for target in _TRIAL_TARGETS for timing in _TRIAL_TIMINGS}
    | {"run it", "try it", "run a trial", "run a trial now", "do a trial run", "do a test run", "do a trial run now", "do a test run now", "try it out", "test it now"}
    | {
        "先跑一次",
        "现在跑一次",
        "先试跑一次",
        "现在试跑一次",
        "先运行一次",
        "现在运行一次",
        "试跑一下",
        "试跑一次",
        "先试一下",
        "先试试",
        "试一下",
        "试试",
        "跑一次",
        "跑一下",
        "先跑一下",
        "现在跑一下",
        "马上跑一次",
        "立即运行一次",
        "运行一次",
        "执行一次",
        "先执行一次",
        "现在执行一次",
        "试运行一次",
        "先试运行一次",
        "现在试运行",
        "立即试运行",
    }
)


def _strip_trailing_punctuation(text: str) -> str:
    return text.rstrip(_TRIAL_TRAILING_PUNCTUATION).strip()


def _strip_acknowledgement(command: str) -> str | None:
    """Remove one leading "yes"/"好的"-style word; None when there is none."""
    for ack in _TRIAL_ACKS:
        if not command.startswith(ack):
            continue
        rest = command[len(ack) :]
        # An English word must end at a separator ("okay" is not "ok" + "ay").
        if ack.isascii() and rest and rest[0] not in _TRIAL_ACK_SEPARATORS:
            continue
        return rest.lstrip(_TRIAL_ACK_SEPARATORS)
    return None


def _has_explicit_trial_request(user_text: str, task: Mapping[str, Any]) -> bool:
    """Accept a bounded direct-run request in the current turn, never a keyword in arbitrary text.

    This is deliberately not a general intent parser: after removing up to
    two leading acknowledgements and one trailing particle, the whole turn
    must be one of the known direct requests. Bare confirmations, quoted,
    conditional or compound turns, other tasks and task titles are rejected.
    """
    if not isinstance(user_text, str) or not user_text.strip() or len(user_text) > 500:
        return False
    command = _strip_trailing_punctuation(" ".join(user_text.casefold().split()))
    for _ in range(2):
        rest = _strip_acknowledgement(command)
        if rest is None:
            break
        command = rest
    if not command:
        return False
    for particle in _TRIAL_PARTICLES:
        if command.endswith(particle) and len(command) > len(particle):
            command = _strip_trailing_punctuation(command[: -len(particle)])
            break
    phrases = set(_TRIAL_PHRASES)
    # Titles are arbitrary prose and may contain quoted/conditional clauses.
    # Only an opaque selector can safely be interpolated into a direct request.
    task_id = task.get("id")
    if isinstance(task_id, str) and 5 < len(task_id) <= 64 and task_id.startswith("task-") and task_id.isascii() and task_id.replace("-", "").replace("_", "").isalnum():
        target = task_id.casefold()
        phrases.update(f"{verb} {target} {timing}" for verb in _TRIAL_VERBS for timing in _TRIAL_TIMINGS)
        phrases.update({f"先试跑{target}", f"现在试跑{target}", f"先运行{target}一次", f"现在运行{target}一次"})
    return command in phrases


# --- Projections ---------------------------------------------------------------


def _as_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _local(value: datetime | str | None, timezone: Any) -> str | None:
    """``2026-10-07 09:00 (Asia/Shanghai)``: model-facing local time, never ISO or UTC offsets."""
    moment = _as_utc(value)
    if moment is None or not isinstance(timezone, str) or not timezone:
        return None
    try:
        zone = ZoneInfo(timezone)
    except _ZONE_ERRORS:
        return None
    return f"{moment.astimezone(zone):%Y-%m-%d %H:%M} ({timezone})"


def _now_local(timezone: Any) -> str | None:
    return _local(datetime.now(UTC), timezone)


def _reason_code(run: Mapping[str, Any]) -> str | None:
    error = run.get("error")
    if isinstance(error, str) and error:
        if error in _HOST_RUN_ERROR_KEYS:
            return _HOST_RUN_ERROR_KEYS[error]
        if _REASON_CODE.fullmatch(error):
            return error
    status = run.get("status")
    verdict = run.get("goal_verdict")
    if status == "unmet" and isinstance(verdict, Mapping) and isinstance(verdict.get("blocker"), str):
        return verdict["blocker"]
    if status == "failed":
        return "launch_failed" if run.get("run_id") is None else "failed"
    return None


def _last_run_view(run: Mapping[str, Any] | None, timezone: Any) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "status": run.get("status"),
        "trigger": run.get("trigger"),
        "finished_local": _local(run.get("finished_at"), timezone),
        "reason_code": _reason_code(run),
    }


def _task_view(
    task: Mapping[str, Any],
    *,
    used: int,
    active_run_status: str | None,
    last_run: Mapping[str, Any] | None = None,
    include_last_run: bool = False,
    timezone_source: str | None = None,
    browser_timezone: str | None = None,
) -> dict[str, Any]:
    """The task as the model and the chat card see it (``last_run`` only in ``list``)."""
    timezone = task.get("timezone")
    view: dict[str, Any] = {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "schedule_type": task.get("schedule_type"),
        "schedule_spec": dict(task.get("schedule_spec") or {}),
        "timezone": timezone,
    }
    if timezone_source is not None:
        view["timezone_source"] = timezone_source
    if browser_timezone is not None:
        view["browser_timezone"] = browser_timezone
    view.update(
        {
            "next_run_local": _local(task.get("next_run_at"), timezone) if task.get("status") == "enabled" else None,
            "active_run_status": active_run_status,
            "prompt": task.get("prompt"),
            "stop_condition": task.get("stop_condition"),
            "goal_objective": task.get("goal_objective"),
            "max_runs": task.get("max_runs"),
            "end_at_local": _local(task.get("end_at"), timezone),
            "automatic_runs_used": int(used),
            "context_mode": task.get("context_mode"),
            "standing_notes": list(task.get("standing_notes") or []),
        }
    )
    if include_last_run:
        view["last_run"] = _last_run_view(last_run, timezone)
    return view


def _with_now_local(exc: HTTPException, timezone: Any) -> HTTPException:
    """Add ``params.now_local`` to a time-related error so the agent can pick a new time."""
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("code") in _TIME_ERROR_CODES:
        exc.detail = {**detail, "params": {**(detail.get("params") or {}), "now_local": _now_local(timezone)}}
    return exc


def _has_offset(value: Any) -> bool | None:
    """Whether an ISO time string carries a UTC offset; None when it is not one."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return parsed.tzinfo is not None


def _needs_timezone(schedule_type: Any, schedule_spec: Any, end_at: Any = None) -> bool:
    """Whether a definition reads local calendar time: a cron, or a one-time run_at or end_at without an offset."""
    if schedule_type == "cron" or _has_offset(end_at) is False:
        return True
    run_at = schedule_spec.get("run_at") if isinstance(schedule_spec, Mapping) else None
    return schedule_type == "once" and _has_offset(run_at) is not True


def _timezone_required() -> HTTPException:
    return scheduler_error(422, "timezone_required", "Ask the user which timezone to use.")


def _fields_with_clears(request: Mapping[str, Any], clearable: frozenset[str]) -> dict[str, Any]:
    """Request fields with ``clear_fields`` turned into ``None`` values."""
    fields = {key: value for key, value in request.items() if key not in {"task_id", "clear_fields"}}
    clear = request.get("clear_fields")
    if clear is None:
        return fields
    if not isinstance(clear, list) or not all(isinstance(name, str) for name in clear) or set(clear) - clearable:
        raise scheduler_error(422, "unsupported_fields", f"clear_fields may only name {', '.join(sorted(clearable))}")
    conflicting = sorted(set(clear) & fields.keys())
    if conflicting:
        raise scheduler_error(422, "invalid_request", f"Do not both set and clear {', '.join(conflicting)}")
    fields.update(dict.fromkeys(clear))
    return fields


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
    # "card" for the web app (session or auth-disabled), "text" for IM/internal runs.
    _display: str = "text"
    # The browser timezone sent with this turn; only new tasks default to it.
    _client_timezone: str | None = None

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
        """A task this conversation may manage: created here, or one whose run this conversation is."""
        if not isinstance(task_id, str) or not task_id:
            raise scheduler_error(422, "task_id_required", "task_id is required")
        task = await self._task_repo.get(task_id, user_id=self._owner_id)
        if task is None or task.get("user_id") != self._owner_id:
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        if task.get("origin_thread_id") != self._origin_thread_id:
            # Re-queried on every call, never cached in the grant.
            run_task_ids = await self._task_run_repo.task_ids_for_thread(self._origin_thread_id, user_id=self._owner_id) if self._origin_thread_id else []
            if task_id not in run_task_ids:
                raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        return task

    async def _view(self, task: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
        task_id = task["id"]
        used = (await self._task_repo.automatic_runs_used_for([task_id])).get(task_id, 0)
        active = await self._task_repo.get_active_run_status(task_id)
        return _task_view(task, used=used, active_run_status=active, **extra)

    async def _ensure_mutable(self, task: Mapping[str, Any]) -> None:
        if task.get("status") == "running":
            raise scheduler_error(409, "task_running", "Scheduled task is currently running; retry after the active execution finishes")
        active = await self._task_repo.get_active_run_status(task["id"])
        if active is not None:
            raise active_occurrence_error(active)

    def _result(self, action: str, **values: Any) -> dict[str, Any]:
        return {"action": action, "display": self._display, **values}

    async def manage(self, *, action: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            if self.mode != "interactive":
                raise scheduler_error(403, "interactive_run_required", "Schedule management requires an interactive run")
            if action not in _MANAGE_PERMISSIONS:
                raise scheduler_error(422, "unsupported_action", "Unsupported scheduled task action")
            await self._require(_MANAGE_PERMISSIONS[action])
            if not isinstance(request, dict):
                raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
            if action == "create":
                return await self._create(request)
            if action == "update":
                return await self._update(request)
            if action == "resume":
                return await self._resume(request)
            allowed = {"task_id", "note"} if action == "note" else {"task_id"} if action != "list" else set()
            if request.keys() - allowed:
                raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
            if action == "list":
                return await self._list()
            task = await self._task(request.get("task_id"))
            if action == "note":
                return await self._note(task, request.get("note"))
            if action == "trial":
                return await self._trial(task)
            return await self._pause_or_delete(action, task)
        except HTTPException as exc:
            return tool_error_payload(exc)
        except (ActiveScheduledTaskMutationConflict, ValueError) as exc:
            # Repository errors, including the safety-cap and quota ValueErrors
            # and type errors from the request models.
            return tool_error_payload(repository_error(exc))

    async def _list(self) -> dict[str, Any]:
        tasks = [task for task in await self._task_repo.list_manageable_from_thread(self._owner_id, self._origin_thread_id) if task.get("user_id") == self._owner_id]
        ids = [task["id"] for task in tasks]
        used = await self._task_repo.automatic_runs_used_for(ids) if ids else {}
        active = await self._task_repo.active_run_status_for(ids) if ids else {}
        views = []
        for task in tasks:
            latest = await self._task_run_repo.list_by_task(task["id"], limit=1)
            views.append(_task_view(task, used=used.get(task["id"], 0), active_run_status=active.get(task["id"]), last_run=latest[0] if latest else None, include_last_run=True))
        return self._result("list", tasks=views, default_timezone=self._client_timezone, now_local=_now_local(self._client_timezone))

    def _create_timezone(self, request: Mapping[str, Any]) -> tuple[Any, str]:
        """Explicit zone > browser zone > none needed (interval, run_at with offset) > ask."""
        if request.get("timezone") is not None:
            return request["timezone"], "explicit"
        if self._client_timezone:
            return self._client_timezone, "browser_default"
        if not _needs_timezone(request.get("schedule_type"), request.get("schedule_spec"), request.get("end_at")):
            # Elapsed time and absolute instants do not depend on a zone.
            return "UTC", "not_needed"
        raise _with_now_local(_timezone_required(), None)

    async def _create(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.gateway.routers.scheduled_tasks import ScheduledTaskCreateRequest, resolve_scheduled_task_assistant_id

        if request.keys() - _CREATE_FIELDS:
            raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
        timezone, timezone_source = self._create_timezone(request)
        try:
            # Same model and validation as REST create (identical codes), plus
            # the chat-only rule that sub-hourly schedules need a safety cap.
            body = ScheduledTaskCreateRequest(
                **{**request, "timezone": timezone},
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
        except HTTPException as exc:
            raise _with_now_local(exc, timezone) from None
        task = await self._task_repo.create(task_id=f"task-{uuid.uuid4().hex}", user_id=self._owner_id, origin_thread_id=self._origin_thread_id, standing_notes=None, **definition)
        browser = self._client_timezone if timezone_source == "explicit" and self._client_timezone and self._client_timezone != timezone else None
        view = _task_view(task, used=0, active_run_status=None, timezone_source=timezone_source, browser_timezone=browser)
        return self._result("create", task=view, now_local=_now_local(timezone))

    async def _update(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.gateway.routers.scheduled_tasks import ScheduledTaskUpdateRequest, resolve_scheduled_task_assistant_id

        if request.keys() - _UPDATE_FIELDS:
            raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
        task = await self._task(request.get("task_id"))
        fields = _fields_with_clears(request, _UPDATE_CLEARABLE)
        explicit = fields.get("timezone")
        timezone = explicit if explicit is not None else task.get("timezone")
        if explicit is None and task.get("timezone") == "UTC" and not _needs_timezone(task.get("schedule_type"), task.get("schedule_spec")):
            # A zone-free schedule (interval, run_at with offset) saved UTC as a
            # placeholder; a new local calendar time (a cron, a run_at or end_at
            # without an offset) must not silently become UTC.
            schedule_type = fields.get("schedule_type", task.get("schedule_type"))
            schedule_spec = fields.get("schedule_spec", task.get("schedule_spec"))
            if _needs_timezone(schedule_type, schedule_spec, fields.get("end_at")):
                raise _with_now_local(_timezone_required(), self._client_timezone)
        try:
            # Types only, as for REST PATCH; value rules raise coded errors below.
            typed = ScheduledTaskUpdateRequest(**fields).model_dump(include=set(fields))
            await self._ensure_mutable(task)
            used = (await self._task_repo.automatic_runs_used_for([task["id"]])).get(task["id"], 0)
            config = await asyncio.to_thread(get_config)
            updates = await validate_scheduled_task_update(
                task,
                typed,
                user_id=self._owner_id,
                thread_store=self._thread_store,
                scheduler_config=config.scheduler,
                assistant_resolver=resolve_scheduled_task_assistant_id,
                used=used,
                now=datetime.now(UTC),
            )
        except HTTPException as exc:
            raise _with_now_local(exc, timezone) from None
        updated = await self._task_repo.update(task["id"], user_id=self._owner_id, updates=updates, require_mutable=True)
        if updated is None:
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        source = "explicit" if explicit is not None else "saved"
        browser = self._client_timezone if source == "explicit" and self._client_timezone and self._client_timezone != explicit else None
        view = await self._view(updated, timezone_source=source, browser_timezone=browser)
        return self._result("update", task=view, now_local=_now_local(updated.get("timezone")))

    async def _resume(self, request: dict[str, Any]) -> dict[str, Any]:
        from app.gateway.routers.scheduled_tasks import ScheduledTaskResumeRequest

        if request.keys() - _RESUME_FIELDS:
            raise scheduler_error(422, "unsupported_fields", "Unsupported scheduled task fields")
        task = await self._task(request.get("task_id"))
        fields = _fields_with_clears(request, _RESUME_CLEARABLE)
        schedule = (task.get("schedule_type"), task.get("schedule_spec"))
        if task.get("timezone") == "UTC" and not _needs_timezone(*schedule) and _needs_timezone(*schedule, fields.get("end_at")):
            # As on update: a local end time must not silently become the UTC
            # placeholder of a zone-free schedule. Resume takes no timezone.
            exc = scheduler_error(422, "timezone_required", "Ask the user which timezone to use, then give end_at with that zone's UTC offset.")
            raise _with_now_local(exc, self._client_timezone)
        try:
            renewal = ScheduledTaskResumeRequest(**fields).model_dump(include=set(fields))
            await self._ensure_mutable(task)
            if task.get("status") == "enabled":
                return self._result("resume", task=await self._view(task))
            used = (await self._task_repo.automatic_runs_used_for([task["id"]])).get(task["id"], 0)
            updates = await asyncio.to_thread(prepare_resume_updates, task, renewal, used=used, now=datetime.now(UTC))
        except HTTPException as exc:
            raise _with_now_local(exc, task.get("timezone")) from None
        updated = await self._task_repo.update(task["id"], user_id=self._owner_id, updates=updates, require_mutable=True)
        if updated is None:
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        return self._result("resume", task=await self._view(updated))

    async def _note(self, task: dict[str, Any], note: Any) -> dict[str, Any]:
        if not isinstance(note, str) or not note.strip() or len(note) > 500 or note not in self._original_user_text:
            raise scheduler_error(422, "note_not_verbatim", "A standing note must be the current user's explicit words verbatim, at most 500 characters")
        # _task() already authorized this task for the conversation.
        updated = await self._task_repo.append_standing_note(task["id"], user_id=self._owner_id, note=note)
        if updated is None:
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        return self._result("note", task=await self._view(updated))

    async def _trial(self, task: dict[str, Any]) -> dict[str, Any]:
        if not _has_explicit_trial_request(self._original_user_text, task):
            raise scheduler_error(403, "trial_requires_direct_request", "A trial requires a direct request in the current user turn, such as 'Run this task now' or '先跑一次'; a task mention or bare confirmation is insufficient")
        result = await self._service.dispatch_task(task, now=datetime.now(UTC), trigger="manual")
        outcome = result.get("outcome")
        error = result.get("error") or "Scheduled task trial could not be dispatched"
        if outcome == "not_found":
            raise scheduler_error(404, "task_not_found", error)
        if outcome == "conflict":
            raise scheduler_error(409, "task_changed" if error == TASK_CHANGED_ERROR else "task_running", error)
        if outcome == "failed":
            raise scheduler_error(502, "trigger_failed", error)
        current = await self._task_repo.get(task["id"], user_id=self._owner_id) or task
        thread_id = result.get("thread_id")
        trial = {"outcome": outcome, "existing": bool(result.get("existing")), "thread_id": thread_id if isinstance(thread_id, str) else None}
        return self._result("trial", task=await self._view(current), trial=trial)

    async def _pause_or_delete(self, action: str, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["id"]
        if action == "pause" and task.get("status") == "running":
            raise scheduler_error(409, "task_running", "Scheduled task is currently running; retry after the active execution finishes")
        if action == "pause":
            outcome = await self._task_repo.pause_with_queue_cancellation(task_id, user_id=self._owner_id, error=host_notes.RUN_ERROR_PAUSED_WHILE_QUEUED, now=datetime.now(UTC))
        else:
            outcome = await self._task_repo.delete_with_queue_cancellation(task_id, user_id=self._owner_id, error=host_notes.RUN_ERROR_DELETED_WHILE_QUEUED, now=datetime.now(UTC))
        if outcome == "not_found":
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        if outcome == "executing":
            raise scheduler_error(409, "task_running", "Scheduled task is already launching or running; retry after the active execution finishes")
        if outcome == "finished":
            raise scheduler_error(409, "task_finished", "Scheduled task has finished; resume it to run again")
        if action == "delete":
            return self._result("delete", deleted=True, task={"id": task_id, "title": task.get("title")})
        paused = await self._task_repo.get(task_id, user_id=self._owner_id)
        if paused is None:
            raise scheduler_error(404, "task_not_found", "Scheduled task not found")
        return self._result("pause", task=await self._view(paused))

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
            return {"action": "stop", "stop_requested": True}
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
    client_timezone: str | None = None,
) -> SchedulerRunCapability | None:
    """Bind private host authority; do not retain the Request or internal user.

    ``client_timezone`` is the already-validated browser zone the web client
    sent with this turn; only new tasks default to it.
    """
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
    # A task made while this process's poller is off would never run on schedule.
    if getattr(service, "is_running", False) is not True:
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
        _display="card" if source in {AUTH_SOURCE_SESSION, AUTH_SOURCE_AUTH_DISABLED} else "text",
        _client_timezone=client_timezone if isinstance(client_timezone, str) and client_timezone else None,
    )
