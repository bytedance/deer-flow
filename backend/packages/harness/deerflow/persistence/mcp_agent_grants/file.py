"""File-backed runtime MCP agent grants, one JSON file per binding."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from deerflow.config.mcp_agent_auth_config import StoredMcpAgentGrant
from deerflow.config.paths import get_paths
from deerflow.persistence.mcp_agent_grants import McpAgentGrantStore
from deerflow.utils.atomic_write import cleanup_failed_atomic_write
from deerflow.utils.host_paths import windows_incompatible_segment

_write_lock = threading.RLock()


class FileMcpAgentGrantStore(McpAgentGrantStore):
    @staticmethod
    def _root() -> Path:
        return get_paths().base_dir / "mcp-agent-grants"

    def _read(self, path: Path) -> tuple[str, StoredMcpAgentGrant] | None:
        """Read one grant file; None when a concurrent delete removed it.

        Parse errors and other I/O failures still raise.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        document = json.loads(text)
        return document.pop("binding"), StoredMcpAgentGrant.model_validate(document)

    def get(self, binding_id: str) -> StoredMcpAgentGrant | None:
        entry = self._read(self._root() / f"{binding_id}.json")
        if entry is None:
            return None
        stored_id, grant = entry
        # A case-insensitive filesystem maps "A" and "a" to one file; a grant
        # never applies to a binding it was not written for.
        return grant if stored_id == binding_id else None

    def list(self) -> dict[str, StoredMcpAgentGrant]:
        root = self._root()
        if not root.exists():
            return {}
        entries = (self._read(path) for path in root.glob("*.json"))
        return dict(sorted(entry for entry in entries if entry is not None))

    def put(self, binding_id: str, grant: StoredMcpAgentGrant) -> None:
        reason = windows_incompatible_segment(binding_id)
        if reason is not None:
            raise ValueError(f"Binding ID {binding_id!r} cannot be stored as a file: {reason}")
        root = self._root()
        payload = json.dumps({"binding": binding_id, **grant.model_dump(mode="json")}, indent=2) + "\n"
        with _write_lock:
            root.mkdir(parents=True, exist_ok=True)
            path = root / f"{binding_id}.json"
            existing = self._read(path)
            if existing is not None and existing[0] != binding_id:
                raise ValueError(f"Binding ID {binding_id!r} collides with a stored grant that differs only in case")
            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=root, suffix=".tmp", delete=False) as handle:
                    tmp_path = Path(handle.name)
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, path)
                tmp_path = None
            finally:
                if tmp_path is not None:
                    cleanup_failed_atomic_write(tmp_path)

    def delete(self, binding_id: str) -> bool:
        path = self._root() / f"{binding_id}.json"
        with _write_lock:
            existing = self._read(path)
            if existing is None or existing[0] != binding_id:
                return False
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            return True
