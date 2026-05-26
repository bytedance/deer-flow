"""Tests for CostConfig storage_backend validation (Task 3.5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.cost_config import CostConfig


class TestStorageBackendValidation:
    """Literal type rejects invalid storage_backend values."""

    def test_json_accepted(self):
        cfg = CostConfig(storage_backend="json")
        assert cfg.storage_backend == "json"

    def test_postgres_accepted(self):
        cfg = CostConfig(storage_backend="postgres")
        assert cfg.storage_backend == "postgres"

    def test_invalid_value_rejected(self):
        with pytest.raises(ValidationError):
            CostConfig(storage_backend="redis")

    def test_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            CostConfig(storage_backend="")

    def test_default_is_json(self):
        cfg = CostConfig()
        assert cfg.storage_backend == "json"
