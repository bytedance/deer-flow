"""Narrow native MCP dependency receipts; checkpoints remain goal authority."""

import asyncio
from copy import deepcopy

from sqlalchemy import select

from ecs_executor.job_store import _JOBS


def source_job(store, run_id):
    with store.engine.connect() as connection:
        row = connection.execute(select(_JOBS.c.record).where(_JOBS.c.record["kind"].as_string() == "C", _JOBS.c.record["native"]["run_id"].as_string() == run_id)).scalar_one_or_none()
    return dict(row) if row is not None else None


def validate_dependency_goal(wait, goal, signature):
    from deerflow.runtime.goal import DEFAULT_MAX_GOAL_CONTINUATIONS, DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS

    if goal != wait["goal"] or signature != wait["conversation_signature"]:
        raise ValueError("Dependency continuation was superseded")
    if not goal or goal.get("status") != "active":
        raise ValueError("Dependency goal is no longer active")
    if int(goal.get("continuation_count", 0)) >= int(goal.get("max_continuations", DEFAULT_MAX_GOAL_CONTINUATIONS)) or int(goal.get("no_progress_count", 0)) >= int(
        goal.get("max_no_progress_continuations", DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS)
    ):
        raise ValueError("Dependency continuation budget exhausted")
    return deepcopy(goal)


async def checkpoint_receipt(app, native):
    from types import SimpleNamespace

    from app.gateway.internal_auth import get_internal_user
    from app.gateway.services import build_thread_checkpoint_state_accessor, get_run_context
    from deerflow.runtime.goal import read_thread_goal, visible_conversation_signature
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    token = set_current_user(get_internal_user(native["user_id"]))
    try:
        request = SimpleNamespace(app=app, state=SimpleNamespace())
        ctx = get_run_context(request)
        accessor, config = await build_thread_checkpoint_state_accessor(request, thread_id=native["thread_id"], fail_closed=True)
        state = await accessor.aget(config)
        return await read_thread_goal(ctx.checkpointer, native["thread_id"]), visible_conversation_signature(list((state.values or {}).get("messages") or []))
    finally:
        reset_current_user(token)


async def persist_wait(host, job):
    native = job["native"]
    goal, signature = await checkpoint_receipt(host.app, native)
    evaluation = (goal or {}).get("last_evaluation", {})
    if evaluation.get("run_id") != native["run_id"] or evaluation.get("blocker") != "external_wait":
        return False
    rows = await host.app.state.mcp_task_repo.list_by_run(native["run_id"], user_id=native["user_id"], thread_id=native["thread_id"], thread_incarnation=native["incarnation"])
    tasks = [row["id"] for row in rows]
    if not tasks:
        return False
    wait = {"goal": goal, "conversation_signature": signature, "task_ids": tasks, "source_run_id": native["run_id"], "active": True}
    await asyncio.to_thread(host.pool.store.mutate, job["id"], lambda row: row.update(dependency_wait=wait))
    return True


async def notification_receipt(host, *, owner_user_id, thread_id, task_id, source_run_id):
    from app.mcp_tasks.errors import PermanentNotificationError
    from deerflow.runtime.runs.manager import ConflictError

    job = await asyncio.to_thread(source_job, host.pool.store, source_run_id) if source_run_id else None
    if job is None:
        return None
    native = job["native"]
    if native["user_id"] != owner_user_id or native["thread_id"] != thread_id:
        raise PermanentNotificationError("Dependency owner mismatch")
    source = await host.app.state.run_store.get(source_run_id, user_id=owner_user_id)
    if not source or source.get("cancel_action") or source["status"] in {"interrupted", "error", "timeout"}:
        raise PermanentNotificationError("Dependency source was cancelled or failed")
    if source["status"] in {"pending", "running"} or not job.get("physical_stopped"):
        raise ConflictError("Dependency source finalizers have not drained")
    wait = job.get("dependency_wait")
    if not wait:
        return None
    if task_id not in wait["task_ids"]:
        raise PermanentNotificationError("Notification is not an awaited dependency")
    existing = await host.app.state.run_store.find_by_idempotency_key("mcp-dependencies:" + source_run_id, user_id=owner_user_id, thread_id=thread_id)
    if existing is not None:
        return {**wait, "continuation_run_id": existing["run_id"]}
    if wait.get("active") is False:
        raise PermanentNotificationError("Dependency continuation was superseded")
    rows = await host.app.state.mcp_task_repo.list_by_run(source_run_id, user_id=owner_user_id, thread_id=thread_id, thread_incarnation=native["incarnation"])
    members = {row["id"]: row for row in rows}
    if any(task not in members for task in wait["task_ids"]):
        raise PermanentNotificationError("Awaited dependency no longer exists")
    if any(members[task]["status"] not in {"completed", "failed", "cancelled"} for task in wait["task_ids"]):
        raise ConflictError("Awaited dependencies are not all terminal")
    if wait.get("continuation_run_id"):
        return wait
    goal, signature = await checkpoint_receipt(host.app, native)
    try:
        validate_dependency_goal(wait, goal, signature)
    except ValueError as exc:
        raise PermanentNotificationError(str(exc)) from exc
    return wait


async def prepare_notification(host, notification):
    """Extend the existing notification launcher with one canonical wait group."""
    from app.mcp_tasks.errors import PermanentNotificationError

    owner, thread_id, task_id = (notification[key] for key in ("owner_user_id", "thread_id", "task_id"))
    thread = await host.app.state.thread_store.get(thread_id, user_id=owner)
    task = await host.app.state.mcp_task_repo.get(task_id, user_id=owner, thread_id=thread_id, thread_incarnation=thread.get("incarnation") if thread else None)
    if task is None:
        raise PermanentNotificationError("Notification task no longer exists")
    try:
        wait = await notification_receipt(host, owner_user_id=owner, thread_id=thread_id, task_id=task_id, source_run_id=task.get("run_id"))
    except PermanentNotificationError:
        # Display the original native task result through its existing delivery
        # path, without granting continuation of a cancelled/replaced goal.
        source = await host.app.state.run_store.get(task.get("run_id"), user_id=owner)
        return {
            "wait": {"notification_only": True},
            "event": notification["event"],
            "metadata": {},
            "runtime": None,
            "model_name": source.get("model_name") if source else None,
            "idempotency_key": f"mcp-task:{task_id}:{notification['dispatch_version']}:{notification['dispatch_attempt']}",
        }
    if wait is None:
        return None
    if wait.get("continuation_run_id"):
        return {"existing_run_id": wait["continuation_run_id"]}
    source = await host.app.state.run_store.get(task["run_id"], user_id=owner)
    rows = await host.app.state.mcp_task_repo.list_by_run(task["run_id"], user_id=owner, thread_id=thread_id, thread_incarnation=thread["incarnation"])
    event = {"dependencies": [{key: row.get(key) for key in ("id", "status", "result_preview", "result_artifact", "error")} for row in sorted(rows, key=lambda value: value["id"]) if row["id"] in wait["task_ids"]]}
    metadata = {key: value for key, value in (source.get("metadata") or {}).items() if key.startswith("scheduled_")}
    runtime = None
    if metadata.get("scheduled_task_id"):
        runtime = {"task_id": metadata["scheduled_task_id"], "occurrence_id": metadata["scheduled_task_run_id"], "user_id": owner, "goal_objective": wait["goal"]["objective"]}
    return {"wait": wait, "event": event, "metadata": metadata, "runtime": runtime, "model_name": source.get("model_name"), "idempotency_key": "mcp-dependencies:" + task["run_id"]}


async def maintain_waits(host, *, source_run_ids=None):
    """Settle superseded scheduled waits outside checkpoint/ORM transactions."""
    from dataclasses import replace

    from deerflow.runtime.runs.schemas import RunStatus
    from deerflow.utils.time import is_lease_expired

    async def candidates():
        if source_run_ids is not None:
            for run_id in source_run_ids:
                job = await asyncio.to_thread(source_job, host.pool.store, run_id)
                if job and (job.get("dependency_wait") or {}).get("active"):
                    yield job
            return
        after_id = ""
        while batch := await asyncio.to_thread(host.pool.store.list_native_dependency_waiting, after_id=after_id):
            for job in batch:
                yield job
            after_id = batch[-1]["id"]

    valid = set()
    async for job in candidates():
        native, wait = job["native"], job["dependency_wait"]
        source = await host.app.state.run_manager.get(native["run_id"], user_id=native["user_id"], raise_on_store_error=True)
        if source is None or source.status.value in {"pending", "running"}:
            continue
        existing = await host.app.state.run_store.find_by_idempotency_key("mcp-dependencies:" + native["run_id"], user_id=native["user_id"], thread_id=native["thread_id"])
        durable_source = await host.app.state.run_store.get(native["run_id"], user_id=native["user_id"])
        occurrence_matches = True
        existing_allows_wait = existing is None
        if source.metadata.get("scheduled_task_id"):
            occurrence = await host.app.state.scheduled_task_run_repo.get_active_run(source.metadata["scheduled_task_id"])
            occurrence_matches = bool(occurrence and occurrence["id"] == source.metadata.get("scheduled_task_run_id") and occurrence["run_id"] == source.run_id)
            if existing is not None:
                if occurrence and occurrence["id"] == source.metadata.get("scheduled_task_run_id") and occurrence["run_id"] == existing["run_id"]:
                    # A native Run row is not the handoff: acknowledge only
                    # the atomic durable occurrence association.
                    await host.acknowledge_continuation(wait, existing["run_id"])
                    continue
                same_occurrence = all((existing.get("metadata") or {}).get(key) == source.metadata.get(key) for key in ("scheduled_task_id", "scheduled_task_run_id"))
                if same_occurrence and existing["status"] == "pending" and not existing.get("cancel_action"):
                    grace = host.app.state.run_manager.grace_seconds
                    if is_lease_expired(existing.get("lease_expires_at"), grace_seconds=grace):
                        # Reuse the native lease CAS. A renewed owner wins;
                        # crashed pre-transfer admissions cannot hold forever.
                        await host.app.state.run_store.claim_for_takeover(existing["run_id"], grace_seconds=grace, error="Dependency continuation admission expired", stop_reason="scheduled_task_orphan_recovered")
                        existing = await host.app.state.run_store.get(existing["run_id"], user_id=native["user_id"])
                    existing_allows_wait = bool(existing and existing["status"] == "pending" and not existing.get("cancel_action") and not is_lease_expired(existing.get("lease_expires_at"), grace_seconds=grace))
        elif existing is not None:
            await host.acknowledge_continuation(wait, existing["run_id"])
            continue
        if source.status.value == "success" and durable_source and not durable_source.get("cancel_action") and occurrence_matches and existing_allows_wait:
            goal, signature = await checkpoint_receipt(host.app, native)
            try:
                validate_dependency_goal(wait, goal, signature)
                valid.add(source.run_id)
                continue
            except ValueError:
                pass
        # Revoke obsolete continuation authority, retaining native task results.
        service = getattr(host.app.state, "scheduled_task_service", None)
        if source.metadata.get("scheduled_task_id") and service is None:
            # Bootstrap installs the native host before the scheduler service.
            # Keep the durable receipt recoverable until that owner is ready.
            continue
        if service is not None and source.metadata.get("scheduled_task_id"):
            await service.handle_run_completion(replace(source, status=RunStatus.interrupted, goal_verdict={**(source.goal_verdict or {}), "native_dependency_wait": False}, error="Dependency wait was superseded"))
            from deerflow.runtime.runs.worker import clear_recovered_scheduled_goal

            await clear_recovered_scheduled_goal(source, run_manager=host.app.state.run_manager, checkpointer=host.app.state.checkpointer)
            current_goal, _ = await checkpoint_receipt(host.app, native)
            if current_goal and current_goal.get("status") == "active" and all(current_goal.get(key) == wait["goal"].get(key) for key in ("objective", "created_at")):
                # An admitted/finalizing peer can defer the native checkpoint
                # reservation. Retain cleanup intent until it drains; a user
                # replacement instance is never cleared or retained here.
                continue
        await asyncio.to_thread(host.pool.store.mutate, job["id"], lambda row: row["dependency_wait"].update(active=False))
    return frozenset(valid)
