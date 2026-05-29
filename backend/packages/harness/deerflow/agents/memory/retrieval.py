"""Session memory retrieval for prompt injection.

Loads thread-scoped session memory and formats it for inclusion in system prompts.
Provides token-budgeted retrieval with in-memory LRU cache.
"""

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from deerflow.agents.memory.prompt import _count_tokens
from deerflow.config.session_memory_config import get_session_memory_config
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)

_SESSION_CACHE_MAX_SIZE = 256
_session_cache: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
_cache_lock = threading.Lock()

_DEFAULT_USER_MEMORY_TOKENS = 1500
_DEFAULT_SESSION_MEMORY_TOKENS = 1500
_DEFAULT_DOMAIN_MEMORY_TOKENS = 1000


def _cache_key(tenant: str, user_id: str | None, thread_id: str) -> tuple[str, str, str]:
    return (tenant, user_id or "", thread_id)


def invalidate_session_cache(thread_id: str, user_id: str | None = None) -> None:
    """Remove cached session memory for a specific thread.

    Called by the updater after saving to ensure stale data is not served.

    Args:
        thread_id: Thread identifier.
        user_id: Optional user identifier.
    """
    key = _cache_key(get_current_tenant_id(), user_id, thread_id)
    with _cache_lock:
        _session_cache.pop(key, None)


def _cache_get(tenant: str, user_id: str | None, thread_id: str) -> dict[str, Any] | None:
    key = _cache_key(tenant, user_id, thread_id)
    with _cache_lock:
        value = _session_cache.get(key)
        if value is not None:
            _session_cache.move_to_end(key)
        return value


def _cache_put(tenant: str, user_id: str | None, thread_id: str, data: dict[str, Any]) -> None:
    key = _cache_key(tenant, user_id, thread_id)
    with _cache_lock:
        _session_cache[key] = data
        _session_cache.move_to_end(key)
        while len(_session_cache) > _SESSION_CACHE_MAX_SIZE:
            _session_cache.popitem(last=False)


def _format_session_context(session_data: dict[str, Any], max_tokens: int) -> str:
    """Format session memory data for prompt injection.

    Args:
        session_data: Session memory data dictionary.
        max_tokens: Maximum tokens to use.

    Returns:
        Formatted session context string, or empty string if no useful data.
    """
    if not session_data:
        return ""

    sections: list[str] = []

    session_ctx = session_data.get("session_context", {})
    summary = session_ctx.get("summary", "")
    if isinstance(summary, str) and summary.strip():
        sections.append(f"Thread summary: {summary.strip()}")

    facts = session_data.get("facts", [])
    if isinstance(facts, list) and facts:
        ranked = sorted(
            (f for f in facts if isinstance(f, dict) and isinstance(f.get("content"), str) and f.get("content", "").strip()),
            key=lambda f: float(f.get("confidence", 0.0)),
            reverse=True,
        )

        fact_lines: list[str] = []
        for fact in ranked:
            content = fact.get("content", "").strip()
            if not content:
                continue
            category = str(fact.get("category", "context")).strip() or "context"
            confidence = float(fact.get("confidence", 0.0))
            source_error = fact.get("sourceError")
            if category == "correction" and isinstance(source_error, str) and source_error.strip():
                fact_lines.append(f"- [{category} | {confidence:.2f}] {content} (avoid: {source_error.strip()})")
            else:
                fact_lines.append(f"- [{category} | {confidence:.2f}] {content}")

        if fact_lines:
            sections.append("Session facts:\n" + "\n".join(fact_lines))

    if not sections:
        return ""

    result = "\n\n".join(sections)

    token_count = _count_tokens(result)
    if token_count > max_tokens:
        char_per_token = len(result) / token_count
        target_chars = int(max_tokens * char_per_token * 0.95)
        result = result[:target_chars] + "\n..."

    return result


def get_session_context(
    thread_id: str,
    user_id: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Retrieve and format session memory for prompt injection.

    Loads session memory from SessionStorage (with in-memory cache),
    formats it, and returns a string suitable for system prompt injection.

    Args:
        thread_id: Thread identifier.
        user_id: Optional user identifier.
        max_tokens: Maximum tokens to use. Defaults to config value.

    Returns:
        Formatted session context string with "Session context:" header,
        or empty string if session memory is disabled or empty.
    """
    config = get_session_memory_config()
    if not config.enabled or not config.injection_enabled:
        return ""

    if max_tokens is None:
        max_tokens = config.max_injection_tokens

    tenant = get_current_tenant_id()
    cached = _cache_get(tenant, user_id, thread_id)

    if cached is not None:
        session_data = cached
    else:
        from deerflow.agents.memory.session_storage import get_session_storage

        storage = get_session_storage()
        if storage is None:
            return ""

        start = time.monotonic()
        session_data = storage.load(thread_id, user_id=user_id)
        latency_ms = (time.monotonic() - start) * 1000
        _cache_put(tenant, user_id, thread_id, session_data)

        facts_count = len(session_data.get("facts", []))
        logger.info(
            "Session memory retrieved: tenant=%s user=%s thread=%s facts=%d latency=%.1fms",
            tenant,
            user_id or "",
            thread_id,
            facts_count,
            latency_ms,
        )

    formatted = _format_session_context(session_data, max_tokens)
    if not formatted.strip():
        return ""

    return f"Session context:\n{formatted}"


async def aget_session_context(
    thread_id: str,
    user_id: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Async version: Retrieve and format session memory for prompt injection.

    Loads session memory from SessionStorage (with in-memory cache),
    formats it, and returns a string suitable for system prompt injection.

    Args:
        thread_id: Thread identifier.
        user_id: Optional user identifier.
        max_tokens: Maximum tokens to use. Defaults to config value.

    Returns:
        Formatted session context string with "Session context:" header,
        or empty string if session memory is disabled or empty.
    """
    config = get_session_memory_config()
    if not config.enabled or not config.injection_enabled:
        return ""

    if max_tokens is None:
        max_tokens = config.max_injection_tokens

    tenant = get_current_tenant_id()
    cached = _cache_get(tenant, user_id, thread_id)

    if cached is not None:
        session_data = cached
    else:
        from deerflow.agents.memory.session_storage import get_session_storage

        storage = get_session_storage()
        if storage is None:
            return ""

        start = time.monotonic()
        session_data = await storage.aload(thread_id, user_id=user_id)
        latency_ms = (time.monotonic() - start) * 1000
        _cache_put(tenant, user_id, thread_id, session_data)

        facts_count = len(session_data.get("facts", []))
        logger.info(
            "Session memory retrieved: tenant=%s user=%s thread=%s facts=%d latency=%.1fms",
            tenant,
            user_id or "",
            thread_id,
            facts_count,
            latency_ms,
        )

    formatted = _format_session_context(session_data, max_tokens)
    if not formatted.strip():
        return ""

    return f"Session context:\n{formatted}"


async def acompose_memory_for_prompt(
    thread_id: str,
    user_id: str | None = None,
    agent_name: str | None = None,
    user_memory_tokens: int = _DEFAULT_USER_MEMORY_TOKENS,
    session_memory_tokens: int = _DEFAULT_SESSION_MEMORY_TOKENS,
    domain_memory_tokens: int = _DEFAULT_DOMAIN_MEMORY_TOKENS,
    memory_config: Any = None,
    domain_query: str | None = None,
) -> str:
    """Async version: Merge User Memory, Session Memory, and Domain Memory into a prompt context string.

    Allocates separate token budgets for each memory layer, formats each,
    and returns the combined result with clear section headers.

    Args:
        thread_id: Thread identifier (required for session memory).
        user_id: Optional user identifier.
        agent_name: Optional agent name for per-agent user memory.
        user_memory_tokens: Token budget for User Memory.
        session_memory_tokens: Token budget for Session Memory.
        domain_memory_tokens: Token budget for Domain Memory.
        memory_config: Explicit MemoryConfig. When omitted, uses global config.
        domain_query: Optional query for domain memory retrieval. If None, uses
            thread_id as fallback query.

    Returns:
        Combined memory context string, or empty string if all are empty/disabled.
    """
    parts: list[str] = []

    from deerflow.agents.memory import format_memory_for_injection
    from deerflow.agents.memory.updater import aget_memory_data
    from deerflow.config.memory_config import get_memory_config

    user_config = memory_config if memory_config is not None else get_memory_config()
    if user_config.enabled and user_config.injection_enabled:
        user_data = await aget_memory_data(agent_name, user_id=user_id)
        user_content = format_memory_for_injection(user_data, max_tokens=user_memory_tokens)
        if user_content.strip():
            parts.append(f"User context:\n{user_content}")

    session_content = await aget_session_context(
        thread_id=thread_id,
        user_id=user_id,
        max_tokens=session_memory_tokens,
    )
    if session_content.strip():
        parts.append(session_content)

    from deerflow.agents.memory.domain_retrieval import get_domain_context
    from deerflow.config.domain_memory_config import get_domain_memory_config

    domain_config = get_domain_memory_config()
    if domain_config.enabled and domain_config.injection_enabled:
        query = domain_query or thread_id
        domain_content = get_domain_context(
            query=query,
            max_tokens=domain_memory_tokens,
        )
        if domain_content.strip():
            parts.append(domain_content)

    if not parts:
        return ""

    return "\n\n".join(parts)
