"""Owner-scoped HTTP decisions for live delegated calls and thread grants."""

import time

from fastapi import HTTPException, Request
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.deps import get_current_user, get_run_manager, get_thread_store
from deerflow.approvals.policy import canonical_json
from deerflow.approvals.store import ApprovalConflict
from deerflow.utils.file_io import await_drained


class ApprovalResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    responses: list[dict] = Field(min_length=1, max_length=32)


async def _scope(request, thread_id):
    owner = await get_current_user(request)
    if not owner:
        raise HTTPException(401, "Authentication required")
    thread = await get_thread_store(request).get(thread_id, user_id=owner)
    if thread is None:
        raise HTTPException(404, "Thread not found")
    incarnation = thread.get("incarnation")
    if not isinstance(incarnation, str):
        raise HTTPException(409, "Thread approval identity is unavailable")
    return (owner, thread_id, incarnation)


def _store(request):
    store = getattr(request.app.state, "approval_store", None)
    if store is None:
        raise HTTPException(503, "Approval storage is unavailable")
    return store


async def _active(request, row, owner):
    if row["expires_at"] is not None and row["expires_at"] <= time.time():
        return False
    run = await get_run_manager(request).get(row["run_id"], user_id=owner)
    return run is not None and run.thread_id == row["thread_id"] and run.status in ("running", "pending") and not run.ownership_lost and not run.abort_event.is_set()


async def list_approvals(thread_id, request):
    scope = await _scope(request, thread_id)
    rows = await _store(request).list(scope=scope, status="pending")
    requests = [row["payload"] for row in rows if row["kind"] == "live" and await _active(request, row, scope[0])]
    grants = await _store(request).list(scope=scope, grants=True)
    return {"requests": requests, "grants": [{"request_id": row["request_id"], "operation": row["payload"]} for row in grants]}


async def answer_approval(thread_id, run_id, request_id, body, request: Request):
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT

    if getattr(request.state, "auth_source", None) in (AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT):
        raise HTTPException(403, "Tool approval requires an interactive user session")
    scope = await _scope(request, thread_id)
    store = _store(request)
    row = await store.get(request_id, scope=scope)
    if row is None or row["run_id"] != run_id or row["kind"] != "live":
        raise HTTPException(404, "Approval not found")
    if not await _active(request, row, scope[0]):
        raise HTTPException(409, "The originating run stopped or the approval expired")
    actions = row["payload"]["actions"]
    if len(body.responses) != len(actions):
        raise HTTPException(422, "An answer is required for each operation")
    by_id = {action["request_id"]: action for action in actions}
    seen = set()
    for response in body.responses:
        response_id = response.get("request_id")
        if not isinstance(response_id, str):
            raise HTTPException(422, "Invalid approval request identity")
        if not isinstance(response.get("value", ""), str) or len(response.get("value", "")) > 2000:
            raise HTTPException(422, "Approval reason must be text of at most 2000 characters")
        action = by_id.get(response_id)
        if action is None or action["request_id"] in seen or response.get("tool_call_id") != action["tool_call_id"]:
            raise HTTPException(422, "Stale or mismatched approval response")
        seen.add(action["request_id"])
        decision = response.get("option_id")
        if decision not in row["payload"]["allowed_decisions"]:
            raise HTTPException(422, "Unsupported approval decision")
        if decision == "edit":
            args, schema = response.get("args"), action.get("args_schema")
            try:
                if not isinstance(args, dict) or len(canonical_json(args).encode()) > row["payload"].get("max_payload_bytes", 512 * 1024):
                    raise ValueError("Invalid arguments")
                Draft202012Validator(schema).validate(args)
                if isinstance(schema.get("properties"), dict) and set(args) - set(schema["properties"]):
                    raise ValueError("Unknown or injected arguments")
            except Exception as exc:
                raise HTTPException(422, "Edited arguments do not match the tool schema") from exc
    try:
        await await_drained(store.decide(request_id, {"responses": body.responses}, scope=scope, fingerprint=row["fingerprint"]))
    except ApprovalConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"accepted": True, "request_id": request_id}


async def revoke_approval_grants(thread_id, request):
    scope = await _scope(request, thread_id)
    await await_drained(_store(request).revoke(scope=scope))
    return {"revoked": True}
