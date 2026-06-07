import re
from pathlib import Path
from typing import Optional

import yaml


class KeywordFilter:
    """Dual-dimension keyword filter: products x actions."""

    def __init__(self, keywords_path: str):
        with open(keywords_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._product_patterns = self._compile_patterns(data.get("products", []))
        self._action_patterns = self._compile_patterns(data.get("actions", []))

    def _compile_patterns(self, keywords: list[str]) -> list[re.Pattern]:
        """Compile keywords into case-insensitive regex patterns."""
        patterns = []
        for kw in keywords:
            escaped = re.escape(kw.strip())
            patterns.append(re.compile(escaped, re.IGNORECASE))
        return patterns

    def matches(self, text: Optional[str]) -> bool:
        """Return True if text matches at least one product AND one action keyword."""
        if not text:
            return False

        has_product = any(p.search(text) for p in self._product_patterns)
        if not has_product:
            return False

        has_action = any(p.search(text) for p in self._action_patterns)
        return has_action

    def get_matched_keywords(self, text: Optional[str]) -> dict:
        """Return dict of matched product and action keywords."""
        if not text:
            return {"products": [], "actions": []}

        products = [p.pattern for p in self._product_patterns if p.search(text)]
        actions = [p.pattern for p in self._action_patterns if p.search(text)]
        return {"products": products, "actions": actions}
