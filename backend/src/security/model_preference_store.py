"""User model preference store with dual-mode support.

When DATABASE_URL is set, uses PostgreSQL via SQLAlchemy.
Otherwise, falls back to file-based JSON storage.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_THINKING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_MISSING = object()

# ---------------------------------------------------------------------------
# File-based storage (local / Electron dev)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_DATA_FILE = _STORE_DIR / "model-preferences.json"


def _ensure_store_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def _read_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_store() -> dict[str, Any]:
    _ensure_store_dir()
    raw = _read_file(_DATA_FILE)
    if not raw:
        return {"schema_version": 2, "users": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"schema_version": 2, "users": {}}
    if not isinstance(data, dict):
        return {"schema_version": 2, "users": {}}
    data.setdefault("users", {})
    return data


def _save_store(data: dict[str, Any]) -> None:
    _ensure_store_dir()
    _write_file(_DATA_FILE, json.dumps(data, indent=2))


def _normalize_model_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("model_name must be a string or null")
    normalized = value.strip()
    return normalized or None


def _normalize_effort(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("thinking_effort must be a string or null")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in ALLOWED_THINKING_EFFORTS:
        raise ValueError(f"Invalid thinking_effort '{value}'")
    return normalized


def _normalize_provider_enabled(value: dict[str, Any] | None) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("provider_enabled must be an object map of provider->enabled.")
    normalized: dict[str, bool] = {}
    for provider, enabled in value.items():
        if not isinstance(provider, str):
            raise ValueError("provider_enabled keys must be strings.")
        normalized_provider = provider.strip().lower()
        if not normalized_provider:
            continue
        normalized[normalized_provider] = bool(enabled)
    return normalized


def _normalize_enabled_models(value: dict[str, Any] | None) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("enabled_models must be an object map of model_id->enabled.")
    normalized: dict[str, bool] = {}
    for model_id, enabled in value.items():
        if not isinstance(model_id, str):
            raise ValueError("enabled_models keys must be strings.")
        normalized_model_id = model_id.strip()
        if not normalized_model_id:
            continue
        normalized[normalized_model_id] = bool(enabled)
    return normalized


def _normalize_existing_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = record or {}
    return {
        "model_name": _normalize_model_name(source.get("model_name")),
        "thinking_effort": _normalize_effort(source.get("thinking_effort")),
        "provider_enabled": _normalize_provider_enabled(source.get("provider_enabled")),
        "enabled_models": _normalize_enabled_models(source.get("enabled_models")),
        "updated_at": source.get("updated_at"),
    }


def _file_set_model_preferences(
    user_id: str,
    *,
    model_name: str | None | object = _MISSING,
    thinking_effort: str | None | object = _MISSING,
    provider_enabled: dict[str, Any] | None | object = _MISSING,
    enabled_models: dict[str, Any] | None | object = _MISSING,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    with _LOCK:
        data = _load_store()
        users = data.setdefault("users", {})
        current = _normalize_existing_record(users.get(user_id))
        if model_name is not _MISSING:
            current["model_name"] = _normalize_model_name(model_name)
        if thinking_effort is not _MISSING:
            current["thinking_effort"] = _normalize_effort(thinking_effort)
        if provider_enabled is not _MISSING:
            current["provider_enabled"] = _normalize_provider_enabled(provider_enabled)
        if enabled_models is not _MISSING:
            current["enabled_models"] = _normalize_enabled_models(enabled_models)
        current["updated_at"] = now
        users[user_id] = current
        _save_store(data)
    return current


def _file_get_model_preferences(user_id: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _load_store()
        entry = data.get("users", {}).get(user_id)
    if not isinstance(entry, dict):
        return None
    return _normalize_existing_record(entry)


def _db_set_model_preferences(
    user_id: str,
    *,
    model_name: str | None | object = _MISSING,
    thinking_effort: str | None | object = _MISSING,
    provider_enabled: dict[str, Any] | None | object = _MISSING,
    enabled_models: dict[str, Any] | None | object = _MISSING,
) -> dict[str, Any]:
    from src.db.engine import get_db_session
    from src.db.models import UserModelPreferenceModel

    with get_db_session() as session:
        record = session.query(UserModelPreferenceModel).filter(UserModelPreferenceModel.user_id == user_id).first()
        if record is None:
            record = UserModelPreferenceModel(
                user_id=user_id,
                model_name=None,
                thinking_effort=None,
                provider_enabled={},
                enabled_models={},
            )
            session.add(record)

        if model_name is not _MISSING:
            record.model_name = _normalize_model_name(model_name)
        if thinking_effort is not _MISSING:
            record.thinking_effort = _normalize_effort(thinking_effort)
        if provider_enabled is not _MISSING:
            record.provider_enabled = _normalize_provider_enabled(provider_enabled)
        if enabled_models is not _MISSING:
            record.enabled_models = _normalize_enabled_models(enabled_models)

    return {
        "model_name": record.model_name,
        "thinking_effort": record.thinking_effort,
        "provider_enabled": _normalize_provider_enabled(record.provider_enabled),
        "enabled_models": _normalize_enabled_models(record.enabled_models),
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _db_get_model_preferences(user_id: str) -> dict[str, Any] | None:
    from src.db.engine import get_db_session
    from src.db.models import UserModelPreferenceModel

    with get_db_session() as session:
        record = session.query(UserModelPreferenceModel).filter(UserModelPreferenceModel.user_id == user_id).first()
        if not record:
            return None
        return {
            "model_name": record.model_name,
            "thinking_effort": record.thinking_effort,
            "provider_enabled": _normalize_provider_enabled(record.provider_enabled),
            "enabled_models": _normalize_enabled_models(record.enabled_models),
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }


def set_model_preferences(
    user_id: str,
    *,
    model_name: str | None | object = _MISSING,
    thinking_effort: str | None | object = _MISSING,
    provider_enabled: dict[str, Any] | None | object = _MISSING,
    enabled_models: dict[str, Any] | None | object = _MISSING,
) -> dict[str, Any]:
    """Persist user model selection preferences."""
    if not user_id:
        raise ValueError("user_id is required")
    from src.db.engine import is_db_enabled

    kwargs = {
        "model_name": model_name,
        "thinking_effort": thinking_effort,
        "provider_enabled": provider_enabled,
        "enabled_models": enabled_models,
    }
    if is_db_enabled():
        return _db_set_model_preferences(user_id, **kwargs)
    return _file_set_model_preferences(user_id, **kwargs)


def get_model_preferences(user_id: str) -> dict[str, Any] | None:
    """Load persisted user model selection preferences."""
    if not user_id:
        return None
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_model_preferences(user_id)
    return _file_get_model_preferences(user_id)

