"""Tests for deerflow.utils.network — PortAllocator and free-port helpers.

Tests thread-safe port allocation, context-manager-based lifecycle,
concurrent allocation correctness, and the global helper functions.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure heavy dependencies are mocked before importing deerflow modules.
# ---------------------------------------------------------------------------
for _mod in ("yaml", "dotenv", "langchain", "langchain_core", "langchain_core.tools"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_harness_path = str(Path(__file__).resolve().parents[1] / "packages" / "harness")
if _harness_path not in sys.path:
    sys.path.insert(0, _harness_path)

from deerflow.utils.network import PortAllocator, get_free_port, release_port  # noqa: E402
import deerflow.utils.network as _net_mod  # noqa: E402


# ---------------------------------------------------------------------------
# PortAllocator — basic allocation
# ---------------------------------------------------------------------------


class TestPortAllocatorBasic:
    def test_allocate_returns_int(self):
        alloc = PortAllocator()
        port = alloc.allocate(start_port=50000, max_range=100)
        assert isinstance(port, int)
        assert 50000 <= port < 50100
        alloc.release(port)

    def test_allocate_marks_port_reserved(self):
        alloc = PortAllocator()
        port = alloc.allocate(start_port=50000, max_range=100)
        assert port in alloc._reserved_ports
        alloc.release(port)
        assert port not in alloc._reserved_ports

    def test_allocate_skips_reserved_ports(self):
        alloc = PortAllocator()
        p1 = alloc.allocate(start_port=50200, max_range=10)
        p2 = alloc.allocate(start_port=50200, max_range=10)
        assert p1 != p2
        alloc.release(p1)
        alloc.release(p2)

    def test_allocate_raises_when_no_port_available(self):
        alloc = PortAllocator()
        alloc._reserved_ports = set(range(60000, 60003))
        with pytest.raises(RuntimeError, match="No available port"):
            alloc.allocate(start_port=60000, max_range=3)

    def test_release_nonexistent_port_no_error(self):
        alloc = PortAllocator()
        alloc.release(99999)  # Should not raise (uses discard)


# ---------------------------------------------------------------------------
# PortAllocator — context manager
# ---------------------------------------------------------------------------


class TestPortAllocatorContext:
    def test_context_manager_allocates_and_releases(self):
        alloc = PortAllocator()
        with alloc.allocate_context(start_port=50300, max_range=10) as port:
            assert isinstance(port, int)
            assert port in alloc._reserved_ports
        assert port not in alloc._reserved_ports

    def test_context_manager_releases_on_exception(self):
        alloc = PortAllocator()
        port = None
        with pytest.raises(ValueError):
            with alloc.allocate_context(start_port=50400, max_range=10) as p:
                port = p
                raise ValueError("test error")
        assert port is not None
        assert port not in alloc._reserved_ports


# ---------------------------------------------------------------------------
# PortAllocator — thread safety
# ---------------------------------------------------------------------------


class TestPortAllocatorThreadSafety:
    def test_concurrent_allocations_no_duplicates(self):
        alloc = PortAllocator()
        results: list[int] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def allocate_port():
            try:
                port = alloc.allocate(start_port=51000, max_range=200)
                with lock:
                    results.append(port)
            except RuntimeError as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=allocate_port) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during allocation: {errors}"
        assert len(results) == len(set(results)), "Duplicate port allocations detected"

        for port in results:
            alloc.release(port)


# ---------------------------------------------------------------------------
# PortAllocator — _is_port_available
# ---------------------------------------------------------------------------


class TestIsPortAvailable:
    def test_reserved_port_not_available(self):
        alloc = PortAllocator()
        alloc._reserved_ports.add(55555)
        assert alloc._is_port_available(55555) is False

    def test_bound_port_not_available(self):
        alloc = PortAllocator()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        occupied_port = sock.getsockname()[1]
        try:
            assert alloc._is_port_available(occupied_port) is False
        finally:
            sock.close()

    def test_free_port_is_available(self):
        alloc = PortAllocator()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        free_port = sock.getsockname()[1]
        sock.close()
        assert alloc._is_port_available(free_port) is True


# ---------------------------------------------------------------------------
# Global helpers: get_free_port / release_port
# ---------------------------------------------------------------------------


class TestGlobalHelpers:
    def test_get_free_port_returns_int(self):
        port = get_free_port(start_port=52000, max_range=100)
        assert isinstance(port, int)
        release_port(port)

    def test_get_free_port_raises_when_exhausted(self):
        original = _net_mod._global_port_allocator._reserved_ports.copy()
        _net_mod._global_port_allocator._reserved_ports = set(range(59000, 59003))
        try:
            with pytest.raises(RuntimeError):
                get_free_port(start_port=59000, max_range=3)
        finally:
            _net_mod._global_port_allocator._reserved_ports = original

    def test_release_port_works(self):
        port = get_free_port(start_port=52100, max_range=50)
        assert port in _net_mod._global_port_allocator._reserved_ports
        release_port(port)
        assert port not in _net_mod._global_port_allocator._reserved_ports
