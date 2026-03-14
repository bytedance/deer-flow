"""File-based sandbox state store implementation."""

import fcntl
import json
from pathlib import Path
from typing import Optional

from src.sandbox.state_store.base import SandboxInfo, SandboxStateStore
from src.utils.file_helpers import atomic_write_json


class FileSandboxStateStore(SandboxStateStore):
    """File-based sandbox state store with file locking.

    This implementation uses JSON files for persistence and fcntl-based
    file locking for cross-process synchronization. Each sandbox state
    is stored as a separate JSON file with a corresponding lock file.
    """

    def __init__(self, base_dir: Path | None = None):
        """Initialize the file-based state store.

        Args:
            base_dir: Base directory for state files. Defaults to {base_dir}/sandbox_state
        """
        if base_dir is None:
            from src.config.paths import get_paths
            base_dir = get_paths().base_dir

        self._base_dir = Path(base_dir) / "sandbox_state"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, thread_id: str, user_id: Optional[str] = None) -> Path:
        """Get the file path for a sandbox state.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.

        Returns:
            Path to the state file.
        """
        key = self._get_key(thread_id, user_id)
        # Sanitize the key to ensure it's a valid filename
        safe_key = key.replace("/", "_").replace("\\", "_")
        return self._base_dir / f"{safe_key}.json"

    def lock(self, thread_id: str, user_id: Optional[str] = None):
        """Acquire a file-based lock for the given thread and user.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.

        Returns:
            A context manager that acquires and releases the lock.
        """
        lock_path = self._get_file_path(thread_id, user_id).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        class Lock:
            """File lock context manager."""

            def __init__(self, path: Path):
                self.path = path
                self.fd = None

            def __enter__(self):
                self.fd = open(self.path, 'w')
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)
                return self

            def __exit__(self, *args):
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
                self.fd.close()

        return Lock(lock_path)

    def save(self, thread_id: str, info: SandboxInfo, user_id: Optional[str] = None) -> None:
        """Save sandbox information to file.

        Args:
            thread_id: The thread ID.
            info: The sandbox information to persist.
            user_id: Optional user ID for multi-tenant mode.
        """
        path = self._get_file_path(thread_id, user_id)
        data = {
            "thread_id": info.thread_id,
            "user_id": info.user_id,
            "sandbox_id": info.sandbox_id,
            "created_at": info.created_at,
        }

        atomic_write_json(path, data)

    def load(self, thread_id: str, user_id: Optional[str] = None) -> Optional[SandboxInfo]:
        """Load sandbox information from file.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.

        Returns:
            The sandbox information if found, None otherwise.
        """
        path = self._get_file_path(thread_id, user_id)

        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return SandboxInfo(
                thread_id=data["thread_id"],
                user_id=data.get("user_id"),
                sandbox_id=data.get("sandbox_id", "local"),
                created_at=data.get("created_at", 0.0),
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
            return None

    def remove(self, thread_id: str, user_id: Optional[str] = None) -> None:
        """Remove sandbox information.

        Args:
            thread_id: The thread ID.
            user_id: Optional user ID for multi-tenant mode.
        """
        path = self._get_file_path(thread_id, user_id)
        path.unlink(missing_ok=True)
        # Also remove lock file if it exists
        path.with_suffix(".lock").unlink(missing_ok=True)
