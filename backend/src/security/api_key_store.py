"""API key store with dual-mode support.

When DATABASE_URL is set, uses PostgreSQL via SQLAlchemy.
Otherwise, falls back to file-based encrypted JSON storage.
In both modes, API keys are encrypted with Fernet before storage.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------------------
# File-based storage (local / Electron dev)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
# Derive backend/ dir from this file's location (backend/src/security/api_key_store.py)
# instead of os.getcwd() which is blocked inside the async event loop by blockbuster.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_KEY_FILE = _STORE_DIR / "api-keys.key"
_DATA_FILE = _STORE_DIR / "api-keys.json"


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
        # Best-effort permissions; ignore on unsupported platforms.
        pass


def _get_or_create_master_key() -> bytes:
    """Get or create the master encryption key for API key storage.

    Priority: ENCRYPTION_KEY env var > file-based key > generate new key.
    When REQUIRE_ENV_SECRETS is set (production), ENCRYPTION_KEY env var
    is required and file-based generation is disabled.
    """
    # 1. Environment variable (preferred, required in production)
    env_key = os.environ.get("ENCRYPTION_KEY")
    if env_key:
        # Validate early: Fernet keys must be 32 url-safe base64-encoded bytes
        key_bytes = env_key.encode("utf-8")
        try:
            Fernet(key_bytes)
        except (ValueError, Exception) as exc:
            raise RuntimeError(
                f"ENCRYPTION_KEY is not a valid Fernet key: {exc}. "
                "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ) from exc
        return key_bytes

    # 2. Production mode requires env var
    if os.environ.get("REQUIRE_ENV_SECRETS"):
        raise RuntimeError("ENCRYPTION_KEY environment variable is required when REQUIRE_ENV_SECRETS is set. Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")

    # 3. File-based fallback (development only)
    _ensure_store_dir()
    existing = _read_file(_KEY_FILE)
    if existing:
        return existing.encode("utf-8")
    key = Fernet.generate_key()
    _write_file(_KEY_FILE, key.decode("utf-8"))
    return key


def _load_store() -> dict:
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

    # Migrate legacy "devices" key to "users" for backward compatibility
    if "devices" in data and "users" not in data:
        data["users"] = data.pop("devices")
        data["schema_version"] = 2

    data.setdefault("users", {})
    return data


def _save_store(data: dict) -> None:
    _ensure_store_dir()
    _write_file(_DATA_FILE, json.dumps(data, indent=2))


def _get_cipher() -> Fernet:
    key = _get_or_create_master_key()
    return Fernet(key)


# ---------------------------------------------------------------------------
# File-based implementations
# ---------------------------------------------------------------------------
def _file_set_api_key(user_id: str, provider: str, api_key: str) -> None:
    cipher = _get_cipher()
    token = cipher.encrypt(api_key.encode("utf-8")).decode("utf-8")
    with _LOCK:
        data = _load_store()
        users = data.setdefault("users", {})
        user_entry = users.setdefault(user_id, {})
        user_entry[provider] = token
        _save_store(data)


def _file_delete_api_key(user_id: str, provider: str) -> None:
    with _LOCK:
        data = _load_store()
        users = data.get("users", {})
        user_entry = users.get(user_id)
        if not isinstance(user_entry, dict):
            return
        user_entry.pop(provider, None)
        if not user_entry:
            users.pop(user_id, None)
        _save_store(data)


def _file_has_api_key(user_id: str, provider: str) -> bool:
    with _LOCK:
        data = _load_store()
        user_entry = data.get("users", {}).get(user_id, {})
        return isinstance(user_entry, dict) and bool(user_entry.get(provider))


def _file_get_api_key(user_id: str, provider: str) -> str | None:
    cipher = _get_cipher()
    with _LOCK:
        data = _load_store()
        user_entry = data.get("users", {}).get(user_id, {})
        if not isinstance(user_entry, dict):
            return None
        token = user_entry.get(provider)
        if not isinstance(token, str):
            return None
    try:
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


# ---------------------------------------------------------------------------
# Database-backed implementations
# ---------------------------------------------------------------------------
def _db_set_api_key(user_id: str, provider: str, api_key: str) -> None:
    from src.db.engine import get_db_session
    from src.db.models import UserApiKeyModel

    cipher = _get_cipher()
    encrypted = cipher.encrypt(api_key.encode("utf-8")).decode("utf-8")

    with get_db_session() as session:
        existing = (
            session.query(UserApiKeyModel)
            .filter(
                UserApiKeyModel.user_id == user_id,
                UserApiKeyModel.provider == provider,
            )
            .first()
        )
        if existing:
            existing.encrypted_key = encrypted
        else:
            key_record = UserApiKeyModel(
                id=uuid.uuid4().hex,
                user_id=user_id,
                provider=provider,
                encrypted_key=encrypted,
            )
            session.add(key_record)


def _db_delete_api_key(user_id: str, provider: str) -> None:
    from src.db.engine import get_db_session
    from src.db.models import UserApiKeyModel

    with get_db_session() as session:
        session.query(UserApiKeyModel).filter(
            UserApiKeyModel.user_id == user_id,
            UserApiKeyModel.provider == provider,
        ).delete()


def _db_has_api_key(user_id: str, provider: str) -> bool:
    from src.db.engine import get_db_session
    from src.db.models import UserApiKeyModel

    with get_db_session() as session:
        count = (
            session.query(UserApiKeyModel)
            .filter(
                UserApiKeyModel.user_id == user_id,
                UserApiKeyModel.provider == provider,
            )
            .count()
        )
        return count > 0


def _db_get_api_key(user_id: str, provider: str) -> str | None:
    from src.db.engine import get_db_session
    from src.db.models import UserApiKeyModel

    cipher = _get_cipher()
    with get_db_session() as session:
        record = (
            session.query(UserApiKeyModel)
            .filter(
                UserApiKeyModel.user_id == user_id,
                UserApiKeyModel.provider == provider,
            )
            .first()
        )
        if not record:
            return None
        token = record.encrypted_key

    try:
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


# ---------------------------------------------------------------------------
# Public API (delegates to DB or file based on configuration)
# ---------------------------------------------------------------------------
def set_api_key(user_id: str, provider: str, api_key: str) -> None:
    """Store an encrypted API key for a user and provider.

    Args:
        user_id: The user identifier (was device_id in v1).
        provider: The provider name (e.g., "openai", "anthropic").
        api_key: The plaintext API key to encrypt and store.

    Raises:
        ValueError: If user_id, provider, or api_key is empty.
    """
    if not user_id or not provider:
        raise ValueError("user_id and provider are required")
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("api_key must be non-empty")

    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_set_api_key(user_id, provider, api_key)
    return _file_set_api_key(user_id, provider, api_key)


def delete_api_key(user_id: str, provider: str) -> None:
    """Delete an API key for a user and provider.

    Args:
        user_id: The user identifier.
        provider: The provider name.

    Raises:
        ValueError: If user_id or provider is empty.
    """
    if not user_id or not provider:
        raise ValueError("user_id and provider are required")

    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_delete_api_key(user_id, provider)
    return _file_delete_api_key(user_id, provider)


def has_api_key(user_id: str, provider: str) -> bool:
    """Check if an API key exists for a user and provider.

    Args:
        user_id: The user identifier.
        provider: The provider name.

    Returns:
        True if a key is stored, False otherwise.
    """
    if not user_id or not provider:
        return False

    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_has_api_key(user_id, provider)
    return _file_has_api_key(user_id, provider)


def get_api_key(user_id: str, provider: str) -> str | None:
    """Retrieve and decrypt an API key for a user and provider.

    Args:
        user_id: The user identifier.
        provider: The provider name.

    Returns:
        The decrypted API key string, or None if not found or decryption fails.
    """
    if not user_id or not provider:
        return None

    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_api_key(user_id, provider)
    return _file_get_api_key(user_id, provider)
