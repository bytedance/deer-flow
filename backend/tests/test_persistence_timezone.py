"""Regression tests for #3120: SQLite-backed stores must emit tz-aware ISO timestamps.

SQLAlchemy's ``DateTime(timezone=True)`` is a no-op on SQLite because the
backend has no native timezone type, so values read back are naive
``datetime`` instances. The four SQL ``_row_to_dict`` helpers therefore
have to normalize through :func:`deerflow.utils.time.coerce_iso` instead
of calling ``.isoformat()`` directly; otherwise the API ships
timezone-less strings (e.g. ``"2026-05-20T06:10:22.970977"``) and the
frontend's ``new Date(...)`` parses them as local time, shifting recent
threads by the local UTC offset.
"""

import re
from datetime import UTC, datetime

import pytest

_TZ_SUFFIX_RE = re.compile(r"(?:\+\d{2}:\d{2}|Z)$")


def _assert_tz_aware(value: str | None, *, context: str) -> None:
    assert value, f"{context}: expected ISO string, got {value!r}"
    assert _TZ_SUFFIX_RE.search(value), f"{context}: timestamp lacks tz suffix: {value!r}"


async def _init_sqlite(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'tz.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return get_session_factory()


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


@pytest.mark.anyio
@pytest.mark.parametrize("write_method", ["put", "put_batch", "put_if_absent"])
@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-10-14T12:34:56.123456+08:00", "2026-10-14T04:34:56.123456+00:00"),
        ("2026-10-14T23:45:00-05:30", "2026-10-15T05:15:00+00:00"),
        ("2026-10-14T04:34:56Z", "2026-10-14T04:34:56+00:00"),
        ("2026-10-14T04:34:56", "2026-10-14T04:34:56+00:00"),
    ],
)
async def test_run_event_timestamp_preserves_instant_after_sqlite_round_trip(tmp_path, write_method, timestamp, expected):
    from deerflow.runtime.events.store.db import DbRunEventStore

    store = DbRunEventStore(await _init_sqlite(tmp_path))
    event = dict(thread_id="t-tz", run_id="r-tz", event_type="llm.ai.response", category="message", content="answer", created_at=timestamp)
    try:
        if write_method == "put_batch":
            written = (await store.put_batch([event]))[0]
        elif write_method == "put_if_absent":
            written, created = await store.put_if_absent(**event)
            assert created
        else:
            written = await store.put(**event)

        assert written["created_at"] == expected
        # A new query must read the persisted clock value, not the ORM identity map.
        fetched = await store.list_events("t-tz", "r-tz", user_id=None)
        assert len(fetched) == 1
        assert fetched[0]["created_at"] == expected
        assert datetime.fromisoformat(fetched[0]["created_at"]).tzinfo == UTC

        if write_method == "put_if_absent":
            existing, created = await store.put_if_absent(**{**event, "created_at": "2026-10-16T00:00:00Z"})
            assert not created
            assert existing["created_at"] == expected
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_thread_meta_emits_tz_aware_timestamps(tmp_path):
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    repo = ThreadMetaRepository(await _init_sqlite(tmp_path))
    try:
        created = await repo.create("t-tz", user_id="u1", display_name="tz")
        _assert_tz_aware(created["created_at"], context="thread_meta.create.created_at")
        _assert_tz_aware(created["updated_at"], context="thread_meta.create.updated_at")

        # Second read from DB exercises the same _row_to_dict path on a
        # value that SQLite has round-tripped (where tzinfo is lost).
        fetched = await repo.get("t-tz", user_id="u1")
        _assert_tz_aware(fetched["created_at"], context="thread_meta.get.created_at")
        _assert_tz_aware(fetched["updated_at"], context="thread_meta.get.updated_at")

        listed = await repo.search(user_id="u1")
        assert listed, "search must return the created row"
        _assert_tz_aware(listed[0]["created_at"], context="thread_meta.search.created_at")
        _assert_tz_aware(listed[0]["updated_at"], context="thread_meta.search.updated_at")
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_run_repository_emits_tz_aware_timestamps(tmp_path):
    from deerflow.persistence.run import RunRepository

    repo = RunRepository(await _init_sqlite(tmp_path))
    try:
        await repo.put("r-tz", thread_id="t-tz", user_id="u1")
        row = await repo.get("r-tz", user_id="u1")
        _assert_tz_aware(row["created_at"], context="run.get.created_at")
        _assert_tz_aware(row["updated_at"], context="run.get.updated_at")
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_feedback_repository_emits_tz_aware_timestamps(tmp_path):
    from deerflow.persistence.feedback import FeedbackRepository

    repo = FeedbackRepository(await _init_sqlite(tmp_path))
    try:
        record = await repo.create(run_id="r-tz", thread_id="t-tz", rating=1, user_id="u1")
        _assert_tz_aware(record["created_at"], context="feedback.create.created_at")
    finally:
        await _cleanup()


@pytest.mark.anyio
async def test_run_event_store_emits_tz_aware_timestamps(tmp_path):
    from deerflow.runtime.events.store.db import DbRunEventStore

    store = DbRunEventStore(await _init_sqlite(tmp_path))
    try:
        await store.put(
            thread_id="t-tz",
            run_id="r-tz",
            event_type="log",
            category="log",
            content="hello",
        )
        events = await store.list_events("t-tz", "r-tz", user_id=None)
        assert events, "expected at least one event"
        _assert_tz_aware(events[0]["created_at"], context="run_event.list.created_at")
    finally:
        await _cleanup()
