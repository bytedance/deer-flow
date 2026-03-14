"""Tests for sandbox provider singleton thread safety and lifecycle."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.sandbox.sandbox_provider import (
    get_sandbox_provider,
    reset_sandbox_provider,
    set_sandbox_provider,
    shutdown_sandbox_provider,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_sandbox_provider()
    yield
    reset_sandbox_provider()


@patch("src.sandbox.sandbox_provider.get_app_config")
@patch("src.sandbox.sandbox_provider.resolve_class")
class TestGetSandboxProvider:
    """Tests for get_sandbox_provider() thread safety."""

    def test_singleton_returns_same_instance(self, mock_resolve, mock_config) -> None:
        mock_cls = MagicMock()
        mock_resolve.return_value = mock_cls

        a = get_sandbox_provider()
        b = get_sandbox_provider()

        assert a is b
        mock_cls.assert_called_once()

    def test_concurrent_singleton_creation(self, mock_resolve, mock_config) -> None:
        """Spawn 10 threads that call get_sandbox_provider() — only one instance should be created."""
        mock_cls = MagicMock(side_effect=lambda **kw: (time.sleep(0.01), MagicMock())[-1])
        mock_resolve.return_value = mock_cls

        results: list = [None] * 10

        def worker(idx: int) -> None:
            results[idx] = get_sandbox_provider()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads got the same instance
        assert all(r is results[0] for r in results)
        # Class was instantiated exactly once
        assert mock_cls.call_count == 1

    def test_reset_clears_singleton(self, mock_resolve, mock_config) -> None:
        mock_cls = MagicMock(side_effect=lambda **kw: MagicMock())
        mock_resolve.return_value = mock_cls

        a = get_sandbox_provider()
        reset_sandbox_provider()
        b = get_sandbox_provider()

        assert a is not b
        assert mock_cls.call_count == 2


class TestShutdownSandboxProvider:
    """Tests for shutdown_sandbox_provider()."""

    def test_shutdown_calls_shutdown_method(self) -> None:
        mock_provider = MagicMock()
        mock_provider.shutdown = MagicMock()
        set_sandbox_provider(mock_provider)

        shutdown_sandbox_provider()

        mock_provider.shutdown.assert_called_once()

    @patch("src.sandbox.sandbox_provider.get_app_config")
    @patch("src.sandbox.sandbox_provider.resolve_class")
    def test_shutdown_clears_singleton(self, mock_resolve, mock_config) -> None:
        mock_cls = MagicMock()
        mock_resolve.return_value = mock_cls
        set_sandbox_provider(MagicMock())

        shutdown_sandbox_provider()

        # After shutdown, get_sandbox_provider creates a new instance
        new = get_sandbox_provider()
        assert new is mock_cls.return_value
