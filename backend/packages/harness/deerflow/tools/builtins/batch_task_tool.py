"""Explicit durable batch mode for many independent native-subagent items."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import asdict, replace
from typing import Annotated, Any, cast

from langchain.tools import InjectedToolCallId, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from deerflow.authz.principal import normalize_authz_attributes
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.subagents.batch_runtime import (
    BatchSubmitRequest,
    SubagentBatchSubmitter,
    get_subagent_batch_submitter,
)
from deerflow.subagents.registry import get_available_subagent_names, get_subagent_config
from deerflow.tools.types import Runtime


class BatchTaskItem(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=100_000)


_NO_EXPLICIT_BATCH_SUBMITTER = object()
_explicit_batch_submitter: ContextVar[SubagentBatchSubmitter | None | object] = ContextVar(
    "deerflow_explicit_subagent_batch_submitter",
    default=_NO_EXPLICIT_BATCH_SUBMITTER,
)
_explicit_batch_app_config: ContextVar[Any | None] = ContextVar(
    "deerflow_explicit_subagent_batch_app_config",
    default=None,
)


def _batch_submitter() -> SubagentBatchSubmitter | None:
    explicit = _explicit_batch_submitter.get()
    if explicit is not _NO_EXPLICIT_BATCH_SUBMITTER:
        return cast(SubagentBatchSubmitter | None, explicit)
    return get_subagent_batch_submitter()


def _batch_app_config(runtime: Runtime) -> Any | None:
    explicit = _explicit_batch_app_config.get()
    if explicit is not None:
        return explicit
    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    return context.get("app_config")


def _bind_batch_tool(
    tool,
    submitter_provider: Callable[[], SubagentBatchSubmitter | None],
    app_config: Any | None,
):
    original_coroutine = tool.coroutine
    if original_coroutine is None:  # pragma: no cover - all batch tools are async
        raise RuntimeError(f"{tool.name} has no async implementation")

    async def bound_coroutine(**kwargs):
        submitter_token = _explicit_batch_submitter.set(submitter_provider())
        config_token = _explicit_batch_app_config.set(app_config)
        try:
            return await original_coroutine(**kwargs)
        finally:
            _explicit_batch_app_config.reset(config_token)
            _explicit_batch_submitter.reset(submitter_token)

    return tool.model_copy(update={"coroutine": bound_coroutine})


def bind_batch_tools(
    submitter: SubagentBatchSubmitter | None = None,
    *,
    submitter_provider: Callable[[], SubagentBatchSubmitter | None] | None = None,
    app_config: Any | None = None,
):
    """Return batch tools bound to an explicit SDK runtime submitter.

    A provider preserves runtime lifecycle semantics for already-compiled
    graphs: after their owned worker stops, the tools report unavailable and
    never fall through to another application's process-global submitter.
    """

    if (submitter is None) == (submitter_provider is None):
        raise ValueError("Provide exactly one of submitter or submitter_provider")
    provider = submitter_provider if submitter_provider is not None else lambda: submitter

    return tuple(_bind_batch_tool(tool, provider, app_config) for tool in (batch_task, batch_status, cancel_batch))


def _result(tool_call_id: str, *, content: str, batch: dict[str, Any] | None = None, error: bool = False) -> Command:
    metadata: dict[str, Any] = {"subagent_batch_error": error}
    if batch is not None:
        metadata.update(
            {
                "subagent_batch_id": batch["id"],
                "subagent_batch_status": batch["status"],
                "subagent_batch_total_items": batch["total_items"],
            }
        )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name="batch_task",
                    status="error" if error else "success",
                    additional_kwargs=metadata,
                )
            ]
        }
    )


def _merge_skill_allowlists(parent: list[str] | None, child: list[str] | None) -> list[str] | None:
    if parent is None:
        return child
    if child is None:
        return list(parent)
    allowed = set(parent)
    return [name for name in child if name in allowed]


@tool("batch_task", parse_docstring=True)
async def batch_task(
    runtime: Runtime,
    title: str,
    items: list[BatchTaskItem],
    subagent_type: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_live_items: int | None = None,
    max_running_items: int | None = None,
) -> Command:
    """Submit many independent items to DeerFlow's explicit durable batch mode.

    Use this only when every item is independent, idempotent or read-only, and
    can be completed without another item's output. This tool returns a batch
    identifier immediately; it never inserts thousands of results into the lead
    agent context. Use ``batch_status`` for a compact progress snapshot.

    Args:
        title: Short batch name shown to the user.
        items: Stable item keys and self-contained prompts.
        subagent_type: Native subagent definition used for every item.
        max_live_items: Optional queued-plus-running item window.
        max_running_items: Optional per-batch real execution concurrency.
    """
    submitter = _batch_submitter()
    if submitter is None:
        return _result(
            tool_call_id,
            content="Durable subagent batches are unavailable. Enable subagent_batches with a SQL database and restart Gateway.",
            error=True,
        )
    if not items:
        return _result(tool_call_id, content="A batch must contain at least one item.", error=True)
    keys = [item.key for item in items]
    if len(set(keys)) != len(keys):
        return _result(tool_call_id, content="Batch item keys must be unique.", error=True)

    context = runtime.context if runtime is not None and isinstance(runtime.context, dict) else {}
    metadata = runtime.config.get("metadata", {}) if runtime is not None else {}
    app_config = _batch_app_config(runtime)
    allowed_subagents = metadata.get("allowed_subagents")
    available = get_available_subagent_names(app_config=app_config, allowed_subagents=allowed_subagents)
    config = get_subagent_config(subagent_type, app_config=app_config)
    if config is None or subagent_type not in available:
        names = ", ".join(available) if available else "none"
        return _result(
            tool_call_id,
            content=f"Unknown or disallowed subagent type {subagent_type!r}. Available: {names}",
            error=True,
        )

    parent_skills = metadata.get("available_skills")
    if parent_skills is not None:
        config = replace(config, skills=_merge_skill_allowlists(list(parent_skills), config.skills))

    thread_id = context.get("thread_id") or runtime.config.get("configurable", {}).get("thread_id")
    if not thread_id:
        return _result(tool_call_id, content="Durable batches require a thread_id.", error=True)
    user_id = resolve_runtime_user_id(runtime)
    run_id = context.get("run_id")
    submission_key = f"{run_id or thread_id}:{tool_call_id}"
    execution_spec = {
        "subagent_config": asdict(config),
        "parent_model": metadata.get("model_name"),
        "tool_groups": metadata.get("tool_groups"),
        "user_role": context.get("user_role"),
        "oauth_provider": context.get("oauth_provider"),
        "oauth_id": context.get("oauth_id"),
        "channel_user_id": context.get("channel_user_id"),
        "is_internal": context.get("is_internal") is True,
        "authz_attributes": normalize_authz_attributes(context.get("authz_attributes")),
    }
    try:
        batch = await submitter.submit(
            BatchSubmitRequest(
                user_id=user_id,
                thread_id=str(thread_id),
                run_id=str(run_id) if run_id else None,
                tool_call_id=tool_call_id,
                submission_key=submission_key,
                title=title.strip()[:256] or "Subagent batch",
                subagent_type=subagent_type,
                items=[item.model_dump() for item in items],
                max_live_items=max_live_items,
                max_running_items=max_running_items,
                execution_spec=execution_spec,
            )
        )
    except Exception as exc:
        return _result(tool_call_id, content=f"Batch submission failed: {exc}", error=True)
    return _result(
        tool_call_id,
        batch=batch,
        content=(f"Batch {batch['id']} accepted with {batch['total_items']} items. It is running independently and survives Gateway restarts. Use batch_status for progress; do not launch ordinary task calls for these items."),
    )


@tool("batch_status", parse_docstring=True)
async def batch_status(runtime: Runtime, batch_id: str) -> str:
    """Return a compact durable batch progress snapshot.

    Args:
        batch_id: Server batch identifier returned by ``batch_task``.
    """
    submitter = _batch_submitter()
    if submitter is None:
        return "Durable subagent batches are unavailable."
    batch = await submitter.get_batch(batch_id=batch_id, user_id=resolve_runtime_user_id(runtime))
    if batch is None:
        return "Batch not found."
    return json.dumps(
        {
            "batch_id": batch["id"],
            "status": batch["status"],
            "total_items": batch["total_items"],
            "counts": batch["counts"],
        },
        ensure_ascii=False,
    )


@tool("cancel_batch", parse_docstring=True)
async def cancel_batch(runtime: Runtime, batch_id: str) -> str:
    """Cancel pending and running work in one durable subagent batch.

    Args:
        batch_id: Server batch identifier returned by ``batch_task``.
    """
    submitter = _batch_submitter()
    if submitter is None:
        return "Durable subagent batches are unavailable."
    batch = await submitter.cancel_batch(batch_id=batch_id, user_id=resolve_runtime_user_id(runtime))
    if batch is None:
        return "Batch not found."
    return f"Batch {batch_id} cancellation requested."
