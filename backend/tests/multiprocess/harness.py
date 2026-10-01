"""Parent-side driver for the real multi-process MCP lifecycle acceptance tests.

``spawn_worker`` starts ``worker.py`` as a genuinely separate process with the
same ``DEER_FLOW_EXTENSIONS_CONFIG_PATH`` (and therefore the same sidecar lock
inode). The returned :class:`Worker` speaks the deterministic JSON-line protocol
described in ``worker.py``: every command produces exactly one reply, and a
gated discovery additionally emits one ``event`` line before it blocks.

All ordering is enforced by blocking reads (on the child's stdout) or by the
child blocking on stdin / the cross-process config lock. There are deliberately
no sleeps, so a passing assertion cannot be a scheduling accident.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_WORKER_PATH = Path(__file__).resolve().parent / "worker.py"

_DEFAULT_TIMEOUT = 60.0


class WorkerError(RuntimeError):
    """Raised when a child process misbehaves or times out."""


class Worker:
    """A live child process speaking the JSON-line command protocol."""

    def __init__(self, process: subprocess.Popen[bytes], config_path: Path, label: str) -> None:
        self._process = process
        self._config_path = config_path
        self._label = label
        self.events: list[dict[str, Any]] = []
        self._inbox: queue.Queue[str | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stdout_reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_reader.start()
        self._stderr_reader.start()

    # -- introspection -----------------------------------------------------

    @property
    def label(self) -> str:
        return self._label

    @property
    def config_path(self) -> Path:
        return self._config_path

    def stderr(self) -> str:
        return "\n".join(self._stderr_lines)

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for raw in self._process.stdout:
            self._inbox.put(raw.decode("utf-8").rstrip("\n"))
        self._inbox.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for raw in self._process.stderr:
            self._stderr_lines.append(raw.decode("utf-8", "replace").rstrip("\n"))

    # -- protocol ----------------------------------------------------------

    def write(self, command: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write((json.dumps(command) + "\n").encode("utf-8"))
        self._process.stdin.flush()

    def read_message(self, *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        try:
            line = self._inbox.get(timeout=timeout)
        except queue.Empty:
            raise WorkerError(f"worker {self._label} timed out after {timeout}s; stderr:\n{self.stderr()}") from None
        if line is None:
            raise WorkerError(f"worker {self._label} closed its protocol stream; stderr:\n{self.stderr()}")
        return json.loads(line)

    def read_reply(self, *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        while True:
            message = self.read_message(timeout=timeout)
            kind = message.get("type")
            if kind == "reply":
                return message
            if kind == "event":
                self.events.append(message)
                continue
            raise WorkerError(f"worker {self._label} sent an unknown message: {message!r}")

    def send(self, command: dict[str, Any], *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        self.write(command)
        return self.read_reply(timeout=timeout)

    def wait_event(self, event: str, *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        """Block until the child emits *event* (before it writes its reply)."""
        while True:
            message = self.read_message(timeout=timeout)
            kind = message.get("type")
            if kind == "event" and message.get("event") == event:
                self.events.append(message)
                return message
            if kind == "reply":
                raise WorkerError(
                    f"worker {self._label} replied before emitting event {event!r}: {message!r}",
                )
            raise WorkerError(f"worker {self._label} sent an unexpected message while waiting for {event!r}: {message!r}")

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                if self._process.stdin is not None:
                    self._process.stdin.close()
            except OSError:
                pass
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=15)
        for stream in (self._process.stdout, self._process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> Worker:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def worker_environment(config_path: Path) -> dict[str, str]:
    """Environment for a child: same config file, same local packages on path."""
    env = dict(os.environ)
    parts = [str(_BACKEND_ROOT), str(_BACKEND_ROOT / "packages" / "harness"), str(_BACKEND_ROOT / "packages" / "extension-api")]
    existing = env.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(config_path)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def spawn_worker(config_path: Path, *, label: str = "worker", python: str | None = None) -> Worker:
    """Start one independent worker process against the shared *config_path*."""
    process = subprocess.Popen(
        [python or sys.executable, str(_WORKER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(_BACKEND_ROOT),
        env=worker_environment(config_path),
    )
    return Worker(process, Path(config_path), label)
