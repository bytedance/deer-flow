"""Opt-in Markdown-aware summary storage for DeerMem.

The default :class:`FileMemoryStorage` persists the user-memory *summary* as a
single JSON document. Reasoning/thinking models occasionally emit malformed
JSON, and a partially written summary historically raised
``MemoryStorageCorruption`` and took down the whole agent.

``MarkdownMemoryStorage`` keeps the same on-disk JSON as the default for full
backward compatibility, but its loader is *tolerant*: a corrupt or partially
written summary no longer crashes the agent. It also understands a Markdown
summary (fenced ``memory-json`` block is the lossless source, with a
best-effort structured fallback), so operators can hand-edit memory in a
readable format.

This is intentionally a small, additive change scoped to the load path only:
the write path and the JSON UI are untouched. Enabling it cannot break
existing deployments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .markdown_format import _looks_like_markdown, _parse_markdown_memory
from .storage import FileMemoryStorage, logger


class MarkdownMemoryStorage(FileMemoryStorage):
    """File-backed storage whose summary loader tolerates Markdown/JSON.

    Fully opt-in. Enable via ``memory.storage_class: markdown`` (or the full
    import path ``deerflow.agents.memory.backends.deermem.deermem.core.
    markdown_storage.MarkdownMemoryStorage``). The default JSON summary
    format is unchanged, so the existing JSON UI and all other backends keep
    working.
    """

    def _load_memory_file(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            logger.warning("Cannot read memory summary %s: %s", path, exc)
            return None

        # Opt-in Markdown summary: the fenced ```memory-json block is lossless.
        if _looks_like_markdown(raw):
            parsed = _parse_markdown_memory(raw)
            if isinstance(parsed, dict):
                return parsed

        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            recovered = _parse_markdown_memory(raw)
            if isinstance(recovered, dict):
                return recovered
            logger.warning(
                "Memory summary %s is neither valid JSON nor parseable Markdown; "
                "starting from an empty memory instead of crashing the agent.",
                path,
            )
            return None

        if not isinstance(value, dict):
            logger.warning("Memory summary %s is not a JSON object; starting fresh.", path)
            return None
        return value
