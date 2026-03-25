"""Tests for network utilities."""

import socket
import threading
import time

import pytest

from deerflow.utils.network import (
    PortAllocator,
    get_free_port,
    release_port,
    _global_port_allocator,
)


class TestPortAllocator:
    """Tests for PortAllocator class."""

    def test_allocate_returns_available_port(self):
        """Port allocation should return an available port."""
        allocator = PortAllocator()
        port = allocator.allocate(start_port=65000, max_range=100)
        
        assert isinstance(port, int)
        assert 65000 <= port <= 65100
        
        # Verify port is actually available
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            with pytest.raises(OSError):
                s.bind(("0.0.0.0", port))
        
        allocator.release(port)

    def test_allocate_reserves_port(self):
        """Allocated port should be reserved and not allocated again."""
        allocator = PortAllocator()
        port1 = allocator.allocate(start_port=65000, max_range=100)
        port2 = allocator.allocate(start_port=65000, max_range=100)
        
        # Should get different ports
        assert port1 != port2
        
        allocator.release(port1)
        allocator.release(port2)

    def test_release_makes_port_available(self):
        """Released port should be available for reallocation."""
        allocator = PortAllocator()
        port = allocator.allocate(start_port=65000, max_range=100)
        allocator.release(port)
        
        # Should be able to allocate the same port again
        port2 = allocator.allocate(start_port=port, max_range=1)
        assert port2 == port
        allocator.release(port2)

    def test_allocate_raises_when_no_ports_available(self):
        """Should raise RuntimeError when no ports are available."""
        allocator = PortAllocator()
        
        # Try to allocate from a very small range that may be occupied
        with pytest.raises(RuntimeError, match="No available port found"):
            allocator.allocate(start_port=22, max_range=1)  # Port 22 is likely occupied

    def test_allocate_context_manager(self):
        """Context manager should automatically release port."""
        allocator = PortAllocator()
        
        with allocator.allocate_context(start_port=65000, max_range=100) as port:
            assert isinstance(port, int)
            # Port should be reserved
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                with pytest.raises(OSError):
                    s.bind(("0.0.0.0", port))
        
        # After context exit, port should be released
        # (We can't easily test this without potentially race conditions)

    def test_thread_safety(self):
        """Port allocator should be thread-safe."""
        allocator = PortAllocator()
        allocated_ports = set()
        errors = []
        
        def allocate_ports():
            try:
                for _ in range(5):
                    port = allocator.allocate(start_port=65000, max_range=200)
                    time.sleep(0.01)  # Small delay to increase contention
                    allocated_ports.add(port)
                    allocator.release(port)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=allocate_ports) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert not errors, f"Thread errors: {errors}"
        # All allocations should have succeeded with unique ports
        assert len(allocated_ports) >= 5  # At least 5 unique ports


class TestGlobalPortFunctions:
    """Tests for global port allocator functions."""

    def test_get_free_port_returns_available_port(self):
        """get_free_port should return an available port."""
        port = get_free_port(start_port=65000, max_range=100)
        
        assert isinstance(port, int)
        assert 65000 <= port <= 65100
        
        release_port(port)

    def test_release_port_releases_allocated_port(self):
        """release_port should release a previously allocated port."""
        port = get_free_port(start_port=65000, max_range=100)
        release_port(port)
        
        # Should be able to get the same port again
        port2 = get_free_port(start_port=port, max_range=1)
        assert port2 == port
        release_port(port2)

    def test_is_port_available_private_method(self):
        """Test the internal _is_port_available method."""
        allocator = PortAllocator()
        
        # Port 22 should not be available (occupied by SSH or privileged)
        # Port 0 is a special case for auto-allocation
        
        # Test with a likely available port
        # First allocate a port to make sure it's reserved
        port = allocator.allocate(start_port=65000, max_range=100)
        assert not allocator._is_port_available(port)  # Should not be available
        allocator.release(port)
