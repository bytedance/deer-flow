"""Insights cache interface and JSON-file implementation.

The cache stores aggregation results, improvement suggestions, and KB candidates
with tenant isolation. The JSON-file implementation is suitable for MVP; the
interface is designed to swap to PostgreSQL once migration lands.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from deerflow.config.paths import Paths


class InsightsCache(ABC):
    """Abstract cache interface for insights data."""

    @abstractmethod
    def get(self, tenant_id: str, key: str) -> Any | None:
        """Retrieve cached data for a tenant."""

    @abstractmethod
    def set(self, tenant_id: str, key: str, value: Any) -> None:
        """Store data in cache for a tenant."""

    @abstractmethod
    def delete(self, tenant_id: str, key: str) -> None:
        """Remove cached data for a tenant."""

    @abstractmethod
    def list_keys(self, tenant_id: str, prefix: str = "") -> list[str]:
        """List all cache keys for a tenant, optionally filtered by prefix."""


class JsonFileInsightsCache(InsightsCache):
    """JSON-file implementation with tenant isolation.

    Storage layout: ``{DEER_FLOW_HOME}/insights/{tenant_id}/{key}.json``
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        paths = Paths(base_dir)
        self._insights_dir = paths.base_dir / "insights"

    def _cache_path(self, tenant_id: str, key: str) -> Path:
        tenant_dir = self._insights_dir / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir / f"{key}.json"

    def get(self, tenant_id: str, key: str) -> Any | None:
        path = self._cache_path(tenant_id, key)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, tenant_id: str, key: str, value: Any) -> None:
        path = self._cache_path(tenant_id, key)
        tmp_path = path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
        os.replace(tmp_path, path)

    def delete(self, tenant_id: str, key: str) -> None:
        path = self._cache_path(tenant_id, key)
        if path.exists():
            path.unlink()

    def list_keys(self, tenant_id: str, prefix: str = "") -> list[str]:
        tenant_dir = self._insights_dir / tenant_id
        if not tenant_dir.exists():
            return []
        keys = []
        for path in tenant_dir.glob("*.json"):
            key = path.stem
            if key.startswith(prefix):
                keys.append(key)
        return sorted(keys)
