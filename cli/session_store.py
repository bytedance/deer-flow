"""
Session Store for DeerFlow Production Engine

Thread-safe asynchronous session persistence layer.
Handles loading, saving, archiving, and deletion of session metadata.
Uses a background worker thread to avoid blocking the main event loop.

Author: heart-scalpel
License: MIT
"""

import json
import queue
import threading
from collections import defaultdict
from pathlib import Path


class SessionStore:
    """
    Thread-safe asynchronous session storage manager.
    
    Provides non-blocking save operations via a background worker thread.
    Maintains in-memory cache of session metadata and metrics for fast access.
    Supports session archiving and graceful shutdown.
    """

    def __init__(self, sessions_dir: Path, archive_dir: Path):
        """
        Initialize the session store.
        
        Args:
            sessions_dir: Directory to store active session files
            archive_dir: Directory to store archived session files
        """
        self.sessions_dir = sessions_dir
        self.archive_dir = archive_dir
        
        # Create directories if they don't exist
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        # In-memory session cache
        self.sessions = {}
        self.session_metrics = defaultdict(lambda: {"total_tokens": 0, "tool_calls": 0, "turns": 0})

        # Async write infrastructure
        self._write_queue = queue.Queue()
        self._pending_writes = {}
        self._lock = threading.Lock()
        self._write_thread = threading.Thread(target=self._write_worker, daemon=True)
        self._write_thread.start()

        # Load existing sessions from disk
        self._load_sessions_from_disk()

    def _load_sessions_from_disk(self):
        """Load all active sessions from disk into memory on startup."""
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session_id = data["session_id"]
                self.sessions[session_id] = data["info"]
                self.session_metrics[session_id] = data["metrics"]
            except Exception:
                # Skip corrupted files silently
                continue

    def _write_worker(self):
        """Background worker thread that handles asynchronous file writes."""
        while True:
            try:
                session_id = self._write_queue.get(timeout=1)
                if session_id is None:
                    # Shutdown signal received
                    break

                with self._lock:
                    data = self._pending_writes.pop(session_id, None)

                if data is not None:
                    session_file = self.sessions_dir / f"{session_id}.json"
                    with open(session_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)

                self._write_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                # Continue running even if a write fails
                continue

    def save_async(self, session_id: str):
        """
        Queue a session for asynchronous saving to disk.
        
        Multiple rapid calls to save_async for the same session will be
        coalesced into a single write operation.
        
        Args:
            session_id: ID of the session to save
        """
        if session_id not in self.sessions:
            return

        data = {
            "session_id": session_id,
            "info": self.sessions[session_id],
            "metrics": self.session_metrics[session_id],
        }

        with self._lock:
            self._pending_writes[session_id] = data
        self._write_queue.put(session_id)

    def delete_session_files(self, session_id: str):
        """
        Delete a session and all associated files.
        
        Args:
            session_id: ID of the session to delete
        """
        with self._lock:
            self._pending_writes.pop(session_id, None)

        session_file = self.sessions_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()

        # Remove from in-memory cache
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.session_metrics:
            del self.session_metrics[session_id]

    def archive_session_files(self, session_id: str):
        """
        Move a session from active to archived status.
        
        Args:
            session_id: ID of the session to archive
        """
        with self._lock:
            self._pending_writes.pop(session_id, None)

        session_file = self.sessions_dir / f"{session_id}.json"
        archive_file = self.archive_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.rename(archive_file)

        # Remove from in-memory cache
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.session_metrics:
            del self.session_metrics[session_id]

    def shutdown(self):
        """Gracefully shut down the session store, flushing all pending writes."""
        # Wait for all pending writes to complete
        self._write_queue.join()
        # Send shutdown signal to worker thread
        self._write_queue.put(None)
        # Wait for worker thread to exit
        self._write_thread.join(timeout=5)