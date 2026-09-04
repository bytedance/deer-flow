"""File-backed managed subagent store."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from collections.abc import Hashable
from pathlib import Path

from deerflow.config.paths import get_paths
from deerflow.persistence.managed_subagents.base import (
    ManagedSubagentDefinition,
    ManagedSubagentExistsError,
    ManagedSubagentStore,
    normalize_managed_subagent_name,
)

logger = logging.getLogger(__name__)
_write_lock = threading.RLock()


def _normalized_name(name: str) -> str:
    return normalize_managed_subagent_name(name)


class FileManagedSubagentStore(ManagedSubagentStore):
    def cache_identity(self) -> Hashable:
        return ("file", str(get_paths().managed_subagents_dir))

    def get(self, name: str) -> ManagedSubagentDefinition:
        path = get_paths().managed_subagent_file(_normalized_name(name))
        if not path.is_file():
            raise FileNotFoundError(f"Managed subagent not found: {name}")
        return ManagedSubagentDefinition.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[ManagedSubagentDefinition]:
        root = get_paths().managed_subagents_dir
        if not root.exists():
            return []
        definitions: list[ManagedSubagentDefinition] = []
        for path in sorted(root.glob("*.json")):
            try:
                definitions.append(ManagedSubagentDefinition.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 — one corrupt definition must not hide the catalog
                logger.warning("Skipping invalid managed subagent definition %s", path, exc_info=True)
        return sorted(definitions, key=lambda item: item.name)

    def create(self, definition: ManagedSubagentDefinition) -> None:
        path = get_paths().managed_subagent_file(definition.name)
        with _write_lock:
            if path.exists():
                raise ManagedSubagentExistsError(f"Managed subagent '{definition.name}' already exists")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, definition)

    def update(self, definition: ManagedSubagentDefinition) -> None:
        path = get_paths().managed_subagent_file(definition.name)
        with _write_lock:
            if not path.is_file():
                raise FileNotFoundError(f"Managed subagent not found: {definition.name}")
            self._atomic_write(path, definition)

    def delete(self, name: str) -> bool:
        path = get_paths().managed_subagent_file(_normalized_name(name))
        with _write_lock:
            if not path.is_file():
                return False
            path.unlink()
            return True

    def signature(self) -> Hashable:
        root = get_paths().managed_subagents_dir
        if not root.exists():
            return ()
        signature: list[tuple[str, int, int]] = []
        for path in sorted(root.glob("*.json")):
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    @staticmethod
    def _atomic_write(path: Path, definition: ManagedSubagentDefinition) -> None:
        payload = definition.model_dump_json(indent=2) + "\n"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                tmp_path = Path(handle.name)
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
