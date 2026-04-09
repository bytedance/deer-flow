"""Tests for _ensure_admin_user() in app.py.

Covers: first-boot admin creation, auto-reset on needs_setup=True,
no-op on needs_setup=False, migration, and edge cases.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-ensure-admin-testing-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.models import User

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


def _make_provider(user_count=0, admin_user=None):
    p = AsyncMock()
    p.count_users = AsyncMock(return_value=user_count)
    p.create_user = AsyncMock(
        side_effect=lambda **kw: User(
            email=kw["email"],
            password_hash="hashed",
            system_role=kw.get("system_role", "user"),
            needs_setup=kw.get("needs_setup", False),
        )
    )
    p.get_user_by_email = AsyncMock(return_value=admin_user)
    p.update_user = AsyncMock(side_effect=lambda u: u)
    return p


# ── First boot: no users ─────────────────────────────────────────────────


def test_first_boot_creates_admin():
    """count_users==0 → create admin with needs_setup=True."""
    provider = _make_provider(user_count=0)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("app.gateway.auth.password.hash_password_async", new_callable=AsyncMock, return_value="hashed"):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    provider.create_user.assert_called_once()
    call_kwargs = provider.create_user.call_args[1]
    assert call_kwargs["email"] == "admin@deerflow.dev"
    assert call_kwargs["system_role"] == "admin"
    assert call_kwargs["needs_setup"] is True
    assert len(call_kwargs["password"]) > 10  # random password generated


def test_first_boot_triggers_migration_if_store_present():
    """First boot with store → _migrate_orphaned_threads called."""
    provider = _make_provider(user_count=0)
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("app.gateway.auth.password.hash_password_async", new_callable=AsyncMock, return_value="hashed"):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    store.asearch.assert_called_once()


def test_first_boot_no_store_skips_migration():
    """First boot without store → no crash, migration skipped."""
    provider = _make_provider(user_count=0)
    app = _make_app_stub(store=None)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("app.gateway.auth.password.hash_password_async", new_callable=AsyncMock, return_value="hashed"):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    provider.create_user.assert_called_once()


# ── Subsequent boot: needs_setup=True → auto-reset ───────────────────────


def test_needs_setup_true_resets_password():
    """Existing admin with needs_setup=True → password reset + token_version bumped."""
    admin = User(
        email="admin@deerflow.dev",
        password_hash="old-hash",
        system_role="admin",
        needs_setup=True,
        token_version=0,
        created_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    provider = _make_provider(user_count=1, admin_user=admin)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("app.gateway.auth.password.hash_password_async", new_callable=AsyncMock, return_value="new-hash"):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    # Password was reset
    provider.update_user.assert_called_once()
    updated = provider.update_user.call_args[0][0]
    assert updated.password_hash == "new-hash"
    assert updated.token_version == 1


def test_needs_setup_true_consecutive_resets_increment_version():
    """Two boots with needs_setup=True → token_version increments each time."""
    admin = User(
        email="admin@deerflow.dev",
        password_hash="hash",
        system_role="admin",
        needs_setup=True,
        token_version=3,
        created_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    provider = _make_provider(user_count=1, admin_user=admin)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("app.gateway.auth.password.hash_password_async", new_callable=AsyncMock, return_value="new-hash"):
            from app.gateway.app import _ensure_admin_user

            asyncio.run(_ensure_admin_user(app))

    updated = provider.update_user.call_args[0][0]
    assert updated.token_version == 4


# ── Subsequent boot: needs_setup=False → no-op ──────────────────────────


def test_needs_setup_false_no_reset():
    """Admin with needs_setup=False → no password reset, no update."""
    admin = User(
        email="admin@deerflow.dev",
        password_hash="stable-hash",
        system_role="admin",
        needs_setup=False,
        token_version=2,
    )
    provider = _make_provider(user_count=1, admin_user=admin)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        from app.gateway.app import _ensure_admin_user

        asyncio.run(_ensure_admin_user(app))

    provider.update_user.assert_not_called()
    assert admin.password_hash == "stable-hash"
    assert admin.token_version == 2


# ── Edge cases ───────────────────────────────────────────────────────────


def test_no_admin_email_found_no_crash():
    """Users exist but no admin@deerflow.dev → no crash, no reset."""
    provider = _make_provider(user_count=3, admin_user=None)
    app = _make_app_stub()

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        from app.gateway.app import _ensure_admin_user

        asyncio.run(_ensure_admin_user(app))

    provider.update_user.assert_not_called()
    provider.create_user.assert_not_called()


def test_migration_failure_is_non_fatal():
    """_migrate_orphaned_threads exception is caught and logged."""
    provider = _make_provider(user_count=0)
    store = AsyncMock()
    store.asearch = AsyncMock(side_effect=RuntimeError("store crashed"))
    app = _make_app_stub(store=store)

    with patch("app.gateway.deps.get_local_provider", return_value=provider):
        with patch("app.gateway.auth.password.hash_password_async", new_callable=AsyncMock, return_value="hashed"):
            from app.gateway.app import _ensure_admin_user

            # Should not raise
            asyncio.run(_ensure_admin_user(app))

    provider.create_user.assert_called_once()


# ── Section 5.1-5.6 upgrade path: orphan thread migration ────────────────


def test_migrate_orphaned_threads_stamps_owner_id_on_unowned_rows():
    """First boot finds Store-only legacy threads → stamps admin's id.

    Validates the **TC-UPG-02 upgrade story**: an operator running main
    (no auth) accumulates threads in the LangGraph Store namespace
    ``("threads",)`` with no ``metadata.owner_id``. After upgrading to
    feat/auth-on-2.0-rc, the first ``_ensure_admin_user`` boot should
    rewrite each unowned item with the freshly created admin's id.
    """
    from app.gateway.app import _migrate_orphaned_threads

    # Three orphan items + one already-owned item that should be left alone.
    items = [
        SimpleNamespace(key="t1", value={"metadata": {"title": "old-thread-1"}}),
        SimpleNamespace(key="t2", value={"metadata": {"title": "old-thread-2"}}),
        SimpleNamespace(key="t3", value={"metadata": {}}),
        SimpleNamespace(key="t4", value={"metadata": {"owner_id": "someone-else", "title": "preserved"}}),
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
    # Each rewrite carries the new owner_id; titles preserved where present.
    by_key = {call[1]: call[2] for call in aput_calls}
    assert by_key["t1"]["metadata"]["owner_id"] == "admin-id-42"
    assert by_key["t1"]["metadata"]["title"] == "old-thread-1"
    assert by_key["t3"]["metadata"]["owner_id"] == "admin-id-42"
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
