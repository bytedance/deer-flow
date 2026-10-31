"""HTTP admission and ordinary AgentRuns dispatch for in-flight user inputs."""

import copy
import json
import logging
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.gateway.deps import get_current_user, get_run_context, get_run_manager
from deerflow.runtime.runs.inputs import InputConflict, RunInputs

logger = logging.getLogger(__name__)


class RunInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=96)
    text: str = Field(min_length=1, max_length=16 * 1024)
    mode: Literal["queue", "steer"]
    context: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_context(self):
        if len(json.dumps(self.context, ensure_ascii=True, allow_nan=False).encode()) > 32 * 1024:
            raise ValueError("Input context exceeds 32 KiB")
        return self


def _store(request):
    store = get_run_manager(request).input_store
    if store is None:
        raise HTTPException(503, "Run inputs are unavailable")
    return store


async def submit_run_input(thread_id: str, run_id: str, body: RunInputRequest, request: Request):
    manager = get_run_manager(request)
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    run = await manager.get(run_id, user_id=user_id)
    if run is None or run.thread_id != thread_id:
        raise HTTPException(404, "Run not found")
    if get_run_context(request).agent_runs is None:
        raise HTTPException(503, "Run inputs require an authenticated session")
    row = await _store(request).get(run_id, user_id=user_id)
    if row is None or row.get("run_inputs") is None:
        raise HTTPException(409, "This Run has not enabled interactive inputs")
    try:
        from app.gateway.services import _CONTEXT_CONFIGURABLE_KEYS
        from deerflow.runtime.run_origin import admit_origin

        context = {key: value for key, value in body.context.items() if key in _CONTEXT_CONFIGURABLE_KEYS and key not in ("agent_name", "is_bootstrap")}
        if isinstance(body.context.get("locale"), str):
            context["locale"] = body.context["locale"]
        source = "extension" if admit_origin(getattr(request.state, "run_origin", None)) is not None else "user"
        item = await RunInputs(_store(request), run_id, user_id).submit(body.request_id, body.text, body.mode, context=context, source=source)
    except InputConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**item, "target_run_id": run_id}


async def list_thread_inputs(thread_id: str, request: Request):
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    rows = await _store(request).list_input_runs(thread_id, user_id=user_id)
    items = []
    for row in reversed(rows):
        for entry in (row.get("run_inputs") or {}).get("items", []):
            status = entry["status"]
            if status in ("pending", "applying") and (row["status"] not in ("pending", "running", "success") or row.get("stop_reason")):
                status = "not_applied"
            items.append({key: value for key, value in {**entry, "status": status, "target_run_id": row["run_id"]}.items() if key != "context"})
    return {"items": items[-32:], "active_run_id": await _store(request).active_input_run(thread_id, user_id=user_id)}


async def dispatch_queued_inputs(inputs: RunInputs, *, agent_runs, thread_id: str):
    """Use normal admission/authorization and its stable idempotency key.

    This runs after the previous worker has fully finalized. No second main
    Agent, task queue service or recovery scheduler is introduced.
    """
    row = await inputs.store.get(inputs.run_id, user_id=inputs.user_id)
    if row is None or row["status"] != "success" or row.get("stop_reason"):
        return
    state = await inputs.read()
    for entry in state["items"]:
        if entry["mode"] != "queue" or entry["status"] != "pending":
            continue
        try:
            run = await agent_runs.dispatch_input(thread_id=thread_id, run_id=inputs.run_id, input_id=entry["id"])
            while run.status in ("pending", "running"):
                # AgentRuns.wait retains its capped backoff and revocation
                # checks; a long task exceeding a wait window is still live.
                try:
                    run = await agent_runs.wait(thread_id=thread_id, run_id=run.run_id, timeout=60)
                except TimeoutError:
                    continue
            if run.status != "success" or run.stop_reason:
                await inputs.pause()
                return
        except Exception:
            # Unknown admission outcomes retain the original key and input;
            # retrying can reconcile the same Run instead of running it twice.
            logger.warning("Queued input remains undelivered for Run %s", inputs.run_id, exc_info=True)
            return


async def dispatch_one_input(thread_id, run_id, input_id, request, *, retry=False):
    from deerflow_extension_api.agent_runs import AgentRun

    from app.gateway.routers.thread_runs import create_run, get_run
    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import resolve_thread_assistant_id

    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    source = await _store(request).get(run_id, user_id=user_id)
    if source is None or source["thread_id"] != thread_id:
        raise HTTPException(404, "Run not found")
    inputs = RunInputs(_store(request), run_id, user_id)
    entry = await inputs.claim(input_id, retry=retry)
    if entry.get("run_id"):
        run = await get_run(thread_id, entry["run_id"], request)
        return AgentRun(thread_id, run.run_id, run.status, run.assistant_id, run.stop_reason)
    message_id = str(uuid5(NAMESPACE_URL, f"deerflow-dispatch:{inputs.run_id}:{input_id}"))
    context = entry.get("context", {})
    source_config = (source.get("kwargs") or {}).get("config") or {}
    limit = source_config.get("recursion_limit")
    config = {"recursion_limit": limit} if type(limit) is int else None
    # Carry only the parent's admitted retrieval scope, never its files,
    # credentials or framework markers. Normal admission rechecks access.
    from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_KEY

    scope = None
    for message in ((source.get("kwargs") or {}).get("input") or {}).get("messages", []):
        if message.get("type", message.get("role")) in ("human", "user"):
            scope = message.get("additional_kwargs", {}).get(KNOWLEDGE_SCOPE_KEY)
    message = {"role": "user", "content": entry["text"], "id": message_id}
    if scope is not None:
        message["additional_kwargs"] = {KNOWLEDGE_SCOPE_KEY: copy.deepcopy(scope)}
    if entry.get("source", "user") == "user":
        # This fact comes from the stored, authenticated input, not from text
        # or an arbitrary extension-supplied metadata flag.
        request.state.run_origin = None
    body = RunCreateRequest(assistant_id=await resolve_thread_assistant_id(request, thread_id, fail_closed=True), input={"messages": [message]}, context=context, config=config, on_disconnect="continue")
    run = await create_run(thread_id, body, request, idempotency_key=f"run-input:{run_id}:{input_id}")
    await inputs.dispatched(entry["id"], run.run_id)
    return AgentRun(thread_id, run.run_id, run.status, run.assistant_id, run.stop_reason)


async def change_run_input(thread_id: str, run_id: str, input_id: str, request: Request, *, retry=False):
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    run = await get_run_manager(request).get(run_id, user_id=user_id)
    if run is None or run.thread_id != thread_id:
        raise HTTPException(404, "Run not found")
    inputs = RunInputs(_store(request), run_id, user_id)
    try:
        if retry:
            handle = get_run_context(request).agent_runs
            if handle is None:
                raise HTTPException(503, "Run inputs require an authenticated session")
            from deerflow.runtime.run_origin import admit_origin

            if admit_origin(getattr(request.state, "run_origin", None)) is not None:
                raise HTTPException(403, "An unapplied input requires an explicit user retry")
            dispatched = await dispatch_one_input(thread_id, run_id, input_id, request, retry=True)
            return {"run_id": dispatched.run_id}
        await inputs.cancel(input_id)
        return {"removed": True}
    except InputConflict as exc:
        raise HTTPException(409, str(exc)) from exc
