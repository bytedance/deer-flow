"""Canonical serialization for LangChain / LangGraph objects.

Provides a single source of truth for converting LangChain message
objects, Pydantic models, and LangGraph state dicts into plain
JSON-serialisable Python structures.

Consumers: ``deerflow.runtime.runs.worker`` (SSE publishing) and
``app.gateway.routers.threads`` (REST responses).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def serialize_lc_object(obj: Any) -> Any:
    """Recursively serialize a LangChain object to a JSON-serialisable dict."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    # Pydantic v1 / older objects
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    # Interrupt is a __slots__ class — no model_dump/dict/__dict__, so it
    # would reach str() and produce a malformed payload.
    try:
        from langgraph.types import Interrupt
    except ImportError:
        pass
    else:
        if isinstance(obj, Interrupt):
            return serialize_lc_object(
                {
                    "value": obj.value,
                    "id": getattr(obj, "id", None),
                }
            )
    # Last resort
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def serialize_channel_values(channel_values: dict[str, Any]) -> dict[str, Any]:
    """Serialize channel values, stripping internal LangGraph keys.

    Only ``__pregel_*`` keys are removed — ``__interrupt__`` is deliberately
    preserved so the LangGraph SDK can detect interrupt events from values
    chunks (see issue #3595).
    """
    result: dict[str, Any] = {}
    for key, value in channel_values.items():
        if key.startswith("__pregel_"):
            continue
        result[key] = serialize_lc_object(value)
    return result


def strip_data_url_image_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove ``data:``-scheme ``image_url`` blocks from *hide_from_ui* messages.

    The history and run-wait endpoints return checkpoint-persisted messages to
    the frontend.  ``ViewImageMiddleware`` now keeps its base64 image payloads
    inside the model request, but threads checkpointed by earlier versions still
    hold them in ``hide_from_ui`` human messages — these are internal model
    context and must not be sent over the wire (huge response bodies, no UI
    value).

    Only content blocks of type ``image_url`` whose URL starts with ``data:``
    are stripped.  Text blocks, ``https://`` image URLs, and non-hidden
    messages are left untouched so that message ordering and count are
    preserved.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            result.append(msg)
            continue

        # Only touch messages explicitly flagged as hidden from the UI.
        additional_kwargs = msg.get("additional_kwargs")
        if not (isinstance(additional_kwargs, dict) and additional_kwargs.get("hide_from_ui") is True):
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue

        # Filter out image_url blocks with data: scheme.
        filtered = [block for block in content if not (isinstance(block, dict) and block.get("type") == "image_url" and isinstance(block.get("image_url"), dict) and str(block["image_url"].get("url", "")).startswith("data:"))]
        result.append({**msg, "content": filtered})
    return result


def serialize_channel_values_for_api(channel_values: dict[str, Any]) -> dict[str, Any]:
    """Serialize channel values and strip base64 image data from messages.

    Convenience wrapper combining :func:`serialize_channel_values` with
    :func:`strip_data_url_image_blocks`.  Use this in all REST endpoints
    that return channel values to the frontend so that ``data:``-scheme
    base64 image payloads are never sent over the wire.
    """
    result = serialize_channel_values(channel_values)
    if isinstance(result.get("messages"), list):
        result["messages"] = strip_data_url_image_blocks(result["messages"])
    return result


def serialize_interrupts(raw_interrupts: Any) -> list[dict[str, Any]]:
    """Reshape LangGraph interrupts into the ``{"id", "value"}`` wire format.

    LangGraph publishes a tuple of ``Interrupt`` objects, both on the
    ``__interrupt__`` channel and on ``PregelTask.interrupts``. They use
    ``__slots__``, so they are not dict-like and must be projected field by
    field. A checkpoint replay can hand back plain dicts instead, so both
    forms are accepted.

    Args:
        raw_interrupts: Interrupt objects, dicts, or ``None``.

    Returns:
        One entry per interrupt, empty when nothing is pending.
    """
    if not raw_interrupts:
        return []
    if isinstance(raw_interrupts, (str, bytes)) or not isinstance(raw_interrupts, Iterable):
        raw_interrupts = [raw_interrupts]

    serialized: list[dict[str, Any]] = []
    for item in raw_interrupts:
        if isinstance(item, dict):
            serialized.append({"id": item.get("id"), "value": serialize_lc_object(item.get("value"))})
            continue
        if not hasattr(item, "value"):
            # Not interrupt-shaped; a str would otherwise yield one entry per
            # character once it reached the iteration above.
            continue
        serialized.append({"id": getattr(item, "id", None), "value": serialize_lc_object(item.value)})
    return serialized


def serialize_tasks_for_api(raw_tasks: Any) -> list[dict[str, Any]]:
    """Project snapshot tasks for REST responses, preserving interrupts.

    ``interrupts`` is included only when a task actually carries one, so an
    ordinary in-flight task keeps the shape older clients already parse.
    """
    tasks: list[dict[str, Any]] = []
    for task in raw_tasks or ():
        entry: dict[str, Any] = {"id": getattr(task, "id", ""), "name": getattr(task, "name", "")}
        if interrupts := serialize_interrupts(getattr(task, "interrupts", None)):
            entry["interrupts"] = interrupts
        tasks.append(entry)
    return tasks


def interrupts_by_task(snapshot: Any) -> dict[str, list[dict[str, Any]]]:
    """Map task id -> pending interrupts, the LangGraph SDK's ``interrupts`` shape.

    A parked run keeps its payload only on ``snapshot.tasks``; the checkpoint's
    channel values do not carry ``__interrupt__``. Tasks without an interrupt
    are omitted so an ordinary in-flight run stays an empty mapping.
    """
    mapping: dict[str, list[dict[str, Any]]] = {}
    for task in getattr(snapshot, "tasks", None) or ():
        if interrupts := serialize_interrupts(getattr(task, "interrupts", None)):
            mapping[str(getattr(task, "id", ""))] = interrupts
    return mapping


#: Wait-response status for a run parked on tool approval. Deliberately not
#: ``RunStatus.interrupted``, which the *cancellation* path persists: the wait
#: endpoints' fallback branch returns that durable status, so one value would
#: have to mean both "resume this" and "this is over".
WAIT_STATUS_AWAITING_APPROVAL = "interrupted_for_approval"


def project_snapshot_for_wait(snapshot: Any) -> dict[str, Any]:
    """Project a finished run's snapshot for a blocking ``/wait`` response.

    ``interrupt()`` exits the graph normally, so a run parked on tool approval
    is indistinguishable from a completion at ``snapshot.values`` alone — a
    resume that parks again would return a mid-turn approval request as the
    run's final answer. When interrupts are pending, wrap the values in a
    :data:`WAIT_STATUS_AWAITING_APPROVAL` envelope carrying the payload;
    otherwise return the bare values object that clients already parse.
    """
    values = serialize_channel_values_for_api(snapshot.values)
    interrupts = interrupts_by_task(snapshot)
    if not interrupts:
        return values
    return {
        "status": WAIT_STATUS_AWAITING_APPROVAL,
        "interrupts": interrupts,
        "tasks": serialize_tasks_for_api(getattr(snapshot, "tasks", None)),
        "values": values,
    }


def serialize_messages_tuple(obj: Any) -> Any:
    """Serialize a messages-mode tuple ``(chunk, metadata)``."""
    if isinstance(obj, tuple) and len(obj) == 2:
        chunk, metadata = obj
        return [serialize_lc_object(chunk), metadata if isinstance(metadata, dict) else {}]
    return serialize_lc_object(obj)


def serialize(obj: Any, *, mode: str = "") -> Any:
    """Serialize LangChain objects with mode-specific handling.

    * ``messages`` — obj is ``(message_chunk, metadata_dict)``
    * ``values`` — obj is the full state dict; ``__pregel_*`` keys stripped and
      base64 ``data:`` image blocks dropped from hide_from_ui messages
    * everything else — recursive ``model_dump()`` / ``dict()`` fallback
    """
    if mode == "messages":
        return serialize_messages_tuple(obj)
    if mode == "values":
        # ``values`` snapshots stream the full state to the frontend, so they
        # must drop base64 image payloads the same way the REST endpoints do.
        return serialize_channel_values_for_api(obj) if isinstance(obj, dict) else serialize_lc_object(obj)
    return serialize_lc_object(obj)
