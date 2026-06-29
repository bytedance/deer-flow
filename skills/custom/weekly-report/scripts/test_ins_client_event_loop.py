"""Tests for ins/client.py shared HTTP client event loop handling.

These tests verify that the shared HTTP client correctly handles event loop
changes, which was the root cause of "RuntimeError: Event loop is closed"
errors in weekly report generation.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add features-tool to path for imports
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parents[2] / "features-tool"
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))

import pytest

from ins.client import (
    _get_current_loop_id,
    _shared_http_client,
    _shared_http_client_loop_id,
    get_shared_http_client,
)


class TestSharedHttpClientEventLoop:
    """Test shared HTTP client behavior across event loops."""

    def test_get_current_loop_id_inside_loop(self):
        """_get_current_loop_id returns the loop id when inside a running loop."""
        async def check():
            loop_id = _get_current_loop_id()
            assert loop_id is not None
            assert loop_id == id(asyncio.get_running_loop())

        asyncio.run(check())

    def test_get_current_loop_id_outside_loop(self):
        """_get_current_loop_id returns None when no loop is running."""
        assert _get_current_loop_id() is None

    def test_client_created_lazily(self):
        """Client is created on first access."""
        import ins.client as client_module

        # Save and reset state
        old_client = client_module._shared_http_client
        old_loop_id = client_module._shared_http_client_loop_id
        try:
            client_module._shared_http_client = None
            client_module._shared_http_client_loop_id = None

            async def create_and_check():
                client = get_shared_http_client()
                assert client is not None
                assert not client.is_closed
                assert client_module._shared_http_client is client

            asyncio.run(create_and_check())
        finally:
            # Restore state
            client_module._shared_http_client = old_client
            client_module._shared_http_client_loop_id = old_loop_id

    def test_client_recreated_when_loop_changes(self):
        """Client is recreated when called from a different event loop.

        This is the core fix for "Event loop is closed" error.
        """
        import ins.client as client_module

        # Save and reset state
        old_client = client_module._shared_http_client
        old_loop_id = client_module._shared_http_client_loop_id
        try:
            client_module._shared_http_client = None
            client_module._shared_http_client_loop_id = None

            first_client = None
            second_client = None

            # First event loop
            async def first_loop():
                nonlocal first_client
                first_client = get_shared_http_client()
                first_loop_id = client_module._shared_http_client_loop_id
                assert first_loop_id is not None

            asyncio.run(first_loop())
            # Event loop is now closed

            # Second event loop (simulates second asyncio.run() call)
            async def second_loop():
                nonlocal second_client
                second_client = get_shared_http_client()
                second_loop_id = client_module._shared_http_client_loop_id
                assert second_loop_id is not None

            asyncio.run(second_loop())

            # Clients should be different instances because loop changed
            assert first_client is not second_client, (
                "Client should be recreated when event loop changes"
            )

        finally:
            # Restore state
            client_module._shared_http_client = old_client
            client_module._shared_http_client_loop_id = old_loop_id

    def test_multiple_asyncio_run_calls_work(self):
        """Multiple asyncio.run() calls don't cause Event loop is closed errors.

        This simulates the weekly report flow where fetch_week_with_provenance
        is called twice (current week + compare week).
        """
        import ins.client as client_module

        # Save and reset state
        old_client = client_module._shared_http_client
        old_loop_id = client_module._shared_http_client_loop_id
        try:
            client_module._shared_http_client = None
            client_module._shared_http_client_loop_id = None

            results = []

            async def make_request(request_num: int):
                client = get_shared_http_client()
                # Verify client is usable (not bound to closed loop)
                assert not client.is_closed
                results.append(request_num)

            # Simulate multiple calls like in weekly report
            asyncio.run(make_request(1))
            asyncio.run(make_request(2))
            asyncio.run(make_request(3))

            assert results == [1, 2, 3]

        finally:
            # Restore state
            client_module._shared_http_client = old_client
            client_module._shared_http_client_loop_id = old_loop_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
