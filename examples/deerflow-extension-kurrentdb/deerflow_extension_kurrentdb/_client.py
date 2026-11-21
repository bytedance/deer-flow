"""Lazy, memoized KurrentDB clients.

Constructing ``KurrentDBClient`` connects, so nothing here runs at import or
install time. One client is kept per settings value; the async client is also
keyed by event loop, because its gRPC channel belongs to the loop it connected on.
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from collections.abc import Awaitable, Callable
from functools import cache

from kurrentdbclient import AsyncKurrentDBClient, KurrentDBClient

from ._settings import KurrentSettings

_lock = threading.Lock()
_sync_clients: dict[KurrentSettings, KurrentDBClient] = {}
_async_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[KurrentSettings, asyncio.Task[AsyncKurrentDBClient]]] = weakref.WeakKeyDictionary()


@cache
def sync_client_factory(settings: KurrentSettings) -> Callable[[], KurrentDBClient]:
    def get_client() -> KurrentDBClient:
        with _lock:
            client = _sync_clients.get(settings)
            if client is None:
                client = _sync_clients[settings] = KurrentDBClient(settings.connection_string)
            return client

    return get_client


@cache
def async_client_factory(settings: KurrentSettings) -> Callable[[], Awaitable[AsyncKurrentDBClient]]:
    async def get_client() -> AsyncKurrentDBClient:
        loop = asyncio.get_running_loop()
        per_loop = _async_clients.setdefault(loop, {})
        task = per_loop.get(settings)
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            # Share one connect among concurrent callers; a failed connect is retried next call.
            task = per_loop[settings] = loop.create_task(_connect(settings))
        return await asyncio.shield(task)

    return get_client


async def _connect(settings: KurrentSettings) -> AsyncKurrentDBClient:
    client = AsyncKurrentDBClient(settings.connection_string)
    await client.connect()
    return client


def reset_clients() -> None:
    """Forget memoized clients without closing them (tests and reconfiguration)."""
    with _lock:
        _sync_clients.clear()
        _async_clients.clear()
