"""In-memory KurrentDB for the KurrentDB extension suites (a helper, not collected).

``FakeKurrentDB`` is one server shared by any number of ``FakeSyncClient`` and
``FakeAsyncClient`` instances, whose methods mirror the signatures of
``kurrentdbclient`` 1.3's ``KurrentDBClient`` / ``AsyncKurrentDBClient`` and use its
real ``NewEvent``, ``RecordedEvent``, ``StreamState`` and exception types.

Semantics modelled (see ``test_kurrentdb_extension_basics.py``), each confirmed
against a real KurrentDB server by ``test_kurrentdb_extension_live.py``, which runs
the same checks on this fake and on the server:

- Appends are atomic and checked against ``current_version`` (an int head,
  ``NO_STREAM``, ``EXISTS`` or ``ANY``); a mismatch raises ``WrongCurrentVersionError``
  whose ``actual_version`` is the last position ever written (``NO_STREAM`` only
  for a stream that never had events)
- Idempotent appends: with an int or ``NO_STREAM`` (``-1``), when the event at the
  expected version + 1 has the batch's first id, the batch is a retry: it is
  accepted without writing if the following ids match too, and a conflict if they
  do not. With ``ANY`` or ``EXISTS`` the first id is looked up anywhere in the
  stream. Positions hidden by ``$tb`` or a soft delete still count
- Stream metadata lives in its own versioned history; ``$tb`` (truncate before)
  hides lower positions from every read without renumbering, and lowering it shows
  them again. ``$tb`` past the last event leaves the stream readable but empty, and
  then the real ``get_current_version`` fails (the sync client raises
  ``StopIteration``, the async one ``IndexError``)
- ``WrongCurrentVersionError`` carries ``stream_name``, ``actual_version`` and
  ``expected_version`` like the real one (metadata conflicts name ``$$<stream>``)
- A soft delete (``delete_stream``) is conditional on the head and replaces the
  metadata with ``{"$tb": <max int64>}`` (other keys are dropped); the stream then
  reads as missing (``NotFoundError``, ``get_current_version`` -> ``NO_STREAM``). An
  append with ``NO_STREAM``, ``ANY`` or the pre-delete head recreates it, positions
  continue, and ``$tb`` drops to the first new event; ``EXISTS`` raises
  ``StreamIsDeletedError``. Deleting a stream that never had events raises
  ``NotFoundError`` whatever the expected version. Deleting a soft-deleted stream
  again succeeds with ``ANY``, ``NO_STREAM`` or the pre-delete head (writing the
  metadata again), raises ``StreamIsDeletedError`` with ``EXISTS`` and
  ``WrongCurrentVersionError`` with another int

Not modelled: after an append recreates a soft-deleted stream, the server lowers
``$tb`` in a separate write, so for a few milliseconds reads may still report the
stream as deleted (``NotFoundError``; ``get_current_version`` -> ``NO_STREAM``). An
append is always checked against the real head, so a second recreation is rejected.

Failure injection, per method name:

- ``fail_next(method, exc, after_commit=False, stream_name=None)``: the next call
  raises ``exc`` before applying (lost request) or after applying (lost ack)
- ``delay_commit(method, exc, stream_name=None)``: the next call raises ``exc`` and
  applies nothing until ``PendingCommit.release()``, which applies it then, against
  the state at that moment (a late server commit racing a fence)
- With ``stream_name``, only a call on that stream consumes the injection, so a
  test can target one write of a multi-stream protocol
- ``set_unavailable(exc)``: every call raises ``exc`` until cleared with ``None``

``calls`` records every client call for assertions about read patterns.
``read_stream`` hands out events one at a time like the real streaming read
(``NotFoundError`` surfaces on the first iteration, as the server reports it in
the response); ``read_responses`` keeps every response and its ``yielded``
stream positions, so tests can assert how much of a stream a reader consumed.
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
from kurrentdbclient.exceptions import NotFoundError, StreamIsDeletedError, WrongCurrentVersionError

DELETED_TB = 2**63 - 1


class _NoReadableEvent(Exception):
    """The stream exists but ``$tb`` hides every event: the real ``get_current_version`` fails here."""


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
    stream_name: str | None = None
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


class FakeReadResponse:
    """A streaming read (``AbstractReadResponse``): iterator and context manager; ``stop()`` ends it."""

    def __init__(self, events: tuple[RecordedEvent, ...], error: BaseException | None = None) -> None:
        self._events = events
        self._error = error
        self._index = 0
        self.yielded: list[int] = []
        self.stopped = False

    def __iter__(self) -> FakeReadResponse:
        return self

    def __next__(self) -> RecordedEvent:
        if self.stopped:
            raise StopIteration
        if self._error is not None:
            error, self._error = self._error, None
            self.stopped = True
            raise error
        if self._index >= len(self._events):
            self.stopped = True
            raise StopIteration
        event = self._events[self._index]
        self._index += 1
        self.yielded.append(event.stream_position)
        return event

    def __enter__(self) -> FakeReadResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    def stop(self, *, cancel: bool = False) -> None:
        self.stopped = True


class FakeAsyncReadResponse:
    """Async twin of ``FakeReadResponse`` (``AbstractAsyncReadResponse``); each event yields to the loop once."""

    def __init__(self, response: FakeReadResponse) -> None:
        self._response = response

    @property
    def yielded(self) -> list[int]:
        return self._response.yielded

    @property
    def stopped(self) -> bool:
        return self._response.stopped

    def __aiter__(self) -> FakeAsyncReadResponse:
        return self

    async def __anext__(self) -> RecordedEvent:
        await asyncio.sleep(0)
        try:
            return next(self._response)
        except StopIteration:
            raise StopAsyncIteration from None

    async def __aenter__(self) -> FakeAsyncReadResponse:
        return self

    async def __aexit__(self, *args: object, **kwargs: Any) -> None:
        await self.stop(timeout=5)

    async def stop(self, *, timeout: float | None = None) -> None:
        self._response.stop()


@dataclass
class _Stream:
    events: list[RecordedEvent] = field(default_factory=list)
    metadata: list[dict[str, Any]] = field(default_factory=list)


class FakeKurrentDB:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._streams: dict[str, _Stream] = defaultdict(_Stream)
        self._commit_position = 0
        self._failures: dict[str, deque[tuple[BaseException, bool, str | None]]] = defaultdict(deque)
        self._delays: dict[str, deque[PendingCommit]] = defaultdict(deque)
        self._unavailable: BaseException | None = None
        self.calls: list[Call] = []
        self.read_responses: list[FakeReadResponse] = []

    # --- clients and failure injection ----------------------------------

    def sync_client(self) -> FakeSyncClient:
        return FakeSyncClient(self)

    def async_client(self) -> FakeAsyncClient:
        return FakeAsyncClient(self)

    def fail_next(self, method: str, exc: BaseException, *, after_commit: bool = False, stream_name: str | None = None) -> None:
        self._failures[method].append((exc, after_commit, stream_name))

    def delay_commit(self, method: str, exc: BaseException, *, stream_name: str | None = None) -> PendingCommit:
        pending = PendingCommit(method=method, exc=exc, _server=self, stream_name=stream_name)
        self._delays[method].append(pending)
        return pending

    @staticmethod
    def _take(queue: deque, stream_name: str, target: Callable[[Any], str | None]) -> Any:
        """Pop the first injection aimed at ``stream_name`` (or at any stream)."""
        for index, item in enumerate(queue):
            if target(item) in (None, stream_name):
                del queue[index]
                return item
        return None

    def set_unavailable(self, exc: BaseException | None) -> None:
        self._unavailable = exc

    def calls_to(self, method: str, stream_name: str | None = None) -> list[Call]:
        return [call for call in self.calls if call.method == method and (stream_name is None or call.stream_name == stream_name)]

    def _invoke(self, method: str, stream_name: str, kwargs: dict[str, Any], apply: Callable[[], Any]) -> Any:
        with self._lock:
            self.calls.append(Call(method, stream_name, kwargs))
            if self._unavailable is not None:
                raise self._unavailable
            pending = self._take(self._delays[method], stream_name, lambda item: item.stream_name)
            if pending is not None:
                pending._apply = apply
                raise pending.exc
            failure = self._take(self._failures[method], stream_name, lambda item: item[2])
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

    def _current_version(self, name: str) -> int | StreamState:
        """``get_current_version``: a backwards read of one event, like the real clients."""
        stream = self._live(name)
        if stream is None:
            return StreamState.NO_STREAM
        if stream.events[-1].stream_position < self._tb(stream):
            raise _NoReadableEvent(name)
        return stream.events[-1].stream_position

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

        replay = self._idempotent_replay(name, stream, batch, current_version)
        if replay is not None:
            return replay

        if current_version is StreamState.ANY:
            ok = True
        elif current_version is StreamState.NO_STREAM:
            ok = not stream.events or deleted
        elif current_version is StreamState.EXISTS:
            if deleted:
                raise StreamIsDeletedError(f"Stream {name!r} is deleted")
            ok = bool(stream.events)
        else:
            # The pre-delete head stays a valid expectation after a soft delete.
            ok = bool(stream.events) and current_version == last
        if not ok:
            # The server reports the last position ever written, even of a soft-deleted stream.
            actual = StreamState.NO_STREAM if not stream.events else last
            raise WrongCurrentVersionError(f"stream {name!r}: expected {current_version!r}, current {actual!r}", stream_name=name, actual_version=actual, expected_version=current_version)
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

    def _idempotent_replay(self, name: str, stream: _Stream, batch: list[NewEvent], current_version: int | StreamState) -> int | None:
        """The commit position when ``batch`` repeats events already written (nothing is written then), else ``None``.

        Physical positions count, including those hidden by ``$tb`` or a soft delete:
        a retry of a deleted event is accepted and leaves the stream deleted.
        """
        if not batch or not stream.events:
            return None
        ids = [event.id for event in batch]
        if current_version is StreamState.ANY or current_version is StreamState.EXISTS:
            starts = [index for index, recorded in enumerate(stream.events) if recorded.id == ids[0]]
            if not starts:
                return None
            start = starts[-1]
        else:
            # Positions run from 0 without gaps, so a position is an index.
            start = 0 if current_version is StreamState.NO_STREAM else current_version + 1
            if not 0 <= start < len(stream.events) or stream.events[start].id != ids[0]:
                return None
        window = stream.events[start : start + len(ids)]
        if [recorded.id for recorded in window] != ids:
            last = stream.events[-1].stream_position
            raise WrongCurrentVersionError(f"stream {name!r}: a partial retry at {start}, current {last!r}", stream_name=name, actual_version=last, expected_version=current_version)
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

    def _read_response(self, name: str, stream_position: int | None, backwards: bool, limit: int) -> FakeReadResponse:
        try:
            response = FakeReadResponse(self._read(name, stream_position, backwards, limit))
        except NotFoundError as error:
            response = FakeReadResponse((), error)
        self.read_responses.append(response)
        return response

    def _delete(self, name: str, current_version: int | StreamState) -> None:
        stream = self._streams.get(name)
        if stream is None or not stream.events:
            # The server reports actual version -1, which the client maps to NotFoundError, whatever was expected.
            raise NotFoundError(f"stream {name!r} not found (expected {current_version!r})")
        last = stream.events[-1].stream_position
        if self._tb(stream) == DELETED_TB:
            # Deleting again succeeds (and writes the metadata again) unless it expects a live stream.
            if current_version is StreamState.EXISTS:
                raise StreamIsDeletedError(f"Event stream {name!r} is deleted.")
            ok = current_version in (StreamState.ANY, StreamState.NO_STREAM) or current_version == last
        else:
            ok = current_version in (StreamState.ANY, StreamState.EXISTS) or current_version == last
        if not ok:
            raise WrongCurrentVersionError(f"stream {name!r}: expected {current_version!r}, current {last!r}", stream_name=name, actual_version=last, expected_version=current_version)
        # The delete replaces the whole metadata document: other keys are dropped.
        self._write_metadata(name, {"$tb": DELETED_TB})

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
            raise WrongCurrentVersionError(f"metadata of {name!r}: expected {current_version!r}, current {version!r}", stream_name=f"$${name}", actual_version=version, expected_version=current_version)
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

    def read_stream(self, stream_name, *, stream_position=None, backwards=False, resolve_links=False, limit=sys.maxsize, timeout=None, credentials=None) -> FakeReadResponse:
        kwargs = {"stream_position": stream_position, "backwards": backwards, "limit": limit, "timeout": timeout}
        return self.server._invoke("read_stream", stream_name, kwargs, lambda: self.server._read_response(stream_name, stream_position, backwards, limit))

    def get_current_version(self, stream_name, *, timeout=None, credentials=None) -> int | StreamState:
        try:
            return self.server._invoke("get_current_version", stream_name, {"timeout": timeout}, lambda: self.server._current_version(stream_name))
        except _NoReadableEvent:
            raise StopIteration from None  # the real sync client's next() on an empty backwards read

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

    async def read_stream(self, stream_name, *, stream_position=None, backwards=False, resolve_links=False, limit=sys.maxsize, timeout=None, credentials=None) -> FakeAsyncReadResponse:
        await asyncio.sleep(0)
        return FakeAsyncReadResponse(self._sync.read_stream(stream_name, stream_position=stream_position, backwards=backwards, limit=limit, timeout=timeout))

    async def get_current_version(self, stream_name, *, timeout=None, credentials=None) -> int | StreamState:
        await asyncio.sleep(0)
        try:
            return self._sync.get_current_version(stream_name, timeout=timeout)
        except StopIteration:
            raise IndexError("list index out of range") from None  # the real async client's events[0] on an empty read

    async def delete_stream(self, stream_name, *, current_version, timeout=None, credentials=None) -> None:
        await asyncio.sleep(0)
        return self._sync.delete_stream(stream_name, current_version=current_version, timeout=timeout)

    async def get_stream_metadata(self, stream_name, *, timeout=None, credentials=None) -> tuple[dict[str, Any], int | StreamState]:
        await asyncio.sleep(0)
        return self._sync.get_stream_metadata(stream_name, timeout=timeout)

    async def set_stream_metadata(self, stream_name, *, metadata, current_version=StreamState.ANY, timeout=None, credentials=None) -> None:
        await asyncio.sleep(0)
        return self._sync.set_stream_metadata(stream_name, metadata=metadata, current_version=current_version, timeout=timeout)
