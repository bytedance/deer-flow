"""Compute a per-category breakdown of the context window usage for a thread.

The breakdown mirrors the layout shown by Claude Code's context indicator:
messages, system prompt, skills, system / MCP tools (active + deferred),
custom agents (subagents), memory injection, the summarization headroom we
treat as an autocompact buffer, and finally the free space left over.

Every category is computed in isolation in its own ``try`` block — if any
single component fails to render we still return the rest, never the whole
endpoint. The numbers are approximate (``count_tokens_approximately`` /
``chars // 4``); they intentionally do not call the model's real tokenizer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException, Request

from app.gateway.deps import get_checkpointer, get_config

logger = logging.getLogger(__name__)


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
    "system_tools_deferred",
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


def _approx_tool_schema_tokens(tool: Any) -> int:
    """Approximate the tokens a tool's OpenAI schema occupies in the prompt."""
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        schema = convert_to_openai_tool(tool)
        return _approx_text_tokens(json.dumps(schema, ensure_ascii=False))
    except Exception:
        # Fall back to a description-only estimate so a single broken tool
        # never causes the whole breakdown to collapse.
        name = getattr(tool, "name", "") or ""
        description = getattr(tool, "description", "") or ""
        return _approx_text_tokens(f"{name}\n{description}")


async def _resolve_thread_model_name(run_store: Any, thread_id: str, app_config: Any) -> str | None:
    """Pick the model name a thread is currently using.

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
        if isinstance(name, str) and name:
            return name
    models = getattr(app_config, "models", None) or []
    return models[0].name if models else None


async def _count_message_tokens(checkpointer: Any, thread_id: str) -> int:
    """Approximate the tokens of the messages currently in the checkpoint."""
    from langchain_core.messages.utils import count_tokens_approximately

    try:
        checkpoint_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    except Exception:
        logger.warning("Failed to load checkpoint for thread %s", thread_id, exc_info=True)
        raise

    if checkpoint_tuple is None:
        return 0
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    messages = channel_values.get("messages") or []
    if not messages:
        return 0
    return int(count_tokens_approximately(messages))


def _count_skills_section(app_config: Any) -> int:
    try:
        from deerflow.agents.lead_agent.prompt import get_skills_prompt_section

        return _approx_text_tokens(get_skills_prompt_section(app_config=app_config))
    except Exception:
        logger.warning("Failed to render skills prompt section", exc_info=True)
        return 0


def _count_subagent_section(app_config: Any) -> int:
    """Tokens for the subagent / custom-agents section when enabled."""
    try:
        subagents_cfg = getattr(app_config, "subagents", None)
        if subagents_cfg is None or not getattr(subagents_cfg, "enabled", False):
            return 0
        from deerflow.agents.lead_agent.prompt import _build_subagent_section  # noqa: SLF001

        max_concurrent = getattr(subagents_cfg, "max_concurrent_subagents", 3)
        return _approx_text_tokens(_build_subagent_section(max_concurrent, app_config=app_config))
    except Exception:
        logger.warning("Failed to render subagent prompt section", exc_info=True)
        return 0


def _count_system_prompt(app_config: Any) -> int:
    """System prompt tokens *excluding* skills/subagent/deferred-tools sections.

    Those breakdown items get their own row, so we render the full prompt and
    subtract the per-row pieces to avoid double-counting.
    """
    try:
        from deerflow.agents.lead_agent.prompt import (
            apply_prompt_template,
            get_deferred_tools_prompt_section,
            get_skills_prompt_section,
        )

        subagents_cfg = getattr(app_config, "subagents", None)
        subagent_enabled = bool(getattr(subagents_cfg, "enabled", False))
        max_concurrent = getattr(subagents_cfg, "max_concurrent_subagents", 3) if subagents_cfg else 3

        full = apply_prompt_template(
            subagent_enabled=subagent_enabled,
            max_concurrent_subagents=max_concurrent,
            app_config=app_config,
        )
        full_tokens = _approx_text_tokens(full)

        # Pieces accounted for under their own breakdown rows.
        skills_tokens = _approx_text_tokens(get_skills_prompt_section(app_config=app_config))
        deferred_section_tokens = _approx_text_tokens(get_deferred_tools_prompt_section(app_config=app_config))
        subagent_section_tokens = _count_subagent_section(app_config) if subagent_enabled else 0

        return max(0, full_tokens - skills_tokens - deferred_section_tokens - subagent_section_tokens)
    except Exception:
        logger.warning("Failed to render system prompt for token breakdown", exc_info=True)
        return 0


def _count_memory_files(app_config: Any) -> int:
    try:
        from deerflow.agents.lead_agent.prompt import _get_memory_context  # noqa: SLF001

        return _approx_text_tokens(_get_memory_context(app_config=app_config))
    except Exception:
        logger.warning("Failed to render memory context", exc_info=True)
        return 0


def _split_tools(app_config: Any, model_name: str | None) -> tuple[int, int, int, int]:
    """Return (system_tools_active, mcp_tools_active, system_tools_deferred, mcp_tools_deferred).

    Active vs deferred is determined by the tool_search deferred registry.
    System vs MCP is determined by name-matching against the MCP cache —
    :func:`deerflow.mcp.cache.get_cached_mcp_tools` returns the same snapshot
    that :func:`deerflow.tools.get_available_tools` itself consumes
    internally, so a single cache read is enough to classify every tool.
    Skipping the redundant ``ExtensionsConfig.from_file()`` here avoids extra
    file I/O and INFO-level log noise on every ``GET /token-usage`` poll.
    """
    try:
        from deerflow.tools.builtins.tool_search import get_deferred_registry
        from deerflow.tools.tools import get_available_tools

        subagents_cfg = getattr(app_config, "subagents", None)
        subagent_enabled = bool(getattr(subagents_cfg, "enabled", False))

        # Snapshot MCP names BEFORE `get_available_tools` so we have a stable
        # set to classify against. The cache is mtime-invalidated so this is
        # cheap on a hit; if MCP is currently disabled the cache simply
        # returns an empty list.
        mcp_names: set[str] = set()
        try:
            from deerflow.mcp.cache import get_cached_mcp_tools

            mcp_names = {t.name for t in get_cached_mcp_tools() if getattr(t, "name", None)}
        except Exception:
            mcp_names = set()

        all_tools = get_available_tools(
            model_name=model_name,
            subagent_enabled=subagent_enabled,
            app_config=app_config,
        )

        deferred_registry = get_deferred_registry()
        deferred_names: set[str] = deferred_registry.deferred_names if deferred_registry is not None else set()

        system_active = 0
        mcp_active = 0
        system_deferred = 0
        mcp_deferred = 0
        for tool in all_tools:
            name = getattr(tool, "name", None) or ""
            tokens = _approx_tool_schema_tokens(tool)
            is_mcp = name in mcp_names
            is_deferred = name in deferred_names
            if is_deferred:
                if is_mcp:
                    mcp_deferred += tokens
                else:
                    system_deferred += tokens
            else:
                if is_mcp:
                    mcp_active += tokens
                else:
                    system_active += tokens
        return system_active, mcp_active, system_deferred, mcp_deferred
    except Exception:
        logger.warning("Failed to enumerate tools for context-usage breakdown", exc_info=True)
        return 0, 0, 0, 0


def _summarization_trigger_tokens(app_config: Any) -> int | None:
    """Return the token-based summarization trigger, or ``None`` if not set."""
    summarization = getattr(app_config, "summarization", None)
    if summarization is None or not getattr(summarization, "enabled", False):
        return None
    triggers = getattr(summarization, "trigger", None) or []
    for trig in triggers:
        if isinstance(trig, dict):
            ttype = trig.get("type")
            tvalue = trig.get("value")
        else:
            ttype = getattr(trig, "type", None)
            tvalue = getattr(trig, "value", None)
        if ttype == "tokens" and isinstance(tvalue, int) and tvalue > 0:
            return int(tvalue)
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
    system_tools_deferred: int,
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
        "system_tools_deferred": system_tools_deferred,
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
        messages_tokens = await _count_message_tokens(checkpointer, thread_id)
    except Exception:
        return None

    max_context_tokens: int | None = None
    skills_tokens = 0
    custom_agents_tokens = 0
    memory_tokens = 0
    system_prompt_tokens = 0
    system_tools_active = 0
    mcp_tools_active = 0
    system_tools_deferred = 0
    mcp_tools_deferred = 0
    summarization_trigger: int | None = None

    if app_config is not None:
        model_name = await _resolve_thread_model_name(run_store, thread_id, app_config)
        if model_name:
            model_cfg = app_config.get_model_config(model_name)
            if model_cfg is not None and getattr(model_cfg, "context_window", None):
                max_context_tokens = int(model_cfg.context_window)

        skills_tokens = _count_skills_section(app_config)
        custom_agents_tokens = _count_subagent_section(app_config)
        memory_tokens = _count_memory_files(app_config)
        system_prompt_tokens = _count_system_prompt(app_config)
        system_tools_active, mcp_tools_active, system_tools_deferred, mcp_tools_deferred = _split_tools(app_config, model_name)
        summarization_trigger = _summarization_trigger_tokens(app_config)

    return build_context_usage_payload(
        max_context_tokens=max_context_tokens,
        messages_tokens=messages_tokens,
        system_prompt_tokens=system_prompt_tokens,
        skills_tokens=skills_tokens,
        custom_agents_tokens=custom_agents_tokens,
        memory_tokens=memory_tokens,
        system_tools_active=system_tools_active,
        mcp_tools_active=mcp_tools_active,
        system_tools_deferred=system_tools_deferred,
        mcp_tools_deferred=mcp_tools_deferred,
        summarization_trigger=summarization_trigger,
    )
