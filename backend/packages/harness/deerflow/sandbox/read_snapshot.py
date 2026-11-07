"""Invocation-local evidence from the source of a first-party file read."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadSnapshot:
    content_hash: str
    displayed_content: str


@dataclass
class ReadSnapshotCapture:
    path: str
    snapshot: ReadSnapshot | None = None


_active_capture: ContextVar[ReadSnapshotCapture | None] = ContextVar("deerflow_read_snapshot", default=None)


@contextmanager
def capture_read_snapshot(path: str) -> Iterator[ReadSnapshotCapture]:
    # to_thread copies the ContextVar value. Its worker records into this one
    # invocation's holder, while sibling calls each receive their own holder.
    capture = ReadSnapshotCapture(path)
    token = _active_capture.set(capture)
    try:
        yield capture
    finally:
        _active_capture.reset(token)


def read_snapshot_requested(path: str) -> bool:
    capture = _active_capture.get()
    return capture is not None and capture.path == path


def record_read_snapshot(path: str, content: str, displayed_content: str) -> None:
    capture = _active_capture.get()
    if capture is not None and capture.path == path:
        capture.snapshot = ReadSnapshot(hashlib.sha256(content.encode("utf-8")).hexdigest(), displayed_content)
