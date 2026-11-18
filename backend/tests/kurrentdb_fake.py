"""In-memory KurrentDB for the KurrentDB extension suites (a helper, not collected).

``FakeKurrentDB`` is one server shared by any number of ``FakeSyncClient`` and
``FakeAsyncClient`` instances, whose methods mirror the signatures of
``kurrentdbclient`` 1.3's ``KurrentDBClient`` / ``AsyncKurrentDBClient`` and use its
real ``NewEvent``, ``RecordedEvent``, ``StreamState`` and exception types.

Semantics modelled (see ``test_kurrentdb_extension_basics.py``):

- Appends are atomic and checked against ``current_version`` (an int head,
  ``NO_STREAM``, ``EXISTS`` or ``ANY``); a mismatch raises ``WrongCurrentVersionError``
- Re-appending the same event ids at the same place is idempotent and returns the
  original commit position; a different event there is a conflict
- Stream metadata lives in its own versioned history; ``$tb`` (truncate before)
  hides lower positions from every read without renumbering
- A soft delete (``delete_stream``) is conditional on the head and sets ``$tb`` to
  the maximum int64, keeping other metadata keys; the stream then reads as missing
  (``NotFoundError``, ``get_current_version`` -> ``NO_STREAM``). An append with
  ``NO_STREAM``, ``ANY`` or the pre-delete head recreates it, positions continue,
  and ``$tb`` drops to the first new event

Failure injection, per method name:

- ``fail_next(method, exc, after_commit=False)``: the next call raises ``exc``
  before applying (lost request) or after applying (lost ack)
- ``delay_commit(method, exc)``: the next call raises ``exc`` and applies nothing
  until ``PendingCommit.release()``, which applies it then, against the state at
  that moment (a late server commit racing a fence)
- ``set_unavailable(exc)``: every call raises ``exc`` until cleared with ``None``

``calls`` records every client call for assertions about read patterns.
"""

from __future__ import annotations

import asyncio
import copy
import datetime
import sys
import threading
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from kurrentdbclient import NewEvent, RecordedEvent, StreamState
from kurrentdbclient.exceptions import NotFoundError, WrongCurrentVersionError

DELETED_TB = 2**63 - 1


@dataclass(frozen=True)
class Call:
    method: str
    stream_name: str
    kwargs: dict[str, Any]


@dataclass
class PendingCommit:
    """A server-side commit held back by ``delay_commit`` until ``release()``."""

    method: str
    exc: BaseException
    _server: FakeKurrentDB
    _apply: Callable[[], Any] | None = None
    committed: bool | None = None
    result: Any = None
    error: BaseException | None = None

    def release(self) -> None:
        if self._apply is None:
            raise RuntimeError(f"no {self.method} call was delayed")
        with self._server._lock:
            try:
                self.result = self._apply()
            except Exception as error:  # the late commit lost, e.g. to a fence
                self.committed, self.error = False, error
            else:
                self.committed = True
        self._apply = None


@dataclass
class _Stream:
    events: list[RecordedEvent] = field(default_factory=list)
    metadata: list[dict[str, Any]] = field(default_factory=list)


class FakeKurrentDB:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._streams: dict[str, _Stream] = defaultdict(_Stream)
        self._commit_position = 0
        self._failures: dict[str, deque[tuple[BaseException, bool]]] = defaultdict(deque)
        self._delays: dict[str, deque[PendingCommit]] = defaultdict(deque)
        self._unavailable: BaseException | None = None
        self.calls: list[Call] = []

    # --- clients and failure injection ----------------------------------

    def sync_client(self) -> FakeSyncClient:
        return FakeSyncClient(self)

    def async_client(self) -> FakeAsyncClient:
        return FakeAsyncClient(self)

    def fail_next(self, method: str, exc: BaseException, *, after_commit: bool = False) -> None:
        self._failures[method].append((exc, after_commit))

    def delay_commit(self, method: str, exc: BaseException) -> PendingCommit:
        pending = PendingCommit(method=method, exc=exc, _server=self)
        self._delays[method].append(pending)
        return pending

    def set_unavailable(self, exc: BaseException | None) -> None:
        self._unavailable = exc

    def calls_to(self, method: str, stream_name: str | None = None) -> list[Call]:
        return [call for call in self.calls if call.method == method and (stream_name is None or call.stream_name == stream_name)]

    def _invoke(self, method: str, stream_name: str, kwargs: dict[str, Any], apply: Callable[[], Any]) -> Any:
        with self._lock:
            self.calls.append(Call(method, stream_name, kwargs))
            if self._unavailable is not None:
                raise self._unavailable
            if self._delays[method]:
                pending = self._delays[method].popleft()
                pending._apply = apply
                raise pending.exc
            failure = self._failures[method].popleft() if self._failures[method] else None
            if failure is not None and not failure[1]:
                raise failure[0]
            result = apply()
            if failure is not None:
                raise failure[0]
            return result

    # --- server state -----------------------------------------------------

    def _tb(self, stream: _Stream) -> int:
        tb = stream.metadata[-1].get("$tb", 0) if stream.metadata else 0
        return tb if isinstance(tb, int) else 0

    def _live(self, name: str) -> _Stream | None:
        """The stream when it exists and is not soft-deleted."""
        stream = self._streams.get(name)
        if stream is None or not stream.events or self._tb(stream) == DELETED_TB:
            return None
        return stream

    def _head(self, name: str) -> int | StreamState:
        stream = self._live(name)
        return StreamState.NO_STREAM if stream is None else stream.events[-1].stream_position

    def _next_commit_position(self) -> int:
        self._commit_position += 1
        return self._commit_position

    def _write_metadata(self, name: str, metadata: dict[str, Any]) -> None:
        self._streams[name].metadata.append(copy.deepcopy(metadata))
        self._next_commit_position()

    def _append(self, name: str, events: NewEvent | Iterable[NewEvent], current_version: int | StreamState) -> int:
        batch = [events] if isinstance(events, NewEvent) else list(events)
        stream = self._streams.get(name) or _Stream()
        deleted = bool(stream.events) and self._tb(stream) == DELETED_TB
        last = stream.events[-1].stream_position if stream.events else -1

        replay = self._idempotent_replay(stream, batch, current_version, deleted)
        if replay is not None:
            return replay

        if current_version is StreamState.ANY:
            ok = True
        elif current_version is StreamState.NO_STREAM:
            ok = not stream.events or deleted
        elif current_version is StreamState.EXISTS:
            ok = bool(stream.events) and not deleted
        else:
            # The pre-delete head stays a valid expectation after a soft delete.
            ok = bool(stream.events) and current_version == last
        if not ok:
            raise WrongCurrentVersionError(f"stream {name!r}: expected {current_version!r}, current {StreamState.NO_STREAM if deleted or not stream.events else last!r}")
        if not batch:
            return self._commit_position

        stream = self._streams[name]
        if deleted:
            self._write_metadata(name, {**stream.metadata[-1], "$tb": last + 1})
        now = datetime.datetime.now(datetime.UTC)
        for offset, event in enumerate(batch):
            position = self._next_commit_position()
            stream.events.append(
                RecordedEvent(
                    type=event.type,
                    data=event.data,
                    metadata=event.metadata,
                    content_type=event.content_type,
                    id=event.id,
                    stream_name=name,
                    stream_position=last + 1 + offset,
                    commit_position=position,
                    prepare_position=position,
                    recorded_at=now,
                )
            )
        return self._commit_position

    def _idempotent_replay(self, stream: _Stream, batch: list[NewEvent], current_version: int | StreamState, deleted: bool) -> int | None:
        if not batch:
            return None
        ids = [event.id for event in batch]
        starts = [index for index, recorded in enumerate(stream.events) if recorded.id == ids[0]]
        if not starts:
            return None
        start = starts[-1]
        window = stream.events[start : start + len(ids)]
        if [recorded.id for recorded in window] != ids:
            return None
        if deleted:
            return None
        if isinstance(current_version, int) and start != current_version + 1:
            return None
        if current_version is StreamState.NO_STREAM and start not in (0, self._tb(stream)):
            # A stream recreated after a soft delete starts at its $tb.
            return None
        return window[-1].commit_position

    def _read(self, name: str, stream_position: int | None, backwards: bool, limit: int) -> tuple[RecordedEvent, ...]:
        stream = self._live(name)
        if stream is None:
            raise NotFoundError(f"stream {name!r} not found")
        tb = self._tb(stream)
        visible = [event for event in stream.events if event.stream_position >= tb]
        if backwards:
            visible.reverse()
            if stream_position is not None:
                visible = [event for event in visible if event.stream_position <= stream_position]
        elif stream_position is not None:
            visible = [event for event in visible if event.stream_position >= stream_position]
        return tuple(visible[:limit])

    def _delete(self, name: str, current_version: int | StreamState) -> None:
        head = self._head(name)
        if current_version is StreamState.ANY:
            ok = True
        elif current_version is StreamState.NO_STREAM:
            ok = head is StreamState.NO_STREAM
        elif current_version is StreamState.EXISTS:
            ok = head is not StreamState.NO_STREAM
        else:
            ok = current_version == head
        if not ok:
            raise WrongCurrentVersionError(f"stream {name!r}: expected {current_version!r}, current {head!r}")
        if head is StreamState.NO_STREAM:
            return
        stream = self._streams[name]
        self._write_metadata(name, {**(stream.metadata[-1] if stream.metadata else {}), "$tb": DELETED_TB})

    def _get_metadata(self, name: str) -> tuple[dict[str, Any], int | StreamState]:
        stream = self._streams.get(name)
        if stream is None or not stream.metadata:
            return {}, StreamState.NO_STREAM
        return copy.deepcopy(stream.metadata[-1]), len(stream.metadata) - 1

    def _set_metadata(self, name: str, metadata: dict[str, Any], current_version: int | StreamState) -> None:
        _, version = self._get_metadata(name)
        if current_version is StreamState.ANY:
            ok = True
        elif current_version is StreamState.NO_STREAM:
            ok = version is StreamState.NO_STREAM
        elif current_version is StreamState.EXISTS:
            ok = version is not StreamState.NO_STREAM
        else:
            ok = current_version == version
        if not ok:
            raise WrongCurrentVersionError(f"metadata of {name!r}: expected {current_version!r}, current {version!r}")
        self._write_metadata(name, metadata)


class FakeSyncClient:
    def __init__(self, server: FakeKurrentDB) -> None:
        self.server = server
        self.closed = False

    def append_to_stream(self, stream_name, *, events, current_version, timeout=None, credentials=None) -> int:
        events = [events] if isinstance(events, NewEvent) else list(events)
        return self.server._invoke("append_to_stream", stream_name, {"events": events, "current_version": current_version, "timeout": timeout}, lambda: self.server._append(stream_name, events, current_version))

    def get_stream(self, stream_name, *, stream_position=None, backwards=False, resolve_links=False, limit=sys.maxsize, timeout=None, credentials=None) -> tuple[RecordedEvent, ...]:
        kwargs = {"stream_position": stream_position, "backwards": backwards, "limit": limit, "timeout": timeout}
        return self.server._invoke("get_stream", stream_name, kwargs, lambda: self.server._read(stream_name, stream_position, backwards, limit))

    def get_current_version(self, stream_name, *, timeout=None, credentials=None) -> int | StreamState:
        return self.server._invoke("get_current_version", stream_name, {"timeout": timeout}, lambda: self.server._head(stream_name))

    def delete_stream(self, stream_name, *, current_version, timeout=None, credentials=None) -> None:
        return self.server._invoke("delete_stream", stream_name, {"current_version": current_version, "timeout": timeout}, lambda: self.server._delete(stream_name, current_version))

    def get_stream_metadata(self, stream_name, *, timeout=None, credentials=None) -> tuple[dict[str, Any], int | StreamState]:
        return self.server._invoke("get_stream_metadata", stream_name, {"timeout": timeout}, lambda: self.server._get_metadata(stream_name))

    def set_stream_metadata(self, stream_name, *, metadata, current_version=StreamState.ANY, timeout=None, credentials=None) -> None:
        metadata = copy.deepcopy(metadata)
        kwargs = {"metadata": metadata, "current_version": current_version, "timeout": timeout}
        return self.server._invoke("set_stream_metadata", stream_name, kwargs, lambda: self.server._set_metadata(stream_name, metadata, current_version))

    def close(self) -> None:
        self.closed = True


class FakeAsyncClient:
    """Async twin of ``FakeSyncClient``; every call yields to the loop once, as I/O would."""

    def __init__(self, server: FakeKurrentDB) -> None:
        self._sync = FakeSyncClient(server)
        self.server = server
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def append_to_stream(self, stream_name, *, events, current_version, timeout=None, credentials=None) -> int:
        await asyncio.sleep(0)
        return self._sync.append_to_stream(stream_name, events=events, current_version=current_version, timeout=timeout)

    async def get_stream(self, stream_name, *, stream_position=None, backwards=False, resolve_links=False, limit=sys.maxsize, timeout=None, credentials=None) -> tuple[RecordedEvent, ...]:
        await asyncio.sleep(0)
        return self._sync.get_stream(stream_name, stream_position=stream_position, backwards=backwards, limit=limit, timeout=timeout)

    async def get_current_version(self, stream_name, *, timeout=None, credentials=None) -> int | StreamState:
        await asyncio.sleep(0)
        return self._sync.get_current_version(stream_name, timeout=timeout)

    async def delete_stream(self, stream_name, *, current_version, timeout=None, credentials=None) -> None:
        await asyncio.sleep(0)
        return self._sync.delete_stream(stream_name, current_version=current_version, timeout=timeout)

    async def get_stream_metadata(self, stream_name, *, timeout=None, credentials=None) -> tuple[dict[str, Any], int | StreamState]:
        await asyncio.sleep(0)
        return self._sync.get_stream_metadata(stream_name, timeout=timeout)

    async def set_stream_metadata(self, stream_name, *, metadata, current_version=StreamState.ANY, timeout=None, credentials=None) -> None:
        await asyncio.sleep(0)
        return self._sync.set_stream_metadata(stream_name, metadata=metadata, current_version=current_version, timeout=timeout)
