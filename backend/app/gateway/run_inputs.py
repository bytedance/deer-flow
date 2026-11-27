"""HTTP admission and ordinary AgentRuns dispatch for in-flight user inputs."""

import asyncio
import copy
import json
import logging
from dataclasses import dataclass
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.datastructures import UploadFile

from app.gateway.authz import require_permission
from app.gateway.deps import get_agent_runs, get_config, get_current_user, get_run_manager
from deerflow.config.app_config import AppConfig
from deerflow.runtime.runs.inputs import InputCancelled, InputConflict, RunInputs
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueuedAttachments:
    source: RunInputs
    input_id: str
    attempt: int
    stage: dict


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


class QueuedFileInputRequest(RunInputRequest):
    text: str = Field(max_length=16 * 1024)
    mode: Literal["queue"]


def _parse_input(model: type[RunInputRequest], data: str | bytearray) -> RunInputRequest:
    try:
        return model.model_validate_json(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_input=False, include_context=False)) from exc


async def submit_http_run_input(thread_id: str, run_id: str, request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "multipart/form-data":
        return await _submit_file_run_input(thread_id, run_id, request)
    # Multipart needs a larger ingress limit. Keep the former 1 MiB limit for
    # plain JSON even when both payload types share the same proxy location.
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 1024 * 1024:
            raise HTTPException(413, "Run input JSON exceeds 1 MiB")
        data.extend(chunk)
    return await submit_run_input(thread_id, run_id, _parse_input(RunInputRequest, data), request)


@require_permission("threads", "write")
async def _submit_file_run_input(thread_id: str, run_id: str, request: Request):
    from app.gateway.routers.uploads import _get_upload_limits

    config = await asyncio.to_thread(get_config)
    limits = _get_upload_limits(config)
    async with request.form(max_files=limits.max_files, max_fields=1, max_part_size=256 * 1024) as form:
        data = form.get("input")
        files = form.getlist("files")
        if not isinstance(data, str) or not files or len(form.multi_items()) != 1 + len(files) or not all(isinstance(file, UploadFile) for file in files):
            raise HTTPException(422, "Expected a queue input and one or more files")
        body = _parse_input(QueuedFileInputRequest, data)
        return await await_drained(submit_run_input(thread_id, run_id, body, request, files=files, upload_config=config))


def _store(request):
    store = get_run_manager(request).input_store
    if store is None:
        raise HTTPException(503, "Run inputs are unavailable")
    return store


async def submit_run_input(
    thread_id: str,
    run_id: str,
    body: RunInputRequest,
    request: Request,
    *,
    files: list[UploadFile] | None = None,
    upload_config: AppConfig | None = None,
):
    manager = get_run_manager(request)
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    run = await manager.get(run_id, user_id=user_id)
    if run is None or run.thread_id != thread_id:
        raise HTTPException(404, "Run not found")
    if get_agent_runs(request) is None:
        raise HTTPException(503, "Run inputs require an authenticated session")
    from deerflow_extension_api.agent_runs import AgentRunError

    from app.gateway.coordination_workers import managed_task, worker_context, worker_error
    from deerflow.persistence.coordination.sql import TaskConflict, TaskNotFound

    if task_id := await managed_task(request, thread_id):
        if files:
            raise HTTPException(409, "Managed worker updates accept text only")
        service, owner, _runs = worker_context(request)
        if body.mode != "queue":
            raise HTTPException(409, "Use queue mode to update a managed worker")
        try:
            item = await service.submit_input(owner, task_id, request_id=f"run-input:{run_id}:{body.request_id}", content=body.text)
            return _worker_input_receipt(item, run_id, body.request_id)
        except (TaskConflict, TaskNotFound, AgentRunError) as exc:
            raise worker_error(exc) from exc
    store = _store(request)
    row = await store.get(run_id, user_id=user_id)
    if row is None or row.get("run_inputs") is None:
        raise HTTPException(409, "This Run has not enabled interactive inputs")
    from app.gateway.run_input_files import discard_input_files, stage_input_files

    stage = None
    if files:
        if body.mode != "queue" or upload_config is None:
            raise HTTPException(422, "Attachments require queue mode")
        if row["run_inputs"].get("queue_attachments") is not True:
            raise HTTPException(409, "This Run cannot dispatch queued attachments")
        stage_id, metadata = await stage_input_files(thread_id, user_id, files, upload_config)
        stage = {"id": stage_id, "files": metadata}
    try:
        from app.gateway.services import _CONTEXT_CONFIGURABLE_KEYS
        from deerflow.runtime.run_origin import admit_origin

        context = {key: value for key, value in body.context.items() if key in _CONTEXT_CONFIGURABLE_KEYS and key not in ("agent_name", "is_bootstrap")}
        if isinstance(body.context.get("locale"), str):
            context["locale"] = body.context["locale"]
        source = "extension" if admit_origin(getattr(request.state, "run_origin", None)) is not None else "user"
        item = await RunInputs(store, run_id, user_id).submit(body.request_id, body.text, body.mode, context=context, source=source, attachment_stage=stage)
    except InputConflict as exc:
        if stage is not None:
            await discard_input_files(thread_id, user_id, stage["id"])
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        if stage is not None:
            # A failed response from the store can follow a successful commit.
            # Keep the files unless we can confirm that no item owns them.
            try:
                current = await RunInputs(store, run_id, user_id).read()
                if not any(item.get("attachment_stage", {}).get("id") == stage["id"] for item in current["items"]):
                    await discard_input_files(thread_id, user_id, stage["id"])
            except Exception:
                logger.warning("Could not reconcile queued attachments after a RunStore failure")
        raise
    if stage is not None and item.get("attachment_stage", {}).get("id") != stage["id"]:
        await discard_input_files(thread_id, user_id, stage["id"])
    return _input_receipt(item, run_id)


def _input_receipt(item: dict, run_id: str) -> dict:
    receipt = {key: value for key, value in item.items() if key not in ("attachment_stage", "attachment_attempt")}
    stage = item.get("attachment_stage")
    if stage is not None and item["status"] != "cancelled":
        receipt["files"] = [{"filename": file["filename"], "size": file["size"]} for file in stage["files"]]
    return {**receipt, "target_run_id": run_id}


async def _recover_unpublished_input(inputs: RunInputs, thread_id: str, entry: dict) -> dict:
    stage = entry.get("attachment_stage")
    child_id = entry.get("run_id")
    attempt = entry.get("attachment_attempt", 0)
    if not stage or not child_id or entry["status"] not in ("dispatching", "applied") or stage.get("published") is True or stage.get("publishing_attempt") == attempt:
        return entry
    child = await inputs.store.get(child_id, user_id=inputs.user_id)
    # Older admission records never fenced publication. Missing proof is
    # ambiguous for those runs, as it is when the worker crossed the fence.
    if child is None or child["thread_id"] != thread_id or child["status"] not in (RunStatus.error, RunStatus.interrupted, RunStatus.timeout) or (child.get("kwargs") or {}).get("queued_input_checks_publication") is not True:
        return entry
    return await inputs.publication_failed(entry["id"], child_id, attempt=attempt, require_unstarted=True)


def _worker_input_receipt(item, run_id, request_id, consuming_run=None, cancelled=False):
    return {
        "id": request_id,
        "target_run_id": run_id,
        "message_id": str(uuid5(NAMESPACE_URL, f"deerflow-input:{run_id}:{request_id}")),
        "mode": "queue",
        "text": item["content"],
        "created_at": item["created_at"],
        "status": "applied" if consuming_run else "cancelled" if cancelled else "pending",
        **({"run_id": consuming_run} if consuming_run else {}),
    }


async def list_thread_inputs(thread_id: str, request: Request):
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    from app.gateway.coordination_workers import managed_task
    from deerflow.persistence.coordination.sql import TaskNotFound

    if task_id := await managed_task(request, thread_id):
        try:
            receipts, active, cancelled = await request.app.state.coordination_workers.repo.input_receipts(user_id, task_id)
        except TaskNotFound as exc:
            raise HTTPException(404, "Task not found") from exc
        items = []
        for item, consuming_run in receipts:
            _, run, key = item["request_id"].split(":", 2)
            items.append(_worker_input_receipt(item, run, key, consuming_run, cancelled))
        return {"items": items, "active_run_id": active}
    store = _store(request)
    rows = await store.list_input_runs(thread_id, user_id=user_id)
    items = []
    for row in reversed(rows):
        inputs = RunInputs(store, row["run_id"], user_id)
        for entry in (row.get("run_inputs") or {}).get("items", []):
            entry = await _recover_unpublished_input(inputs, thread_id, entry)
            status = entry["status"]
            if status in ("pending", "applying") and (row["status"] not in ("pending", "running", "success") or row.get("stop_reason")):
                status = "not_applied"
            receipt = _input_receipt({**entry, "status": status}, row["run_id"])
            receipt.pop("context", None)
            items.append(receipt)
    # Rank unresolved inputs (pending / not_applied / ...) ahead of terminal
    # applied/cancelled receipts, prefer the newest entry within each group,
    # cap at 32 records, then restore chronological order. A plain items[-32:]
    # slice lets two full batches of receipts hide an older retryable input
    # (issue #7972). If more than 32 inputs are unresolved, this deliberately
    # returns 32 unresolved rows and no receipts for submission reconciliation;
    # that trade-off follows the priority the issue asks for.
    keep = sorted(range(len(items)), key=lambda i: (items[i]["status"] in ("applied", "cancelled"), -i))[:32]
    return {"items": [items[i] for i in sorted(keep)], "active_run_id": await store.active_input_run(thread_id, user_id=user_id)}


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
            try:
                run = await agent_runs.dispatch_input(thread_id=thread_id, run_id=inputs.run_id, input_id=entry["id"])
            except InputCancelled:
                # Cancellation can win after the snapshot, even during
                # admission. The atomic claim proves no Run was started.
                logger.info("Skipping cancelled queued input %s for Run %s", entry["id"], inputs.run_id)
                continue
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
    store = _store(request)
    source = await store.get(run_id, user_id=user_id)
    if source is None or source["thread_id"] != thread_id:
        raise HTTPException(404, "Run not found")
    inputs = RunInputs(store, run_id, user_id)
    if retry:
        original = next((entry for entry in (source.get("run_inputs") or {}).get("items", []) if entry["id"] == input_id), None)
        if original is not None:
            await _recover_unpublished_input(inputs, thread_id, original)
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
    attempt = entry.get("attachment_attempt", 0)
    if stage := entry.get("attachment_stage"):
        request.state.queued_input_attachments = QueuedAttachments(inputs, input_id, attempt, stage)
    if entry.get("source", "user") == "user":
        # This fact comes from the stored, authenticated input, not from text
        # or an arbitrary extension-supplied metadata flag.
        request.state.run_origin = None
    body = RunCreateRequest(assistant_id=await resolve_thread_assistant_id(request, thread_id, fail_closed=True), input={"messages": [message]}, context=context, config=config, on_disconnect="continue")
    # A new key is safe only when the earlier run failed before entering the graph.
    key = f"run-input-retry:{run_id}:{attempt}:{input_id}" if attempt else f"run-input:{run_id}:{input_id}"
    run = await create_run(thread_id, body, request, idempotency_key=key)
    await inputs.dispatched(input_id, run.run_id, attempt=attempt)
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
            handle = get_agent_runs(request)
            if handle is None:
                raise HTTPException(503, "Run inputs require an authenticated session")
            from deerflow.runtime.run_origin import admit_origin

            if admit_origin(getattr(request.state, "run_origin", None)) is not None:
                raise HTTPException(403, "An unapplied input requires an explicit user retry")
            dispatched = await dispatch_one_input(thread_id, run_id, input_id, request, retry=True)
            return {"run_id": dispatched.run_id}
        original = next((entry for entry in (await inputs.read())["items"] if entry["id"] == input_id), None)
        if original is not None:
            await _recover_unpublished_input(inputs, thread_id, original)
        await await_drained(_cancel_input(inputs, thread_id, user_id, input_id))
        return {"removed": True}
    except InputConflict as exc:
        raise HTTPException(409, str(exc)) from exc


async def _cancel_input(inputs: RunInputs, thread_id: str, user_id: str, input_id: str):
    from app.gateway.run_input_files import discard_input_files

    item = await inputs.cancel(input_id)
    if stage := item.get("attachment_stage"):
        await discard_input_files(thread_id, user_id, stage["id"])
