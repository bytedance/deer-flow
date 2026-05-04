"""Audit log storage — JSON-file persistence for content safety decisions."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


@dataclass
class AuditLogEntry:
    """A single content safety audit log entry."""

    timestamp: str
    tenant_id: str
    thread_id: str | None
    direction: str  # "input" or "output"
    role: str  # "user" or "assistant"
    original_text: str
    sanitized_text: str | None = None
    allowed: bool = True
    flagged_categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    provider: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "thread_id": self.thread_id,
            "direction": self.direction,
            "role": self.role,
            "original_text": self.original_text,
            "sanitized_text": self.sanitized_text,
            "allowed": self.allowed,
            "flagged_categories": self.flagged_categories,
            "reasons": self.reasons,
            "provider": self.provider,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AuditLogEntry:
        return cls(
            timestamp=d.get("timestamp", ""),
            tenant_id=d.get("tenant_id", ""),
            thread_id=d.get("thread_id"),
            direction=d.get("direction", ""),
            role=d.get("role", ""),
            original_text=d.get("original_text", ""),
            sanitized_text=d.get("sanitized_text"),
            allowed=d.get("allowed", True),
            flagged_categories=d.get("flagged_categories", []),
            reasons=d.get("reasons", []),
            provider=d.get("provider", ""),
        )


class AuditLogStorage:
    """JSON-file storage for content safety audit logs. Tenant-aware."""

    MAX_ENTRIES = 10000

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            from deerflow.config.paths import Paths

            self._paths = Paths(base_dir)
        else:
            self._paths = get_paths()

    @property
    def _log_file(self) -> Path:
        return self._paths.base_dir / "content_safety_logs.json"

    def _read(self) -> list[dict]:
        if not self._log_file.exists():
            return []
        try:
            with open(self._log_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read audit log file, starting fresh")
            return []

    def _write_atomic(self, entries: list[dict]) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._log_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._log_file)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def add_entry(self, entry: AuditLogEntry) -> None:
        entries = self._read()
        entries.append(entry.to_dict())
        if len(entries) > self.MAX_ENTRIES:
            entries = entries[-self.MAX_ENTRIES :]
        self._write_atomic(entries)

    def query(
        self,
        *,
        tenant_id: str | None = None,
        thread_id: str | None = None,
        direction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLogEntry], int]:
        entries = self._read()
        results: list[AuditLogEntry] = []
        for d in entries:
            rec = AuditLogEntry.from_dict(d)
            if tenant_id and rec.tenant_id != tenant_id:
                continue
            if thread_id and rec.thread_id != thread_id:
                continue
            if direction and rec.direction != direction:
                continue
            if start_date and rec.timestamp < start_date:
                continue
            if end_date and rec.timestamp > end_date:
                continue
            results.append(rec)

        total = len(results)
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[offset : offset + limit], total
