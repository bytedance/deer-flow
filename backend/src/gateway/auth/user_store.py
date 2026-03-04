"""User persistence store with dual-mode support.

When DATABASE_URL is set, uses PostgreSQL via SQLAlchemy.
Otherwise, falls back to file-based JSON storage.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# File-based storage (local / Electron dev)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
# Derive backend/ dir from this file's location (backend/src/gateway/auth/user_store.py)
# instead of os.getcwd() which is blocked inside the async event loop by blockbuster.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_DATA_FILE = _STORE_DIR / "users.json"


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
        return {"schema_version": 1, "users": {}, "email_index": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"schema_version": 1, "users": {}, "email_index": {}}
    if not isinstance(data, dict) or "users" not in data:
        return {"schema_version": 1, "users": {}, "email_index": {}}
    data.setdefault("email_index", {})
    return data


def _save_store(data: dict[str, Any]) -> None:
    _ensure_store_dir()
    _write_file(_DATA_FILE, json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# File-based implementations
# ---------------------------------------------------------------------------
def _file_create_user(
    email: str,
    password_hash: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    user_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    normalized_email = email.lower().strip()

    with _LOCK:
        data = _load_store()
        if normalized_email in data["email_index"]:
            raise ValueError("Email already registered")

        user_record = {
            "id": user_id,
            "email": normalized_email,
            "password_hash": password_hash,
            "display_name": display_name,
            "created_at": now,
        }
        data["users"][user_id] = user_record
        data["email_index"][normalized_email] = user_id
        _save_store(data)

    return {
        "id": user_id,
        "email": normalized_email,
        "display_name": display_name,
        "created_at": now,
    }


def _file_get_user_by_email(email: str) -> dict[str, Any] | None:
    normalized_email = email.lower().strip()
    with _LOCK:
        data = _load_store()
        user_id = data["email_index"].get(normalized_email)
        if not user_id:
            return None
        return data["users"].get(user_id)


def _file_get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _load_store()
        return data["users"].get(user_id)


# ---------------------------------------------------------------------------
# Database-backed implementations
# ---------------------------------------------------------------------------
def _db_create_user(
    email: str,
    password_hash: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    from src.db.engine import get_db_session
    from src.db.models import UserModel

    user_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    normalized_email = email.lower().strip()

    with get_db_session() as session:
        existing = session.query(UserModel).filter(UserModel.email == normalized_email).first()
        if existing:
            raise ValueError("Email already registered")

        user = UserModel(
            id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            display_name=display_name,
            created_at=now,
            updated_at=now,
        )
        session.add(user)

    return {
        "id": user_id,
        "email": normalized_email,
        "display_name": display_name,
        "created_at": now.isoformat(),
    }


def _db_get_user_by_email(email: str) -> dict[str, Any] | None:
    from src.db.engine import get_db_session
    from src.db.models import UserModel

    normalized_email = email.lower().strip()
    with get_db_session() as session:
        user = session.query(UserModel).filter(UserModel.email == normalized_email).first()
        if not user:
            return None
        return user.to_dict(include_password=True)


def _db_get_user_by_id(user_id: str) -> dict[str, Any] | None:
    from src.db.engine import get_db_session
    from src.db.models import UserModel

    with get_db_session() as session:
        user = session.query(UserModel).filter(UserModel.id == user_id).first()
        if not user:
            return None
        return user.to_dict(include_password=True)


# ---------------------------------------------------------------------------
# Public API (delegates to DB or file based on configuration)
# ---------------------------------------------------------------------------
def create_user(
    email: str,
    password_hash: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Create a new user.

    Args:
        email: User email (must be unique).
        password_hash: Bcrypt-hashed password.
        display_name: Optional display name.

    Returns:
        The created user record (without password_hash).

    Raises:
        ValueError: If the email is already registered.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_create_user(email, password_hash, display_name)
    return _file_create_user(email, password_hash, display_name)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Look up a user by email.

    Args:
        email: The email to search for.

    Returns:
        The full user record (including password_hash), or None if not found.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_user_by_email(email)
    return _file_get_user_by_email(email)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """Look up a user by ID.

    Args:
        user_id: The user's unique identifier.

    Returns:
        The full user record (including password_hash), or None if not found.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_user_by_id(user_id)
    return _file_get_user_by_id(user_id)
