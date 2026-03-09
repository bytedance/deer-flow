"""Project store with dual-mode support.

When DATABASE_URL is set, uses PostgreSQL via SQLAlchemy.
Otherwise, falls back to file-based JSON storage.
Manages projects and thread-to-project assignments for organizing
threads into user-defined folders.
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
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_STORE_DIR = _BACKEND_DIR / ".think-tank"
_DATA_FILE = _STORE_DIR / "projects.json"


def _ensure_store_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, Any]:
    _ensure_store_dir()
    if not _DATA_FILE.exists():
        return {"schema_version": 1, "projects": {}, "thread_projects": {}}
    try:
        raw = _DATA_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {"schema_version": 1, "projects": {}, "thread_projects": {}}
    if not isinstance(data, dict) or "projects" not in data:
        return {"schema_version": 1, "projects": {}, "thread_projects": {}}
    if "thread_projects" not in data:
        data["thread_projects"] = {}
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
def _file_create_project(project_id: str, user_id: str, name: str) -> bool:
    now = datetime.now(UTC).isoformat()
    with _LOCK:
        data = _load_store()
        # Check for duplicate name for this user
        for p in data["projects"].values():
            if p["user_id"] == user_id and p["name"] == name:
                return False
        data["projects"][project_id] = {
            "user_id": user_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
        }
        _save_store(data)
        return True


def _file_get_user_projects(user_id: str) -> list[dict]:
    with _LOCK:
        data = _load_store()
        result = []
        for pid, p in data["projects"].items():
            if p["user_id"] == user_id:
                # Count threads assigned to this project
                thread_count = sum(
                    1 for tp in data["thread_projects"].values() if tp == pid
                )
                result.append({
                    "project_id": pid,
                    "name": p["name"],
                    "thread_count": thread_count,
                    "created_at": p["created_at"],
                    "updated_at": p.get("updated_at", p["created_at"]),
                })
        return result


def _file_rename_project(project_id: str, user_id: str, name: str) -> bool:
    with _LOCK:
        data = _load_store()
        project = data["projects"].get(project_id)
        if not project or project["user_id"] != user_id:
            return False
        # Check for duplicate name
        for pid, p in data["projects"].items():
            if pid != project_id and p["user_id"] == user_id and p["name"] == name:
                return False
        project["name"] = name
        project["updated_at"] = datetime.now(UTC).isoformat()
        _save_store(data)
        return True


def _file_delete_project(project_id: str, user_id: str) -> bool:
    with _LOCK:
        data = _load_store()
        project = data["projects"].get(project_id)
        if not project or project["user_id"] != user_id:
            return False
        del data["projects"][project_id]
        # Unassign all threads from this project
        data["thread_projects"] = {
            tid: pid for tid, pid in data["thread_projects"].items()
            if pid != project_id
        }
        _save_store(data)
        return True


def _file_assign_thread_to_project(
    thread_id: str, project_id: str | None, user_id: str
) -> bool:
    with _LOCK:
        data = _load_store()
        if project_id is not None:
            # Verify project exists and belongs to user
            project = data["projects"].get(project_id)
            if not project or project["user_id"] != user_id:
                return False
            data["thread_projects"][thread_id] = project_id
        else:
            # Remove assignment (move to Default)
            data["thread_projects"].pop(thread_id, None)
        _save_store(data)
        return True


def _file_get_thread_project(thread_id: str) -> str | None:
    with _LOCK:
        data = _load_store()
        return data["thread_projects"].get(thread_id)


# ---------------------------------------------------------------------------
# Database-backed implementations
# ---------------------------------------------------------------------------
def _db_create_project(project_id: str, user_id: str, name: str) -> bool:
    from sqlalchemy.exc import IntegrityError

    from src.db.engine import get_db_session
    from src.db.models import ProjectModel

    now = datetime.now(UTC)
    with get_db_session() as session:
        try:
            project = ProjectModel(
                project_id=project_id,
                user_id=user_id,
                name=name,
                created_at=now,
                updated_at=now,
            )
            session.add(project)
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def _db_get_user_projects(user_id: str) -> list[dict]:
    from sqlalchemy import func

    from src.db.engine import get_db_session
    from src.db.models import ProjectModel, ThreadModel

    with get_db_session() as session:
        # Query projects with thread counts via left join
        results = (
            session.query(
                ProjectModel.project_id,
                ProjectModel.name,
                ProjectModel.created_at,
                ProjectModel.updated_at,
                func.count(ThreadModel.thread_id).label("thread_count"),
            )
            .outerjoin(ThreadModel, ThreadModel.project_id == ProjectModel.project_id)
            .filter(ProjectModel.user_id == user_id)
            .group_by(
                ProjectModel.project_id,
                ProjectModel.name,
                ProjectModel.created_at,
                ProjectModel.updated_at,
            )
            .all()
        )
        return [
            {
                "project_id": r.project_id,
                "name": r.name,
                "thread_count": r.thread_count,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "updated_at": r.updated_at.isoformat() if r.updated_at else "",
            }
            for r in results
        ]


def _db_rename_project(project_id: str, user_id: str, name: str) -> bool:
    from sqlalchemy.exc import IntegrityError

    from src.db.engine import get_db_session
    from src.db.models import ProjectModel

    with get_db_session() as session:
        project = (
            session.query(ProjectModel)
            .filter(ProjectModel.project_id == project_id, ProjectModel.user_id == user_id)
            .first()
        )
        if not project:
            return False
        try:
            project.name = name
            project.updated_at = datetime.now(UTC)
            session.flush()
            return True
        except IntegrityError:
            session.rollback()
            return False


def _db_delete_project(project_id: str, user_id: str) -> bool:
    from src.db.engine import get_db_session
    from src.db.models import ProjectModel, ThreadModel

    with get_db_session() as session:
        project = (
            session.query(ProjectModel)
            .filter(ProjectModel.project_id == project_id, ProjectModel.user_id == user_id)
            .first()
        )
        if not project:
            return False
        # Unassign all threads from this project
        session.query(ThreadModel).filter(
            ThreadModel.project_id == project_id
        ).update({"project_id": None})
        session.delete(project)
        return True


def _db_assign_thread_to_project(
    thread_id: str, project_id: str | None, user_id: str
) -> bool:
    from src.db.engine import get_db_session
    from src.db.models import ProjectModel, ThreadModel

    with get_db_session() as session:
        if project_id is not None:
            # Verify project exists and belongs to user
            project = (
                session.query(ProjectModel)
                .filter(ProjectModel.project_id == project_id, ProjectModel.user_id == user_id)
                .first()
            )
            if not project:
                return False
        thread = session.query(ThreadModel).filter(ThreadModel.thread_id == thread_id).first()
        if not thread:
            return False
        thread.project_id = project_id
        return True


def _db_get_thread_project(thread_id: str) -> str | None:
    from src.db.engine import get_db_session
    from src.db.models import ThreadModel

    with get_db_session() as session:
        thread = session.query(ThreadModel).filter(ThreadModel.thread_id == thread_id).first()
        return thread.project_id if thread else None


# ---------------------------------------------------------------------------
# Public API (delegates to DB or file based on configuration)
# ---------------------------------------------------------------------------
def create_project(project_id: str, user_id: str, name: str) -> bool:
    """Create a new project for a user.

    Returns True if created, False if duplicate name.
    """
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_create_project(project_id, user_id, name)
    return _file_create_project(project_id, user_id, name)


def get_user_projects(user_id: str) -> list[dict]:
    """Get all projects for a user with thread counts."""
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_user_projects(user_id)
    return _file_get_user_projects(user_id)


def rename_project(project_id: str, user_id: str, name: str) -> bool:
    """Rename a project. Returns False if not found or duplicate name."""
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_rename_project(project_id, user_id, name)
    return _file_rename_project(project_id, user_id, name)


def delete_project(project_id: str, user_id: str) -> bool:
    """Delete a project. Associated threads move to Default (project_id=None)."""
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_delete_project(project_id, user_id)
    return _file_delete_project(project_id, user_id)


def assign_thread_to_project(
    thread_id: str, project_id: str | None, user_id: str
) -> bool:
    """Assign a thread to a project, or unassign (None) to move to Default."""
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_assign_thread_to_project(thread_id, project_id, user_id)
    return _file_assign_thread_to_project(thread_id, project_id, user_id)


def get_thread_project(thread_id: str) -> str | None:
    """Get the project_id for a thread, or None if unassigned."""
    from src.db.engine import is_db_enabled

    if is_db_enabled():
        return _db_get_thread_project(thread_id)
    return _file_get_thread_project(thread_id)
