"""Tests for get_usage_storage factory and PgUsageStorage."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.cost.pg_storage import PgUsageStorage
from deerflow.cost.storage import UsageStorage, get_usage_storage


class TestGetUsageStorage:
    """Tests for the get_usage_storage() factory function."""

    def test_returns_json_storage_by_default(self):
        """Default storage_backend='json' returns UsageStorage."""
        mock_cost_cfg = MagicMock()
        mock_cost_cfg.storage_backend = "json"

        with patch("deerflow.config.cost_config.get_cost_config", return_value=mock_cost_cfg):
            storage = get_usage_storage()
            assert isinstance(storage, UsageStorage)

    def test_returns_pg_storage_when_postgres(self):
        """storage_backend='postgres' returns PgUsageStorage."""
        mock_cost_cfg = MagicMock()
        mock_cost_cfg.storage_backend = "postgres"

        mock_app_cfg = MagicMock()
        mock_app_cfg.database.postgres_url = "postgresql://localhost/test"

        with (
            patch("deerflow.config.cost_config.get_cost_config", return_value=mock_cost_cfg),
            patch("deerflow.config.app_config.get_app_config", return_value=mock_app_cfg),
        ):
            storage = get_usage_storage()
            assert isinstance(storage, PgUsageStorage)
            assert storage._dsn == "postgresql://localhost/test"


class TestPgUsageStorage:
    """Tests for PgUsageStorage interface compatibility."""

    def test_fallback_to_json_when_no_dsn(self):
        """PgUsageStorage with empty DSN falls back to JSON storage."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = PgUsageStorage(dsn="", base_dir=Path(tmp))
            assert not storage.available

    def test_has_query_all_tenants(self):
        """PgUsageStorage implements query_all_tenants for admin router compatibility."""
        storage = PgUsageStorage(dsn="")
        assert hasattr(storage, "query_all_tenants")
        assert callable(storage.query_all_tenants)

    def test_query_all_tenants_falls_back(self):
        """query_all_tenants falls back to JSON when postgres unavailable."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = PgUsageStorage(dsn="", base_dir=Path(tmp))
            records = storage.query_all_tenants()
            assert isinstance(records, list)
