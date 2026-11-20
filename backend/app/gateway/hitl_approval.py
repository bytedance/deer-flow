"""Server-side validation for HITL tool-approval resume and admission.

All checks live here (called from ``services.start_run``) so every entry point
— HTTP routes, extension host, internal launchers — shares one choke point.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from app.gateway.checkpoint_lineage import hitl_approval_payloads
from deerflow.approvals.protocol import combine_approval_payloads
from deerflow.runtime.checkpoint_history import recent_checkpoint_history

logger = logging.getLogger(__name__)


class ApprovalRequestIds(dict):
    """Identity map plus the validated LangGraph interrupt-ID resume map."""

    resume_map: dict | None = None


if TYPE_CHECKING:
    from deerflow.runtime.runs.manager import ApprovalAnswerHandle


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _responses_of(command: Any) -> list[Any] | None:
    if not isinstance(command, Mapping):
        return None
    resume = command.get("resume")
    if not isinstance(resume, Mapping):
        return None
    responses = resume.get("responses")
    return responses if isinstance(responses, list) else None


def _all_reject(responses: list[Any] | None) -> bool:
    return bool(responses) and all(isinstance(r, Mapping) and r.get("option_id") == "reject" for r in responses)


async def has_any_pending_interrupt(accessor: Any, read_config: dict[str, Any]) -> bool:
    """Whether a recent checkpoint has an unconsumed interrupt write.
    Used for generic (non-hitl) resume admission where snapshot.next may be
    empty after a head-moving write. The newest resume/interrupt marker wins,
    so an answered pause cannot be resurrected by its older interrupt write.
    """
    async for checkpoint in recent_checkpoint_history(accessor.checkpointer, read_config):
        writes = list(getattr(checkpoint, "pending_writes", ()) or ())
        if any(len(write) >= 2 and write[1] == "__resume__" for write in writes):
            return False
        if any(len(write) >= 2 and write[1] == "__interrupt__" for write in writes):
            return True
    return False


async def _pending_interrupts_from_checkpoint_history(checkpointer: Any, read_config: dict[str, Any]) -> dict[str, list[Any]]:
    """Read pending interrupts without materializing a graph state snapshot."""
    async for checkpoint in recent_checkpoint_history(checkpointer, read_config):
        writes = list(getattr(checkpoint, "pending_writes", ()) or ())
        if any(len(write) >= 2 and write[1] == "__resume__" for write in writes):
            return {}
        interrupt_writes = [write for write in writes if len(write) >= 3 and write[1] == "__interrupt__"]
        if not interrupt_writes:
            continue
        grouped: dict[str, list[Any]] = {}
        for write in interrupt_writes:
            interrupts = write[2] if isinstance(write[2], (list, tuple)) else (write[2],)
            grouped.setdefault(str(write[0]), []).extend(interrupts)
        return grouped
    return {}


async def has_waiting_for_input_run(request: Any, thread_id: str) -> bool:
    """Whether any run in the thread is paused for input (any interrupt kind)."""
    from app.gateway.deps import get_run_store

    try:
        run_store = get_run_store(request)
    except (HTTPException, AttributeError) as exc:
        if isinstance(exc, AttributeError) or exc.status_code == 503:
            return False
        raise
    runs = await run_store.list_by_thread(thread_id, limit=5)
    return any(run.get("status") == "waiting_for_input" for run in runs)


async def mark_approval_answered(request: Any, thread_id: str, *, expected_request_ids: dict[str, str] | None = None) -> ApprovalAnswerHandle | None:
    """Mark the validated paused run as answered and return its recovery handle."""
    from app.gateway.deps import get_run_manager, get_run_store

    try:
        run_manager = get_run_manager(request)
    except (HTTPException, AttributeError) as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 503:
            raise
        # Lightweight compositions may provide only a store. Keep their
        # persistence on RunManager's retry and in-memory mutation path too.
        from deerflow.runtime import RunManager

        try:
            run_manager = RunManager(store=get_run_store(request))
        except (HTTPException, AttributeError) as store_exc:
            if isinstance(store_exc, AttributeError) or store_exc.status_code == 503:
                return None
            raise
    return await run_manager.mark_approval_answered(thread_id, expected_request_ids=expected_request_ids)


async def _interrupt_from_checkpoint_history(accessor: Any, read_config: dict[str, Any], payload: dict[str, Any]) -> tuple[str, Any] | None:
    """Recover the original LangGraph task identity after the head has moved."""
    if accessor is None:
        return None
    if getattr(accessor, "checkpointer", None) is None:
        return None
    async for checkpoint in recent_checkpoint_history(accessor.checkpointer, read_config):
        writes = list(getattr(checkpoint, "pending_writes", ()) or ())
        if any(len(write) >= 2 and write[1] == "__resume__" for write in writes):
            return None
        for write in writes:
            if len(write) < 3 or write[1] != "__interrupt__":
                continue
            interrupts = write[2] if isinstance(write[2], (list, tuple)) else (write[2],)
            for pending_interrupt in interrupts:
                if getattr(pending_interrupt, "value", None) == payload:
                    return str(write[0]), pending_interrupt
    return None


async def find_pending_interrupts(
    request: Any,
    thread_id: str,
    *,
    accessor: Any = None,
    read_config: dict[str, Any] | None = None,
    snapshot: Any = None,
) -> dict[str, list[Any]]:
    """Find pending interrupts from an existing snapshot or raw checkpoints.

    The live snapshot catches a pause before the worker has finalized the run;
    raw pending writes cover head-moving writes and restricted mutation graphs;
    the durable run record remains the final fallback.
    """
    from langgraph.types import Interrupt

    from app.gateway.checkpoint_lineage import task_interrupts_by_id
    from app.gateway.deps import get_checkpointer, get_run_store

    if snapshot is None and accessor is not None and read_config is not None:
        snapshot = await accessor.aget(read_config)
    if snapshot is not None:
        grouped = task_interrupts_by_id(snapshot)
        if grouped:
            return grouped

    try:
        run_store = get_run_store(request)
    except (HTTPException, AttributeError) as exc:
        if not isinstance(exc, AttributeError) and exc.status_code != 503:
            raise
        runs = []
    else:
        runs = await run_store.list_by_thread(thread_id, limit=10)
    # A current loop snapshot is authoritative for ordinary polling. Update
    # checkpoints can have moved the head past an unconsumed interrupt, and
    # checkpoint-only compositions have no snapshot: retain recovery for both.
    if (
        snapshot is not None
        and (getattr(snapshot, "metadata", None) or {}).get("source") == "loop"
        and (getattr(snapshot, "config", None) or {}).get("configurable", {}).get("checkpoint_id")
        and not (read_config or {}).get("configurable", {}).get("checkpoint_id")
        and not any(run.get("status") == "waiting_for_input" for run in runs)
    ):
        return {}

    checkpointer = getattr(accessor, "checkpointer", None)
    if checkpointer is None:
        try:
            checkpointer = get_checkpointer(request)
        except (HTTPException, AttributeError) as exc:
            if not isinstance(exc, AttributeError) and exc.status_code != 503:
                raise
    if checkpointer is not None:
        grouped = await _pending_interrupts_from_checkpoint_history(
            checkpointer,
            read_config or {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        )
        if grouped:
            return grouped

    for run in runs:
        if run.get("status") != "waiting_for_input":
            continue
        payload = (run.get("metadata") or {}).get("hitl_approval")
        if payload:
            recovered = await _interrupt_from_checkpoint_history(accessor, read_config, payload) if read_config is not None else None
            if recovered is not None:
                task_id, pending_interrupt = recovered
                return {task_id: [pending_interrupt]}
            task_id = run.get("run_id") or "approval"
            return {task_id: [Interrupt(value=payload, id=payload.get("request_id", task_id))]}
    return {}


def _approval_request_ids(payload: dict[str, Any]) -> dict[str, str]:
    """Extract and validate the action identity binding for one HITL pause."""
    expected_ids = payload.get("pending_tool_call_ids")
    if not isinstance(expected_ids, list) or any(not isinstance(call_id, str) for call_id in expected_ids) or len(set(expected_ids)) != len(expected_ids):
        raise _error(422, "invalid_approval_response", "pending approval has invalid tool_call_ids")
    expected_set = set(expected_ids)
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise _error(422, "invalid_approval_response", "pending approval has invalid actions")
    expected_request_ids: dict[str, str] = {}
    for action in actions:
        if not isinstance(action, Mapping):
            raise _error(422, "invalid_approval_response", "pending approval has invalid actions")
        call_id = action.get("tool_call_id")
        request_id = action.get("request_id")
        if not isinstance(call_id, str) or call_id not in expected_set or call_id in expected_request_ids or not isinstance(request_id, str) or not request_id:
            raise _error(422, "invalid_approval_response", "pending approval has invalid actions")
        expected_request_ids[call_id] = request_id
    if set(expected_request_ids) != expected_set:
        raise _error(422, "invalid_approval_response", "pending approval has invalid actions")
    return expected_request_ids


async def current_approval_request_ids(
    request: Any,
    thread_id: str,
    *,
    accessor: Any,
    read_config: dict[str, Any],
) -> dict[str, str] | None:
    """Read the current live pause's identity for checkpoint-only recovery."""
    pending = await find_pending_interrupts(request, thread_id, accessor=accessor, read_config=read_config)
    payloads = hitl_approval_payloads(pending)
    return _approval_request_ids(combine_approval_payloads(payloads)) if payloads else None


async def validate_resume_request(*, request: Any, thread_id: str, accessor: Any, read_config: dict[str, Any], enabled: bool, body: Any) -> dict[str, str] | None:
    """Validate a command.resume against the current pause, or raise 409/422.

    Static breakpoints (next non-empty, no approval payload) pass through
    unchanged. All-reject remains the escape hatch for the validated pause when
    the feature is disabled or the payload was lost; attachment later verifies
    that checkpoint-only recovery still targets that same pause.
    """
    snapshot = await accessor.aget(read_config)
    responses = _responses_of(getattr(body, "command", None))
    all_reject = _all_reject(responses)
    pending = await find_pending_interrupts(request, thread_id, accessor=accessor, read_config=read_config, snapshot=snapshot)
    payloads = hitl_approval_payloads(pending)
    has_waiting_run = await has_waiting_for_input_run(request, thread_id)
    has_pending_interrupt = await has_any_pending_interrupt(accessor, read_config)
    head_checkpoint_id = (getattr(snapshot, "config", None) or {}).get("configurable", {}).get("checkpoint_id")
    if not pending and not has_waiting_run and not (getattr(snapshot, "next", None) or ()) and not has_pending_interrupt:
        raise _error(409, "no_pending_approval", "No resumable pause exists for this thread")

    if not payloads:
        return None

    if responses is None:
        raise _error(422, "invalid_approval_response", "resume must carry a 'responses' list for hitl_approval")
    expected_request_ids = ApprovalRequestIds(_approval_request_ids(combine_approval_payloads(payloads)))
    action_by_request = {action["request_id"]: action for payload in payloads for action in payload["actions"]}
    expected_ids = list(expected_request_ids)
    expected_set = set(expected_ids)
    if len(responses) != len(expected_ids):
        raise _error(422, "invalid_approval_response", f"expected {len(expected_ids)} responses, got {len(responses)}")
    seen_ids: set[str] = set()
    for response in responses:
        if not isinstance(response, Mapping):
            raise _error(422, "invalid_approval_response", "each response must be an object")
        response_id = response.get("tool_call_id")
        if not isinstance(response_id, str) or response_id not in expected_set:
            raise _error(422, "invalid_approval_response", "unknown tool_call_id")
        if response.get("request_id") != expected_request_ids[response_id]:
            raise _error(422, "invalid_approval_response", "stale or mismatched request_id")
        if response_id in seen_ids:
            raise _error(422, "invalid_approval_response", "duplicate tool_call_id")
        seen_ids.add(response_id)
        action = action_by_request[response["request_id"]]
        supported = ("approve", "reject", "edit", "approve_thread") if all(payload.get("version") == 2 for payload in payloads) else ("approve", "reject")
        if response.get("option_id") not in supported:
            raise _error(422, "invalid_approval_response", f"unsupported option_id; expected one of {', '.join(repr(option) for option in supported)}")
        if response.get("option_id") == "approve_thread" and not action.get("grant_allowed"):
            raise _error(422, "invalid_approval_response", "This operation does not permit a thread grant")
        if response.get("option_id") == "edit":
            from jsonschema import Draft202012Validator

            from deerflow.approvals.policy import canonical_json

            args, schema = response.get("args"), action.get("args_schema")
            try:
                limit = min(payload.get("max_payload_bytes", 512 * 1024) for payload in payloads)
                if not isinstance(args, dict) or not isinstance(schema, dict) or len(canonical_json(args).encode()) > limit:
                    raise ValueError("Invalid arguments")
                Draft202012Validator(schema).validate(args)
                if isinstance(schema.get("properties"), dict) and set(args) - set(schema["properties"]):
                    raise ValueError("Unknown or injected arguments")
            except Exception as exc:
                raise _error(422, "invalid_approval_arguments", "Edited arguments do not match the tool schema") from exc

    if all(payload.get("version") == 2 for payload in payloads):
        expected_request_ids.resume_map = {
            item.id: {"responses": [response for response in responses if response["request_id"] in {action["request_id"] for action in item.value["actions"]}]}
            for interrupts in pending.values()
            for item in interrupts
            if isinstance(getattr(item, "value", None), dict) and item.value.get("kind") == "hitl_approval"
        }

    if all_reject:
        return expected_request_ids

    if not enabled:
        raise _error(409, "hitl_approval_disabled", "hitl_approval is currently disabled; resume with all-reject to clear the pause")

    requested_checkpoint_id = getattr(body, "checkpoint_id", None)
    body_checkpoint = getattr(body, "checkpoint", None)
    if requested_checkpoint_id is None and isinstance(body_checkpoint, Mapping):
        requested_checkpoint_id = body_checkpoint.get("checkpoint_id")
    if requested_checkpoint_id and head_checkpoint_id and str(requested_checkpoint_id) != str(head_checkpoint_id):
        raise _error(422, "checkpoint_not_head", "A resume must target the current head checkpoint, never an older pause checkpoint")
    return expected_request_ids


async def reject_new_run_when_approval_pending(
    request: Any,
    thread_id: str,
    *,
    accessor: Any = None,
    read_config: dict[str, Any] | None = None,
) -> None:
    """Reject a brand-new (non-resume) run while an approval is pending.

    Without this guard a fresh input silently discards the pending approval
    (measured behavior of LangGraph). Internal launchers catch this specific
    error code to implement skip-and-retry semantics.
    """
    pending = await find_pending_interrupts(request, thread_id, accessor=accessor, read_config=read_config)
    if hitl_approval_payloads(pending):
        raise _error(409, "approval_pending", "Thread has a pending tool approval; resume or reject it before starting a new run")
