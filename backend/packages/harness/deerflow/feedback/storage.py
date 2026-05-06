"""User feedback storage — JSON-file persistence for thumbs up/down feedback."""

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
class FeedbackEntry:
    """A single user feedback entry."""

    id: str
    tenant_id: str
    thread_id: str
    message_id: str
    rating: int  # 1-5
    categories: list[str] = field(default_factory=list)
    comment: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "rating": self.rating,
            "categories": self.categories,
            "comment": self.comment,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FeedbackEntry:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            thread_id=d["thread_id"],
            message_id=d["message_id"],
            rating=d["rating"],
            categories=d.get("categories", []),
            comment=d.get("comment", ""),
            created_at=d.get("created_at", ""),
        )


class FeedbackStorage:
    """JSON-file storage for user feedback. Tenant-aware."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            from deerflow.config.paths import Paths

            self._paths = Paths(base_dir)
        else:
            self._paths = get_paths()

    @property
    def _feedback_file(self) -> Path:
        return self._paths.tenant_base_dir / "feedback.json"

    def _read(self) -> list[dict]:
        if not self._feedback_file.exists():
            return []
        try:
            with open(self._feedback_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read feedback file, starting fresh")
            return []

    def _write_atomic(self, records: list[dict]) -> None:
        self._feedback_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._feedback_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._feedback_file)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def add(self, entry: FeedbackEntry) -> None:
        records = self._read()
        records.append(entry.to_dict())
        self._write_atomic(records)

    def query(
        self,
        *,
        thread_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[FeedbackEntry]:
        records = self._read()
        results: list[FeedbackEntry] = []
        for d in records:
            entry = FeedbackEntry.from_dict(d)
            if thread_id and entry.thread_id != thread_id:
                continue
            if start_date and entry.created_at < start_date:
                continue
            if end_date and entry.created_at > end_date:
                continue
            results.append(entry)
        return results

    def get_summary(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        entries = self.query(start_date=start_date, end_date=end_date)
        if not entries:
            return {
                "total_feedback": 0,
                "avg_rating": 0.0,
                "rating_distribution": {},
                "top_categories": [],
            }

        ratings = [e.rating for e in entries]
        avg_rating = sum(ratings) / len(ratings)

        distribution: dict[str, int] = {}
        for r in ratings:
            key = str(r)
            distribution[key] = distribution.get(key, 0) + 1

        cat_counts: dict[str, int] = {}
        for e in entries:
            for cat in e.categories:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        top_categories = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_feedback": len(entries),
            "avg_rating": round(avg_rating, 2),
            "rating_distribution": distribution,
            "top_categories": [{"category": c, "count": n} for c, n in top_categories],
        }

    # ------------------------------------------------------------------
    # Cross-tenant helpers (for admin endpoints)
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_tenant_feedback_files(base_dir: Path) -> list[tuple[str, Path]]:
        result: list[tuple[str, Path]] = []
        default_file = base_dir / "feedback.json"
        if default_file.exists():
            result.append(("default", default_file))
        tenants_root = base_dir / "tenants"
        if tenants_root.is_dir():
            for child in sorted(tenants_root.iterdir()):
                if not child.is_dir():
                    continue
                fb_file = child / "feedback.json"
                if fb_file.exists():
                    result.append((child.name, fb_file))
        return result

    @staticmethod
    def _read_file(path: Path) -> list[dict]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    @classmethod
    def query_all_tenants(
        cls,
        base_dir: Path | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        tenant_id: str | None = None,
    ) -> list[FeedbackEntry]:
        if base_dir is None:
            base_dir = get_paths().base_dir

        all_entries: list[FeedbackEntry] = []
        for tid, file_path in cls._iter_tenant_feedback_files(base_dir):
            if tenant_id and tid != tenant_id:
                continue
            for d in cls._read_file(file_path):
                entry = FeedbackEntry.from_dict(d)
                if start_date and entry.created_at < start_date:
                    continue
                if end_date and entry.created_at > end_date:
                    continue
                all_entries.append(entry)

        all_entries.sort(key=lambda e: e.created_at, reverse=True)
        return all_entries

    @classmethod
    def get_cross_tenant_summary(
        cls,
        base_dir: Path | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        entries = cls.query_all_tenants(
            base_dir=base_dir,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )
        if not entries:
            return {
                "total_feedback": 0,
                "avg_rating": 0.0,
                "rating_distribution": {},
                "top_categories": [],
            }

        ratings = [e.rating for e in entries]
        avg_rating = sum(ratings) / len(ratings)

        distribution: dict[str, int] = {}
        for r in ratings:
            key = str(r)
            distribution[key] = distribution.get(key, 0) + 1

        cat_counts: dict[str, int] = {}
        for e in entries:
            for cat in e.categories:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        top_categories = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_feedback": len(entries),
            "avg_rating": round(avg_rating, 2),
            "rating_distribution": distribution,
            "top_categories": [{"category": c, "count": n} for c, n in top_categories],
        }
