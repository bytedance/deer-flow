"""Canonical serialization for LangChain / LangGraph objects.

Provides a single source of truth for converting LangChain message
objects, Pydantic models, and LangGraph state dicts into plain
JSON-serialisable Python structures.

Consumers: ``deerflow.runtime.runs.worker`` (SSE publishing) and
``app.gateway.routers.threads`` (REST responses).
"""

from __future__ import annotations

import math
from typing import Any


def serialize_lc_object(obj: Any) -> Any:
    """Recursively serialize a LangChain object to a JSON-serialisable dict.

    Non-finite floats (``NaN`` / ``inf`` / ``-inf``) are normalized to ``None``.
    They are not valid JSON (RFC 8259) and reach this serializer from ordinary
    runtime data — e.g. ``json.loads("1e400")`` yields ``inf`` for a tool parsing
    external JSON, or a provider logprob of ``-inf`` for a zero-probability token.
    Left untouched they break both display paths that share this serializer: the
    SSE wire (``format_sse`` / the Redis bridge encode with the lenient default,
    emitting bare ``NaN`` / ``Infinity`` tokens the ``langgraph-sdk`` / useStream
    decoder rejects) and the REST surface (Starlette's ``JSONResponse`` uses
    ``allow_nan=False`` and raises, turning a thread read into HTTP 500). This is
    a display/wire normalization only; persisted checkpoint state is never routed
    through here.
    """
    if obj is None:
        return None
    # ``bool`` is a subclass of ``int``, so it passes through unchanged here.
    if isinstance(obj, (str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(item) for item in obj]
    # Pydantic v2 — recurse so non-finite floats nested in the dump (e.g. a
    # message's ``response_metadata``) are normalized too, not returned raw.
    if hasattr(obj, "model_dump"):
        try:
            return serialize_lc_object(obj.model_dump())
        except Exception:
            pass
    # Pydantic v1 / older objects
    if hasattr(obj, "dict"):
        try:
            return serialize_lc_object(obj.dict())
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


def serialize_messages_tuple(obj: Any) -> Any:
    """Serialize a messages-mode tuple ``(chunk, metadata)``.

    The metadata dict rides the same wire as the chunk, so it goes through the
    same canonical serializer: a non-finite float in metadata (LangGraph merges
    caller-supplied run metadata, which can carry one) would otherwise reach
    ``format_sse`` / the Redis bridge encode and emit a bare ``NaN`` /
    ``Infinity`` token the SSE decoder rejects. Real LangGraph metadata also
    contains tuples (``langgraph_triggers`` / ``langgraph_path``); they become
    lists here, their JSON wire shape anyway.
    """
    if isinstance(obj, tuple) and len(obj) == 2:
        chunk, metadata = obj
        return [
            serialize_lc_object(chunk),
            serialize_lc_object(metadata) if isinstance(metadata, dict) else {},
        ]
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
