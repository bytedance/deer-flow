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

    def __init__(self) -> None:
        self._entries: OrderedDict[
            tuple[str, str],
            tuple[ClientSession, asyncio.AbstractEventLoop],
        ] = OrderedDict()
        self._context_managers: dict[tuple[str, str], Any] = {}
        self._lock = asyncio.Lock()

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

        async with self._lock:
            if key in self._entries:
                session, loop = self._entries[key]
                if loop is current_loop:
                    self._entries.move_to_end(key)
                    return session
                # Session belongs to a different event loop – close it.
                await self._close_session(key)

            # Evict oldest entries when at capacity.
            while len(self._entries) >= self.MAX_SESSIONS:
                oldest_key = next(iter(self._entries))
                await self._close_session(oldest_key)

            from langchain_mcp_adapters.sessions import create_session

            cm = create_session(connection)
            session = await cm.__aenter__()
            await session.initialize()
            self._entries[key] = (session, current_loop)
            self._context_managers[key] = cm
            logger.info("Created persistent MCP session for %s/%s", server_name, scope_key)
            return session

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    async def _close_session(self, key: tuple[str, str]) -> None:
        cm = self._context_managers.pop(key, None)
        self._entries.pop(key, None)
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing MCP session %s", key, exc_info=True)

    async def close_scope(self, scope_key: str) -> None:
        """Close all sessions for a given scope (e.g. thread_id)."""
        async with self._lock:
            keys_to_close = [k for k in self._entries if k[1] == scope_key]
            for key in keys_to_close:
                await self._close_session(key)

    async def close_server(self, server_name: str) -> None:
        """Close all sessions for a given server."""
        async with self._lock:
            keys_to_close = [k for k in self._entries if k[0] == server_name]
            for key in keys_to_close:
                await self._close_session(key)

    async def close_all(self) -> None:
        """Close every managed session."""
        async with self._lock:
            for key in list(self._context_managers.keys()):
                await self._close_session(key)


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
