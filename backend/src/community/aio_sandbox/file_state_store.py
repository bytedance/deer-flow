"""File-based sandbox state store.

Uses JSON files for persistence and fcntl file locking for cross-process
mutual exclusion. Works across processes on the same machine or across
K8s pods with a shared PVC mount.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .sandbox_info import SandboxInfo
from .state_store import SandboxStateStore

logger = logging.getLogger(__name__)

SANDBOX_STATE_FILE = "sandbox.json"
SANDBOX_LOCK_FILE = "sandbox.lock"


class FileSandboxStateStore(SandboxStateStore):
    """File-based state store using JSON files and fcntl file locking.

    State is stored at: {base_dir}/{threads_subdir}/{thread_id}/sandbox.json
    Lock files at:      {base_dir}/{threads_subdir}/{thread_id}/sandbox.lock

    This works across processes on the same machine sharing a filesystem.
    For K8s multi-pod scenarios, requires a shared PVC mount at base_dir.
    """

    def __init__(self, base_dir: str, threads_subdir: str = ".deer-flow/threads"):
        """Initialize the file-based state store.

        Args:
            base_dir: Root directory for state files (typically the project root / cwd).
            threads_subdir: Subdirectory path for thread state (default: ".deer-flow/threads").
        """
        self._base_dir = Path(base_dir)
        self._threads_subdir = threads_subdir

    def _thread_dir(self, thread_id: str) -> Path:
        """Get the directory for a thread's state files."""
        return self._base_dir / self._threads_subdir / thread_id

    def save(self, thread_id: str, info: SandboxInfo) -> None:
        thread_dir = self._thread_dir(thread_id)
        os.makedirs(thread_dir, exist_ok=True)
        state_file = thread_dir / SANDBOX_STATE_FILE
        try:
            state_file.write_text(json.dumps(info.to_dict()))
            logger.info(f"Saved sandbox state for thread {thread_id}: {info.sandbox_id}")
        except OSError as e:
            logger.warning(f"Failed to save sandbox state for thread {thread_id}: {e}")

    def load(self, thread_id: str) -> SandboxInfo | None:
        state_file = self._thread_dir(thread_id) / SANDBOX_STATE_FILE
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text())
            return SandboxInfo.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load sandbox state for thread {thread_id}: {e}")
            return None

    def remove(self, thread_id: str) -> None:
        state_file = self._thread_dir(thread_id) / SANDBOX_STATE_FILE
        try:
            if state_file.exists():
                state_file.unlink()
                logger.info(f"Removed sandbox state for thread {thread_id}")
        except OSError as e:
            logger.warning(f"Failed to remove sandbox state for thread {thread_id}: {e}")

    @contextmanager
    def lock(self, thread_id: str) -> Generator[None, None, None]:
        """Acquire a cross-process file lock using fcntl.flock.

        The lock is held for the duration of the context manager.
        Only one process can hold the lock at a time for a given thread_id.

        Note: fcntl.flock is available on macOS and Linux.
        """
        thread_dir = self._thread_dir(thread_id)
        os.makedirs(thread_dir, exist_ok=True)
        lock_path = thread_dir / SANDBOX_LOCK_FILE
        lock_file = open(lock_path, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except OSError:
                pass
