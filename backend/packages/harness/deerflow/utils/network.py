"""线程-safe 网络 utilities."""

import socket
import threading
from contextlib import contextmanager


class PortAllocator:
    """线程-safe port allocator that prevents port conflicts in 并发 environments.

    This 类 maintains a 集合 of reserved ports and uses a lock to ensure that
    port allocation is atomic. Once a port is allocated, it remains reserved until
    explicitly released.

    Usage:
        allocator = PortAllocator()

        #    Option 1: Manual allocation and release


        port = allocator.allocate(start_port=8080)
        try:
            #    Use the port...


        finally:
            allocator.release(port)

        #    Option 2: Context manager (recommended)


        with allocator.allocate_context(start_port=8080) as port:
            #    Use the port...


            #    Port is automatically released when exiting the context


    """

    def __init__(self):
        self._lock = threading.Lock()
        self._reserved_ports: set[int] = set()

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is 可用的 for binding.

        Args:
            port: The port 数字 to 检查.

        Returns:
            True if the port is 可用的, False otherwise.
        """
        if port in self._reserved_ports:
            return False

        #    Bind to 0.0.0.0 (wildcard) rather than localhost so that the 检查


        #    mirrors exactly what Docker does.  Docker binds to 0.0.0.0:PORT;


        #    checking only 127.0.0.1 can falsely report a port as 可用的 even


        #    when Docker already occupies it on the wildcard address.


        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    def allocate(self, start_port: int = 8080, max_range: int = 100) -> int:
        """Allocate an 可用的 port in a 线程-safe manner.

        This 方法 is 线程-safe. It finds an 可用的 port, marks it as reserved,
        and returns it. The port remains reserved until release() is called.

        Args:
            start_port: The port 数字 to 开始 searching from.
            max_range: Maximum 数字 of ports to search.

        Returns:
            An 可用的 port 数字.

        Raises:
            RuntimeError: If no 可用的 port is found in the specified range.
        """
        with self._lock:
            for port in range(start_port, start_port + max_range):
                if self._is_port_available(port):
                    self._reserved_ports.add(port)
                    return port

            raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_range}")

    def release(self, port: int) -> None:
        """Release a previously allocated port.

        Args:
            port: The port 数字 to release.
        """
        with self._lock:
            self._reserved_ports.discard(port)

    @contextmanager
    def allocate_context(self, start_port: int = 8080, max_range: int = 100):
        """Context manager for port allocation with automatic release.

        Args:
            start_port: The port 数字 to 开始 searching from.
            max_range: Maximum 数字 of ports to search.

        Yields:
            An 可用的 port 数字.
        """
        port = self.allocate(start_port, max_range)
        try:
            yield port
        finally:
            self.release(port)


#    Global port allocator instance 对于 shared use across the application


_global_port_allocator = PortAllocator()


def get_free_port(start_port: int = 8080, max_range: int = 100) -> int:
    """Get a free port in a 线程-safe manner.

    This 函数 uses a global port allocator to ensure that 并发 calls
    don't 返回 the same port. The port is marked as reserved until release_port()
    is called.

    Args:
        start_port: The port 数字 to 开始 searching from.
        max_range: Maximum 数字 of ports to search.

    Returns:
        An 可用的 port 数字.

    Raises:
        RuntimeError: If no 可用的 port is found in the specified range.
    """
    return _global_port_allocator.allocate(start_port, max_range)


def release_port(port: int) -> None:
    """Release a previously allocated port.

    Args:
        port: The port 数字 to release.
    """
    _global_port_allocator.release(port)
