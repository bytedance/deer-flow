"""Index of raw Telegram messages keyed by (group_name, msg_id).

Built once at startup by scanning output/raw/<date>_<group>.json files.
Returns None for missing keys — callers must handle the miss path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("tg_crawler")


class RawMessageLookup:
    """In-memory index of raw messages, keyed by (group_name, msg_id) -> text."""

    def __init__(self, raw_dir: str | Path):
        self._raw_dir = Path(raw_dir)
        self._index: dict[tuple[str, int], str] = {}
        if self._raw_dir.exists():
            self._build_index()

    def _build_index(self) -> None:
        for path in self._raw_dir.glob("*.json"):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("raw_lookup: skip %s: %s", path, e)
                continue
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                msg_id = rec.get("msg_id")
                group_name = rec.get("group_name")
                text = rec.get("text") or ""
                if msg_id is None or not group_name:
                    continue
                self._index[(group_name, int(msg_id))] = text

    def get(self, group_name: str, msg_id: int) -> str | None:
        return self._index.get((group_name, int(msg_id)))

    def size(self) -> int:
        return len(self._index)
