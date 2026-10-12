"""Gateway schedule grants retain the owner's permissions and origin scope."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from _router_auth_helpers import call_unwrapped

from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION
from app.gateway.authz import AuthContext
from app.gateway.routers import scheduled_tasks
from deerflow.agents.interaction_policy import RunInteractionMode, RunInteractionPolicy
from deerflow.config.app_config import AppConfig
from deerflow.persistence.scheduled_tasks import ActiveScheduledTaskMutationConflict

_PERMISSIONS = ("threads:read", "threads:write", "runs:create")


def _user(*, user_id="alice", token_version=0, role="user"):
    return SimpleNamespace(id=user_id, token_version=token_version, system_role=role, needs_setup=False)


_FUTURE = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()


def _task(*, user_id="alice", origin="origin", **updates):
    return {
        "id": "task-1",
        "user_id": user_id,
        "origin_thread_id": origin,
        "title": "Report",
        "prompt": "Write the report",
        "stop_condition": None,
        "status": "enabled",
        "schedule_type": "interval",
        "schedule_spec": {"every_seconds": 3600},
        "timezone": "UTC",
        "next_run_at": _FUTURE,
        "context_mode": "fresh_thread_per_run",
        "goal_objective": None,
        "max_runs": None,
        "end_at": None,
        "standing_notes": [],
        **updates,
    }


def _setup(monkeypatch, *, source=AUTH_SOURCE_SESSION, permissions=_PERMISSIONS, original_text="Run this task now", mode="interactive", task=None, enabled=True, tool_enabled=True):
    from app.gateway import scheduled_task_access as access

    user = _user()
    repo = SimpleNamespace(
        get=AsyncMock(return_value=task or _task()),
        list_by_origin_thread=AsyncMock(return_value=[task or _task()]),
        list_manageable_from_thread=AsyncMock(return_value=[task or _task()]),
        create=AsyncMock(side_effect=lambda **values: {"id": values["task_id"], "status": "enabled", **values}),
        pause_with_queue_cancellation=AsyncMock(return_value="paused"),
        delete_with_queue_cancellation=AsyncMock(return_value="deleted"),
        append_standing_note=AsyncMock(return_value=task or _task(standing_notes=["use develop"])),
        get_active_run_status=AsyncMock(return_value=None),
        active_run_status_for=AsyncMock(return_value={}),
        automatic_runs_used_for=AsyncMock(return_value={}),
    )

    async def update(task_id, *, user_id, updates, require_mutable=False):
        return {**(await repo.get(task_id, user_id=user_id)), **updates}

    repo.update = AsyncMock(side_effect=update)
    occurrences = SimpleNamespace(request_stop=AsyncMock(return_value=True), task_ids_for_thread=AsyncMock(return_value=[]), list_by_task=AsyncMock(return_value=[]))
    service = SimpleNamespace(is_running=True, dispatch_task=AsyncMock(return_value={"outcome": "launched", "run_id": "trial-run", "thread_id": "trial-thread", "existing": False}))
    threads = SimpleNamespace(get=AsyncMock(return_value={"user_id": "alice"}), check_access=AsyncMock(return_value=True))
    provider = SimpleNamespace(get_user=AsyncMock(return_value=user))
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "scheduler": {"enabled": enabled, "tool_enabled": tool_enabled}})
    request = SimpleNamespace(state=SimpleNamespace(auth_source=source, user=user, auth=AuthContext(user, list(permissions))), app=SimpleNamespace(state=SimpleNamespace(scheduled_task_service=service)))
    monkeypatch.setattr(access, "get_config", lambda: config)
    monkeypatch.setattr(access, "get_scheduled_task_repo", lambda _request: repo)
    monkeypatch.setattr(access, "get_scheduled_task_run_repo", lambda _request: occurrences)
    monkeypatch.setattr(access, "get_scheduled_task_service", lambda _request: service)
    monkeypatch.setattr(access, "get_thread_store", lambda _request: threads)
    monkeypatch.setattr(access, "get_local_provider", lambda: provider)
    resolve = AsyncMock(return_value=list(permissions))
    monkeypatch.setattr(access, "resolve_route_permissions", resolve)

    async def prepare(**updates):
        return await access.prepare_scheduler_capability(
            request,
            user=user,
            thread_id="origin",
            run_id="run-1",
            assistant_id="lead_agent",
            original_user_text=original_text,
            interaction_policy=RunInteractionPolicy(RunInteractionMode(mode)),
            **updates,
        )

    return prepare, repo, occurrences, service, threads, provider, resolve, request


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, AUTH_SOURCE_PAT, "unknown"])
async def test_untrusted_auth_sources_cannot_receive_a_schedule_grant(monkeypatch, source):
    prepare, *_ = _setup(monkeypatch, source=source)
    assert await prepare() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("enabled", "tool_enabled"), [(False, True), (True, False)])
async def test_operator_flags_withhold_the_gateway_grant(monkeypatch, enabled, tool_enabled):
    prepare, *_ = _setup(monkeypatch, enabled=enabled, tool_enabled=tool_enabled)
    assert await prepare() is None


@pytest.mark.asyncio
async def test_capability_requires_the_running_scheduler_service(monkeypatch):
    from fastapi import HTTPException

    from app.gateway import scheduled_task_access as access

    prepare, _, _, service, *_ = _setup(monkeypatch)
    service.is_running = False
    assert await prepare() is None
    service.is_running = True
    assert await prepare() is not None
    monkeypatch.setattr(access, "get_scheduled_task_service", lambda _request: (_ for _ in ()).throw(HTTPException(503)))
    assert await prepare() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scheduled", "autonomous", "webhook"])
async def test_noninteractive_runs_without_private_occurrence_authority_get_no_grant(monkeypatch, mode):
    prepare, *_ = _setup(monkeypatch, mode=mode)
    assert await prepare() is None


@pytest.mark.asyncio
async def test_session_principal_and_permission_ceiling_cannot_be_widened(monkeypatch):
    prepare, repo, _, _, _, _, resolve, request = _setup(monkeypatch, permissions=("threads:read",))
    capability = await prepare()
    resolve.return_value = list(_PERMISSIONS)
    result = await capability.manage(action="create", request={})
    assert result["status_code"] == 403
    repo.create.assert_not_awaited()
    request.state.auth.user = _user(user_id="bob")
    assert await prepare() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, _user(user_id="bob"), _user(token_version=1)])
async def test_deleted_changed_or_revoked_owner_cannot_use_an_existing_grant(monkeypatch, owner):
    prepare, repo, _, _, _, provider, _, _ = _setup(monkeypatch)
    capability = await prepare()
    provider.get_user.return_value = owner
    result = await capability.manage(action="list", request={})
    assert result["status_code"] == 401
    repo.list_manageable_from_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_permission_revocation_is_honored_each_action(monkeypatch):
    prepare, repo, _, _, _, _, resolve, _ = _setup(monkeypatch)
    capability = await prepare()
    resolve.return_value = []
    result = await capability.manage(action="list", request={})
    assert result["status_code"] == 403
    repo.list_manageable_from_thread.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "permission"), [("list", "threads:read"), ("create", "runs:create"), ("pause", "threads:write"), ("delete", "threads:write"), ("note", "threads:write"), ("trial", "runs:create")])
async def test_each_action_checks_its_route_permissions(monkeypatch, action, permission):
    prepare, repo, _, service, *_ = _setup(monkeypatch, permissions=tuple(value for value in _PERMISSIONS if value != permission))
    capability = await prepare()
    result = await capability.manage(action=action, request={"task_id": "task-1"})
    assert result["status_code"] == 403
    repo.get.assert_not_awaited()
    repo.create.assert_not_awaited()
    service.dispatch_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("source_owner", [None, "bob"])
async def test_deleted_shared_or_foreign_origin_is_not_a_management_grant(monkeypatch, source_owner):
    prepare, _, _, _, threads, *_ = _setup(monkeypatch)
    threads.get.return_value = None if source_owner is None else {"user_id": source_owner}
    assert await prepare() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("task", [_task(user_id="bob"), _task(origin="other-origin"), _task(origin=None)])
@pytest.mark.parametrize("action", ["pause", "delete", "note", "trial"])
async def test_management_targets_require_both_owner_and_origin(monkeypatch, task, action):
    prepare, repo, _, service, *_ = _setup(monkeypatch, task=task, original_text="use develop")
    capability = await prepare()
    payload = {"task_id": "task-1", **({"note": "use develop"} if action == "note" else {})}
    result = await capability.manage(action=action, request=payload)
    assert result["status_code"] == 404
    repo.pause_with_queue_cancellation.assert_not_awaited()
    repo.delete_with_queue_cancellation.assert_not_awaited()
    repo.append_standing_note.assert_not_awaited()
    service.dispatch_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_projects_only_safe_fields_from_the_bound_origin(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, task=_task(secret="must-not-leak", lease_owner="private-worker", standing_notes=["use develop"]))
    capability = await prepare()
    result = await capability.manage(action="list", request={})
    repo.list_manageable_from_thread.assert_awaited_once_with("alice", "origin")
    assert result["tasks"][0]["standing_notes"] == ["use develop"]
    assert "secret" not in result["tasks"][0]
    assert "lease_owner" not in result["tasks"][0]
    assert "next_run_at" not in result["tasks"][0]


@pytest.mark.asyncio
async def test_create_uses_bound_origin_and_echoes_goal_and_stop_details(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    result = await capability.manage(
        action="create",
        request={"title": "Report", "prompt": "Write the report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC", "goal_objective": "Write a report from the source documents", "max_runs": 3},
    )
    values = repo.create.await_args.kwargs
    assert values["user_id"] == "alice"
    assert values["origin_thread_id"] == "origin"
    assert values["thread_id"] is None
    assert values["assistant_id"] == "lead_agent"
    task = result["task"]
    assert task["goal_objective"] == "Write a report from the source documents"
    assert task["max_runs"] == 3
    assert task["next_run_local"].endswith("(UTC)")
    assert "next_run_at" not in task
    assert "stop_instructions" not in result
    assert "stop_instructions" not in task


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", ["", " \t\n ", "g" * 4001])
async def test_create_rejects_invalid_goal_before_persisting_schedule(monkeypatch, objective):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    result = await capability.manage(action="create", request={"title": "Report", "prompt": "Write report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC", "goal_objective": objective})
    assert result["status_code"] == 422
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [None, "  " + "g" * 4000 + "\t\n"])
async def test_create_preserves_optional_and_normalized_boundary_goal(monkeypatch, objective):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    result = await capability.manage(action="create", request={"title": "Report", "prompt": "Write report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC", "goal_objective": objective})
    assert "error" not in result
    assert result["task"]["goal_objective"] == objective
    assert repo.create.await_args.kwargs["goal_objective"] == objective


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"user_id": "bob"}, {"thread_id": "other-origin"}, {"assistant_id": "other-agent"}, {"origin_thread_id": "other-origin"}])
async def test_model_identity_fields_are_rejected_even_if_directly_called(monkeypatch, payload):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    result = await capability.manage(action="create", request=payload)
    assert result["status_code"] == 422
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("schedule_type,schedule_spec", [("interval", {"every_seconds": 60}), ("cron", {"cron": "*/5 * * * *"}), ("cron", {"cron": "0,30 * * * *"})])
async def test_frequent_conversation_schedules_require_a_user_end_condition(monkeypatch, schedule_type, schedule_spec):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    result = await capability.manage(action="create", request={"title": "Check", "prompt": "Check sources", "schedule_type": schedule_type, "schedule_spec": schedule_spec, "timezone": "UTC"})
    assert result["status_code"] == 422
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_reused_thread_goal_is_rejected(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    result = await capability.manage(
        action="create", request={"title": "Report", "prompt": "Write report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC", "context_mode": "reuse_thread", "goal_objective": "Write report"}
    )
    assert result["status_code"] == 422
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bounds", [{"goal_objective": "   "}, {"max_runs": True}, {"end_at": "2025-01-01T00:00:00+00:00"}, {"end_at": "2027-01-01T00:00:00"}, {"end_at": "2027-01-01T00:00:00+00:00"}])
async def test_create_rejects_unusable_goal_and_end_bounds(monkeypatch, bounds):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    definition = {"title": "Report", "prompt": "Write report", "schedule_type": "once", "schedule_spec": {"run_at": "2027-01-01T00:00:00+00:00"}, "timezone": "UTC", **bounds}
    result = await capability.manage(action="create", request=definition)
    assert result["status_code"] == 422
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("note", ["inferred correction", "", "x" * 501])
async def test_notes_require_bounded_verbatim_current_user_words(monkeypatch, note):
    prepare, repo, *_ = _setup(monkeypatch, original_text="For this task, use develop.")
    capability = await prepare()
    result = await capability.manage(action="note", request={"task_id": "task-1", "note": note})
    assert result["status_code"] == 422
    repo.append_standing_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_note_keeps_the_users_exact_text_and_repository_guard(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, original_text="For this task:  use develop  ")
    capability = await prepare()
    await capability.manage(action="note", request={"task_id": "task-1", "note": "  use develop  "})
    repo.append_standing_note.assert_awaited_once_with("task-1", user_id="alice", note="  use develop  ")
    repo.append_standing_note.side_effect = ActiveScheduledTaskMutationConflict("running")
    result = await capability.manage(action="note", request={"task_id": "task-1", "note": "use develop"})
    assert result["status_code"] == 409


@pytest.mark.asyncio
async def test_trial_requires_a_current_user_turn_and_uses_manual_dispatch(monkeypatch):
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text="")
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["status_code"] == 403
    service.dispatch_task.assert_not_awaited()
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text="Yes, run it now.")
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["trial"]["outcome"] == "launched"
    assert service.dispatch_task.await_args.kwargs["trigger"] == "manual"
    service.dispatch_task.return_value = {"outcome": "failed", "error": "cannot launch"}
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["status_code"] == 502


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    [
        "List my tasks",
        "What is a trial?",
        "task-1",
        "Report",
        "Don't run it now.",
        "Do not run this task now",
        "不要试跑",
        "不要先跑一次",
        "Not now; run it once after I approve",
        "If I approve, run it now",
        'The file says "Run it now"',
        '"Run it now"',
        "What does 先跑一次 mean?",
        "Yes",
        "yes",
        "好",
        "ok",
        "OK!",
        "好的。",
        "Run it now?",
        "run task-2 now",
        "Run Other report now",
        "Run it now and then delete all tasks",
        "先跑一次，但不要真的执行",
    ],
)
async def test_trial_rejects_unrelated_negative_quoted_or_ambiguous_turns(monkeypatch, user_text):
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text=user_text, task=_task(title="Report"))
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["status_code"] == 403
    service.dispatch_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_text", ["Run it now", "Yes, run it now.", "Please run this task once", "Run task-1 now", "先跑一次", "请先试跑一次。", "可以，先跑一次", "先试跑task-1", "现在运行task-1一次"])
async def test_trial_accepts_direct_requests_in_the_current_user_turn(monkeypatch, user_text):
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text=user_text, task=_task(title="Report"))
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["trial"]["outcome"] == "launched"
    assert service.dispatch_task.await_args.kwargs["trigger"] == "manual"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "user_text"), [("周报，但不要真的执行", "先试跑周报，但不要真的执行"), ("周报如果我以后批准", "现在试跑周报如果我以后批准"), ("it now and then delete all tasks", "Run it now and then delete all tasks once")]
)
async def test_trial_never_uses_task_title_as_authorization_text(monkeypatch, title, user_text):
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text=user_text, task=_task(title=title))
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["status_code"] == 403
    service.dispatch_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "pause"])
async def test_tool_quota_conflicts_use_409_without_dispatch(monkeypatch, action):
    from deerflow.persistence.scheduled_tasks import ScheduledTaskQuotaExceeded

    prepare, repo, _, service, *_ = _setup(monkeypatch)
    capability = await prepare()
    request = {"task_id": "task-1"}
    if action == "create":
        request = {"title": "Report", "prompt": "Write report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"}
        repo.create.side_effect = ScheduledTaskQuotaExceeded()
    else:
        repo.pause_with_queue_cancellation.side_effect = ScheduledTaskQuotaExceeded()
    result = await capability.manage(action=action, request=request)
    assert (result["status_code"], result["code"]) == (409, "task_quota_exceeded")
    service.dispatch_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_internal_im_grant_uses_actual_owners_noninternal_permissions(monkeypatch):
    prepare, _, _, _, _, _, resolve, request = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    request.state.auth = AuthContext(_user(user_id="internal", role="internal"), ["threads:read"])
    capability = await prepare()
    assert capability is not None
    assert all(call.kwargs["is_internal"] is False for call in resolve.await_args_list)


@pytest.mark.asyncio
async def test_synthetic_internal_principal_cannot_become_the_schedule_owner(monkeypatch):
    prepare, _, _, _, _, provider, _, request = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    request.state.user.system_role = "internal"
    provider.get_user.return_value.system_role = "internal"
    assert await prepare() is None


@pytest.mark.asyncio
async def test_scheduled_grant_only_stops_the_privately_bound_occurrence(monkeypatch):
    prepare, _, occurrences, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled")
    capability = await prepare(scheduled_task_runtime={"user_id": "alice", "task_id": "task-1", "occurrence_id": "occurrence-1"})
    assert capability.mode == "scheduled"
    result = await capability.stop_current_schedule()
    assert result == {"action": "stop", "stop_requested": True}
    occurrences.request_stop.assert_awaited_once_with("occurrence-1", task_id="task-1", run_id="run-1", user_id="alice")
    result = await capability.manage(action="list", request={})
    assert result["status_code"] == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", [{"user_id": "bob", "task_id": "task-1", "occurrence_id": "occurrence-1"}, {"user_id": "alice", "task_id": "task-1"}])
async def test_scheduled_runtime_must_bind_the_actual_owner_and_occurrence(monkeypatch, runtime):
    prepare, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled")
    assert await prepare(scheduled_task_runtime=runtime) is None


@pytest.mark.asyncio
async def test_self_stop_rechecks_permissions_and_durable_occurrence_binding(monkeypatch):
    prepare, _, occurrences, _, _, _, resolve, _ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled")
    capability = await prepare(scheduled_task_runtime={"user_id": "alice", "task_id": "task-1", "occurrence_id": "occurrence-1"})
    occurrences.request_stop.return_value = False
    stopped = await capability.stop_current_schedule()
    assert (stopped["status_code"], stopped["code"]) == (409, "occurrence_not_active")
    resolve.return_value = ["threads:read"]
    stopped = await capability.stop_current_schedule()
    assert (stopped["status_code"], stopped["code"]) == (403, "permission_denied")
    assert occurrences.request_stop.await_count == 1


@pytest.mark.asyncio
async def test_auth_disabled_default_owner_needs_the_explicit_host_mode(monkeypatch):
    from app.gateway import scheduled_task_access as access
    from app.gateway.auth_disabled import get_auth_disabled_user

    prepare, _, _, _, threads, provider, _, request = _setup(monkeypatch, source=AUTH_SOURCE_AUTH_DISABLED)
    user = get_auth_disabled_user()
    request.state.user = user
    request.state.auth = AuthContext(user, list(_PERMISSIONS))
    threads.get.return_value = {"user_id": str(user.id)}
    provider.get_user.return_value = None
    monkeypatch.setattr(access, "is_auth_disabled", lambda: True)
    capability = await access.prepare_scheduler_capability(request, user=user, thread_id="origin", run_id="run-1", assistant_id="lead_agent", original_user_text="List tasks", interaction_policy=RunInteractionPolicy.interactive())
    assert capability is not None
    result = await capability.manage(action="list", request={})
    assert "error" not in result
    monkeypatch.setattr(access, "is_auth_disabled", lambda: False)
    result = await capability.manage(action="list", request={})
    assert result["status_code"] == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"timezone": "missing/zone"},
        {"timezone": "Europe"},
        {"schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "Europe"},
        {"schedule_type": "unsupported"},
        {"schedule_spec": {"every_seconds": 1}},
        {"schedule_type": "cron", "schedule_spec": {"cron": "not cron"}},
        {"context_mode": "wrong"},
        {"schedule_type": "once", "schedule_spec": {"run_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}},
    ],
)
async def test_rest_and_tool_share_creation_validation_status_and_reason(monkeypatch, updates):
    prepare, repo, _, _, threads, _, _, request = _setup(monkeypatch)
    capability = await prepare()
    body = {"title": "Task", "prompt": "Work", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC", **updates}
    tool_result = await capability.manage(action="create", request=body)
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda _request: repo)
    monkeypatch.setattr(scheduled_tasks, "get_thread_store", lambda _request: threads)
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=_user()))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await call_unwrapped(scheduled_tasks.create_scheduled_task, request=request, body=scheduled_tasks.ScheduledTaskCreateRequest(**body))
    assert tool_result["status_code"] == error.value.status_code
    assert tool_result["code"] == error.value.detail["code"]
    assert tool_result["error"] == error.value.detail["message"]


@pytest.mark.asyncio
async def test_capability_maps_real_repository_note_capacity_and_live_task_limit(monkeypatch, tmp_path):
    from app.gateway import scheduled_task_access as access
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        prepare, *_ = _setup(monkeypatch, original_text=" ".join(f"note-{index}" for index in range(11)))
        repo = ScheduledTaskRepository(get_session_factory())
        monkeypatch.setattr(access, "get_scheduled_task_repo", lambda _request: repo)
        capability = await prepare()
        definition = {"title": "Report", "prompt": "Write report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"}
        created = (await capability.manage(action="create", request=definition))["task"]
        for index in range(10):
            result = await capability.manage(action="note", request={"task_id": created["id"], "note": f"note-{index}"})
            assert "error" not in result
        result = await capability.manage(action="note", request={"task_id": created["id"], "note": "note-10"})
        assert (result["status_code"], result["code"], result["params"]) == (422, "note_limit_reached", {"limit": 10})
        stored = await repo.get(created["id"], user_id="alice")
        assert len(stored["standing_notes"]) == 10
        for _ in range(19):
            assert "error" not in await capability.manage(action="create", request=definition)
        result = await capability.manage(action="create", request=definition)
        assert (result["status_code"], result["code"]) == (409, "task_quota_exceeded")
        assert "20 live" in result["error"]
        assert len(await repo.list_by_origin_thread("alice", "origin")) == 20
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_capability_and_shared_validation_offload_configuration_and_timezone_io(monkeypatch, tmp_path):
    from support.detectors.blocking_io_runtime import detect_blocking_io_strict

    from app.gateway import scheduled_task_access as access
    from app.gateway import scheduled_task_validation as validation

    prepare, *_ = _setup(monkeypatch)
    config = access.get_config()
    marker = tmp_path / "configuration-and-timezone-fixture.txt"
    marker.write_text("fixture", encoding="utf-8")
    original_validate_timezone = validation.validate_timezone

    def read_config():
        marker.read_text(encoding="utf-8")
        return config

    def read_timezone(timezone):
        marker.read_text(encoding="utf-8")
        return original_validate_timezone(timezone)

    monkeypatch.setattr(access, "get_config", read_config)
    monkeypatch.setattr(validation, "validate_timezone", read_timezone)
    with detect_blocking_io_strict():
        capability = await prepare()
        result = await capability.manage(action="create", request={"title": "Report", "prompt": "Write report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "timezone": "UTC"})
    assert "error" not in result


@pytest.mark.asyncio
async def test_scheduled_grant_for_a_page_created_task_stops_only_its_own_occurrence(monkeypatch):
    prepare, repo, occurrences, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled", task=_task(origin=None))
    capability = await prepare(scheduled_task_runtime={"user_id": "alice", "task_id": "task-1", "occurrence_id": "occurrence-1"})
    assert capability is not None
    result = await capability.stop_current_schedule()
    assert result["stop_requested"] is True
    occurrences.request_stop.assert_awaited_once_with("occurrence-1", task_id="task-1", run_id="run-1", user_id="alice")
    managed = await capability.manage(action="pause", request={"task_id": "task-1"})
    assert (managed["status_code"], managed["code"]) == (403, "interactive_run_required")
    repo.pause_with_queue_cancellation.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_grant_cannot_stop_another_task(monkeypatch):
    prepare, repo, occurrences, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled", task=_task(origin=None))
    capability = await prepare(scheduled_task_runtime={"user_id": "alice", "task_id": "task-1", "occurrence_id": "occurrence-1"})
    repo.get.return_value = {**_task(origin=None), "id": "task-2"}
    result = await capability.stop_current_schedule()
    assert (result["status_code"], result["code"]) == (404, "task_not_found")
    occurrences.request_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_capability_pause_of_a_finished_task_is_coded(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    repo.pause_with_queue_cancellation.return_value = "finished"
    capability = await prepare()
    result = await capability.manage(action="pause", request={"task_id": "task-1"})
    assert result == {"error": "Scheduled task has finished; resume it to run again", "code": "task_finished", "status_code": 409}


# --- WP2: conversation update/resume, run-conversation authority, results --------------------------

_INTERVAL = {"title": "Report", "prompt": "Write the report", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}}


async def _real_repos(monkeypatch, tmp_path, **setup):
    """``_setup`` backed by real SQLite repositories (owner ``alice``, conversation ``origin``)."""
    from app.gateway import scheduled_task_access as access
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import get_session_factory, init_engine_from_config
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    prepare, _, _, service, threads, *_ = _setup(monkeypatch, **setup)
    sf = get_session_factory()
    repo, runs = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    monkeypatch.setattr(access, "get_scheduled_task_repo", lambda _request: repo)
    monkeypatch.setattr(access, "get_scheduled_task_run_repo", lambda _request: runs)
    return prepare, sf, repo, runs, service, threads


async def _seed_task(repo, task_id="task-1", *, origin_thread_id="origin", schedule_spec=None, **extra):
    from _scheduled_rows import BASE

    return await repo.create(
        task_id=task_id,
        user_id="alice",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title=task_id,
        prompt="Summarize the notifications.",
        schedule_type="interval",
        schedule_spec=schedule_spec or {"every_seconds": 3600},
        timezone="UTC",
        next_run_at=BASE,
        origin_thread_id=origin_thread_id,
        **extra,
    )


async def _seed_runs(sf, *rows):
    async with sf() as session:
        session.add_all(list(rows))
        await session.commit()


@pytest.mark.asyncio
async def test_update_keeps_task_id_and_never_deletes(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence

    from deerflow.persistence.engine import close_engine

    prepare, sf, repo, runs, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        await _seed_task(repo)
        await _seed_runs(sf, occurrence("trial", "task-1", seq=None, trigger="manual", accounted=None))
        capability = await prepare(client_timezone="Asia/Shanghai")
        result = await capability.manage(action="update", request={"task_id": "task-1", "schedule_type": "cron", "schedule_spec": {"cron": "0 10 * * *"}, "timezone": "Asia/Shanghai"})
        assert result["action"] == "update"
        assert result["task"]["id"] == "task-1"
        assert result["task"]["schedule_spec"] == {"cron": "0 10 * * *"}
        assert result["task"]["next_run_local"].endswith("10:00 (Asia/Shanghai)")
        assert [task["id"] for task in await repo.list_by_user("alice")] == ["task-1"]
        assert len(await runs.list_by_task("task-1")) == 1
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_create_and_update_store_stop_condition_separately(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare(client_timezone="Asia/Shanghai")
    created = await capability.manage(action="create", request={**_INTERVAL, "prompt": "Check release-checklist.md", "stop_condition": "every item\n  is checked", "max_runs": 5})
    values = repo.create.await_args.kwargs
    assert values["prompt"] == "Check release-checklist.md"
    assert values["stop_condition"] == "every item is checked"
    assert created["task"]["prompt"] == "Check release-checklist.md"
    assert created["task"]["stop_condition"] == "every item is checked"
    repo.get.return_value = _task(stop_condition="every item is checked")
    updated = await capability.manage(action="update", request={"task_id": "task-1", "clear_fields": ["stop_condition"]})
    updates = repo.update.await_args.kwargs["updates"]
    assert updates["stop_condition"] is None
    assert "prompt" not in updates
    assert updated["task"]["stop_condition"] is None
    assert updated["task"]["prompt"] == "Write the report"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_updates", "fields"),
    [
        ({}, {"schedule_spec": {"every_seconds": 600}}),
        ({"timezone": "Asia/Shanghai"}, {"end_at": "2020-01-01T00:00:00"}),
        ({}, {"timezone": "missing/zone"}),
        ({}, {"timezone": "Europe"}),
    ],
    ids=["sub-hourly-without-cap", "end-at-past", "invalid-timezone", "timezone-directory"],
)
async def test_update_shares_rest_validation_codes(monkeypatch, task_updates, fields):
    from fastapi import HTTPException

    prepare, repo, _, _, threads, _, _, request = _setup(monkeypatch, task=_task(**task_updates))
    capability = await prepare()
    tool_result = await capability.manage(action="update", request={"task_id": "task-1", **fields})
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda _request: repo)
    monkeypatch.setattr(scheduled_tasks, "get_thread_store", lambda _request: threads)
    monkeypatch.setattr(scheduled_tasks, "get_config", lambda: AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=_user()))
    with pytest.raises(HTTPException) as error:
        await call_unwrapped(scheduled_tasks.update_scheduled_task, task_id="task-1", request=request, body=scheduled_tasks.ScheduledTaskUpdateRequest(**fields))
    assert tool_result["code"] == error.value.detail["code"]
    assert tool_result["status_code"] == error.value.status_code
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_recomputes_and_reports_limits_exhausted_with_renewal(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence

    from deerflow.persistence.engine import close_engine

    prepare, sf, repo, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        await _seed_task(repo, max_runs=2)
        await _seed_runs(sf, occurrence("a1", seq=1), occurrence("a2", seq=2))
        await repo.update("task-1", user_id="alice", updates={"status": "completed", "next_run_at": None})
        capability = await prepare()
        exhausted = await capability.manage(action="resume", request={"task_id": "task-1"})
        assert (exhausted["status_code"], exhausted["code"]) == (409, "limits_exhausted")
        assert exhausted["params"] == {"limit": "max_runs", "used": 2, "max_runs": 2, "end_at": None}
        assert (await repo.get("task-1", user_id="alice"))["status"] == "completed"
        too_low = await capability.manage(action="resume", request={"task_id": "task-1", "max_runs": 2})
        assert (too_low["code"], too_low["params"]) == ("max_runs_not_above_used", {"used": 2})
        resumed = await capability.manage(action="resume", request={"task_id": "task-1", "max_runs": 4})
        assert resumed["action"] == "resume"
        assert (resumed["task"]["status"], resumed["task"]["max_runs"], resumed["task"]["automatic_runs_used"]) == ("enabled", 4, 2)
        stored = await repo.get("task-1", user_id="alice")
        # No catch-up run: the next run is computed from now.
        assert datetime.fromisoformat(stored["next_run_at"]).astimezone(UTC) > datetime.now(UTC) + timedelta(minutes=55)
        assert resumed["task"]["next_run_local"].endswith("(UTC)")
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_run_conversation_can_manage_its_task(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence

    from deerflow.persistence.engine import close_engine

    # This turn runs in "origin", which is a run conversation of a page-created task.
    prepare, sf, repo, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        await _seed_task(repo, origin_thread_id=None)
        await _seed_runs(sf, occurrence("a1", seq=1, thread_id="origin"))
        capability = await prepare()
        listed = await capability.manage(action="list", request={})
        assert [task["id"] for task in listed["tasks"]] == ["task-1"]
        assert listed["tasks"][0]["last_run"]["status"] == "success"
        paused = await capability.manage(action="pause", request={"task_id": "task-1"})
        assert (paused["action"], paused["task"]["status"]) == ("pause", "paused")
    finally:
        await close_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["foreign-owner", "unrelated-thread"])
async def test_foreign_or_unrelated_run_thread_grants_nothing(monkeypatch, tmp_path, case):
    from _scheduled_rows import create_task, occurrence

    from deerflow.persistence.engine import close_engine

    prepare, sf, repo, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        if case == "foreign-owner":
            await create_task(repo, "task-1", user_id="bob")
            await _seed_runs(sf, occurrence("a1", seq=1, thread_id="origin"))
        else:
            await _seed_task(repo, origin_thread_id=None)
            await _seed_runs(sf, occurrence("a1", seq=1, thread_id="other-thread"))
        capability = await prepare()
        assert (await capability.manage(action="list", request={}))["tasks"] == []
        for action in ("pause", "update", "resume", "delete", "trial"):
            result = await capability.manage(action=action, request={"task_id": "task-1"})
            assert (result["status_code"], result["code"]) == (404, "task_not_found"), action
        assert (await repo.get_internal("task-1"))["status"] == "enabled"
    finally:
        await close_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["list", "update", "resume", "pause", "create"])
async def test_scheduled_mode_still_cannot_manage(monkeypatch, action):
    prepare, repo, occurrences, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL, mode="scheduled")
    occurrences.task_ids_for_thread.return_value = ["task-1"]
    capability = await prepare(scheduled_task_runtime={"user_id": "alice", "task_id": "task-1", "occurrence_id": "occurrence-1"})
    result = await capability.manage(action=action, request={"task_id": "task-1"})
    assert (result["status_code"], result["code"]) == (403, "interactive_run_required")
    repo.update.assert_not_awaited()
    repo.pause_with_queue_cancellation.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_uses_browser_timezone_by_default(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare(client_timezone="Asia/Shanghai")
    result = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * 1-5"}})
    assert repo.create.await_args.kwargs["timezone"] == "Asia/Shanghai"
    assert (result["task"]["timezone"], result["task"]["timezone_source"]) == ("Asia/Shanghai", "browser_default")
    assert "browser_timezone" not in result["task"]
    assert result["task"]["next_run_local"].endswith("09:00 (Asia/Shanghai)")


@pytest.mark.asyncio
async def test_create_cron_without_any_timezone_asks(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    capability = await prepare()
    result = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}})
    assert (result["status_code"], result["code"]) == (422, "timezone_required")
    assert result["error"] == "Ask the user which timezone to use."
    assert result["params"] == {"now_local": None}
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_interval_without_any_timezone_needs_none(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    capability = await prepare()
    result = await capability.manage(action="create", request={**_INTERVAL, "schedule_spec": {"every_seconds": 1800}, "max_runs": 5})
    assert "error" not in result
    assert repo.create.await_args.kwargs["timezone"] == "UTC"
    assert (result["task"]["timezone"], result["task"]["timezone_source"]) == ("UTC", "not_needed")


@pytest.mark.asyncio
async def test_create_once_with_offset_needs_no_timezone(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    capability = await prepare()
    run_at = (datetime.now(UTC) + timedelta(days=1)).astimezone(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()
    result = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "once", "schedule_spec": {"run_at": run_at}})
    assert "error" not in result
    assert result["task"]["timezone_source"] == "not_needed"
    assert repo.create.await_args.kwargs["next_run_at"] == datetime.fromisoformat(run_at)


@pytest.mark.asyncio
async def test_create_once_local_time_without_any_timezone_asks(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    capability = await prepare()
    run_at = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0, tzinfo=None).isoformat()
    result = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "once", "schedule_spec": {"run_at": run_at}})
    assert result["code"] == "timezone_required"
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_timezone_wins(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare(client_timezone="Europe/Berlin")
    result = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "Asia/Shanghai"})
    assert repo.create.await_args.kwargs["timezone"] == "Asia/Shanghai"
    assert (result["task"]["timezone_source"], result["task"]["browser_timezone"]) == ("explicit", "Europe/Berlin")
    same = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}, "timezone": "Europe/Berlin"})
    assert same["task"]["timezone_source"] == "explicit"
    assert "browser_timezone" not in same["task"]


@pytest.mark.asyncio
async def test_update_keeps_saved_timezone(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, task=_task(schedule_type="cron", schedule_spec={"cron": "0 9 * * *"}, timezone="Asia/Shanghai"))
    capability = await prepare(client_timezone="Europe/Berlin")
    result = await capability.manage(action="update", request={"task_id": "task-1", "schedule_spec": {"cron": "0 10 * * *"}})
    updates = repo.update.await_args.kwargs["updates"]
    assert "timezone" not in updates
    assert datetime.fromisoformat(str(updates["next_run_at"])).astimezone(ZoneInfo("Asia/Shanghai")).hour == 10
    assert (result["task"]["timezone"], result["task"]["timezone_source"]) == ("Asia/Shanghai", "saved")
    assert "browser_timezone" not in result["task"]


@pytest.mark.asyncio
async def test_update_from_a_zone_free_schedule_to_local_time_asks_for_a_timezone(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, task=_task(timezone="UTC"))
    capability = await prepare(client_timezone="Asia/Shanghai")
    result = await capability.manage(action="update", request={"task_id": "task-1", "schedule_type": "cron", "schedule_spec": {"cron": "0 9 * * *"}})
    assert result["code"] == "timezone_required"
    # "Now" is reported in the browser zone, never in the UTC placeholder.
    assert result["params"]["now_local"].endswith("(Asia/Shanghai)")
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_naive_end_at_without_any_timezone_asks(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, source=AUTH_SOURCE_INTERNAL)
    capability = await prepare()
    end_local = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0, tzinfo=None).isoformat()
    created = await capability.manage(action="create", request={**_INTERVAL, "end_at": end_local})
    assert (created["code"], created["params"]) == ("timezone_required", {"now_local": None})
    repo.create.assert_not_awaited()
    with_offset = await capability.manage(action="create", request={**_INTERVAL, "end_at": f"{end_local}+08:00"})
    assert with_offset["task"]["timezone_source"] == "not_needed"
    # An interval task saved with the UTC placeholder: a local end time asks too.
    updated = await capability.manage(action="update", request={"task_id": "task-1", "end_at": end_local})
    assert updated["code"] == "timezone_required"
    # Resume takes no timezone: it asks too, and an end time with an offset passes.
    resumed = await capability.manage(action="resume", request={"task_id": "task-1", "end_at": end_local})
    assert resumed["code"] == "timezone_required"
    assert "code" not in await capability.manage(action="resume", request={"task_id": "task-1", "end_at": f"{end_local}+08:00"})
    repo.update.assert_not_awaited()
    named = await capability.manage(action="update", request={"task_id": "task-1", "end_at": end_local, "timezone": "Asia/Shanghai"})
    assert named["task"]["timezone_source"] == "explicit"
    assert repo.update.await_args.kwargs["updates"]["end_at"] == datetime.fromisoformat(end_local).replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)


@pytest.mark.asyncio
async def test_create_and_update_results_have_now_local(monkeypatch):
    prepare, *_ = _setup(monkeypatch)
    capability = await prepare(client_timezone="Asia/Shanghai")
    created = await capability.manage(action="create", request=_INTERVAL)
    assert created["now_local"].endswith("(Asia/Shanghai)")
    updated = await capability.manage(action="update", request={"task_id": "task-1", "title": "Weekly report"})
    assert updated["now_local"].endswith("(UTC)")
    past = await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "once", "schedule_spec": {"run_at": "2020-01-01T09:00:00"}})
    assert past["code"] == "once_in_past"
    assert past["params"]["now_local"].endswith("(Asia/Shanghai)")


@pytest.mark.asyncio
async def test_naive_end_at_uses_task_timezone(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch, task=_task(timezone="Asia/Shanghai"))
    capability = await prepare(client_timezone="Asia/Shanghai")
    end_local = (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=30)).replace(hour=20, minute=0, second=0, microsecond=0)
    naive = end_local.replace(tzinfo=None).isoformat()
    created = await capability.manage(action="create", request={**_INTERVAL, "end_at": naive})
    assert repo.create.await_args.kwargs["end_at"] == end_local.astimezone(UTC)
    assert created["task"]["end_at_local"] == f"{end_local:%Y-%m-%d} 20:00 (Asia/Shanghai)"
    await capability.manage(action="update", request={"task_id": "task-1", "end_at": naive})
    assert repo.update.await_args.kwargs["updates"]["end_at"] == end_local.astimezone(UTC)


@pytest.mark.asyncio
async def test_resume_clear_fields_removes_cap_and_reactivates(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence

    from deerflow.persistence.engine import close_engine

    prepare, sf, repo, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        # Page-created, run conversation "origin": no sub-hourly cap rule.
        await _seed_task(repo, origin_thread_id=None, max_runs=1)
        await _seed_runs(sf, occurrence("a1", seq=1, thread_id="origin"))
        await repo.update("task-1", user_id="alice", updates={"status": "completed", "next_run_at": None})
        capability = await prepare()
        resumed = await capability.manage(action="resume", request={"task_id": "task-1", "clear_fields": ["max_runs"]})
        assert (resumed["task"]["status"], resumed["task"]["max_runs"]) == ("enabled", None)
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_resume_clear_fields_keeps_the_cap_rule_for_sub_hourly_chat_tasks(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence

    from deerflow.persistence.engine import close_engine

    prepare, sf, repo, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        await _seed_task(repo, schedule_spec={"every_seconds": 600}, max_runs=1)
        await _seed_runs(sf, occurrence("a1", seq=1))
        await repo.update("task-1", user_id="alice", updates={"status": "completed", "next_run_at": None})
        before = await repo.get("task-1", user_id="alice")
        capability = await prepare()
        result = await capability.manage(action="resume", request={"task_id": "task-1", "clear_fields": ["max_runs"]})
        assert (result["status_code"], result["code"]) == (422, "frequent_requires_limit")
        assert await repo.get("task-1", user_id="alice") == before
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_clear_fields_are_bounded_per_action(monkeypatch):
    prepare, repo, *_ = _setup(monkeypatch)
    capability = await prepare()
    resume = await capability.manage(action="resume", request={"task_id": "task-1", "clear_fields": ["stop_condition"]})
    assert resume["code"] == "unsupported_fields"
    both = await capability.manage(action="update", request={"task_id": "task-1", "max_runs": 3, "clear_fields": ["max_runs"]})
    assert both["code"] == "invalid_request"
    repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_trial_existing_queued_is_reported(monkeypatch):
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text="Run it now")
    service.dispatch_task.return_value = {"outcome": "queued", "existing": True, "thread_id": "queued-thread", "run_id": None}
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["trial"] == {"outcome": "queued", "existing": True, "thread_id": "queued-thread"}


@pytest.mark.asyncio
async def test_trial_result_has_thread_id(monkeypatch):
    prepare, *_ = _setup(monkeypatch, original_text="先跑一次")
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["action"] == "trial"
    assert result["trial"] == {"outcome": "launched", "existing": False, "thread_id": "trial-thread"}
    assert result["task"]["id"] == "task-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    [
        "Sure, run it now",
        "OK, run it now",
        "Run the task now",
        "Run this task now please",
        "好的，先跑一次",
        "先跑一次吧",
        "可以，先试一下吧",
        "试跑一下",
        "那就先跑一次看看",
        "Go ahead and run it now!",
        "好的，请先试跑一次。",
        "Try it out",
        "立即试运行",
    ],
)
async def test_trial_accepts_natural_direct_requests(monkeypatch, user_text):
    prepare, _, _, service, *_ = _setup(monkeypatch, original_text=user_text)
    capability = await prepare()
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["trial"]["outcome"] == "launched"
    assert service.dispatch_task.await_args.kwargs["trigger"] == "manual"


@pytest.mark.asyncio
@pytest.mark.parametrize(("source", "display"), [(AUTH_SOURCE_SESSION, "card"), (AUTH_SOURCE_INTERNAL, "text")])
async def test_results_are_display_card_for_session_and_text_for_internal(monkeypatch, source, display):
    prepare, *_ = _setup(monkeypatch, source=source, original_text="Run it now")
    capability = await prepare(client_timezone="UTC")
    for action, request in (("create", _INTERVAL), ("list", {}), ("pause", {"task_id": "task-1"}), ("trial", {"task_id": "task-1"})):
        result = await capability.manage(action=action, request=request)
        assert (result["action"], result["display"]) == (action, display)


def _keys(value):
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


async def _every_action_result(monkeypatch):
    task = _task(secret="must-not-leak", lease_owner="worker-1", lease_expires_at=_FUTURE, last_run_id="run-x", end_at=_FUTURE, max_runs=5, stop_condition="all done")
    prepare, repo, occurrences, *_ = _setup(monkeypatch, original_text="Run it now; use develop", task=task)
    repo.automatic_runs_used_for.return_value = {"task-1": 2}
    occurrences.list_by_task.return_value = [{"status": "unmet", "trigger": "scheduled", "finished_at": _FUTURE, "error": None, "goal_verdict": {"blocker": "goal_not_met_yet", "reason": "no"}, "run_id": "run-x"}]
    capability = await prepare(client_timezone="Asia/Shanghai")
    results = [
        await capability.manage(action="create", request={**_INTERVAL, "stop_condition": "all done", "max_runs": 5}),
        await capability.manage(action="update", request={"task_id": "task-1", "title": "Weekly"}),
        await capability.manage(action="list", request={}),
        await capability.manage(action="pause", request={"task_id": "task-1"}),
        await capability.manage(action="note", request={"task_id": "task-1", "note": "use develop"}),
        await capability.manage(action="trial", request={"task_id": "task-1"}),
        await capability.manage(action="delete", request={"task_id": "task-1"}),
        await capability.manage(action="create", request={**_INTERVAL, "schedule_type": "once", "schedule_spec": {"run_at": "2020-01-01T09:00:00"}}),
    ]
    repo.get.return_value = {**task, "status": "paused"}
    results.append(await capability.manage(action="resume", request={"task_id": "task-1"}))
    return results


@pytest.mark.asyncio
async def test_every_action_result_is_json_serializable(monkeypatch):
    import json

    results = await _every_action_result(monkeypatch)
    for result in results:
        assert json.loads(json.dumps(result)) == result
    assert results[-2]["code"] == "once_in_past"


@pytest.mark.asyncio
async def test_results_have_no_utc_or_lease_fields(monkeypatch):
    results = await _every_action_result(monkeypatch)
    forbidden = {"next_run_at", "end_at", "user_id", "lease_owner", "lease_expires_at", "stop_instructions", "origin_thread_id", "last_run_id", "secret"}
    for result in results:
        assert _keys(result).isdisjoint(forbidden), result
    listed = results[2]["tasks"][0]
    assert listed["last_run"] == {"status": "unmet", "trigger": "scheduled", "finished_local": listed["last_run"]["finished_local"], "reason_code": "goal_not_met_yet"}
    assert listed["last_run"]["finished_local"].endswith("(UTC)")
    assert (listed["automatic_runs_used"], listed["end_at_local"].endswith("(UTC)")) == (2, True)


@pytest.mark.asyncio
async def test_list_reports_last_run_and_no_next_run_when_paused(monkeypatch, tmp_path):
    from _scheduled_rows import occurrence

    from deerflow.persistence.engine import close_engine

    prepare, sf, repo, *_ = await _real_repos(monkeypatch, tmp_path)
    try:
        await _seed_task(repo, "task-1")
        await _seed_task(repo, "task-2")
        await _seed_runs(sf, occurrence("a1", seq=1, status="failed", error="interrupted: gateway restarted before the run reached a terminal state"), occurrence("a2", seq=2, status="unmet", error="evaluator_failed"))
        await repo.update("task-2", user_id="alice", updates={"status": "paused"})
        capability = await prepare(client_timezone="Asia/Shanghai")
        listed = await capability.manage(action="list", request={})
        by_id = {task["id"]: task for task in listed["tasks"]}
        assert by_id["task-1"]["last_run"]["status"] == "unmet"
        assert by_id["task-1"]["last_run"]["reason_code"] == "evaluator_failed"
        assert by_id["task-1"]["next_run_local"] is not None
        assert by_id["task-2"]["status"] == "paused"
        assert by_id["task-2"]["next_run_local"] is None
        assert by_id["task-2"]["last_run"] is None
        assert listed["default_timezone"] == "Asia/Shanghai"
        assert listed["now_local"].endswith("(Asia/Shanghai)")
    finally:
        await close_engine()


def test_host_run_errors_reach_the_agent_as_short_keys():
    from app.gateway.scheduled_task_access import _reason_code
    from deerflow.scheduler.host_notes import RUN_ERROR_QUEUE_TIMEOUT

    assert _reason_code({"status": "failed", "error": RUN_ERROR_QUEUE_TIMEOUT}) == "queue_timeout"
    assert _reason_code({"status": "unmet", "error": "blocked:external_wait"}) == "blocked:external_wait"
    assert _reason_code({"status": "failed", "error": "boom: Traceback ...", "run_id": None}) == "launch_failed"
    assert _reason_code({"status": "success"}) is None
