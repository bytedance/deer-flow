"""Tests for legacy checkpoint thread maintenance."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import Response

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-checkpoint-maintenance-min-32")

from app.gateway.auth.config import AuthConfig, set_auth_config
from app.gateway.auth.models import User
from deerflow.config.paths import Paths

_JWT_SECRET = "test-secret-key-checkpoint-maintenance-min-32"


def test_migrate_checkpoint_thread_ids_creates_meta_with_title_and_copies_legacy_files(tmp_path):
    """A checkpoint-only legacy thread becomes visible and keeps artifacts readable."""
    from app.gateway.checkpoint_maintenance import _migrate_checkpoint_thread_ids

    paths = Paths(tmp_path)
    legacy_outputs = paths.sandbox_outputs_dir("thread-1")
    legacy_outputs.mkdir(parents=True)
    (legacy_outputs / "report.md").write_text("legacy artifact", encoding="utf-8")

    checkpointer = SimpleNamespace(aget_tuple=AsyncMock(return_value=SimpleNamespace(checkpoint={"channel_values": {"title": "Legacy Report"}})))
    thread_store = AsyncMock()
    thread_store.get = AsyncMock(return_value=None)
    created: list[dict] = []

    async def _create(thread_id, **kwargs):
        created.append({"thread_id": thread_id, **kwargs})
        return {"thread_id": thread_id, **kwargs}

    thread_store.create = AsyncMock(side_effect=_create)

    migrated, failed = asyncio.run(
        _migrate_checkpoint_thread_ids(
            checkpointer,
            thread_store,
            "admin-1",
            ["thread-1"],
            paths=paths,
        )
    )

    assert migrated == 1
    assert failed is False
    assert created == [
        {
            "thread_id": "thread-1",
            "user_id": "admin-1",
            "display_name": "Legacy Report",
            "metadata": {"migrated_from": "legacy_checkpointer"},
        }
    ]
    user_artifact = paths.sandbox_outputs_dir("thread-1", user_id="admin-1") / "report.md"
    assert user_artifact.read_text(encoding="utf-8") == "legacy artifact"


def test_migrate_checkpoint_thread_ids_does_not_copy_other_users_existing_thread(tmp_path):
    """Existing owned rows are not reassigned or copied into the admin layout."""
    from app.gateway.checkpoint_maintenance import _migrate_checkpoint_thread_ids

    paths = Paths(tmp_path)
    legacy_outputs = paths.sandbox_outputs_dir("thread-2")
    legacy_outputs.mkdir(parents=True)
    (legacy_outputs / "report.md").write_text("legacy artifact", encoding="utf-8")

    checkpointer = SimpleNamespace(aget_tuple=AsyncMock())
    thread_store = AsyncMock()
    thread_store.get = AsyncMock(return_value={"thread_id": "thread-2", "user_id": "other-user"})
    thread_store.create = AsyncMock()

    migrated, failed = asyncio.run(
        _migrate_checkpoint_thread_ids(
            checkpointer,
            thread_store,
            "admin-1",
            ["thread-2"],
            paths=paths,
        )
    )

    assert migrated == 0
    assert failed is False
    thread_store.create.assert_not_called()
    assert not (paths.sandbox_outputs_dir("thread-2", user_id="admin-1") / "report.md").exists()


def test_schedule_app_checkpoint_thread_migration_debounces_running_task():
    """Setup can schedule migration once without blocking the response path."""
    import app.gateway.checkpoint_maintenance as maintenance

    calls: list[str] = []

    async def _migrate(_app, admin_user_id):
        calls.append(admin_user_id)
        await asyncio.sleep(0)
        return 0

    async def _run():
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.object(maintenance, "migrate_app_checkpoint_threads_to_thread_meta", side_effect=_migrate):
            assert maintenance.schedule_app_checkpoint_thread_migration(app, "admin-1") is True
            assert maintenance.schedule_app_checkpoint_thread_migration(app, "admin-1") is False
            await app.state.checkpoint_thread_migration_task

    asyncio.run(_run())
    assert calls == ["admin-1"]


def test_initialize_admin_schedules_checkpoint_thread_migration_after_first_setup():
    """First admin creation kicks off legacy checkpoint recovery immediately."""
    from app.gateway.routers.auth import InitializeAdminRequest, initialize_admin

    set_auth_config(AuthConfig(jwt_secret=_JWT_SECRET))
    user = User(
        id=uuid4(),
        email="admin@example.com",
        password_hash="hash",
        system_role="admin",
        needs_setup=False,
    )
    provider = AsyncMock()
    provider.count_admin_users = AsyncMock(return_value=0)
    provider.create_user = AsyncMock(return_value=user)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace()),
        headers={},
        url=SimpleNamespace(scheme="http"),
    )

    async def _run():
        with patch("app.gateway.routers.auth.get_local_provider", return_value=provider):
            with patch("app.gateway.checkpoint_maintenance.schedule_app_checkpoint_thread_migration") as schedule:
                result = await initialize_admin(
                    request,
                    Response(),
                    InitializeAdminRequest(email="admin@example.com", password="StrongPass123!"),
                )

        assert result.id == str(user.id)
        schedule.assert_called_once_with(request.app, str(user.id))

    asyncio.run(_run())
