"""Cross-user isolation tests — non-negotiable safety gate.

Mirrors TC-API-17..20 from backend/docs/AUTH_TEST_PLAN.md. A failure
here means users can see each other's data; PR must not merge.

Architecture note
-----------------
These tests bypass the HTTP layer and exercise the storage-layer
owner filter directly by switching the ``user_context`` contextvar
between two users. The safety property under test is:

  After a repository write with user_id=A, a subsequent read with
  user_id=B must not return the row, and vice versa.

The HTTP layer is covered by test_auth_middleware.py, which proves
that a request cookie reaches the ``set_current_user`` call. Together
the two suites prove the full chain:

  cookie → middleware → contextvar → repository → isolation

Every test in this file opts out of the autouse contextvar fixture
(``@pytest.mark.no_auto_user``) so it can set the contextvar to the
specific users it cares about.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.runtime.user_context import (
    reset_current_user,
    set_current_user,
)

USER_A = SimpleNamespace(id="user-a", email="a@test.local")
USER_B = SimpleNamespace(id="user-b", email="b@test.local")


async def _make_engines(tmp_path):
    """Initialize the shared engine against a per-test SQLite DB.

    Returns a cleanup coroutine the caller should await at the end.
    """
    from deerflow.persistence.engine import close_engine, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return close_engine


def _as_user(user):
    """Context manager-like helper that set/reset the contextvar."""

    class _Ctx:
        def __enter__(self):
            self._token = set_current_user(user)
            return user

        def __exit__(self, *exc):
            reset_current_user(self._token)

    return _Ctx()


# ── TC-API-17 — threads_meta isolation ────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_thread_meta_cross_user_isolation(tmp_path):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())

        # User A creates a thread.
        with _as_user(USER_A):
            await repo.create("t-alpha", display_name="A's private thread")

        # User B creates a thread.
        with _as_user(USER_B):
            await repo.create("t-beta", display_name="B's private thread")

        # User A must see only A's thread.
        with _as_user(USER_A):
            a_view = await repo.get("t-alpha")
            assert a_view is not None
            assert a_view["display_name"] == "A's private thread"

            # CRITICAL: User A must NOT see B's thread.
            leaked = await repo.get("t-beta")
            assert leaked is None, f"User A leaked User B's thread: {leaked}"

            # Search should only return A's threads.
            results = await repo.search()
            assert [r["thread_id"] for r in results] == ["t-alpha"]

        # User B must see only B's thread.
        with _as_user(USER_B):
            b_view = await repo.get("t-beta")
            assert b_view is not None
            assert b_view["display_name"] == "B's private thread"

            leaked = await repo.get("t-alpha")
            assert leaked is None, f"User B leaked User A's thread: {leaked}"

            results = await repo.search()
            assert [r["thread_id"] for r in results] == ["t-beta"]
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_thread_meta_cross_user_mutation_denied(tmp_path):
    """User B cannot update or delete a thread owned by User A."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())

        with _as_user(USER_A):
            await repo.create("t-alpha", display_name="original")

        # User B tries to rename A's thread — must be a no-op.
        with _as_user(USER_B):
            await repo.update_display_name("t-alpha", "hacked")

        # Verify the row is unchanged from A's perspective.
        with _as_user(USER_A):
            row = await repo.get("t-alpha")
            assert row is not None
            assert row["display_name"] == "original"

        # User B tries to delete A's thread — must be a no-op.
        with _as_user(USER_B):
            await repo.delete("t-alpha")

        # A's thread still exists.
        with _as_user(USER_A):
            row = await repo.get("t-alpha")
            assert row is not None
    finally:
        await cleanup()


# ── TC-API-18 — runs isolation ────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_runs_cross_user_isolation(tmp_path):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.run import RunRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = RunRepository(get_session_factory())

        with _as_user(USER_A):
            await repo.put("run-a1", thread_id="t-alpha")
            await repo.put("run-a2", thread_id="t-alpha")

        with _as_user(USER_B):
            await repo.put("run-b1", thread_id="t-beta")

        # User A must see only A's runs.
        with _as_user(USER_A):
            r = await repo.get("run-a1")
            assert r is not None
            assert r["run_id"] == "run-a1"

            leaked = await repo.get("run-b1")
            assert leaked is None, "User A leaked User B's run"

            a_runs = await repo.list_by_thread("t-alpha")
            assert {r["run_id"] for r in a_runs} == {"run-a1", "run-a2"}

            # Listing B's thread from A's perspective: empty
            empty = await repo.list_by_thread("t-beta")
            assert empty == []

        # User B must see only B's runs.
        with _as_user(USER_B):
            leaked = await repo.get("run-a1")
            assert leaked is None, "User B leaked User A's run"

            b_runs = await repo.list_by_thread("t-beta")
            assert [r["run_id"] for r in b_runs] == ["run-b1"]
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_runs_cross_user_delete_denied(tmp_path):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.run import RunRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = RunRepository(get_session_factory())

        with _as_user(USER_A):
            await repo.put("run-a1", thread_id="t-alpha")

        # User B tries to delete A's run — no-op.
        with _as_user(USER_B):
            await repo.delete("run-a1")

        # A's run still exists.
        with _as_user(USER_A):
            row = await repo.get("run-a1")
            assert row is not None
    finally:
        await cleanup()


# ── TC-API-19 — run_events isolation (CRITICAL: content leak) ─────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_run_events_cross_user_isolation(tmp_path):
    """run_events holds raw conversation content — most sensitive leak vector."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.events.store.db import DbRunEventStore

    cleanup = await _make_engines(tmp_path)
    try:
        store = DbRunEventStore(get_session_factory())

        with _as_user(USER_A):
            await store.put(
                thread_id="t-alpha",
                run_id="run-a1",
                event_type="human_message",
                category="message",
                content="User A private question",
            )
            await store.put(
                thread_id="t-alpha",
                run_id="run-a1",
                event_type="ai_message",
                category="message",
                content="User A private answer",
            )

        with _as_user(USER_B):
            await store.put(
                thread_id="t-beta",
                run_id="run-b1",
                event_type="human_message",
                category="message",
                content="User B private question",
            )

        # User A must see only A's events — CRITICAL.
        with _as_user(USER_A):
            msgs = await store.list_messages("t-alpha")
            contents = [m["content"] for m in msgs]
            assert "User A private question" in contents
            assert "User A private answer" in contents
            # CRITICAL: User B's content must not appear.
            assert "User B private question" not in contents

            # Attempt to read B's thread by guessing thread_id.
            leaked = await store.list_messages("t-beta")
            assert leaked == [], f"User A leaked User B's messages: {leaked}"

            leaked_events = await store.list_events("t-beta", "run-b1")
            assert leaked_events == [], "User A leaked User B's events"

            # count_messages must also be zero for B's thread from A's view.
            count = await store.count_messages("t-beta")
            assert count == 0

        # User B must see only B's events.
        with _as_user(USER_B):
            msgs = await store.list_messages("t-beta")
            contents = [m["content"] for m in msgs]
            assert "User B private question" in contents
            assert "User A private question" not in contents
            assert "User A private answer" not in contents

            count = await store.count_messages("t-alpha")
            assert count == 0
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_run_events_cross_user_delete_denied(tmp_path):
    """User B cannot delete User A's event stream."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.events.store.db import DbRunEventStore

    cleanup = await _make_engines(tmp_path)
    try:
        store = DbRunEventStore(get_session_factory())

        with _as_user(USER_A):
            await store.put(
                thread_id="t-alpha",
                run_id="run-a1",
                event_type="human_message",
                category="message",
                content="hello",
            )

        # User B tries to wipe A's thread events.
        with _as_user(USER_B):
            removed = await store.delete_by_thread("t-alpha")
            assert removed == 0, f"User B deleted {removed} of User A's events"

        # A's events still exist.
        with _as_user(USER_A):
            count = await store.count_messages("t-alpha")
            assert count == 1
    finally:
        await cleanup()


# ── TC-API-20 — feedback isolation ────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_feedback_cross_user_isolation(tmp_path):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.feedback import FeedbackRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = FeedbackRepository(get_session_factory())

        # User A submits positive feedback.
        with _as_user(USER_A):
            a_feedback = await repo.create(
                run_id="run-a1",
                thread_id="t-alpha",
                rating=1,
                comment="A liked this",
            )

        # User B submits negative feedback.
        with _as_user(USER_B):
            b_feedback = await repo.create(
                run_id="run-b1",
                thread_id="t-beta",
                rating=-1,
                comment="B disliked this",
            )

        # User A must see only A's feedback.
        with _as_user(USER_A):
            retrieved = await repo.get(a_feedback["feedback_id"])
            assert retrieved is not None
            assert retrieved["comment"] == "A liked this"

            # CRITICAL: cannot read B's feedback by id.
            leaked = await repo.get(b_feedback["feedback_id"])
            assert leaked is None, "User A leaked User B's feedback"

            # list_by_run for B's run must be empty.
            empty = await repo.list_by_run("t-beta", "run-b1")
            assert empty == []

        # User B must see only B's feedback.
        with _as_user(USER_B):
            leaked = await repo.get(a_feedback["feedback_id"])
            assert leaked is None, "User B leaked User A's feedback"

            b_list = await repo.list_by_run("t-beta", "run-b1")
            assert len(b_list) == 1
            assert b_list[0]["comment"] == "B disliked this"
    finally:
        await cleanup()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_feedback_cross_user_delete_denied(tmp_path):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.feedback import FeedbackRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = FeedbackRepository(get_session_factory())

        with _as_user(USER_A):
            fb = await repo.create(run_id="run-a1", thread_id="t-alpha", rating=1)

        # User B tries to delete A's feedback — must return False (no-op).
        with _as_user(USER_B):
            deleted = await repo.delete(fb["feedback_id"])
            assert deleted is False, "User B deleted User A's feedback"

        # A's feedback still retrievable.
        with _as_user(USER_A):
            row = await repo.get(fb["feedback_id"])
            assert row is not None
    finally:
        await cleanup()


# ── Regression: AUTO sentinel without contextvar must raise ───────────────


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_repository_without_context_raises(tmp_path):
    """Defense-in-depth: calling repo methods without a user context errors."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())
        # Contextvar is explicitly unset under @pytest.mark.no_auto_user.
        with pytest.raises(RuntimeError, match="no user context is set"):
            await repo.get("anything")
    finally:
        await cleanup()


# ── Escape hatch: explicit user_id=None bypasses filter (for migration) ──


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_explicit_none_bypasses_filter(tmp_path):
    """Migration scripts pass user_id=None to see all rows regardless of owner."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    cleanup = await _make_engines(tmp_path)
    try:
        repo = ThreadMetaRepository(get_session_factory())

        # Seed data as two different users.
        with _as_user(USER_A):
            await repo.create("t-alpha")
        with _as_user(USER_B):
            await repo.create("t-beta")

        # Migration-style read: no contextvar, explicit None bypass.
        all_rows = await repo.search(user_id=None)
        thread_ids = {r["thread_id"] for r in all_rows}
        assert thread_ids == {"t-alpha", "t-beta"}

        # Explicit get with None does not apply the filter either.
        row_a = await repo.get("t-alpha", user_id=None)
        assert row_a is not None
        row_b = await repo.get("t-beta", user_id=None)
        assert row_b is not None
    finally:
        await cleanup()
