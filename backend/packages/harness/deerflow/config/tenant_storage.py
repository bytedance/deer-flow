"""Tenant storage — JSON-file persistence for tenant configurations."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


@dataclass
class TenantConfig:
    """Persisted configuration for a single tenant."""

    tenant_id: str
    name: str
    created_at: str = ""
    is_active: bool = True
    daily_quota_usd: float = 50.0
    monthly_quota_usd: float = 1000.0

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "daily_quota_usd": self.daily_quota_usd,
            "monthly_quota_usd": self.monthly_quota_usd,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TenantConfig:
        return cls(
            tenant_id=d["tenant_id"],
            name=d["name"],
            created_at=d.get("created_at", ""),
            is_active=d.get("is_active", True),
            daily_quota_usd=d.get("daily_quota_usd", 50.0),
            monthly_quota_usd=d.get("monthly_quota_usd", 1000.0),
        )


class TenantStorage:
    """JSON-file storage for tenant configurations. Cross-tenant (admin-scoped)."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            from deerflow.config.paths import Paths

            self._paths = Paths(base_dir)
        else:
            self._paths = get_paths()

    @property
    def _tenants_file(self) -> Path:
        return self._paths.base_dir / "tenants.json"

    def _read(self) -> list[dict]:
        if not self._tenants_file.exists():
            return []
        try:
            with open(self._tenants_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read tenants file, starting fresh")
            return []

    def _write_atomic(self, tenants: list[dict]) -> None:
        self._tenants_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._tenants_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(tenants, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._tenants_file)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def list_all(self) -> list[TenantConfig]:
        return [TenantConfig.from_dict(d) for d in self._read()]

    def get(self, tenant_id: str) -> TenantConfig | None:
        for d in self._read():
            if d.get("tenant_id") == tenant_id:
                return TenantConfig.from_dict(d)
        return None

    def create(self, config: TenantConfig) -> TenantConfig:
        tenants = self._read()
        for d in tenants:
            if d.get("tenant_id") == config.tenant_id:
                raise ValueError(f"Tenant {config.tenant_id!r} already exists")
        if not config.created_at:
            config.created_at = datetime.now(timezone.utc).isoformat()
        tenants.append(config.to_dict())
        self._write_atomic(tenants)
        return config

    def update(self, tenant_id: str, **fields) -> TenantConfig | None:
        tenants = self._read()
        for i, d in enumerate(tenants):
            if d.get("tenant_id") == tenant_id:
                updated = {**d, **{k: v for k, v in fields.items() if v is not None}}
                tenants[i] = updated
                self._write_atomic(tenants)
                return TenantConfig.from_dict(updated)
        return None

    def delete(self, tenant_id: str) -> bool:
        tenants = self._read()
        new_tenants = [d for d in tenants if d.get("tenant_id") != tenant_id]
        if len(new_tenants) == len(tenants):
            return False
        self._write_atomic(new_tenants)
        return True

    def ensure_default(self) -> TenantConfig:
        """Ensure the 'default' tenant exists, creating it if needed."""
        existing = self.get("default")
        if existing is not None:
            return existing
        config = TenantConfig(
            tenant_id="default",
            name="Default Tenant",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.create(config)
        return config
