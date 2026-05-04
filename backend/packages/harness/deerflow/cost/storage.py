"""Usage storage — JSON-file persistence for token usage records."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """A single token usage record."""

    timestamp: str
    tenant_id: str
    thread_id: str | None
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "thread_id": self.thread_id,
            "model_name": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, d: dict) -> UsageRecord:
        return cls(
            timestamp=d["timestamp"],
            tenant_id=d["tenant_id"],
            thread_id=d.get("thread_id"),
            model_name=d["model_name"],
            input_tokens=d["input_tokens"],
            output_tokens=d["output_tokens"],
            total_tokens=d["total_tokens"],
            cost_usd=d["cost_usd"],
        )


class UsageStorage:
    """JSON-file storage for token usage records. Tenant-aware."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            from deerflow.config.paths import Paths

            self._paths = Paths(base_dir)
        else:
            self._paths = get_paths()

    @property
    def _usage_file(self) -> Path:
        return self._paths.tenant_base_dir / "token_usage.json"

    def _read(self) -> list[dict]:
        if not self._usage_file.exists():
            return []
        try:
            with open(self._usage_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read usage file, starting fresh")
            return []

    def _write_atomic(self, records: list[dict]) -> None:
        self._usage_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._usage_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._usage_file)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def add_record(self, record: UsageRecord) -> None:
        """Append a usage record atomically."""
        records = self._read()
        records.append(record.to_dict())
        self._write_atomic(records)

    def query(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        model_name: str | None = None,
    ) -> list[UsageRecord]:
        """Query usage records with optional filters."""
        records = self._read()
        results: list[UsageRecord] = []
        for d in records:
            rec = UsageRecord.from_dict(d)
            if start_date and rec.timestamp < start_date:
                continue
            if end_date and rec.timestamp > end_date:
                continue
            if model_name and rec.model_name != model_name:
                continue
            results.append(rec)
        return results

    def get_daily_total(self, date_str: str) -> float:
        """Get total cost for a specific day (YYYY-MM-DD)."""
        records = self.query(start_date=date_str, end_date=date_str + "T23:59:59")
        return sum(r.cost_usd for r in records)

    def get_monthly_total(self, year_month: str) -> float:
        """Get total cost for a specific month (YYYY-MM)."""
        start = f"{year_month}-01"
        end = f"{year_month}-31"
        records = self.query(start_date=start, end_date=end)
        return sum(r.cost_usd for r in records)

    def get_today_total(self) -> float:
        """Get total cost for today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.get_daily_total(today)

    def get_current_month_total(self) -> float:
        """Get total cost for the current month."""
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self.get_monthly_total(month)

    def get_total_tokens_today(self) -> int:
        """Get total tokens used today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        records = self.query(start_date=today)
        return sum(r.total_tokens for r in records)

    def get_total_tokens_month(self) -> int:
        """Get total tokens used this month."""
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        records = self.query(start_date=f"{month}-01")
        return sum(r.total_tokens for r in records)

    # ------------------------------------------------------------------
    # Cross-tenant helpers (for admin endpoints)
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_tenant_usage_files(base_dir: Path) -> list[tuple[str, Path]]:
        """Discover all ``token_usage.json`` files across tenant directories.

        Returns a list of ``(tenant_id, file_path)`` tuples.
        """
        result: list[tuple[str, Path]] = []

        # Default tenant file (backward-compatible single-tenant layout)
        default_file = base_dir / "token_usage.json"
        if default_file.exists():
            result.append(("default", default_file))

        # Named tenant directories
        tenants_root = base_dir / "tenants"
        if tenants_root.is_dir():
            for child in sorted(tenants_root.iterdir()):
                if not child.is_dir():
                    continue
                usage_file = child / "token_usage.json"
                if usage_file.exists():
                    result.append((child.name, usage_file))

        return result

    @staticmethod
    def _read_file(path: Path) -> list[dict]:
        """Read a single usage JSON file, returning parsed records."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read usage file %s", path)
            return []

    @classmethod
    def query_all_tenants(
        cls,
        base_dir: Path | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        model_name: str | None = None,
    ) -> list[UsageRecord]:
        """Query usage records across **all** tenants.

        This is the admin-facing equivalent of :meth:`query` — it scans every
        tenant directory under *base_dir* and returns a merged, time-sorted
        result set.
        """
        if base_dir is None:
            base_dir = get_paths().base_dir

        all_records: list[UsageRecord] = []
        for _tid, file_path in cls._iter_tenant_usage_files(base_dir):
            for d in cls._read_file(file_path):
                rec = UsageRecord.from_dict(d)
                if start_date and rec.timestamp < start_date:
                    continue
                if end_date and rec.timestamp > end_date:
                    continue
                if model_name and rec.model_name != model_name:
                    continue
                all_records.append(rec)

        all_records.sort(key=lambda r: r.timestamp, reverse=True)
        return all_records
