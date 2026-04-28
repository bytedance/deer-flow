"""Global variables storage provider."""

import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

SYSTEM_VARIABLES: dict[str, Any] = {
    "workdir": {
        "value": "/mnt/shared-data",
        "description": "Shared workspace directory",
        "is_system": True,
        "llm_editable": False,
        "updated_at": "system",
        "updated_by": "system",
    },
}


def utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def create_empty_variables() -> dict[str, Any]:
    return {"variables": {}}


def get_system_variables() -> dict[str, Any]:
    return {"variables": dict(SYSTEM_VARIABLES), "is_system": True}


class GlobalVariablesStorage:
    """File-based storage for global variables with mtime caching."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[dict[str, Any], float | None]] = {}
        self._lock = threading.Lock()

    def _project_file(self) -> Path:
        return get_paths().base_dir / "global_variables.json"

    def _thread_file(self, thread_id: str) -> Path:
        return get_paths().thread_dir(thread_id) / "variables.json"

    def _load_from_file(self, file_path: Path) -> dict[str, Any]:
        if not file_path.exists():
            return create_empty_variables()
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load variables file %s: %s", file_path, e)
            return create_empty_variables()

    def _get_mtime(self, file_path: Path) -> float | None:
        try:
            return file_path.stat().st_mtime if file_path.exists() else None
        except OSError:
            return None

    def _cache_key(self, scope: str, thread_id: str | None) -> str:
        if scope == "project":
            return "__project__"
        return f"thread:{thread_id}"

    def load(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        if scope == "project":
            file_path = self._project_file()
        else:
            if not thread_id:
                return {**get_system_variables(), "is_custom": False}
            file_path = self._thread_file(thread_id)

        current_mtime = self._get_mtime(file_path)
        key = self._cache_key(scope, thread_id)

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[1] == current_mtime:
                custom_vars = cached[0]
                return {
                    "variables": {**SYSTEM_VARIABLES, **custom_vars.get("variables", {})},
                    "lastUpdated": custom_vars.get("lastUpdated", ""),
                    "is_custom": True,
                }

        custom_data = self._load_from_file(file_path)
        merged = {
            "variables": {**SYSTEM_VARIABLES, **custom_data.get("variables", {})},
            "lastUpdated": custom_data.get("lastUpdated", ""),
            "is_custom": True,
        }

        with self._lock:
            self._cache[key] = (custom_data, current_mtime)
        return merged

    def reload(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        if scope == "project":
            file_path = self._project_file()
        else:
            if not thread_id:
                return {**get_system_variables(), "is_custom": False}
            file_path = self._thread_file(thread_id)

        custom_data = self._load_from_file(file_path)
        mtime = self._get_mtime(file_path)
        key = self._cache_key(scope, thread_id)

        with self._lock:
            self._cache[key] = (custom_data, mtime)
        return {
            "variables": {**SYSTEM_VARIABLES, **custom_data.get("variables", {})},
            "lastUpdated": custom_data.get("lastUpdated", ""),
            "is_custom": True,
        }

    def save(self, data: dict[str, Any], scope: str, thread_id: str | None = None) -> bool:
        if scope == "project":
            file_path = self._project_file()
        else:
            if not thread_id:
                return False
            file_path = self._thread_file(thread_id)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Strip system variables - only save custom variables
            all_vars = data.get("variables", {})
            custom_vars = {k: v for k, v in all_vars.items() if not (isinstance(v, dict) and v.get("is_system"))}

            save_data = {"variables": custom_vars, "lastUpdated": utc_now_iso_z()}

            temp_path = file_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)

            temp_path.replace(file_path)
            mtime = self._get_mtime(file_path)
            key = self._cache_key(scope, thread_id)

            with self._lock:
                self._cache[key] = (save_data, mtime)

            logger.info("Global variables saved to %s", file_path)
            return True
        except OSError as e:
            logger.error("Failed to save variables file %s: %s", file_path, e)
            return False


_storage_instance: GlobalVariablesStorage | None = None
_storage_lock = threading.Lock()


def get_storage() -> GlobalVariablesStorage:
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    with _storage_lock:
        if _storage_instance is not None:
            return _storage_instance

        _storage_instance = GlobalVariablesStorage()
    return _storage_instance


def reset_storage() -> None:
    global _storage_instance
    with _storage_lock:
        _storage_instance = None
