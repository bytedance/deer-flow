"""Regression: ``AioSandboxProvider.get()`` must not do blocking IO.

``ensure_sandbox_initialized_async`` (``sandbox/tools.py``) calls
``provider.get()`` directly on the LangGraph event loop for every sandbox tool
lookup. A prior change renewed the cross-process lease inside ``get()``
(``mkdir`` + temp-file write + ``fsync`` + ``os.replace`` via ``write_lease``),
which blocks the loop — reported on PR #4221.

Under the strict Blockbuster context (this directory's conftest), any blocking
IO reached from ``deerflow.*`` while on the event loop raises ``BlockingError``.
This anchors ``get()`` as a pure in-memory lookup; if lease renewal is put back
on this path, the test fails.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


def _make_provider(tmp_path: Path):
    """Build an ``AioSandboxProvider`` without ``__init__`` (no Docker, no threads)."""
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    provider = AioSandboxProvider.__new__(AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._shutdown_called = False
    provider._config = {"idle_timeout": 600, "replicas": 3}
    provider._backend = MagicMock()
    provider._worker_id = "worker-blockingio"
    provider._lease_base_dir = tmp_path
    return provider


async def test_get_does_no_blocking_io_on_event_loop(tmp_path):
    provider = _make_provider(tmp_path)
    provider._sandboxes["sb-blockingio"] = MagicMock()

    # If get() renews the lease (mkdir/fsync/os.replace) the strict gate raises.
    assert provider.get("sb-blockingio") is not None
