"""Compute a per-category breakdown of the context window usage for a thread.

The breakdown mirrors the layout shown by Claude Code's context indicator:
messages, system prompt, skills, system tools, MCP tools (active + deferred),
custom agents (subagents), memory injection, the summarization headroom we
treat as an autocompact buffer, and finally the free space left over.

Every category is computed in isolation in its own ``try`` block — if any
single component fails to render we still return the rest, never the whole
endpoint. Counting is configurable: ``approximate`` uses LangChain's
network-free heuristic, while ``exact`` tokenizes text and serialized tool or
structured payloads, retaining a bounded estimate for images.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import hashlib
import json
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import HTTPException, Request

from app.gateway.deps import get_checkpointer, get_config, get_thread_store

logger = logging.getLogger(__name__)

_CONTEXT_COUNT_TIMEOUT_SECONDS = 5.0
_CONTEXT_COUNT_CACHE_SIZE = 64
_CONTEXT_COUNT_EXECUTOR: ThreadPoolExecutor | None = None
_MESSAGE_FRAME_TOKENS = 4
_TOKENS_PER_IMAGE = 85
_IMAGE_CONTENT_BLOCK_TYPES: frozenset[str] = frozenset({"image", "image_url", "input_image"})
_TOOL_CALL_CONTENT_BLOCK_TYPES: frozenset[str] = frozenset({"custom_tool_call", "function_call", "tool_call", "tool_use"})
_REASONING_CONTENT_BLOCK_TYPES: frozenset[str] = frozenset({"reasoning", "reasoning_content", "thinking"})
_RESPONSES_TEXT_METADATA_FIELDS: tuple[str, ...] = ("annotations", "id", "phase")
_RESPONSES_FUNCTION_CALL_IDS_KEY = "__openai_function_call_ids__"
_REASONING_REPLAY_MODEL_CLASSES: frozenset[str] = frozenset(
    {
        "PatchedChatDeepSeek",
        "PatchedChatMiMo",
        "PatchedChatStepFun",
        "VllmChatModel",
    }
)

type _ContextCountCacheKey = tuple[str, str, str, str, str, str, str, str]

_CONTEXT_COUNT_CACHE: OrderedDict[_ContextCountCacheKey, dict[str, Any]] = OrderedDict()
_CONTEXT_COUNT_INFLIGHT: dict[_ContextCountCacheKey, asyncio.Task[dict[str, Any]]] = {}


def _get_context_count_executor() -> ThreadPoolExecutor:
    global _CONTEXT_COUNT_EXECUTOR
    if _CONTEXT_COUNT_EXECUTOR is None:
        _CONTEXT_COUNT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="context-usage")
    return _CONTEXT_COUNT_EXECUTOR


# Order in which breakdown rows are listed in the UI. Items missing from the
# computed breakdown (because they are zero) are simply skipped.
_BREAKDOWN_ORDER: tuple[str, ...] = (
    "messages",
    "system_tools",
    "system_prompt",
    "skills",
    "mcp_tools",
    "custom_agents",
    "memory_files",
    "mcp_tools_deferred",
    "autocompact_buffer",
    "free_space",
)

# Categories that count toward "used" (i.e. enter the model's context). The
# rest (deferred tool schemas, autocompact reserve, free space) are reserved
# / unoccupied and are shown but do not contribute to the percentage.
_ACTIVE_KEYS: frozenset[str] = frozenset(
    {
        "messages",
        "system_tools",
        "system_prompt",
        "skills",
        "mcp_tools",
        "custom_agents",
        "memory_files",
    }
)


def _approx_text_tokens(text: str | None) -> int:
    """Approximate token count for a raw text fragment.

    Matches the 4-chars-per-token heuristic used by
    :func:`langchain_core.messages.utils.count_tokens_approximately` so the
    breakdown numbers are commensurate with the messages count.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _is_exact_counting(app_config: Any) -> bool:
    """True when ``token_usage.counting == "exact"`` (use the model tokenizer)."""
    cfg = getattr(app_config, "token_usage", None)
    method = getattr(cfg, "is_exact_counting", None)
    return bool(method()) if callable(method) else False


def _count_text(text: str | None, app_config: Any) -> int:
    """Count tokens in ``text`` using the configured strategy.

    ``approximate`` (default) keeps the fast network-free chars//4 heuristic.
    ``exact`` delegates to the model tokenizer (tiktoken cl100k_base) via the
    shared memory-module machinery — lazily loaded, cached, with a CJK-aware
    char fallback when tiktoken is unavailable or the BPE download fails.
    """
    if not text:
        return 0
    if not _is_exact_counting(app_config):
        return _approx_text_tokens(text)
    try:
        from deerflow.agents.memory.backends.deermem.deermem.core.prompt import _count_tokens  # noqa: SLF001

        return int(_count_tokens(text, use_tiktoken=True))
    except Exception:
        # tiktoken unavailable / import failure → keep the heuristic rather
        # than zeroing the row (a single category failure must never collapse
        # the whole breakdown).
        return _approx_text_tokens(text)


def _serialize_message_value(value: Any) -> str:
    """Serialize a model-bound value without pulling in local message metadata."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=repr,
        )
    except Exception:
        return repr(value)


def _count_message_content_exact(content: Any, app_config: Any) -> int:
    """Count one message's provider-facing content in tokenizer mode.

    Text is tokenized directly. Non-text structured blocks are serialized so
    their payload contributes to the count, while image data receives the same
    bounded low-resolution penalty as LangChain's approximate counter instead
    of tokenizing a URL or base64 body.
    """
    if isinstance(content, str):
        return _count_text(content, app_config)
    if not isinstance(content, list):
        return _count_text(repr(content), app_config) if content is not None else 0

    total = 0
    for block in content:
        if isinstance(block, str):
            total += _count_text(block, app_config)
            continue
        if not isinstance(block, dict):
            total += _count_text(repr(block), app_config)
            continue

        block_type = block.get("type", "")
        if block_type in _IMAGE_CONTENT_BLOCK_TYPES:
            total += _TOKENS_PER_IMAGE
        elif block_type == "image_generation_call":
            # The Responses adapter replays generated images by reference and
            # drops the base64 ``result``. Count the provider-bound reference
            # plus one bounded image estimate when a result is present.
            reference = {"type": block_type}
            if isinstance(block.get("id"), str):
                reference["id"] = block["id"]
            total += _count_text(_serialize_message_value(reference), app_config)
            if block.get("result"):
                total += _TOKENS_PER_IMAGE
        elif block_type == "text" and isinstance(block.get("text"), str):
            total += _count_text(block["text"], app_config)
            metadata = {field: block[field] for field in _RESPONSES_TEXT_METADATA_FIELDS if field in block}
            if metadata:
                total += _count_text(_serialize_message_value(metadata), app_config)
        else:
            total += _count_text(_serialize_message_value(block), app_config)
    return total


def _content_tool_call_ids(content: Any) -> frozenset[str]:
    """Return tool-call ids already serialized in list-form content."""
    if not isinstance(content, list):
        return frozenset()
    ids: set[str] = set()
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in _TOOL_CALL_CONTENT_BLOCK_TYPES:
            continue
        call_id = block.get("call_id") or block.get("id")
        if isinstance(call_id, str) and call_id:
            ids.add(call_id)
    return frozenset(ids)


def _message_tool_call_payload(
    message: Any,
    represented_ids: frozenset[str],
    *,
    include_provider_extensions: bool = True,
) -> Any | None:
    """Return the tool payload LangChain will send for an AIMessage.

    Mirrors the adapter preference order: normalized valid/invalid calls win;
    raw provider calls are a fallback, followed by the legacy function-call
    field. Local response metadata and artifacts are intentionally excluded.
    """

    def _unrepresented(calls: list[Any]) -> list[Any]:
        remaining = []
        for call in calls:
            call_id = call.get("id") if isinstance(call, dict) else None
            if not isinstance(call_id, str) or call_id not in represented_ids:
                remaining.append(call)
        return remaining

    def _provider_call(call: Any) -> Any:
        if not isinstance(call, dict):
            return call
        arguments = call.get("args")
        if not isinstance(arguments, str):
            arguments = _serialize_message_value(arguments)
        return {
            "type": "function",
            "id": call.get("id"),
            "function": {
                "name": call.get("name"),
                "arguments": arguments,
            },
        }

    def _raw_provider_call(call: Any) -> Any:
        if not isinstance(call, dict):
            return call
        return {key: call[key] for key in ("id", "type", "function") if key in call}

    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}
    raw_tool_calls = additional_kwargs.get("tool_calls")

    def _provider_extensions(raw_calls: Any, sent_calls: list[Any]) -> list[dict[str, Any]]:
        if isinstance(raw_calls, dict):
            raw_calls = [raw_calls]
        if not isinstance(raw_calls, list):
            return []
        raw_by_id = {call["id"]: call for call in raw_calls if isinstance(call, dict) and isinstance(call.get("id"), str) and call["id"]}
        extensions = []
        for index, sent_call in enumerate(sent_calls):
            sent_id = sent_call.get("id") if isinstance(sent_call, dict) else None
            raw_call = raw_by_id.get(sent_id) if isinstance(sent_id, str) else None
            if raw_call is None and index < len(raw_calls) and isinstance(raw_calls[index], dict):
                raw_call = raw_calls[index]
            if raw_call is None:
                continue
            # PatchedChatOpenAI restores either spelling as the canonical
            # ``thought_signature`` field on the provider-bound tool call.
            signature = raw_call.get("thought_signature") or raw_call.get("thoughtSignature")
            if signature:
                extensions.append({"thought_signature": signature})
        return extensions

    tool_calls = getattr(message, "tool_calls", None) or []
    invalid_tool_calls = getattr(message, "invalid_tool_calls", None) or []
    if tool_calls or invalid_tool_calls:
        normalized_calls = [*tool_calls, *invalid_tool_calls]
        remaining = _unrepresented([_provider_call(call) for call in normalized_calls])
        if include_provider_extensions:
            remaining.extend(_provider_extensions(raw_tool_calls, normalized_calls))
        return remaining or None

    if raw_tool_calls:
        if isinstance(raw_tool_calls, list):
            remaining = []
            for call in raw_tool_calls:
                call_id = call.get("id") if isinstance(call, dict) else None
                if isinstance(call_id, str) and call_id in represented_ids:
                    if include_provider_extensions:
                        remaining.extend(_provider_extensions(call, [call]))
                else:
                    remaining.append(_raw_provider_call(call))
                    if include_provider_extensions:
                        remaining.extend(_provider_extensions(call, [call]))
            return remaining or None
        return raw_tool_calls
    function_call = additional_kwargs.get("function_call")
    return function_call if function_call else None


def _message_reasoning_payload(message: Any, content: Any) -> dict[str, Any] | None:
    """Return an explicitly replayed provider reasoning field, if any."""
    if isinstance(content, list) and any(isinstance(block, dict) and block.get("type") in _REASONING_CONTENT_BLOCK_TYPES for block in content):
        return None

    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict):
        return None
    if additional_kwargs.get("reasoning") is not None:
        return {"reasoning": additional_kwargs["reasoning"]}
    if additional_kwargs.get("reasoning_content") is not None:
        return {"reasoning_content": additional_kwargs["reasoning_content"]}
    return None


def _model_replays_reasoning(app_config: Any, model_name: str | None) -> bool:
    """Whether the selected adapter sends saved reasoning back to the model."""
    if model_name is None:
        # Helper-level callers do not have runtime model context. Preserve the
        # conservative standalone behavior; production always supplies a name.
        return True
    get_model_config = getattr(app_config, "get_model_config", None)
    if not callable(get_model_config):
        return False
    model_config = get_model_config(model_name)
    if model_config is None:
        return False
    if bool(getattr(model_config, "use_responses_api", False)) or getattr(model_config, "output_version", None) == "responses/v1":
        return True
    provider_path = getattr(model_config, "use", "")
    provider_class = provider_path.replace(":", ".").rsplit(".", 1)[-1] if isinstance(provider_path, str) else ""
    return provider_class in _REASONING_REPLAY_MODEL_CLASSES


def _model_replays_tool_call_signatures(app_config: Any, model_name: str | None) -> bool:
    """Whether the selected adapter restores raw Gemini thought signatures."""
    if model_name is None:
        return True
    get_model_config = getattr(app_config, "get_model_config", None)
    if not callable(get_model_config):
        return False
    model_config = get_model_config(model_name)
    provider_path = getattr(model_config, "use", "") if model_config is not None else ""
    provider_class = provider_path.replace(":", ".").rsplit(".", 1)[-1] if isinstance(provider_path, str) else ""
    return provider_class == "PatchedChatOpenAI"


def _content_item_key(block: Any) -> tuple[str, str] | None:
    if not isinstance(block, dict) or not isinstance(block.get("type"), str):
        return None
    item_id = block.get("id") or block.get("call_id")
    if not isinstance(item_id, str) or not item_id:
        return None
    return block["type"], item_id


def _count_ai_replayed_fields_exact(message: Any, content: Any, app_config: Any) -> int:
    """Count explicit Responses/Chat fields stored outside message content."""
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}

    content_blocks = content if isinstance(content, list) else []
    content_types = {block.get("type") for block in content_blocks if isinstance(block, dict) and isinstance(block.get("type"), str)}
    content_keys = {key for block in content_blocks if (key := _content_item_key(block)) is not None}
    content_ids = {key[1] for key in content_keys}
    total = 0

    message_id = getattr(message, "id", None)
    response_metadata = getattr(message, "response_metadata", None)
    response_id = response_metadata.get("id") if isinstance(response_metadata, dict) else None
    is_responses_v03 = (
        isinstance(content, list)
        and all(isinstance(block, dict) for block in content)
        and (
            any(key in additional_kwargs for key in ("reasoning", "tool_outputs", "refusal", _RESPONSES_FUNCTION_CALL_IDS_KEY))
            or (isinstance(message_id, str) and message_id.startswith("msg_") and isinstance(response_id, str) and response_id.startswith("resp_"))
        )
    )
    if is_responses_v03:
        refusal = additional_kwargs.get("refusal")
        if refusal and "refusal" not in content_types:
            total += _count_text(_serialize_message_value({"type": "refusal", "refusal": refusal}), app_config)

        tool_outputs = additional_kwargs.get("tool_outputs")
        if isinstance(tool_outputs, list):
            unrepresented_outputs = [block for block in tool_outputs if (key := _content_item_key(block)) is None or key not in content_keys]
            total += _count_message_content_exact(unrepresented_outputs, app_config)

        function_call_ids = additional_kwargs.get(_RESPONSES_FUNCTION_CALL_IDS_KEY)
        if isinstance(function_call_ids, dict):
            item_ids = []
            for tool_call in getattr(message, "tool_calls", None) or []:
                call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
                item_id = function_call_ids.get(call_id) if isinstance(call_id, str) else None
                if isinstance(item_id, str) and item_id and item_id not in content_ids:
                    item_ids.append({"id": item_id})
            if item_ids:
                total += _count_text(_serialize_message_value(item_ids), app_config)

        if isinstance(message_id, str) and message_id.startswith("msg_"):
            missing_text_ids = sum(1 for block in content_blocks if isinstance(block, dict) and block.get("type") == "text" and "id" not in block)
            for _ in range(missing_text_ids):
                total += _count_text(_serialize_message_value({"id": message_id}), app_config)

    audio = additional_kwargs.get("audio")
    if audio and "audio" not in content_types:
        audio_reference = {"id": audio["id"]} if isinstance(audio, dict) and "id" in audio else audio
        total += _count_text(_serialize_message_value({"audio": audio_reference}), app_config)

    return total


def _count_messages(messages: list[Any], app_config: Any, *, model_name: str | None = None) -> int:
    """Count tokens across checkpoint messages using the configured strategy.

    ``approximate`` reuses LangChain's ``count_tokens_approximately``.
    ``exact`` explicitly counts text, structured content, AI tool-call payloads,
    ToolMessage call ids, and message names. Image blocks use a bounded estimate
    and framing remains a small fixed overhead because it is provider-specific.
    """
    if not messages:
        return 0
    if not _is_exact_counting(app_config):
        from langchain_core.messages.utils import count_tokens_approximately

        return int(count_tokens_approximately(messages))

    from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

    total = 0
    count_replayed_reasoning = _model_replays_reasoning(app_config, model_name)
    count_tool_call_signatures = _model_replays_tool_call_signatures(app_config, model_name)
    for msg in messages:
        content = getattr(msg, "content", None)
        total += _count_message_content_exact(content, app_config)

        # Anthropic and OpenAI Responses may normalize calls into both content
        # blocks and ``tool_calls``. Deduplicate by id so any call missing from
        # the content list still contributes its provider-bound payload.
        if isinstance(msg, AIMessage):
            tool_payload = _message_tool_call_payload(
                msg,
                _content_tool_call_ids(content),
                include_provider_extensions=count_tool_call_signatures,
            )
            if tool_payload is not None:
                total += _count_text(_serialize_message_value(tool_payload), app_config)
            if count_replayed_reasoning:
                reasoning_payload = _message_reasoning_payload(msg, content)
                if reasoning_payload is not None:
                    total += _count_text(_serialize_message_value(reasoning_payload), app_config)
            total += _count_ai_replayed_fields_exact(msg, content, app_config)

        if isinstance(msg, ToolMessage):
            tool_call_id = getattr(msg, "tool_call_id", None)
            if isinstance(tool_call_id, str):
                total += _count_text(tool_call_id, app_config)

        name = getattr(msg, "name", None)
        additional_kwargs = getattr(msg, "additional_kwargs", None)
        if not name and isinstance(additional_kwargs, dict):
            name = additional_kwargs.get("name")
        if isinstance(name, str) and name:
            total += _count_text(name, app_config)

        # Role tags and provider-specific delimiters are not exposed on the
        # LangChain message, so retain the existing bounded framing estimate.
        if isinstance(msg, BaseMessage):
            total += _MESSAGE_FRAME_TOKENS
    return total


def _approx_tool_schema_tokens(tool: Any, app_config: Any | None = None) -> int:
    """Approximate the tokens a tool's OpenAI schema occupies in the prompt."""
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        schema = convert_to_openai_tool(tool)
        return _count_text(json.dumps(schema, ensure_ascii=False), app_config)
    except Exception:
        # Fall back to a description-only estimate so a single broken tool
        # never causes the whole breakdown to collapse.
        name = getattr(tool, "name", "") or ""
        description = getattr(tool, "description", "") or ""
        return _count_text(f"{name}\n{description}", app_config)


async def _resolve_thread_runtime(run_store: Any, thread_id: str, app_config: Any) -> tuple[str | None, dict[str, Any]]:
    """Pick the model and persisted runtime options for the latest run.

    Prefers the most recent run's ``model_name`` (set by the runtime when
    the run starts), falling back to the first configured model.
    """
    try:
        runs = await run_store.list_by_thread(thread_id, limit=1)
    except Exception:
        runs = []
    if runs:
        latest = runs[0]
        name = latest.get("model_name") if isinstance(latest, dict) else getattr(latest, "model_name", None)
        kwargs = latest.get("kwargs", {}) if isinstance(latest, dict) else getattr(latest, "kwargs", {})
        persisted_config = kwargs.get("config", {}) if isinstance(kwargs, dict) else {}
        runtime: dict[str, Any] = {}
        if isinstance(persisted_config, dict):
            for key in ("configurable", "context"):
                values = persisted_config.get(key)
                if isinstance(values, dict):
                    runtime.update(values)
        if isinstance(name, str) and name:
            return name, runtime
    else:
        runtime = {}
    models = getattr(app_config, "models", None) or []
    return (models[0].name if models else None), runtime


def _checkpoint_cache_token(checkpoint: dict[str, Any], messages: list[Any], promoted: dict[str, Any] | None) -> str:
    checkpoint_id = checkpoint.get("id")
    if isinstance(checkpoint_id, str) and checkpoint_id:
        return checkpoint_id

    snapshot = {
        "messages": [
            {
                "type": type(message).__name__,
                "id": getattr(message, "id", None),
                "name": getattr(message, "name", None),
                "content": getattr(message, "content", None),
                "additional_kwargs": getattr(message, "additional_kwargs", None),
                "response_metadata": getattr(message, "response_metadata", None),
                "tool_calls": getattr(message, "tool_calls", None),
                "invalid_tool_calls": getattr(message, "invalid_tool_calls", None),
                "tool_call_id": getattr(message, "tool_call_id", None),
            }
            for message in messages
        ],
        "promoted": promoted,
    }
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=repr)
    return f"snapshot:{hashlib.sha256(serialized.encode()).hexdigest()}"


async def _load_checkpoint_messages(checkpointer: Any, thread_id: str) -> tuple[list[Any], dict[str, Any] | None, str]:
    """Load messages and the raw promoted-tool entry from the thread checkpoint.

    Returns ``(messages, promoted, checkpoint_token)``. ``promoted`` is the raw
    ``{"catalog_hash", "names"}`` dict persisted by ``tool_search`` (or ``None``);
    it is scoped by catalog hash later in :func:`_split_tools` so a stale
    promotion from MCP-config drift cannot inflate the active count. The stable
    checkpoint token keys the bounded per-turn render cache.
    """
    checkpoint_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    if checkpoint_tuple is None:
        return [], None, _checkpoint_cache_token({}, [], None)
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    messages = list(channel_values.get("messages") or [])
    promoted = channel_values.get("promoted")
    promoted = promoted if isinstance(promoted, dict) else None
    return messages, promoted, _checkpoint_cache_token(checkpoint, messages, promoted)


def _is_injected_memory_message(message: Any) -> bool:
    """Identify the persisted memory copy added by DynamicContextMiddleware."""
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    message_id = getattr(message, "id", None)
    return bool(additional_kwargs.get("dynamic_context_reminder") and isinstance(message_id, str) and message_id.endswith("__memory"))


def _count_checkpoint_tokens(messages: list[Any], app_config: Any, *, model_name: str | None = None) -> tuple[int, int]:
    """Return (conversation, injected-memory) tokens without double counting."""
    memory_messages = [message for message in messages if _is_injected_memory_message(message)]
    conversation_messages = [message for message in messages if not _is_injected_memory_message(message)]
    return _count_messages(conversation_messages, app_config, model_name=model_name), _count_messages(
        memory_messages,
        app_config,
        model_name=model_name,
    )


async def _resolve_thread_agent_name(request: Request, thread_id: str) -> str | None:
    """Read the custom-agent identity persisted with the UI thread."""
    try:
        record = await get_thread_store(request).get(thread_id)
    except Exception:
        logger.warning("Failed to load thread metadata for context usage", exc_info=True)
        return None
    metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
    agent_name = metadata.get("agent_name") if isinstance(metadata, dict) else None
    return agent_name if isinstance(agent_name, str) and agent_name else None


def _count_skills_section(
    app_config: Any,
    available_skills: set[str] | None = None,
    user_id: str | None = None,
) -> int:
    try:
        from deerflow.agents.lead_agent.prompt import get_skills_prompt_section

        return _count_text(
            get_skills_prompt_section(
                available_skills=available_skills,
                app_config=app_config,
                user_id=user_id,
            ),
            app_config,
        )
    except Exception:
        logger.warning("Failed to render skills prompt section", exc_info=True)
        return 0


def _count_subagent_section(
    app_config: Any,
    *,
    enabled: bool | None = None,
    max_concurrent: int | None = None,
) -> int:
    """Tokens for the subagent / custom-agents section when enabled."""
    try:
        subagents_cfg = getattr(app_config, "subagents", None)
        resolved_enabled = bool(getattr(subagents_cfg, "enabled", False)) if enabled is None else enabled
        if not resolved_enabled:
            return 0
        from deerflow.agents.lead_agent.prompt import _build_subagent_section  # noqa: SLF001

        resolved_max = max_concurrent if max_concurrent is not None else getattr(subagents_cfg, "max_concurrent_subagents", 3)
        return _count_text(_build_subagent_section(resolved_max, app_config=app_config), app_config)
    except Exception:
        logger.warning("Failed to render subagent prompt section", exc_info=True)
        return 0


def _compute_deferred_tool_names(app_config: Any) -> frozenset[str]:
    """Derive the deferred tool-name set from config + MCP cache.

    Mirrors :func:`deerflow.tools.builtins.tool_search.build_deferred_tool_setup`:
    when ``tool_search.enabled`` is on, every MCP-sourced tool is deferred;
    otherwise the set is empty. The deferred set is produced at agent-build
    time as a build-time closure (no global registry / ContextVar), so the
    request path recomputes it deterministically from the same inputs.
    """
    ts_cfg = getattr(app_config, "tool_search", None)
    if not bool(getattr(ts_cfg, "enabled", False)):
        return frozenset()
    try:
        from deerflow.mcp.cache import get_cached_mcp_tools
        from deerflow.tools.mcp_metadata import is_mcp_tool

        return frozenset(t.name for t in get_cached_mcp_tools() if is_mcp_tool(t))
    except Exception:
        return frozenset()


def _count_system_prompt(
    app_config: Any,
    *,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
    user_id: str | None = None,
    subagent_enabled: bool | None = None,
    max_concurrent_subagents: int | None = None,
    skills_tokens: int | None = None,
    subagent_tokens: int | None = None,
) -> int:
    """System prompt tokens *excluding* skills/subagent sections.

    Skills and the subagent section each get their own breakdown row, so we
    render the full prompt and subtract those pieces to avoid double-counting.
    The ``<available-deferred-tools>`` section has no row of its own, so it is
    kept *inside* the system-prompt count by passing the real deferred-name
    set into ``apply_prompt_template``.
    """
    try:
        from deerflow.agents.lead_agent.prompt import (
            apply_prompt_template,
            get_skills_prompt_section,
        )

        subagents_cfg = getattr(app_config, "subagents", None)
        resolved_subagent_enabled = bool(getattr(subagents_cfg, "enabled", False)) if subagent_enabled is None else subagent_enabled
        resolved_max_concurrent = max_concurrent_subagents if max_concurrent_subagents is not None else getattr(subagents_cfg, "max_concurrent_subagents", 3)

        # Render the FULL prompt including the deferred-tools names section;
        # that section has no row of its own, so it must stay inside the
        # system_prompt count.
        deferred_names = _compute_deferred_tool_names(app_config)
        full = apply_prompt_template(
            subagent_enabled=resolved_subagent_enabled,
            max_concurrent_subagents=resolved_max_concurrent,
            agent_name=agent_name,
            available_skills=available_skills,
            app_config=app_config,
            deferred_names=deferred_names,
            user_id=user_id,
        )
        full_tokens = _count_text(full, app_config)

        # Pieces accounted for under their own breakdown rows.
        resolved_skills_tokens = skills_tokens
        if resolved_skills_tokens is None:
            resolved_skills_tokens = _count_text(
                get_skills_prompt_section(
                    available_skills=available_skills,
                    app_config=app_config,
                    user_id=user_id,
                ),
                app_config,
            )
        resolved_subagent_tokens = subagent_tokens
        if resolved_subagent_tokens is None:
            resolved_subagent_tokens = _count_subagent_section(
                app_config,
                enabled=resolved_subagent_enabled,
                max_concurrent=resolved_max_concurrent,
            )

        return max(0, full_tokens - resolved_skills_tokens - resolved_subagent_tokens)
    except Exception:
        logger.warning("Failed to render system prompt for token breakdown", exc_info=True)
        return 0


def _effective_promoted_names(promoted: dict[str, Any] | None, mcp_tools: list[Any]) -> frozenset[str]:
    """Resolve promoted tool names, scoped by the current MCP catalog hash.

    Mirrors :class:`DeferredToolFilterMiddleware._promoted`: a persisted
    promotion only applies when its ``catalog_hash`` matches the catalog built
    from the current (policy-filtered) MCP tools. On catalog drift the
    middleware binds nothing, so we must likewise treat the promotion as empty —
    otherwise a stale name that still happens to be a current MCP tool would be
    over-counted as active.
    """
    if not promoted:
        return frozenset()
    names = promoted.get("names")
    if not isinstance(names, list) or not names:
        return frozenset()
    persisted_hash = promoted.get("catalog_hash")
    if not isinstance(persisted_hash, str) or not persisted_hash:
        return frozenset()
    try:
        from deerflow.tools.builtins.tool_search import DeferredToolCatalog

        current_hash = DeferredToolCatalog(tuple(mcp_tools)).hash if mcp_tools else None
    except Exception:
        # Cannot recompute the current hash -> be conservative: treat nothing as
        # promoted so we never over-count active tools on uncertain state.
        return frozenset()
    if current_hash != persisted_hash:
        return frozenset()
    return frozenset(n for n in names if isinstance(n, str) and n)


def _split_tools(
    app_config: Any,
    model_name: str | None,
    *,
    tool_groups: list[str] | None = None,
    subagent_enabled: bool | None = None,
    promoted: dict[str, Any] | None = None,
) -> tuple[int, int, int]:
    """Return (system_tools_active, mcp_tools_active, mcp_tools_deferred).

    A tool is "deferred" exactly when ``tool_search.enabled`` is on, it is
    MCP-sourced, AND it has not been promoted in this thread — mirroring
    :func:`deerflow.tools.builtins.tool_search.build_deferred_tool_setup`, which
    defers ``[t for t in filtered_tools if is_mcp_tool(t)]`` when enabled, and
    :class:`DeferredToolFilterMiddleware`, which binds the full schema of any
    tool the thread has promoted via ``tool_search`` (catalog-hash scoped).
    Promoted MCP tools are therefore counted under ``mcp_tools`` (active) rather
    than the reserved ``mcp_tools_deferred`` row, so the thread's ``used_tokens``
    reflects what is actually bound. The MCP-source tag is written by
    :func:`deerflow.tools.get_available_tools` via
    :func:`deerflow.tools.mcp_metadata.tag_mcp_tool`, so ``is_mcp_tool(tool)``
    classifies the returned list directly — no registry lookup is needed.

    Skill ``allowed-tools`` filtering is intentionally not replayed here. On
    current main it is model-call-local and applies only to slash-activated or
    in-context skills; globally filtering by every enabled skill would
    under-count ordinary passive turns. The checkpoint endpoint does not retain
    enough run-local slash context to reconstruct that middleware decision.
    """
    try:
        from deerflow.tools.mcp_metadata import is_mcp_tool
        from deerflow.tools.tools import get_available_tools

        resolved_subagent_enabled = bool(getattr(getattr(app_config, "subagents", None), "enabled", False)) if subagent_enabled is None else subagent_enabled

        all_tools = get_available_tools(
            model_name=model_name,
            groups=tool_groups,
            subagent_enabled=resolved_subagent_enabled,
            app_config=app_config,
        )

        # deferred ⟺ (tool_search enabled AND MCP-sourced AND not promoted in this thread).
        ts_cfg = getattr(app_config, "tool_search", None)
        tool_search_enabled = bool(getattr(ts_cfg, "enabled", False))

        # Resolve promoted names with catalog-hash scoping (matches the runtime
        # middleware). Precompute the MCP subset once: it feeds both the hash
        # check and the per-tool classification.
        mcp_tools = [tool for tool in all_tools if is_mcp_tool(tool)]
        promoted_names = _effective_promoted_names(promoted, mcp_tools) if tool_search_enabled else frozenset()

        system_active = 0
        mcp_active = 0
        mcp_deferred = 0
        for tool in all_tools:
            tokens = _approx_tool_schema_tokens(tool, app_config)
            name = getattr(tool, "name", None) or ""
            is_mcp = is_mcp_tool(tool)
            # A promoted tool has its full schema bound (active); only still-deferred
            # MCP tools feed the reserved *_deferred rows. Stale promoted names from
            # catalog drift simply match no tool here, so they cannot misclassify.
            is_deferred = tool_search_enabled and is_mcp and name not in promoted_names
            if is_deferred:
                mcp_deferred += tokens
            elif is_mcp:
                mcp_active += tokens
            else:
                system_active += tokens
        return system_active, mcp_active, mcp_deferred
    except Exception:
        logger.warning("Failed to enumerate tools for context-usage breakdown", exc_info=True)
        return 0, 0, 0


def _compute_context_counts(
    messages: list[Any],
    app_config: Any,
    model_name: str | None,
    runtime: dict[str, Any],
    agent_name: str | None,
    promoted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render and count all synchronous context components in a worker thread."""
    from deerflow.config.agents_config import load_agent_config
    from deerflow.runtime.user_context import get_effective_user_id

    user_id = get_effective_user_id()
    agent_config = None
    if agent_name:
        try:
            agent_config = load_agent_config(agent_name, user_id=user_id)
        except Exception:
            logger.warning("Failed to load custom-agent config for context usage", exc_info=True)

    available_skills = set(agent_config.skills) if agent_config and agent_config.skills is not None else None
    tool_groups = agent_config.tool_groups if agent_config else None
    subagents_cfg = getattr(app_config, "subagents", None)
    subagent_enabled = bool(runtime.get("subagent_enabled", getattr(subagents_cfg, "enabled", False)))
    max_concurrent = int(
        runtime.get(
            "max_concurrent_subagents",
            getattr(subagents_cfg, "max_concurrent_subagents", 3),
        )
    )

    messages_tokens, memory_tokens = _count_checkpoint_tokens(messages, app_config, model_name=model_name)
    skills_tokens = _count_skills_section(app_config, available_skills, user_id)
    custom_agents_tokens = _count_subagent_section(
        app_config,
        enabled=subagent_enabled,
        max_concurrent=max_concurrent,
    )
    system_prompt_tokens = _count_system_prompt(
        app_config,
        agent_name=agent_name,
        available_skills=available_skills,
        user_id=user_id,
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent,
        skills_tokens=skills_tokens,
        subagent_tokens=custom_agents_tokens,
    )
    system_tools_active, mcp_tools_active, mcp_tools_deferred = _split_tools(
        app_config,
        model_name,
        tool_groups=tool_groups,
        subagent_enabled=subagent_enabled,
        promoted=promoted,
    )
    model_cfg = app_config.get_model_config(model_name) if model_name else None
    max_context_tokens = int(model_cfg.context_window) if model_cfg is not None and getattr(model_cfg, "context_window", None) else None
    return {
        "max_context_tokens": max_context_tokens,
        "messages_tokens": messages_tokens,
        "system_prompt_tokens": system_prompt_tokens,
        "skills_tokens": skills_tokens,
        "custom_agents_tokens": custom_agents_tokens,
        "memory_tokens": memory_tokens,
        "system_tools_active": system_tools_active,
        "mcp_tools_active": mcp_tools_active,
        "mcp_tools_deferred": mcp_tools_deferred,
        "summarization_trigger": _summarization_trigger_tokens(app_config),
    }


def _summarization_trigger_tokens(app_config: Any) -> int | None:
    """Return the token-based summarization trigger, or ``None`` if not set."""
    try:
        summarization = getattr(app_config, "summarization", None)
        if summarization is None or not getattr(summarization, "enabled", False):
            return None
        configured = getattr(summarization, "trigger", None)
        triggers = configured if isinstance(configured, (list, tuple)) else [configured] if configured is not None else []
        for trig in triggers:
            if isinstance(trig, dict):
                ttype = trig.get("type")
                tvalue = trig.get("value")
            else:
                ttype = getattr(trig, "type", None)
                tvalue = getattr(trig, "value", None)
            if ttype == "tokens" and isinstance(tvalue, int) and tvalue > 0:
                return int(tvalue)
    except Exception:
        logger.warning("Failed to read summarization trigger for context usage", exc_info=True)
    return None


def build_context_usage_payload(
    *,
    max_context_tokens: int | None,
    messages_tokens: int,
    system_prompt_tokens: int,
    skills_tokens: int,
    custom_agents_tokens: int,
    memory_tokens: int,
    system_tools_active: int,
    mcp_tools_active: int,
    mcp_tools_deferred: int,
    summarization_trigger: int | None,
) -> dict[str, Any]:
    """Assemble the response payload from individual counts.

    Factored out from :func:`build_context_usage` so unit tests can drive the
    payload assembly without touching the checkpointer / config plumbing.
    """
    raw_counts: dict[str, int] = {
        "messages": messages_tokens,
        "system_prompt": system_prompt_tokens,
        "skills": skills_tokens,
        "custom_agents": custom_agents_tokens,
        "memory_files": memory_tokens,
        "system_tools": system_tools_active,
        "mcp_tools": mcp_tools_active,
        "mcp_tools_deferred": mcp_tools_deferred,
    }

    used_tokens = sum(v for k, v in raw_counts.items() if k in _ACTIVE_KEYS)

    # Autocompact buffer = headroom we keep above the trigger (i.e. window − trigger).
    # We only show it when both the trigger and the window are known, and the
    # buffer is positive.
    autocompact_buffer = 0
    if max_context_tokens and summarization_trigger and max_context_tokens > summarization_trigger:
        autocompact_buffer = max_context_tokens - summarization_trigger
    raw_counts["autocompact_buffer"] = autocompact_buffer

    # Free space is whatever is left of the window after every other row.
    free_space = 0
    if max_context_tokens:
        non_free_total = sum(raw_counts.values())
        free_space = max(0, max_context_tokens - non_free_total)
    raw_counts["free_space"] = free_space

    breakdown = [{"key": key, "tokens": raw_counts[key], "active": key in _ACTIVE_KEYS} for key in _BREAKDOWN_ORDER if raw_counts.get(key, 0) > 0]

    percentage: float | None = None
    if max_context_tokens and max_context_tokens > 0:
        percentage = round(used_tokens / max_context_tokens * 100, 1)

    return {
        "max_context_tokens": max_context_tokens,
        "used_tokens": used_tokens,
        "percentage": percentage,
        "breakdown": breakdown,
    }


def _cache_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=repr)


def _context_count_cache_key(
    *,
    thread_id: str,
    checkpoint_token: str,
    app_config: Any,
    model_name: str | None,
    runtime: dict[str, Any],
    agent_name: str | None,
    user_id: str,
    promoted: dict[str, Any] | None,
) -> _ContextCountCacheKey:
    return (
        thread_id,
        checkpoint_token,
        str(id(app_config)),
        model_name or "",
        agent_name or "",
        user_id,
        _cache_json(runtime),
        _cache_json(promoted),
    )


async def _run_context_count(
    messages: list[Any],
    app_config: Any,
    model_name: str | None,
    runtime: dict[str, Any],
    agent_name: str | None,
    promoted: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run one render on a small dedicated executor with ContextVars preserved."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(
        context.run,
        _compute_context_counts,
        messages,
        app_config,
        model_name,
        runtime,
        agent_name,
        promoted,
    )
    return await loop.run_in_executor(_get_context_count_executor(), call)


def _finish_context_count(cache_key: _ContextCountCacheKey, task: asyncio.Task[dict[str, Any]]) -> None:
    if _CONTEXT_COUNT_INFLIGHT.get(cache_key) is task:
        _CONTEXT_COUNT_INFLIGHT.pop(cache_key, None)
    if task.cancelled():
        return
    try:
        counts = task.result()
    except Exception:
        # Retrieving the exception prevents an unobserved-task warning when the
        # only request awaiting this task already timed out. The request path
        # logs failures that complete before its timeout.
        return
    _CONTEXT_COUNT_CACHE[cache_key] = counts
    _CONTEXT_COUNT_CACHE.move_to_end(cache_key)
    while len(_CONTEXT_COUNT_CACHE) > _CONTEXT_COUNT_CACHE_SIZE:
        _CONTEXT_COUNT_CACHE.popitem(last=False)


async def _get_context_counts(
    cache_key: _ContextCountCacheKey,
    messages: list[Any],
    app_config: Any,
    model_name: str | None,
    runtime: dict[str, Any],
    agent_name: str | None,
    promoted: dict[str, Any] | None,
    *,
    timeout_seconds: float = _CONTEXT_COUNT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return per-turn counts, reusing one tracked worker after waiter timeouts."""
    cached = _CONTEXT_COUNT_CACHE.get(cache_key)
    if cached is not None:
        _CONTEXT_COUNT_CACHE.move_to_end(cache_key)
        return cached

    task = _CONTEXT_COUNT_INFLIGHT.get(cache_key)
    if task is None:
        task = asyncio.create_task(
            _run_context_count(
                messages,
                app_config,
                model_name,
                runtime,
                agent_name,
                promoted,
            )
        )
        _CONTEXT_COUNT_INFLIGHT[cache_key] = task
        task.add_done_callback(functools.partial(_finish_context_count, cache_key))

    # Shielding keeps the tracked worker alive after this request times out.
    # A subsequent invalidation/refetch for the same checkpoint reuses it
    # instead of leaking another default-executor thread.
    return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)


async def build_context_usage(request: Request, thread_id: str, run_store: Any) -> dict[str, Any] | None:
    """Compute the full context-usage breakdown for ``thread_id``.

    Returns ``None`` when the checkpointer is unavailable or fails entirely —
    callers should treat that as "context usage is unknown for this request"
    and omit the field from the response.
    """
    try:
        checkpointer = get_checkpointer(request)
    except HTTPException:
        return None

    try:
        app_config = get_config()
    except HTTPException:
        app_config = None

    try:
        messages, promoted, checkpoint_token = await _load_checkpoint_messages(checkpointer, thread_id)
    except Exception:
        logger.warning("Failed to load checkpoint for thread %s", thread_id, exc_info=True)
        return None
    if app_config is None:
        messages_tokens, memory_tokens = await asyncio.to_thread(_count_checkpoint_tokens, messages, None)
        return build_context_usage_payload(
            max_context_tokens=None,
            messages_tokens=messages_tokens,
            system_prompt_tokens=0,
            skills_tokens=0,
            custom_agents_tokens=0,
            memory_tokens=memory_tokens,
            system_tools_active=0,
            mcp_tools_active=0,
            mcp_tools_deferred=0,
            summarization_trigger=None,
        )

    model_name, runtime = await _resolve_thread_runtime(run_store, thread_id, app_config)
    agent_name = await _resolve_thread_agent_name(request, thread_id)
    if not agent_name:
        runtime_agent_name = runtime.get("agent_name")
        agent_name = runtime_agent_name if isinstance(runtime_agent_name, str) else None

    from deerflow.runtime.user_context import get_effective_user_id

    cache_key = _context_count_cache_key(
        thread_id=thread_id,
        checkpoint_token=checkpoint_token,
        app_config=app_config,
        model_name=model_name,
        runtime=runtime,
        agent_name=agent_name,
        user_id=get_effective_user_id(),
        promoted=promoted,
    )

    try:
        counts = await _get_context_counts(
            cache_key,
            messages,
            app_config,
            model_name,
            runtime,
            agent_name,
            promoted,
        )
    except TimeoutError:
        logger.warning("Context-usage calculation timed out for thread %s", thread_id)
        return None
    except Exception:
        logger.warning("Context-usage calculation failed for thread %s", thread_id, exc_info=True)
        return None

    return build_context_usage_payload(**counts)
