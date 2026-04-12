"""Tests for _ensure_admin_user() in app.py.

Covers: first-boot no-op (admin creation removed), orphan migration
when admin exists, no-op on no admin found, and edge cases.
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-ensure-admin-testing-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config

_JWT_SECRET = "test-secret-key-ensure-admin-testing-min-32"


@pytest.fixture(autouse=True)
def _setup_auth_config():
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))
    yield
    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))


def _make_app_stub(store=None):
    """Minimal app-like object with state.store."""
    app = SimpleNamespace()
    app.state = SimpleNamespace()
    app.state.store = store
    return app


def _make_provider(admin_count=0):
    p = AsyncMock()
    p.count_users = AsyncMock(return_value=admin_count)
    p.count_admin_users = AsyncMock(return_value=admin_count)
    p.create_user = AsyncMock()
    p.update_user = AsyncMock(side_effect=lambda u: u)
    return p


def _make_session_factory(admin_row=None):
    """Build a mock async session factory that returns a row from execute()."""
    row_result = MagicMock()
    row_result.scalar_one_or_none.return_value = admin_row

    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = admin_row

    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)

    # Async context manager
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock()
    sf.return_value = session_cm
    return sf


# ── First boot: no admin → return early ──────────────────────────────────


def test_first_boot_does_not_create_admin():
    """admin_count==0 → do NOT create admin automatically."""
    provider = _make_provider(admin_count=0)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        from app.gateway.app import _ensure_admin_user

        asyncio.run(_ensure_admin_user(app))

    provider.create_user.assert_not_called()


def test_first_boot_skips_migration():
    """No admin → return early before any migration attempt."""
    provider = _make_provider(admin_count=0)
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        from app.gateway.app import _ensure_admin_user

        asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_not_called()


# ── Admin exists: migration runs when admin row found ────────────────────


def test_admin_exists_triggers_migration():
    """Admin exists and admin row found → _migrate_orphaned_threads called."""
    from uuid import uuid4

    admin_row = MagicMock()
    admin_row.id = uuid4()

    provider = _make_provider(admin_count=1)
    sf = _make_session_factory(admin_row=admin_row)
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_called_once()


def test_admin_exists_no_admin_row_skips_migration():
    """Admin count > 0 but DB row missing (edge case) → skip migration gracefully."""
    provider = _make_provider(admin_count=2)
    sf = _make_session_factory(admin_row=None)
    store = AsyncMock()
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_not_called()


def test_admin_exists_no_store_skips_migration():
    """Admin exists, row found, but no store → no crash, no migration."""
    from uuid import uuid4

    admin_row = MagicMock()
    admin_row.id = uuid4()

    provider = _make_provider(admin_count=1)
    sf = _make_session_factory(admin_row=admin_row)
    app = _make_app_stub(store=None)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    # No assertion needed — just verify no crash


def test_admin_exists_session_factory_none_skips_migration():
    """get_session_factory() returns None → return early, no crash."""
    provider = _make_provider(admin_count=1)
    store = AsyncMock()
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=None):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_not_called()


def test_migration_failure_is_non_fatal():
    """_migrate_orphaned_threads exception is caught and logged."""
    from uuid import uuid4

    admin_row = MagicMock()
    admin_row.id = uuid4()

    provider = _make_provider(admin_count=1)
    sf = _make_session_factory(admin_row=admin_row)
    store = AsyncMock()
    store.asearch = AsyncMock(side_effect=RuntimeError("store crashed"))
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("deerflow.persistence.engine.get_session_factory", return_value=sf):
            from app.gateway.app import _ensure_admin_user

            # Should not raise
            asyncio.run(_ensure_admin_user(app))


# ── Section 5.1-5.6 upgrade path: orphan thread migration ────────────────


def test_migrate_orphaned_threads_stamps_user_id_on_unowned_rows():
    """First boot finds Store-only legacy threads → stamps admin's id.

    Validates the **TC-UPG-02 upgrade story**: an operator running main
    (no auth) accumulates threads in the LangGraph Store namespace
    ``("threads",)`` with no ``metadata.user_id``. After upgrading to
    feat/auth-on-2.0-rc, the first ``_ensure_admin_user`` boot should
    rewrite each unowned item with the freshly created admin's id.
    """
    from app.gateway.app import _migrate_orphaned_threads

    # Three orphan items + one already-owned item that should be left alone.
    items = [
        SimpleNamespace(key="t1", value={"metadata": {"title": "old-thread-1"}}),
        SimpleNamespace(key="t2", value={"metadata": {"title": "old-thread-2"}}),
        SimpleNamespace(key="t3", value={"metadata": {}}),
        SimpleNamespace(key="t4", value={"metadata": {"user_id": "someone-else", "title": "preserved"}}),
    ]
    store = AsyncMock()
    # asearch returns the entire batch on first call, then an empty page
    # to terminate _iter_store_items.
    store.asearch = AsyncMock(side_effect=[items, []])
    aput_calls: list[tuple[tuple, str, dict]] = []

    async def _record_aput(namespace, key, value):
        aput_calls.append((namespace, key, value))

    store.aput = AsyncMock(side_effect=_record_aput)

    migrated = asyncio.run(_migrate_orphaned_threads(store, "admin-id-42"))

    # Three orphan rows migrated, one preserved.
    assert migrated == 3
    assert len(aput_calls) == 3
    rewritten_keys = {call[1] for call in aput_calls}
    assert rewritten_keys == {"t1", "t2", "t3"}
    # Each rewrite carries the new user_id; titles preserved where present.
    by_key = {call[1]: call[2] for call in aput_calls}
    assert by_key["t1"]["metadata"]["user_id"] == "admin-id-42"
    assert by_key["t1"]["metadata"]["title"] == "old-thread-1"
    assert by_key["t3"]["metadata"]["user_id"] == "admin-id-42"
    # The pre-owned item must NOT have been rewritten.
    assert "t4" not in rewritten_keys


def test_migrate_orphaned_threads_empty_store_is_noop():
    """A store with no threads → migrated == 0, no aput calls."""
    from app.gateway.app import _migrate_orphaned_threads

    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    store.aput = AsyncMock()

    migrated = asyncio.run(_migrate_orphaned_threads(store, "admin-id-42"))

    assert migrated == 0
    store.aput.assert_not_called()


def test_iter_store_items_walks_multiple_pages():
    """Cursor-style iterator pulls every page until a short page terminates.

    Closes the regression where the old hardcoded ``limit=1000`` could
    silently drop orphans on a large pre-upgrade dataset. The migration
    code path uses the default ``page_size=500``; this test pins the
    iterator with ``page_size=2`` so it stays fast.
    """
    from app.gateway.app import _iter_store_items

    page_a = [SimpleNamespace(key=f"t{i}", value={"metadata": {}}) for i in range(2)]
    page_b = [SimpleNamespace(key=f"t{i + 2}", value={"metadata": {}}) for i in range(2)]
    page_c: list = []  # short page → loop terminates

    store = AsyncMock()
    store.asearch = AsyncMock(side_effect=[page_a, page_b, page_c])

    async def _collect():
        return [item.key async for item in _iter_store_items(store, ("threads",), page_size=2)]

    keys = asyncio.run(_collect())
    assert keys == ["t0", "t1", "t2", "t3"]
    # Three asearch calls: full batch, full batch, empty terminator
    assert store.asearch.await_count == 3


def test_iter_store_items_terminates_on_short_page():
    """A short page (len < page_size) ends the loop without an extra call."""
    from app.gateway.app import _iter_store_items

    page = [SimpleNamespace(key=f"t{i}", value={}) for i in range(3)]
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=page)

    async def _collect():
        return [item.key async for item in _iter_store_items(store, ("threads",), page_size=10)]

    keys = asyncio.run(_collect())
    assert keys == ["t0", "t1", "t2"]
    # Only one call — no terminator probe needed because len(batch) < page_size
    assert store.asearch.await_count == 1
