"""Thread ownership store with dual-mode support.

When DATABASE_URL is set, uses PostgreSQL via SQLAlchemy.
Otherwise, falls back to file-based JSON storage.
Tracks which user owns which thread. Uses lazy claiming: the first
authenticated request that touches a thread claims ownership.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# File-based storage (local / Electron dev)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
# Derive backend/ dir from this file's location (backend/src/gateway/auth/thread_store.py)
# instead of os.getcwd() which is blocked inside the async event loop by blockbuster.
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_DATA_FILE = _STORE_DIR / "thread-ownership.json"


def _ensure_store_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, Any]:
    _ensure_store_dir()
    if not _DATA_FILE.exists():
        return {"schema_version": 1, "threads": {}}
    try:
        raw = _DATA_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {"schema_version": 1, "threads": {}}
    if not isinstance(data, dict) or "threads" not in data:
        return {"schema_version": 1, "threads": {}}
    return data


def _save_store(data: dict[str, Any]) -> None:
    _ensure_store_dir()
    tmp_path = _DATA_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, _DATA_FILE)
    try:
        os.chmod(_DATA_FILE, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# File-based implementations
# ---------------------------------------------------------------------------
def _file_claim_thread(thread_id: str, user_id: str) -> bool:
    now = datetime.now(UTC).isoformat()
    with _LOCK:
        data = _load_store()
        threads = data["threads"]
        existing = threads.get(thread_id)
        if existing is None:
            threads[thread_id] = {"user_id": user_id, "created_at": now}
            _save_store(data)
            return True
        return existing["user_id"] == user_id


def _file_get_thread_owner(thread_id: str) -> str | None:
    with _LOCK:
        data = _load_store()
        entry = data["threads"].get(thread_id)
        return entry["user_id"] if entry else None


def _file_get_user_threads(user_id: str) -> list[str]:
    with _LOCK:
        data = _load_store()
        return [tid for tid, entry in data["threads"].items() if entry["user_id"] == user_id]


def _file_delete_thread(thread_id: str) -> None:
    with _LOCK:
        data = _load_store()
        data["threads"].pop(thread_id, None)
        _save_store(data)


# ---------------------------------------------------------------------------
# Database-backed implementations
# ---------------------------------------------------------------------------
def _db_claim_thread(thread_id: str, user_id: str) -> bool:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.exc import IntegrityError

    from src.db.engine import get_db_session
    from src.db.models import ThreadModel

    now = datetime.now(UTC)
    with get_db_session() as session:
        # Use INSERT ... ON CONFLICT to atomically claim the thread,
        # avoiding TOCTOU races between concurrent requests.
        try:
            stmt = (
                pg_insert(ThreadModel)
                .values(
                    thread_id=thread_id,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["thread_id"])
            )
            result = session.execute(stmt)
            if result.rowcount > 0:
                # Newly inserted — this user now owns the thread.
                return True
        except IntegrityError:
            session.rollback()

        # Row already existed (or conflict) — check the actual owner.
        existing = session.query(ThreadModel).filter(ThreadModel.thread_id == thread_id).first()
        return existing is not None and existing.user_id == user_id


def _db_get_thread_owner(thread_id: str) -> str | None:
    from src.db.engine import get_db_session
    from src.db.models import ThreadModel

    with get_db_session() as session:
        thread = session.query(ThreadModel).filter(ThreadModel.thread_id == thread_id).first()
        return thread.user_id if thread else None


def _db_get_user_threads(user_id: str) -> list[str]:
    from src.db.engine import get_db_session
    from src.db.models import ThreadModel

    with get_db_session() as session:
        threads = session.query(ThreadModel.thread_id).filter(ThreadModel.user_id == user_id).all()
        return [t[0] for t in threads]


def _db_delete_thread(thread_id: str) -> None:
    from src.db.engine import get_db_session
    from src.db.models import ThreadModel

    with get_db_session() as session:
        session.query(ThreadModel).filter(ThreadModel.thread_id == thread_id).delete()


# ---------------------------------------------------------------------------
# Public API (delegates to DB or file based on configuration)
# ---------------------------------------------------------------------------
def claim_thread(thread_id: str, user_id: str) -> bool:
    """Claim ownership of a thread.

    If the thread is unclaimed, assigns it to user_id.
    If it's already claimed by user_id, returns True.
    If it's claimed by a different user, returns False.

    Args:
        thread_id: The thread identifier.
        user_id: The user claiming the thread.

    Returns:
        True if the user owns the thread (either newly claimed or already owned).
        False if the thread belongs to a different user.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_claim_thread(thread_id, user_id)
    return _file_claim_thread(thread_id, user_id)


def get_thread_owner(thread_id: str) -> str | None:
    """Get the owner of a thread.

    Args:
        thread_id: The thread identifier.

    Returns:
        The user_id of the owner, or None if the thread is unclaimed.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_thread_owner(thread_id)
    return _file_get_thread_owner(thread_id)


def is_thread_owner(thread_id: str, user_id: str) -> bool:
    """Check if a user owns a thread.

    Args:
        thread_id: The thread identifier.
        user_id: The user to check.

    Returns:
        True if the user owns the thread or the thread is unclaimed.
    """
    owner = get_thread_owner(thread_id)
    return owner is None or owner == user_id


def get_user_threads(user_id: str) -> list[str]:
    """Get all thread IDs owned by a user.

    Args:
        user_id: The user identifier.

    Returns:
        List of thread IDs.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_user_threads(user_id)
    return _file_get_user_threads(user_id)


def delete_thread(thread_id: str) -> None:
    """Remove thread ownership record.

    Args:
        thread_id: The thread identifier to remove.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_delete_thread(thread_id)
    return _file_delete_thread(thread_id)
