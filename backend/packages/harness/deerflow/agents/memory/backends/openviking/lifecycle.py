"""Durable per-session lifecycle state and idle-deadline scheduling."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DeadlineCallback = Callable[[str, str, float], None]


class SessionLifecycleStateError(RuntimeError):
    """A persisted lifecycle cursor cannot be trusted for safe replay."""


class SessionLifecycleStore:
    """Persist cursor state and dispatch the earliest idle deadline.

    Commit policy remains in the memory adapter. This component owns only the
    local durable state file and one condition-driven scheduler thread.
    """

    def __init__(self, root: Path, on_deadline: DeadlineCallback):
        self._root = root
        self._on_deadline = on_deadline
        self._condition = threading.Condition()
        self._deadlines: dict[str, tuple[str, float]] = {}
        self._worker_thread: threading.Thread | None = None
        self._stopped = False

    @property
    def worker_thread(self) -> threading.Thread | None:
        return self._worker_thread

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise SessionLifecycleStateError(f"Unreadable OpenViking lifecycle cursor: {path}") from exc
        if not isinstance(value, dict):
            raise SessionLifecycleStateError(f"Invalid OpenViking lifecycle cursor object: {path}")
        return value

    def save(self, session_id: str, state: dict[str, Any]) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temp_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_path, path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.debug(
                    "Failed to remove OpenViking cursor temp file: %s",
                    temp_path,
                    exc_info=True,
                )

    def iter_states(self) -> list[tuple[str, dict[str, Any]]]:
        states: list[tuple[str, dict[str, Any]]] = []
        try:
            paths = tuple(self._root.glob("*.json"))
        except OSError:
            logger.warning(
                "Could not enumerate OpenViking lifecycle cursors",
                exc_info=True,
            )
            return states
        for path in paths:
            try:
                state = self.load(path.stem)
            except SessionLifecycleStateError:
                logger.error(
                    "Skipping unsafe OpenViking lifecycle cursor during scan: %s",
                    path,
                    exc_info=True,
                )
                continue
            if state:
                states.append((path.stem, state))
        return states

    def schedule(self, session_id: str, peer_id: str, due_at: float) -> None:
        with self._condition:
            if self._stopped:
                return
            self._deadlines[session_id] = (peer_id, due_at)
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(
                    target=self._run,
                    name="openviking-memory-idle-flush",
                    daemon=True,
                )
                self._worker_thread.start()
            self._condition.notify_all()

    def unschedule(self, session_id: str) -> None:
        with self._condition:
            self._deadlines.pop(session_id, None)
            self._condition.notify_all()

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()

    def _path(self, session_id: str) -> Path:
        return self._root / f"{session_id}.json"

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._stopped and not self._deadlines:
                    self._condition.wait()
                if self._stopped:
                    return
                session_id, (peer_id, due_at) = min(
                    self._deadlines.items(),
                    key=lambda item: item[1][1],
                )
                remaining = due_at - time.time()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                if self._deadlines.get(session_id) != (peer_id, due_at):
                    continue
                self._deadlines.pop(session_id, None)

            try:
                self._on_deadline(session_id, peer_id, due_at)
            except Exception:
                # One broken session must not permanently stop idle commits for
                # every other session. The durable cursor remains available for
                # a later capture or process restart to retry safely.
                logger.exception(
                    "OpenViking idle-deadline callback failed (session=%s)",
                    session_id,
                )
