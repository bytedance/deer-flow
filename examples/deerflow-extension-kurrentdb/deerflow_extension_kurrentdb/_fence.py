"""Fence-settled outcomes for ambiguous appends.

Every append carries an expected version, so a write aimed at position ``N`` can only
ever commit at ``N``. When an append's outcome is unknown (timeout, lost ack), a
``deerflow.Fence`` event is appended at the same expected version: if the fence lands,
the original did not commit and now never can; if the fence is rejected, position
``N`` is read and holds either the original's events (committed) or someone else's
(not committed). A failing fence leaves the outcome unknown: ``AmbiguousAppendError``.
Fold code ignores ``FENCE_EVENT_TYPE`` events everywhere.
"""

from __future__ import annotations

import json
import uuid
from typing import Literal
from uuid import UUID

from kurrentdbclient import NewEvent, StreamState
from kurrentdbclient.exceptions import WrongCurrentVersionError

FENCE_EVENT_TYPE = "deerflow.Fence"

AppendOutcome = Literal["committed", "not_committed"]


class AmbiguousAppendError(Exception):
    """The fence itself failed, so whether the original append committed is unknown."""


def _fence_event() -> NewEvent:
    return NewEvent(id=uuid.uuid4(), type=FENCE_EVENT_TYPE, data=json.dumps({"fence": str(uuid.uuid4())}).encode())


def _read_position(expected_version: int | StreamState) -> int:
    if isinstance(expected_version, int) and not isinstance(expected_version, StreamState):
        return expected_version + 1
    if expected_version == StreamState.NO_STREAM:
        return 0
    raise ValueError(f"cannot settle an append with expected_version={expected_version!r}; only an int or NO_STREAM pins a position")


def _decide(events, own_event_ids: set[UUID]) -> AppendOutcome:
    if not events:
        raise AmbiguousAppendError("fence rejected but the contested position is unreadable")
    return "committed" if events[0].id in own_event_ids else "not_committed"


def settle_append(client, stream: str, *, expected_version: int | StreamState, own_event_ids: set[UUID], timeout: float) -> AppendOutcome:
    position = _read_position(expected_version)
    try:
        client.append_to_stream(stream, events=[_fence_event()], current_version=expected_version, timeout=timeout)
        return "not_committed"
    except WrongCurrentVersionError:
        pass
    except Exception as exc:
        raise AmbiguousAppendError(f"fence append to {stream!r} failed: {exc}") from exc
    try:
        events = client.get_stream(stream, stream_position=position, limit=1, timeout=timeout)
    except Exception as exc:
        raise AmbiguousAppendError(f"reading {stream!r} at {position} after a rejected fence failed: {exc}") from exc
    return _decide(events, own_event_ids)


async def asettle_append(client, stream: str, *, expected_version: int | StreamState, own_event_ids: set[UUID], timeout: float) -> AppendOutcome:
    position = _read_position(expected_version)
    try:
        await client.append_to_stream(stream, events=[_fence_event()], current_version=expected_version, timeout=timeout)
        return "not_committed"
    except WrongCurrentVersionError:
        pass
    except Exception as exc:
        raise AmbiguousAppendError(f"fence append to {stream!r} failed: {exc}") from exc
    try:
        events = await client.get_stream(stream, stream_position=position, limit=1, timeout=timeout)
    except Exception as exc:
        raise AmbiguousAppendError(f"reading {stream!r} at {position} after a rejected fence failed: {exc}") from exc
    return _decide(events, own_event_ids)
