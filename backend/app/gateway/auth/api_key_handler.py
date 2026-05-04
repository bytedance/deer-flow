"""API Key generation, hashing, verification, and JSON-file persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from deerflow.config.auth_config import get_auth_config
from deerflow.config.paths import get_paths
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)

_API_KEY_PREFIX = "df-"
_API_KEY_RAW_LENGTH = 64


def generate_api_key() -> str:
    """Generate a new API key with ``df-`` prefix.

    Returns:
        A raw API key string like ``df-<64 hex chars>``.
    """
    raw = secrets.token_hex(_API_KEY_RAW_LENGTH // 2)
    return f"{_API_KEY_PREFIX}{raw}"


def hash_key(raw_key: str) -> str:
    """SHA-256 hash an API key for storage."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_key(raw_key: str, stored_hash: str) -> bool:
    """Compare a raw key against a stored SHA-256 hash."""
    return hash_key(raw_key) == stored_hash


def _api_keys_file() -> Path:
    """Resolve the per-tenant API keys JSON file path."""
    paths = get_paths()
    return paths.tenant_base_dir / "api_keys.json"


def load_api_keys() -> dict[str, dict]:
    """Load all API keys for the current tenant.

    Returns:
        Dict mapping key hash → key metadata.
    """
    file_path = _api_keys_file()
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return data.get("keys", {})
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load API keys from %s: %s", file_path, e)
        return {}


def save_api_keys(keys: dict[str, dict]) -> None:
    """Atomically write API keys for the current tenant."""
    file_path = _api_keys_file()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(".tmp")
    payload = {"keys": keys, "updated_at": datetime.now(timezone.utc).isoformat()}
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(file_path)


def create_api_key(name: str) -> dict:
    """Create a new API key for the current tenant.

    Args:
        name: Human-readable name for the key.

    Returns:
        Dict with ``id``, ``name``, ``raw_key``, ``key_prefix``, ``created_at``.
    """
    raw_key = generate_api_key()
    key_hash = hash_key(raw_key)
    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    keys = load_api_keys()
    keys[key_hash] = {
        "id": key_id,
        "name": name,
        "key_prefix": raw_key[:16],
        "created_at": now,
        "last_used_at": None,
        "revoked_at": None,
    }
    save_api_keys(keys)

    return {
        "id": key_id,
        "name": name,
        "raw_key": raw_key,
        "key_prefix": raw_key[:16],
        "created_at": now,
    }


def list_api_keys() -> list[dict]:
    """List all non-revoked API keys for the current tenant."""
    keys = load_api_keys()
    result = []
    for key_hash, meta in keys.items():
        if meta.get("revoked_at") is None:
            result.append({
                "id": meta["id"],
                "name": meta["name"],
                "key_prefix": meta["key_prefix"],
                "created_at": meta["created_at"],
                "last_used_at": meta.get("last_used_at"),
            })
    return result


def revoke_api_key(key_id: str) -> bool:
    """Revoke an API key by ID.

    Returns:
        True if the key was found and revoked, False otherwise.
    """
    keys = load_api_keys()
    for key_hash, meta in keys.items():
        if meta["id"] == key_id:
            meta["revoked_at"] = datetime.now(timezone.utc).isoformat()
            save_api_keys(keys)
            return True
    return False


def verify_and_track_api_key(raw_key: str) -> dict | None:
    """Verify a raw API key and update its last-used timestamp.

    Returns:
        The key metadata dict if valid, None otherwise.
    """
    key_hash = hash_key(raw_key)
    keys = load_api_keys()
    meta = keys.get(key_hash)
    if meta is None:
        return None
    if meta.get("revoked_at") is not None:
        return None
    # Update last_used_at
    meta["last_used_at"] = datetime.now(timezone.utc).isoformat()
    save_api_keys(keys)
    return meta
