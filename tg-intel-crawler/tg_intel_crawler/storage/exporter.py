import csv
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from tg_intel_crawler.storage.sqlite_store import SQLiteStore


@dataclass
class IntelRecord:
    """A structured intelligence record after LLM analysis.

    The same shape works for both Telegram messages and Twitter tweets — the
    ``source_platform`` and ``source_url`` fields disambiguate the origin.
    """

    id: str
    source_group: str
    date: datetime
    sender_id: int = 0
    sender_name: str = ""
    sender_username: str = ""
    original_text: str = ""
    risk_type: str = ""
    risk_level: str = ""
    entities: dict = field(default_factory=dict)
    summary: str = ""
    llm_model: str = ""
    source_platform: str = "telegram"  # "telegram" | "twitter"
    source_url: str = ""


class Exporter:
    """Export filtered intelligence to JSON/CSV files with date rotation."""

    def __init__(
        self,
        output_dir: str,
        formats: list[str] = None,
        *,
        sqlite: bool = True,
        db_filename: str = "intel.db",
        source: str = "telegram",
    ):
        self._output_dir = Path(output_dir)
        self._formats = formats or ["json", "csv"]
        (self._output_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self._output_dir / "filtered").mkdir(parents=True, exist_ok=True)
        (self._output_dir / "errors").mkdir(parents=True, exist_ok=True)

        # SQLite is the primary store; JSON/CSV are kept as a compatible
        # dual-write so existing downstream consumers don't break. Tables are
        # per-source (``<source>_intel_raw`` / ``<source>_intel_filtered``) so
        # other data sources can share the same DB file. If the DB can't be
        # opened, fall back to file-only writes rather than crashing.
        self._store: Optional[SQLiteStore] = None
        if sqlite:
            try:
                self._store = SQLiteStore(
                    str(self._output_dir / db_filename), source=source
                )
            except Exception:
                self._store = None

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def export_filtered(
        self,
        records: list[IntelRecord],
        file_suffix: str = "",
    ) -> None:
        """Export analyzed intel records to JSON and/or CSV.

        Args:
            records: list of IntelRecord to write.
            file_suffix: optional suffix appended to the filename (e.g. ``"twitter"``
                produces ``intel_twitter_<date>.json``). Empty preserves the
                legacy ``intel_<date>.json`` filename.
        """
        if not records:
            return

        date_str = self._today_str()

        if "json" in self._formats:
            self._write_json(records, date_str, file_suffix)
        if "csv" in self._formats:
            self._write_csv(records, date_str, file_suffix)

        # Dual-write to SQLite (primary store, day-partitioned, (day,id) dedupe).
        if self._store is not None:
            try:
                payload = []
                for record in records:
                    d = asdict(record)
                    d["date"] = record.date.isoformat()
                    payload.append(d)
                self._store.insert_filtered(
                    payload, suffix=file_suffix, day=date_str
                )
            except Exception:
                # Never let a DB hiccup drop the file-based write that already
                # succeeded above.
                pass

    def _write_json(
        self,
        records: list[IntelRecord],
        date_str: str,
        file_suffix: str = "",
    ) -> None:
        suffix = f"_{file_suffix}" if file_suffix else ""
        filepath = self._output_dir / "filtered" / f"intel{suffix}_{date_str}.json"

        existing = []
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                existing = json.load(f)

        new_data = []
        for record in records:
            d = asdict(record)
            d["date"] = record.date.isoformat()
            new_data.append(d)

        existing.extend(new_data)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    def _write_csv(
        self,
        records: list[IntelRecord],
        date_str: str,
        file_suffix: str = "",
    ) -> None:
        suffix = f"_{file_suffix}" if file_suffix else ""
        filepath = self._output_dir / "filtered" / f"intel{suffix}_{date_str}.csv"

        fieldnames = [
            "id", "source_platform", "source_group", "date",
            "sender_id", "sender_name", "sender_username",
            "original_text", "risk_type", "risk_level",
            "entities", "summary", "llm_model", "source_url",
        ]

        file_exists = filepath.exists()
        with open(filepath, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            if not file_exists:
                writer.writeheader()
            for record in records:
                row = asdict(record)
                row["date"] = record.date.isoformat()
                row["entities"] = json.dumps(row["entities"], ensure_ascii=False)
                # 保留原始文本完整性：将换行替换为空格避免CSV断行
                row["original_text"] = row["original_text"].replace("\n", " ").replace("\r", "")
                writer.writerow(row)

    def export_raw(
        self,
        messages: list[dict],
        group_name: str,
        subdir: str = "",
    ) -> int:
        """Export raw messages (pre-filter) to a JSON file.

        Append-and-dedupe by message identity so the raw archive can keep
        accumulating across runs without growing duplicates. This makes the
        raw store safe to re-process if filter rules change later.

        Identity key (first match wins):
          - ``msg_id`` (Telegram), or
          - ``tweet_id`` (Twitter), or
          - the full record (fallback for older shapes).

        Args:
            messages: list of raw message/tweet dicts.
            group_name: source group / search keyword name (used in filename).
            subdir: optional subdirectory under ``raw/`` (e.g. ``"twitter"``).

        Returns:
            Number of NEW records actually appended (after dedupe).
        """
        if not messages:
            return 0

        date_str = self._today_str()
        safe_name = group_name.replace("/", "_").replace(" ", "_")
        target_dir = self._output_dir / "raw"
        if subdir:
            target_dir = target_dir / subdir
            target_dir.mkdir(parents=True, exist_ok=True)
        filepath = target_dir / f"{date_str}_{safe_name}.json"

        existing = []
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                existing = json.load(f)

        seen = set()
        for rec in existing:
            key = self._raw_identity_key(rec)
            if key is not None:
                seen.add(key)

        added = 0
        for msg in messages:
            key = self._raw_identity_key(msg)
            if key is not None and key in seen:
                continue
            existing.append(msg)
            if key is not None:
                seen.add(key)
            added += 1

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        # Dual-write to SQLite (day-partitioned, (day,identity) dedupe).
        if self._store is not None:
            try:
                self._store.insert_raw(
                    messages, group_name=group_name, subdir=subdir, day=date_str
                )
            except Exception:
                pass

        return added

    @staticmethod
    def _raw_identity_key(record: dict):
        """Return a stable identity for a raw record, or None if unidentifiable."""
        if not isinstance(record, dict):
            return None
        for k in ("msg_id", "tweet_id"):
            if k in record and record[k] is not None:
                return (k, record[k])
        return None

    def export_failed_batch(
        self,
        messages: list[dict],
        reason: str,
        group_name: str = "unknown",
    ) -> None:
        """Persist a batch that failed downstream processing (e.g. LLM error).

        Written to ``output/errors/`` so the data is never lost on the
        analysis path — the raw store is the source of truth, this is a
        breadcrumb showing what couldn't be analyzed and why, ready for
        manual re-run later.
        """
        if not messages:
            return

        date_str = self._today_str()
        safe_name = group_name.replace("/", "_").replace(" ", "_")
        filepath = self._output_dir / "errors" / f"{date_str}_{safe_name}_failed.json"

        existing = []
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                existing = json.load(f)

        existing.append({"reason": reason, "messages": messages})
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
