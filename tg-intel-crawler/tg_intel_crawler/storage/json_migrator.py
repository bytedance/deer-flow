"""One-shot backfill of legacy JSON files into the SQLite store.

Reads the existing ``output/raw/**/*.json`` and ``output/filtered/*.json``
files (the pre-SQLite archive) and inserts them into ``intel.db`` with the
same ``(day, id)`` dedupe semantics as live writes. Idempotent — re-running
won't create duplicates.

``day`` resolution:
- filtered: prefer the date in the filename (``intel_<day>.json`` /
  ``intel_<suffix>_<day>.json``); fall back to the record's ``date`` field.
- raw: prefer the date prefix in the filename (``<day>_<group>.json``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tg_intel_crawler.storage.sqlite_store import SQLiteStore

_DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# intel_<day>.json  or  intel_<suffix>_<day>.json
_FILTERED_NAME_RE = re.compile(
    r"^intel(?:_(?P<suffix>[A-Za-z0-9]+))?_(?P<day>\d{4}-\d{2}-\d{2})\.json$"
)


def _day_from_text(text: str) -> str | None:
    m = _DAY_RE.search(text or "")
    return m.group(1) if m else None


def migrate_json_to_sqlite(output_dir: str) -> dict:
    """Backfill raw + filtered JSON under ``output_dir`` into intel.db.

    Returns a stats dict: {raw_files, raw_inserted, filtered_files,
    filtered_inserted}.
    """
    out = Path(output_dir)
    store = SQLiteStore(str(out / "intel.db"))
    stats = {
        "raw_files": 0, "raw_inserted": 0,
        "filtered_files": 0, "filtered_inserted": 0,
    }

    # ---- filtered ----
    filtered_dir = out / "filtered"
    if filtered_dir.exists():
        for fp in sorted(filtered_dir.glob("*.json")):
            try:
                records = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(records, list) or not records:
                continue

            m = _FILTERED_NAME_RE.match(fp.name)
            file_day = m.group("day") if m else _day_from_text(fp.name)
            suffix = (m.group("suffix") if m else "") or ""

            # Group records by their effective day so cross-day files (rare)
            # still partition correctly.
            by_day: dict[str, list[dict]] = {}
            for r in records:
                day = file_day or _day_from_text(r.get("date", "")) or "unknown"
                by_day.setdefault(day, []).append(r)

            stats["filtered_files"] += 1
            for day, recs in by_day.items():
                stats["filtered_inserted"] += store.insert_filtered(
                    recs, suffix=suffix, day=day
                )

    # ---- raw ----
    raw_dir = out / "raw"
    if raw_dir.exists():
        for fp in sorted(raw_dir.rglob("*.json")):
            try:
                messages = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(messages, list) or not messages:
                continue

            # filename: <day>_<group>.json ; subdir = parent under raw/
            file_day = _day_from_text(fp.name)
            rel_parent = fp.parent.relative_to(raw_dir)
            subdir = "" if str(rel_parent) == "." else str(rel_parent)
            group_name = messages[0].get("group_name", fp.stem)

            stats["raw_files"] += 1
            day = file_day or "unknown"
            stats["raw_inserted"] += store.insert_raw(
                messages, group_name=group_name, subdir=subdir, day=day
            )

    store.close()
    return stats
