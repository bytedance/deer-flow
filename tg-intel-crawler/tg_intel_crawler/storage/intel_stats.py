"""Per-source-group intel reputation, derived from output/filtered/intel_*.json.

Scans every intel_*.json file once at startup and tallies how many high /
medium / total records each ``source_group`` produced. Used by the LLM
candidate reviewer's Stage 1 to weigh signals from already-known black/gray
groups higher than signals from low-value groups.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("tg_crawler")


class IntelStatsAggregator:
    """Aggregate filtered intel by source_group."""

    def __init__(self, filtered_dir: str | Path):
        self._dir = Path(filtered_dir)
        # group_name -> {"high": int, "medium": int, "total_msgs": int}
        self._scores: dict[str, dict[str, int]] = {}
        if self._dir.exists():
            self._build()

    def _build(self) -> None:
        # Match all intel*.json files (intel_2026-06-05.json,
        # intel_twitter_2026-06-05.json, intel_bot_2026-06-05.json, ...).
        for path in self._dir.glob("intel*.json"):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("intel_stats: skip %s: %s", path, e)
                continue
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                grp = rec.get("source_group")
                if not grp:
                    continue
                level = (rec.get("risk_level") or "").lower()
                bucket = self._scores.setdefault(
                    grp, {"high": 0, "medium": 0, "total_msgs": 0}
                )
                bucket["total_msgs"] += 1
                if level == "high":
                    bucket["high"] += 1
                elif level == "medium":
                    bucket["medium"] += 1

    def score_for(self, group_name: str) -> dict[str, int]:
        return self._scores.get(
            group_name, {"high": 0, "medium": 0, "total_msgs": 0}
        )

    def all_scores(self) -> dict[str, dict[str, int]]:
        return dict(self._scores)
