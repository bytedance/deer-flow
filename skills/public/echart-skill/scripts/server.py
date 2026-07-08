import os
import sys
import json
import threading
import http.server
import socketserver
import socket
import argparse
import urllib.request
import urllib.error
import urllib.parse
import signal
import atexit
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logging_config import get_logger, configure_logging
from validators import validate_file_path

# Initialize logging
configure_logging()
logger = get_logger(__name__)

# Server lifecycle configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PID_DIR = PROJECT_ROOT / "outputs" / "pids"
SERVER_TIMEOUT_MINUTES = 5


class ServerLifecycle:
    """Manage server process lifecycle with PID tracking.

    Provides:
    - PID file creation and cleanup
    - Orphan process detection
    - Inactivity timeout tracking
    """

    def __init__(self, port: int, pid_dir: Path | None = None):
        """Initialize lifecycle manager for a server port.

        Args:
            port: The port number this server runs on
            pid_dir: Directory for PID files (defaults to outputs/pids)
        """
        self.port = port
        self._pid_dir = pid_dir if pid_dir is not None else PID_DIR
        self.pid_file = self._pid_dir / f"server_{port}.pid"
        self.last_request_file = self._pid_dir / f"server_{port}_last_request"
        self._pid_dir.mkdir(parents=True, exist_ok=True)

    def write_pid(self) -> None:
        """Write current process ID to PID file."""
        self.pid_file.write_text(str(os.getpid()))

    def read_pid(self) -> int | None:
        """Read PID from file, or None if file doesn't exist."""
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text().strip())
        except (ValueError, OSError):
            return None

    def clear_pid(self) -> None:
        """Remove PID and last_request files."""
        if self.pid_file.exists():
            self.pid_file.unlink()
        if self.last_request_file.exists():
            self.last_request_file.unlink()

    def update_last_request(self) -> None:
        """Update last request timestamp to current time."""
        self.last_request_file.write_text(datetime.now().isoformat())

    def is_server_active(self, pid: int) -> bool:
        """Check if a process with given PID is running (cross-platform).

        Args:
            pid: Process ID to check

        Returns:
            True if process is running, False otherwise
        """
        try:
            # Signal 0 checks existence without sending a real signal.
            # Works on Unix (kill(2)) and Windows (OpenProcess + GetExitCodeProcess).
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def kill_orphan(self) -> bool:
        """Check for orphan process and clean up if found.

        An orphan is a PID file without a running process.

        Returns:
            True if orphan was cleaned up, False otherwise
        """
        pid = self.read_pid()
        if pid is None:
            return False

        if not self.is_server_active(pid):
            # Process is dead, clean up PID file
            self.clear_pid()
            return True

        return False

    def should_shutdown(self) -> bool:
        """Check if server should shut down due to inactivity.

        Returns:
            True if last request was more than SERVER_TIMEOUT_MINUTES ago
        """
        if not self.last_request_file.exists():
            return False

        try:
            last_request = datetime.fromisoformat(
                self.last_request_file.read_text().strip()
            )
            timeout = timedelta(minutes=SERVER_TIMEOUT_MINUTES)
            return datetime.now() - last_request > timeout
        except (ValueError, OSError):
            return False

def find_free_port(start_port=8100, max_port=8200):
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    raise IOError("No free ports found")

def check_server_running(start_port=8100, max_port=8200):
    """Check if the data-skill server is already running by probing ports."""
    for port in range(start_port, max_port + 1):
        is_open = False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                is_open = True
                
        if is_open:
            # Port is in use, check if it's our server
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/__data_skill_health")
                with urllib.request.urlopen(req, timeout=1.0) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        if data.get("app") == "data-skill":
                            return port
            except Exception:
                pass
    return None

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler with lifecycle tracking."""

    # Class-level lifecycle instance for tracking requests
    _lifecycle: ServerLifecycle | None = None

    def do_GET(self):
        if self.path == '/__data_skill_health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "app": "data-skill"}).encode())
            return

        # Update last request timestamp for timeout tracking
        if self._lifecycle:
            self._lifecycle.update_last_request()

        # Path traversal protection
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # URL-decode the path to catch encoded traversal attempts
        decoded_path = urllib.parse.unquote(self.path)
        requested_path = os.path.join(base_dir, decoded_path.lstrip('/\\'))

        try:
            # Validate path is within base directory
            validate_file_path(requested_path, base_dir)
            # Continue with normal serving
            super().do_GET()
        except ValueError as e:
            logger.warning("拒绝访问路径", path=self.path, reason=str(e))
            self.send_error(403, "Access denied")

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()
        
    def log_message(self, format, *args):
        logger.debug("HTTP request", method=self.command, path=self.path)

def run_server_forever(port, base_dir):
    """Run the server synchronously with PID tracking."""  # pragma: no cover
    os.chdir(base_dir)

    # Initialize lifecycle management
    lifecycle = ServerLifecycle(port)

    # Clean up any orphan from previous run
    lifecycle.kill_orphan()

    # Write PID file
    lifecycle.write_pid()

    # Register cleanup on exit
    atexit.register(lifecycle.clear_pid)

    # Set lifecycle on handler for request tracking
    CustomHTTPRequestHandler._lifecycle = lifecycle

    handler = CustomHTTPRequestHandler
    
    # Create server with address reuse enabled to allow quick restart
    class ReuseAddressServer(socketserver.TCPServer):
        allow_reuse_address = True
    
    with ReuseAddressServer(("", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            # Ensure cleanup on server stop
            lifecycle.clear_pid()

def ensure_server_running():
    """
    Ensures a lightweight HTTP server is running to serve the generated charts.
    Returns the base URL.

    Uses PID tracking to detect and clean up zombie server processes.
    """  # pragma: no cover
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Check if server is already running via port probe
    port = check_server_running()

    if not port:
        # Clean up orphan processes on ports 8100-8200 (matches find_free_port range)
        for p in range(8100, 8201):
            lifecycle = ServerLifecycle(p)
            lifecycle.kill_orphan()

        import subprocess
        port = find_free_port()

        # Start this very script as a background process using the --daemon flag
        cmd = [sys.executable, os.path.abspath(__file__), "--daemon", "--port", str(port)]

        if sys.platform == 'win32':
            # CREATE_NO_WINDOW (0x08000000) prevents a console window from appearing.
            # DETACHED_PROCESS detaches from the parent console.
            # CREATE_NEW_PROCESS_GROUP ensures Ctrl+C doesn't propagate.
            _CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(cmd,
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                             | subprocess.DETACHED_PROCESS
                             | _CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd,
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait a moment for it to start
        import time
        started = False
        for _ in range(10):
            time.sleep(0.2)
            if check_server_running(port, port):
                started = True
                break
        
        if not started:
            logger.warning("Server failed to start within timeout", port=port)
            return None

    return f"http://127.0.0.1:{port}"

if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Data Skill local HTTP server")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--port", type=int, help="Port to run on")

    args = parser.parse_args()

    if args.daemon and args.port:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logger.info("启动本地服务器", port=args.port)
        run_server_forever(args.port, base_dir)
    else:
        url = ensure_server_running()
        logger.info("服务器已启动", url=url)
