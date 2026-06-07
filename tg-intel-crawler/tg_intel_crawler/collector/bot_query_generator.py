"""Generate bot-search queries from keywords.yaml or explicit overrides."""

from __future__ import annotations

from pathlib import Path

import yaml


class QueryGenerator:
    """Build query strings to feed a search bot.

    Default mode: take products × actions from keywords.yaml as " ".join pairs.
    Override mode: caller supplies explicit query strings (CLI --keywords).
    """

    def __init__(self, keywords_path: str | Path):
        self._path = Path(keywords_path)

    def generate(
        self,
        *,
        max_queries: int,
        override_keywords: list[str] | None = None,
    ) -> list[str]:
        if override_keywords is not None:
            return self._dedupe_truncate(override_keywords, max_queries)

        data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        products = [p.strip() for p in (data.get("products") or []) if p and p.strip()]
        actions = [a.strip() for a in (data.get("actions") or []) if a and a.strip()]
        if not products or not actions:
            return []

        pairs = [f"{p} {a}" for p in products for a in actions]
        return self._dedupe_truncate(pairs, max_queries)

    @staticmethod
    def _dedupe_truncate(items: list[str], cap: int) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            it = (it or "").strip()
            if not it or it in seen:
                continue
            seen.add(it)
            out.append(it)
            if len(out) >= cap:
                break
        return out
