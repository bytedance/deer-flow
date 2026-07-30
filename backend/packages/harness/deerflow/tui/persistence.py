"""Shared-persistence wiring so terminal sessions show up in the Web UI.

The Web UI lists conversations from the ``threads_meta`` SQL table (filtered by
``user_id``), not from the checkpointer. An embedded run only writes the
checkpointer, so a TUI thread would be invisible in the sidebar. This module
closes that gap: it writes a ``threads_meta`` row (owned by the local default
user) into the **same** database the Gateway reads — without requiring the
Gateway process to be running.

Everything here is best-effort: when the database is memory-backed or
unavailable, the writer degrades to a no-op and the TUI keeps working.

The SQLAlchemy async engine is bound to the event loop that created it, so all
DB work runs on one long-lived background loop (``_LoopThread``) rather than a
fresh ``asyncio.run`` per call (which would bind connections to throwaway loops).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable
from typing import Any

from deerflow.runtime.user_context import DEFAULT_USER_ID


class _LoopThread:
    """A daemon thread running a single asyncio event loop for DB work."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="deerflow-tui-db", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Awaitable[Any], *, timeout: float = 15.0) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)


class ThreadMetaWriter:
    """Writes/updates ``threads_meta`` rows for the local default user.

    All methods swallow errors: persistence visibility is a convenience, never a
    reason to break the conversation.
    """

    def __init__(self, loop: _LoopThread, store: Any) -> None:
        self._loop = loop
        self._store = store
        self.user_id = DEFAULT_USER_ID

    @property
    def enabled(self) -> bool:
        return self._store is not None

    def ensure_created(self, thread_id: str, *, assistant_id: str | None = None, metadata: dict | None = None) -> None:
        if not self._store or not thread_id:
            return
        try:
            self._loop.run(self._ensure_created(thread_id, assistant_id, metadata))
        except Exception:  # noqa: BLE001 - best-effort
            pass

    async def _ensure_created(self, thread_id: str, assistant_id: str | None, metadata: dict | None) -> None:
        existing = await self._store.get(thread_id, user_id=self.user_id)
        if existing is None:
            await self._store.create(
                thread_id,
                assistant_id=assistant_id,
                user_id=self.user_id,
                metadata=metadata or {"source": "tui"},
            )

    def set_title(self, thread_id: str, title: str) -> None:
        if not self._store or not thread_id or not title:
            return
        try:
            self._loop.run(self._store.update_display_name(thread_id, title, user_id=self.user_id))
        except Exception:  # noqa: BLE001 - best-effort
            pass


def build_persistence() -> tuple[_LoopThread, ThreadMetaWriter]:
    """Initialise the shared engine on a background loop and return a writer.

    Returns a ``ThreadMetaWriter`` that is a no-op when the configured database
    backend is ``memory`` (no SQL session factory) or initialisation fails.
    """
    loop = _LoopThread()
    store = None
    try:
        from deerflow.config.app_config import get_app_config
        from deerflow.persistence.engine import get_session_factory, init_engine_from_config
        from deerflow.persistence.thread_meta import make_thread_store

        config = get_app_config()
        loop.run(init_engine_from_config(config.database))
        session_factory = get_session_factory()
        if session_factory is not None:
            store = make_thread_store(session_factory)
    except Exception:  # noqa: BLE001 - degrade to no-op writer
        store = None
    return loop, ThreadMetaWriter(loop, store)
