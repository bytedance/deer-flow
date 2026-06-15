"""Tests for industrial migration endpoints.

Covers tasks from the industrial-intelligence-primary-track change:
- GET /api/tenants/{tenant_id}/migration-status
- POST /api/tenants/{tenant_id}/mark-migration-prompted
- POST /api/tenants/{tenant_id}/decline-migration
- POST /api/tenants/{tenant_id}/migrate-industrial
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers.tenant_industrial_migration import (
    _load_migration_state,
    _save_migration_state,
    router,
)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig for dependency injection."""
    from unittest.mock import MagicMock

    config = MagicMock()
    config.skills = MagicMock()
    config.skills.path = "skills"
    config.skills.container_path = "/mnt/skills"
    return config


@pytest.fixture
def app(tmp_path: Path, mock_config):
    """Create a test FastAPI app with the migration router."""
    test_app = FastAPI()
    test_app.dependency_overrides[get_config] = lambda: mock_config
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app: FastAPI):
    return TestClient(app)


@pytest.fixture
def state_file(tmp_path: Path):
    """Mock the migration state file path."""
    state_path = tmp_path / "industrial_migration_state.json"
    with patch(
        "app.gateway.routers.tenant_industrial_migration._get_migration_state_path",
        return_value=state_path,
    ):
        yield state_path


# ===========================================================================
# GET /migration-status
# ===========================================================================


class TestMigrationStatus:
    def test_status_returns_defaults_when_no_state(
        self, client: TestClient, state_file: Path
    ):
        response = client.get("/api/tenants/test-tenant/migration-status")
        assert response.status_code == 200

        data = response.json()
        assert data["tenant_id"] == "test-tenant"
        assert data["prompted"] is False
        assert data["completed"] is False
        assert data["accepted"] is False
        assert data["prompted_at"] is None
        assert data["completed_at"] is None

    def test_status_returns_saved_state(
        self, client: TestClient, state_file: Path
    ):
        _save_migration_state(
            {
                "test-tenant": {
                    "prompted": True,
                    "completed": True,
                    "accepted": True,
                    "prompted_at": "2026-05-26T10:00:00Z",
                    "completed_at": "2026-05-26T10:01:00Z",
                }
            }
        )

        response = client.get("/api/tenants/test-tenant/migration-status")
        data = response.json()

        assert data["prompted"] is True
        assert data["completed"] is True
        assert data["accepted"] is True
        assert data["prompted_at"] == "2026-05-26T10:00:00Z"
        assert data["completed_at"] == "2026-05-26T10:01:00Z"

    def test_status_returns_declined_state(
        self, client: TestClient, state_file: Path
    ):
        _save_migration_state(
            {
                "test-tenant": {
                    "prompted": True,
                    "completed": True,
                    "accepted": False,
                    "prompted_at": "2026-05-26T10:00:00Z",
                    "completed_at": "2026-05-26T10:01:00Z",
                }
            }
        )

        response = client.get("/api/tenants/test-tenant/migration-status")
        data = response.json()

        assert data["prompted"] is True
        assert data["completed"] is True
        assert data["accepted"] is False


# ===========================================================================
# POST /mark-migration-prompted
# ===========================================================================


class TestMarkMigrationPrompted:
    def test_mark_prompted_creates_state(
        self, client: TestClient, state_file: Path
    ):
        response = client.post("/api/tenants/test-tenant/mark-migration-prompted")
        assert response.status_code == 200

        data = response.json()
        assert data["tenant_id"] == "test-tenant"
        assert data["prompted"] is True
        assert data["prompted_at"] is not None

        state = _load_migration_state()
        assert state["test-tenant"]["prompted"] is True

    def test_mark_prompted_preserves_existing_state(
        self, client: TestClient, state_file: Path
    ):
        _save_migration_state(
            {
                "test-tenant": {
                    "completed": True,
                    "accepted": True,
                    "completed_at": "2026-05-26T10:01:00Z",
                }
            }
        )

        response = client.post("/api/tenants/test-tenant/mark-migration-prompted")
        data = response.json()

        assert data["prompted"] is True
        assert data["completed"] is True
        assert data["accepted"] is True


# ===========================================================================
# POST /decline-migration
# ===========================================================================


class TestDeclineMigration:
    def test_decline_marks_completed_not_accepted(
        self, client: TestClient, state_file: Path
    ):
        response = client.post("/api/tenants/test-tenant/decline-migration")
        assert response.status_code == 200

        data = response.json()
        assert data["tenant_id"] == "test-tenant"
        assert "declined" in data["message"].lower() or "not enabled" in data["message"].lower()

        state = _load_migration_state()
        assert state["test-tenant"]["completed"] is True
        assert state["test-tenant"]["accepted"] is False
        assert state["test-tenant"]["completed_at"] is not None

    def test_decline_also_marks_prompted(
        self, client: TestClient, state_file: Path
    ):
        response = client.post("/api/tenants/test-tenant/decline-migration")
        assert response.status_code == 200

        state = _load_migration_state()
        assert state["test-tenant"]["prompted"] is True
        assert state["test-tenant"]["prompted_at"] is not None


# ===========================================================================
# POST /migrate-industrial
# ===========================================================================


class TestMigrateIndustrial:
    def test_migrate_with_no_industrial_skills(
        self, client: TestClient, state_file: Path
    ):
        """When no industrial skills exist, migration completes with 0 enabled."""
        with patch(
            "deerflow.skills.storage.get_or_new_skill_storage",
        ) as mock_storage:
            mock_storage.return_value.load_skills.return_value = []

            response = client.post(
                "/api/tenants/test-tenant/migrate-industrial",
                headers={"x-deerflow-tenant": "test-tenant"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "test-tenant"
        assert data["enabled_count"] == 0
        assert data["skill_names"] == []

        state = _load_migration_state()
        assert state["test-tenant"]["completed"] is True
        assert state["test-tenant"]["accepted"] is True

    def test_migrate_marks_accepted_in_state(
        self, client: TestClient, state_file: Path
    ):
        """Migration should mark tenant as accepted."""
        with patch(
            "deerflow.skills.storage.get_or_new_skill_storage",
        ) as mock_storage:
            mock_storage.return_value.load_skills.return_value = []

            response = client.post(
                "/api/tenants/test-tenant/migrate-industrial",
                headers={"x-deerflow-tenant": "test-tenant"},
            )

        assert response.status_code == 200

        state = _load_migration_state()
        assert state["test-tenant"]["completed"] is True
        assert state["test-tenant"]["accepted"] is True
        assert state["test-tenant"]["completed_at"] is not None


# ===========================================================================
# State file helpers
# ===========================================================================


class TestStateFileHelpers:
    def test_load_empty_when_no_file(self, state_file: Path):
        state = _load_migration_state()
        assert state == {}

    def test_save_and_load_round_trip(self, state_file: Path):
        _save_migration_state(
            {
                "tenant-a": {"prompted": True, "completed": False},
                "tenant-b": {"prompted": True, "completed": True, "accepted": True},
            }
        )
        state = _load_migration_state()
        assert state["tenant-a"]["prompted"] is True
        assert state["tenant-a"]["completed"] is False
        assert state["tenant-b"]["accepted"] is True

    def test_load_handles_corrupted_file(self, state_file: Path):
        state_file.write_text("not valid json{{{")
        state = _load_migration_state()
        assert state == {}
