"""User store with JSON file persistence.

This module provides a simple JSON-file backed user store for DeerFlow's
multi-tenant mode. It uses atomic writes for data safety and can be easily
swapped for Redis or a database backend in production.

Data layout (on disk):
    {base_dir}/users/users.json:
    {
        "users": {
            "<user_id>": {
                "user_id": "...",
                "email": "...",
                "hashed_password": "...",
                "role": "user",
                "created_at": "2024-01-01T00:00:00",
                "quota_limits": {...}
            }
        },
        "by_email": {
            "<email>": {<user object>}
        }
    }
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.gateway.auth.models import UserRole
from deerflow.config.paths import get_paths
from deerflow.utils.file_helpers import atomic_write_json

logger = logging.getLogger(__name__)


class UserStore:
    """JSON-file-backed user store with atomic writes.

    This store maintains two indexes:
    - users: keyed by user_id
    - by_email: keyed by email for fast lookup

    All mutations are atomic (temp file + rename).
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """Initialize the user store.

        Args:
            base_dir: Base directory for user data. Defaults to {DEER_FLOW_HOME}/users
        """
        if base_dir is None:
            base_dir = get_paths().base_dir / "users"

        self._path = Path(base_dir) / "users.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        """Load user data from disk.

        Returns:
            Dict with "users" and "by_email" keys
        """
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Corrupt user store at %s, starting fresh: %s", self._path, e)
        return {"users": {}, "by_email": {}}

    def _save(self) -> None:
        """Atomically save user data to disk.

        Uses temp file + rename pattern for atomicity.
        """
        atomic_write_json(self._path, self._data)

    def get_by_id(self, user_id: UUID | str) -> dict[str, Any] | None:
        """Get a user by ID.

        Args:
            user_id: The user's ID (UUID or string representation)

        Returns:
            User dict or None if not found
        """
        # Convert UUID to string for lookup
        user_id_str = str(user_id) if isinstance(user_id, UUID) else user_id
        return self._data["users"].get(user_id_str)
        """Get a user by ID.

        Args:
            user_id: The user's ID

        Returns:
            User dict or None if not found
        """
        return self._data["users"].get(user_id)

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        """Get a user by email.

        Args:
            email: The user's email address

        Returns:
            User dict or None if not found
        """
        return self._data["by_email"].get(email)

    def create(
        self,
        user_id: UUID,
        email: str,
        hashed_password: str,
        role: UserRole = UserRole.USER,
        quota_limits: dict[str, int | float] | None = None,
    ) -> dict[str, Any]:
        """Create a new user.

        Args:
            user_id: Unique user identifier (UUID)
            email: User's email address
            hashed_password: Hashed password
            role: User role ("user" or "admin")
            quota_limits: Optional quota limits (defaults applied if None)

        Returns:
            Created user dict

        Raises:
            ValueError: If user_id or email already exists
        """
        with self._lock:
            user_id_str = str(user_id)
            if user_id_str in self._data["users"]:
                raise ValueError(f"User ID {user_id_str} already exists")
            if email in self._data["by_email"]:
                raise ValueError(f"Email {email} already registered")

            user = {
                "user_id": user_id_str,
                "email": email,
                "hashed_password": hashed_password,
                "role": role,
                "created_at": datetime.utcnow().isoformat(),
                "quota_limits": quota_limits or self._get_default_quotas(role),
            }

            self._data["users"][user_id_str] = user
            self._data["by_email"][email] = user
            self._save()
            return user

    def update(self, user_id: UUID | str, **updates: Any) -> dict[str, Any]:
        """Update user fields.

        Args:
            user_id: User ID to update (UUID or string)
            **updates: Fields to update

        Returns:
            Updated user dict

        Raises:
            ValueError: If user_id not found
        """
        with self._lock:
            user_id_str = str(user_id) if isinstance(user_id, UUID) else user_id
            if user_id_str not in self._data["users"]:
                raise ValueError(f"User {user_id_str} not found")

            user = self._data["users"][user_id_str]
            old_email = user.get("email")

            # Handle email change (requires updating by_email index)
            if "email" in updates and updates["email"] != old_email:
                new_email = updates["email"]
                if new_email in self._data["by_email"]:
                    raise ValueError(f"Email {new_email} already registered")
                del self._data["by_email"][old_email]
                self._data["by_email"][new_email] = user

            user.update(updates)
            self._save()
            return user

    def delete(self, user_id: UUID | str) -> None:
        """Delete a user.

        Args:
            user_id: User ID to delete (UUID or string)

        Raises:
            ValueError: If user_id not found
        """
        with self._lock:
            user_id_str = str(user_id) if isinstance(user_id, UUID) else user_id
            if user_id_str not in self._data["users"]:
                raise ValueError(f"User {user_id_str} not found")

            user = self._data["users"][user_id_str]
            email = user.get("email")
            if email:
                del self._data["by_email"][email]
            del self._data["users"][user_id_str]
            self._save()

    def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all users with pagination.

        Args:
            limit: Maximum number of users to return
            offset: Number of users to skip

        Returns:
            List of user dicts
        """
        users = list(self._data["users"].values())
        return users[offset : offset + limit]

    def _get_default_quotas(self, role: UserRole) -> dict[str, int]:
        """Get default quota limits for a role.

        Args:
            role: User role

        Returns:
            Default quota limits
        """
        # Default quotas - can be overridden via config
        defaults = {
            UserRole.USER: {
                "max_threads": 10,
                "max_sandboxes": 5,
                "max_storage_mb": 1024,  # 1GB
            },
            UserRole.ADMIN: {
                "max_threads": 1000,
                "max_sandboxes": 500,
                "max_storage_mb": 102400,  # 100GB
            },
        }
        return defaults.get(role, defaults[UserRole.USER])
