"""mem0 memory backend -- a stateless HTTP MemoryManager.

All state lives server-side in mem0 (dedup, extraction, storage): this backend
keeps no queue, watermark, or cache, so it is safe for multi-worker Gateway
deployments. Identity maps 1:1: (user_id, agent_name) -> mem0 (user_id,
agent_id); thread_id -> mem0 run_id.

Default-bucket semantics: an omitted ``agent_name`` selects the *default*
fact bucket, not the user's whole memory -- mirroring DeerMem's reserved
``__default__`` bucket. In mem0 the default bucket is represented by the
absence of ``agent_id`` (main-agent writes have never carried one), so reads
with no ``agent_name`` post-filter unscoped records out of the user-wide
listing; mem0's filter syntax cannot express agent-id absence server-side.
``clear_memory`` is the exception: ``agent_name=None`` clears the user's whole
memory, per the MemoryManager contract.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Literal

from pydantic import PrivateAttr

# ABC contract -- the ONE allowed `from deerflow` import in this backend folder.
from deerflow.agents.memory.manager import MemoryManager, MemoryManagerError

from .client import Mem0APIError, Mem0Client
from .config import Mem0Config
from .message_filtering import extract_message_text, filter_messages_for_memory

logger = logging.getLogger(__name__)

_ROLE_MAP = {"human": "user", "ai": "assistant"}

# Default-scope reads post-filter the user-wide listing down to unscoped
# records, so over-fetch: a top_k-sized window would otherwise fill up with
# other agents' facts and starve the default bucket's injection/view.
_DEFAULT_SCOPE_OVERFETCH = 10


def _default_scope_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only default-bucket records (no ``agent_id``).

    The default bucket is represented by agent-id absence, which mem0's
    filter syntax cannot express, so the scope is applied client-side. This
    keeps existing unscoped records in the default view by construction.
    """
    return [record for record in records if not record.get("agent_id")]


def _build_filters(
    *,
    user_id: str | None = None,
    agent_name: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Build a mem0 ``filters`` object from the available identity parts.

    Returns None when no entity id is available (mem0 requires at least one).
    """
    parts: list[dict[str, Any]] = []
    if user_id:
        parts.append({"user_id": user_id})
    if agent_name:
        parts.append({"agent_id": agent_name})
    if run_id:
        parts.append({"run_id": run_id})
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"AND": parts}


def _to_fact(record: dict[str, Any]) -> dict[str, Any]:
    """Map a mem0 record to the backend-neutral fact shape consumed by the
    host (agents/memory/tools.py): id/content/category/confidence/createdAt/
    source. mem0's relevance score doubles as confidence."""
    categories = record.get("categories") or []
    metadata = record.get("metadata") or {}
    return {
        "id": str(record.get("id", "")),
        "content": str(record.get("memory", "")),
        "category": str(categories[0]) if categories else "context",
        "confidence": float(record.get("score") or 0.0),
        "createdAt": str(record.get("created_at", "")),
        "source": str(metadata.get("source", "")),
    }


class Mem0Manager(MemoryManager):
    """MemoryManager backed by the mem0 Platform API (or compatible server)."""

    # search() is overridden below -> flag must be True (contract invariant);
    # this also enables memory mode="tool".
    supports_search: ClassVar[bool] = True
    # mem0 extracts/deduplicates facts from full conversations through add();
    # its fact CRUD hooks are intentionally unsupported, so tool mode retains
    # passive writes while exposing query-aware search.
    requires_passive_writes_in_tool_mode: ClassVar[bool] = True

    _config: Mem0Config = PrivateAttr()
    _client: Any = PrivateAttr(default=None)  # Mem0Client; tests inject a fake

    def model_post_init(self, __context: Any) -> None:
        self._config = Mem0Config.from_backend_config(self.backend_config)
        self._client = Mem0Client(
            base_url=self._config.base_url,
            api_key=self._config.resolve_api_key(),
            timeout_seconds=self._config.timeout_seconds,
        )

    @classmethod
    def from_config(
        cls,
        backend_config: dict[str, Any] | None = None,
        *,
        mode: Literal["middleware", "tool"] = "middleware",
        **host_hooks: Any,
    ) -> Mem0Manager:
        """Build the manager; ``fail_fast`` startup policy auth-checks via ping."""
        mgr = cls(backend_config=backend_config, mode=mode)
        if mgr._config.startup_policy == "fail_fast":
            mgr._client.ping()
        return mgr

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    # ── Error policies ───────────────────────────────────────────────────
    def _read_or_fallback(self, fallback: Any, fn: Any) -> Any:
        try:
            return fn()
        except Mem0APIError as e:
            if self._config.read_policy == "fail_open":
                logger.warning("mem0 read failed (%s); continuing without memory", e)
                return fallback
            raise MemoryManagerError(f"mem0 read failed: {e}") from e

    def _write_or_drop(self, fn: Any) -> None:
        try:
            fn()
        except Mem0APIError as e:
            if self._config.write_policy == "log_and_drop":
                logger.warning("mem0 write failed (%s); dropping update", e)
                return
            raise MemoryManagerError(f"mem0 write failed: {e}") from e

    # ── Tier 1: write ────────────────────────────────────────────────────
    def add(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """Submit the filtered conversation to mem0 for server-side extraction.

        Fire-and-forget: mem0 processes asynchronously (response event_id is
        not polled). ``thread_id`` maps to mem0 ``run_id`` and always satisfies
        mem0's at-least-one-entity-id requirement.
        """
        kept = filter_messages_for_memory(messages)
        payload = [{"role": _ROLE_MAP[getattr(m, "type", "")], "content": extract_message_text(m).strip()} for m in kept if getattr(m, "type", "") in _ROLE_MAP]
        payload = [p for p in payload if p["content"]]
        if not payload:
            return
        self._write_or_drop(
            lambda: self._client.add_memories(
                messages=payload,
                user_id=user_id,
                agent_id=agent_name,
                run_id=thread_id,
            )
        )

    async def aadd(
        self,
        thread_id: str,
        messages: list[Any],
        *,
        agent_name: str | None = None,
        user_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.add,
            thread_id,
            messages,
            agent_name=agent_name,
            user_id=user_id,
            trace_id=trace_id,
        )

    # ── Tier 1: read-inject ──────────────────────────────────────────────
    def get_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Query-less recall: the contract passes no current query, so inject
        the bucket's most recent memories (top_k). Query-aware recall is
        available via search() in mode="tool"."""
        filters = _build_filters(user_id=user_id, agent_name=agent_name, run_id=thread_id)
        if filters is None:
            return ""
        top_k = self._config.top_k
        # Default scope (no agent_name) post-filters other agents' records out
        # of the user-wide listing, so fetch a wider window first.
        max_items = top_k if agent_name else top_k * _DEFAULT_SCOPE_OVERFETCH
        records = self._read_or_fallback(
            [],
            lambda: self._client.list_memories(
                filters=filters,
                page_size=min(max_items, 200),
                max_items=max_items,
            ),
        )
        if not agent_name:
            records = _default_scope_records(records)
        budget = self._config.max_injection_chars
        seen: set[str] = set()
        lines: list[str] = []
        used = 0
        shortest_line: int | None = None
        for record in records:
            rid = record.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            text = str(record.get("memory") or "").strip()
            if not text:
                continue
            line = f"- {text}"
            line_len = len(line)
            shortest_line = line_len if shortest_line is None else min(shortest_line, line_len)
            # Truncate on entry boundaries: keep only memories that fit whole
            # within the remaining budget (+1 for the joining newline), so the
            # injection never ends mid-entry with a dangling partial line. An
            # oversized entry is skipped -- a shorter later one may still fit.
            added = line_len if not lines else line_len + 1
            if used + added > budget:
                continue
            lines.append(line)
            used += added
        context = "\n".join(lines)
        if not context and shortest_line is not None:
            # Every recalled memory was longer than the configured budget.
            # Keep the entry-boundary guarantee and surface the config problem
            # with a warning rather than injecting a partial fact.
            logger.warning(
                "max_injection_chars=%d is smaller than the shortest recalled memory (%d chars); returning empty context",
                budget,
                shortest_line,
            )
        return context

    async def aget_context(
        self,
        user_id: str | None,
        *,
        agent_name: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self.get_context,
            user_id,
            agent_name=agent_name,
            thread_id=thread_id,
        )

    # ── Tier 2: search ───────────────────────────────────────────────────
    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = _build_filters(user_id=user_id, agent_name=agent_name)
        if filters is None:
            return []
        if category:
            parts = filters["AND"] if "AND" in filters else [filters]
            filters = {"AND": [*parts, {"categories": {"contains": category}}]}
        results = self._read_or_fallback(
            [],
            lambda: self._client.search_memories(
                query=query,
                filters=filters,
                top_k=top_k,
                threshold=self._config.score_threshold,
            ),
        )
        # Default scope (no agent_name): keep only unscoped records so the main
        # agent's search never recalls a custom agent's facts. The post-filter
        # can shrink the result below top_k -- over-fetching a ranked search
        # would change server-side semantics, so the shortfall is accepted.
        if not agent_name:
            results = _default_scope_records(results)
        return [_to_fact(r) for r in results]

    async def asearch(
        self,
        query: str,
        top_k: int = 5,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.search,
            query,
            top_k,
            user_id=user_id,
            agent_name=agent_name,
            category=category,
        )

    # ── Tier 2: management ───────────────────────────────────────────────
    def get_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the bucket's memory document.

        An explicit ``agent_name`` filters server-side. The default bucket
        (``agent_name=None``) is the user's unscoped records only -- mem0
        cannot filter on agent-id absence, so the user-wide listing is
        post-filtered and other agents' facts never leak into the Main
        memory view / export / status.
        """
        filters = _build_filters(user_id=user_id, agent_name=agent_name)
        if filters is None:
            return {"facts": []}
        records = self._read_or_fallback([], lambda: self._client.list_memories(filters=filters))
        if not agent_name:
            records = _default_scope_records(records)
        return {"facts": [_to_fact(r) for r in records]}

    def export_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        return self.get_memory(user_id=user_id, agent_name=agent_name)

    def clear_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Clear the bucket. agent_name=None clears the user's whole memory;
        an explicit agent clears only that agent's bucket."""
        if not user_id and not agent_name:
            return {"facts": []}
        self._write_or_drop(lambda: self._client.delete_all_memories(user_id=user_id, agent_id=agent_name, run_id=None))
        return {"facts": []}

    def delete_memory(
        self,
        *,
        user_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        if not user_id and not agent_name:
            return None
        self._write_or_drop(lambda: self._client.delete_all_memories(user_id=user_id, agent_id=agent_name, run_id=None))
