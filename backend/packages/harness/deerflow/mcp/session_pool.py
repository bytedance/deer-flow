"""Persistent MCP session pool for stateful tool calls.

When MCP tools are loaded via langchain-mcp-adapters with ``session=None``,
each tool call creates a new MCP session. For stateful servers like Playwright,
this means browser state (opened pages, filled forms) is lost between calls.

This module provides a session pool that maintains persistent MCP sessions,
scoped by ``(server_name, scope_key)`` — typically scope_key is the thread_id —
so that consecutive tool calls share the same session and server-side state.
Sessions are evicted in LRU order when the pool reaches capacity.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from typing import Any

from mcp import ClientSession

logger = logging.getLogger(__name__)


class MCPSessionPool:
    """Manages persistent MCP sessions scoped by ``(server_name, scope_key)``."""

    MAX_SESSIONS = 256
    SESSION_CLOSE_TIMEOUT = 5.0  # seconds to wait when closing a session via run_coroutine_threadsafe

    def __init__(self) -> None:
        self._entries: OrderedDict[
            tuple[str, str],
            tuple[ClientSession, asyncio.AbstractEventLoop],
        ] = OrderedDict()
        self._context_managers: dict[tuple[str, str], Any] = {}
        # threading.Lock is not bound to any event loop, so it is safe to
        # acquire from both async paths and sync/worker-thread paths.
        self._lock = threading.Lock()

    async def get_session(
        self,
        server_name: str,
        scope_key: str,
        connection: dict[str, Any],
    ) -> ClientSession:
        """Get or create a persistent MCP session.

        If an existing session was created in a different event loop (e.g.
        the sync-wrapper path), it is closed and replaced with a fresh one
        in the current loop.

        Args:
            server_name: MCP server name.
            scope_key: Isolation key (typically thread_id).
            connection: Connection configuration for ``create_session``.

        Returns:
            An initialized ``ClientSession``.
        """
        key = (server_name, scope_key)
        current_loop = asyncio.get_running_loop()

        # Phase 1: inspect/mutate the registry under the thread lock (no awaits).
        cms_to_close: list[tuple[tuple[str, str], Any]] = []
        with self._lock:
            if key in self._entries:
                session, loop = self._entries[key]
                if loop is current_loop:
                    self._entries.move_to_end(key)
                    return session
                # Session belongs to a different event loop – evict it.
                cm = self._context_managers.pop(key, None)
                self._entries.pop(key)
                if cm is not None:
                    cms_to_close.append((key, cm))

            # Evict LRU entries when at capacity.
            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key = next(iter(self._entries))
                cm = self._context_managers.pop(oldest_key, None)
                self._entries.pop(oldest_key)
                if cm is not None:
                    cms_to_close.append((oldest_key, cm))

        # Phase 2: async cleanup outside the lock so we never await while holding it.
        for close_key, cm in cms_to_close:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing MCP session %s", close_key, exc_info=True)

        from langchain_mcp_adapters.sessions import create_session

        cm = create_session(connection)
        session = await cm.__aenter__()
        await session.initialize()

        # Phase 3: register the new session under the lock.
        with self._lock:
            self._entries[key] = (session, current_loop)
            self._context_managers[key] = cm
        logger.info("Created persistent MCP session for %s/%s", server_name, scope_key)
        return session

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    async def _close_cm(self, key: tuple[str, str], cm: Any) -> None:
        """Close a single context manager (must be called WITHOUT the lock)."""
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            logger.warning("Error closing MCP session %s", key, exc_info=True)

    async def close_scope(self, scope_key: str) -> None:
        """Close all sessions for a given scope (e.g. thread_id)."""
        with self._lock:
            keys = [k for k in self._entries if k[1] == scope_key]
            cms = [(k, self._context_managers.pop(k, None)) for k in keys]
            for k in keys:
                self._entries.pop(k, None)
        for key, cm in cms:
            if cm is not None:
                await self._close_cm(key, cm)

    async def close_server(self, server_name: str) -> None:
        """Close all sessions for a given server."""
        with self._lock:
            keys = [k for k in self._entries if k[0] == server_name]
            cms = [(k, self._context_managers.pop(k, None)) for k in keys]
            for k in keys:
                self._entries.pop(k, None)
        for key, cm in cms:
            if cm is not None:
                await self._close_cm(key, cm)

    async def close_all(self) -> None:
        """Close every managed session."""
        with self._lock:
            cms = list(self._context_managers.items())
            self._context_managers.clear()
            self._entries.clear()
        for key, cm in cms:
            await self._close_cm(key, cm)

    def close_all_sync(self) -> None:
        """Close all sessions using their owning event loops (synchronous).

        Each session is closed on the loop it was created in, avoiding
        cross-loop resource leaks.  Safe to call from any thread without an
        active event loop.
        """
        with self._lock:
            entries = list(self._entries.items())
            cms = dict(self._context_managers)
            self._entries.clear()
            self._context_managers.clear()

        for key, (_, loop) in entries:
            cm = cms.get(key)
            if cm is None or loop.is_closed():
                continue
            try:
                if loop.is_running():
                    # Schedule on the owning loop from this (different) thread.
                    future = asyncio.run_coroutine_threadsafe(cm.__aexit__(None, None, None), loop)
                    future.result(timeout=self.SESSION_CLOSE_TIMEOUT)
                else:
                    loop.run_until_complete(cm.__aexit__(None, None, None))
            except Exception:
                logger.debug("Error closing MCP session %s during sync close", key, exc_info=True)


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_pool: MCPSessionPool | None = None
_pool_lock = threading.Lock()


def get_session_pool() -> MCPSessionPool:
    """Return the global session-pool singleton."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = MCPSessionPool()
    return _pool


def reset_session_pool() -> None:
    """Reset the singleton (for tests)."""
    global _pool
    _pool = None
