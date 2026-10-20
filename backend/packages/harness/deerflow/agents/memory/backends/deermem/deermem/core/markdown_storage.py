"""Opt-in Markdown-aware summary storage for DeerMem.

The default :class:`FileMemoryStorage` persists the user-memory *summary* as a
single JSON document. Reasoning/thinking models occasionally emit malformed
JSON, and a partially written summary historically raised
``MemoryStorageCorruption`` and took down the whole agent.

``MarkdownMemoryStorage`` keeps the same on-disk JSON as the default for full
backward compatibility, but its loader is *tolerant*:

* a corrupt or partially written summary no longer crashes the agent;
* a Markdown summary is accepted only through its fenced ```` ```memory-json ````
  block, which is parsed losslessly;
* invalid UTF-8 bytes, or text that is neither valid JSON nor a Markdown
  summary with a usable fenced block, trigger best-effort quarantine as
  ``memory.json.corrupt-<timestamp>`` before the loader returns ``None``.
  Quarantining keeps the content recoverable: returning ``None`` alone would
  make the next :meth:`save` rebuild the manifest from scratch (revision
  reset, no journal backup) and silently erase the unreadable state;
* file-access and I/O read failures raise ``MemoryStorageCorruption``, matching
  the default storage error contract. The original file stays in place, and
  reads and writes can be retried after access recovers.

Writes still persist JSON (the write path is untouched). Hand-edited
Markdown files are therefore a *read-time* convenience: the next write
rewrites ``memory.json`` as JSON, so the Markdown rendering is temporary
until a Markdown write path lands.

The tolerant decoding policy is scoped to this opt-in loader. Summary I/O
failures use the same storage error contract as the default backend.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .markdown_format import _parse_markdown_memory
from .storage import FileMemoryStorage, MemoryStorageCorruption, logger


class MarkdownMemoryStorage(FileMemoryStorage):
    """File-backed storage whose summary loader tolerates corrupt/Markdown.

    Fully opt-in. Enable via ``memory.backend_config.storage_class: markdown`` (or the full
    import path ``deerflow.agents.memory.backends.deermem.deermem.core.
    markdown_storage.MarkdownMemoryStorage``). The default JSON summary
    format is unchanged, so the existing JSON UI and all other backends keep
    working.
    """

    def _load_memory_file(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            # utf-8-sig, matching the base loader: a BOM does not make the
            # summary unreadable, so it must not trigger the quarantine path.
            raw = path.read_text(encoding="utf-8-sig")
        except UnicodeError as exc:
            logger.warning("Cannot decode memory summary %s as UTF-8: %s", path, exc)
            # Invalid text has the same quarantine contract as an unparseable
            # summary below: preserve its bytes before allowing a rebuild.
            self._quarantine_unreadable(path)
            return None
        except OSError as exc:
            # A failed read does not establish that the bytes are corrupt.
            # Match the default storage error contract, preserving the file
            # and preventing a write from rebuilding over a transient failure.
            raise MemoryStorageCorruption(f"Failed to read memory summary {path}: {exc}") from exc

        parsed: dict[str, Any] | None = None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            parsed = value
        else:
            # Not a JSON object: the opt-in Markdown summary is accepted only
            # through its lossless fenced ```memory-json block. No structured
            # fallback -- a best-effort section parse cannot reproduce the
            # manifest schema (object-shaped user/history) and previously
            # crashed load()/save() on the files it claimed to tolerate.
            parsed = _parse_markdown_memory(raw)

        if parsed is not None:
            return parsed

        logger.warning(
            "Memory summary %s is unreadable (neither valid JSON nor a Markdown summary with a usable ```memory-json block); quarantining the file so its content stays recoverable instead of being silently overwritten by the next save.",
            path,
        )
        self._quarantine_unreadable(path)
        return None

    @staticmethod
    def _quarantine_unreadable(path: Path) -> None:
        """Move an unreadable summary aside; the next save rebuilds from scratch.

        Without this, returning ``None`` would let ``_commit_changes_locked``
        rebuild the manifest from ``create_empty_memory()`` and skip its
        recovery backup (which only runs when a current memory exists),
        silently destroying the previous state.
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            path.replace(target)
            logger.warning("Quarantined unreadable memory summary as %s", target)
        except OSError as exc:
            # Quarantine is best-effort: keep the tolerant-read guarantee.
            logger.error("Could not quarantine unreadable memory summary %s: %s", path, exc)
