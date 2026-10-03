"""Gateway schedule grants retain the owner's permissions and origin scope."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


def _task(*, user_id="alice", origin="origin", **updates):
    return {"id": "task-1", "user_id": user_id, "origin_thread_id": origin, "status": "enabled", "schedule_type": "interval", "schedule_spec": {"every_seconds": 3600}, "goal_objective": None, "standing_notes": [], **updates}


def _setup(monkeypatch, *, source=AUTH_SOURCE_SESSION, permissions=_PERMISSIONS, original_text="Run this task now", mode="interactive", task=None, enabled=True, tool_enabled=True):
    from app.gateway import scheduled_task_access as access

    user = _user()
    repo = SimpleNamespace(
        get=AsyncMock(return_value=task or _task()),
        list_by_origin_thread=AsyncMock(return_value=[task or _task()]),
        create=AsyncMock(side_effect=lambda **values: {"id": values["task_id"], "status": "enabled", **values}),
        pause_with_queue_cancellation=AsyncMock(return_value="paused"),
        delete_with_queue_cancellation=AsyncMock(return_value="deleted"),
        append_standing_note=AsyncMock(return_value=task or _task(standing_notes=["use develop"])),
    )
    occurrences = SimpleNamespace(request_stop=AsyncMock(return_value=True))
    service = SimpleNamespace(dispatch_task=AsyncMock(return_value={"outcome": "launched", "run_id": "trial-run"}))
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

    prepare, *_ = _setup(monkeypatch)
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
    repo.list_by_origin_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_permission_revocation_is_honored_each_action(monkeypatch):
    prepare, repo, _, _, _, _, resolve, _ = _setup(monkeypatch)
    capability = await prepare()
    resolve.return_value = []
    result = await capability.manage(action="list", request={})
    assert result["status_code"] == 403
    repo.list_by_origin_thread.assert_not_awaited()


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
    repo.list_by_origin_thread.assert_awaited_once_with("alice", "origin")
    assert result["tasks"][0]["standing_notes"] == ["use develop"]
    assert "secret" not in result["tasks"][0]
    assert "lease_owner" not in result["tasks"][0]


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
    assert result["goal_objective"] == "Write a report from the source documents"
    assert result["max_runs"] == 3
    assert result["next_run_at"] is not None
    assert "stop_instructions" in result


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
    repo.append_standing_note.assert_awaited_once_with("task-1", user_id="alice", origin_thread_id="origin", note="  use develop  ")
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
    assert result["triggered"] is True
    assert service.dispatch_task.await_args.kwargs["trigger"] == "manual"
    service.dispatch_task.return_value = {"outcome": "failed", "error": "cannot launch"}
    result = await capability.manage(action="trial", request={"task_id": "task-1"})
    assert result["status_code"] == 502


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
    assert result["stop_requested"] is True
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
    assert (await capability.stop_current_schedule())["status_code"] == 409
    resolve.return_value = ["threads:read"]
    assert (await capability.stop_current_schedule())["status_code"] == 403
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
    assert tool_result["error"] == error.value.detail


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
        created = await capability.manage(action="create", request=definition)
        for index in range(10):
            result = await capability.manage(action="note", request={"task_id": created["id"], "note": f"note-{index}"})
            assert "error" not in result
        result = await capability.manage(action="note", request={"task_id": created["id"], "note": "note-10"})
        assert result["status_code"] == 422
        stored = await repo.get(created["id"], user_id="alice")
        assert len(stored["standing_notes"]) == 10
        for _ in range(19):
            assert "error" not in await capability.manage(action="create", request=definition)
        result = await capability.manage(action="create", request=definition)
        assert result["status_code"] == 422
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
