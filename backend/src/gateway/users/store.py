"""
User store with JSON file persistence.

This module provides a simple JSON-file backed user store for Deer-Flow's
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

from src.gateway.middleware.auth_enums import UserRole
from src.utils.file_helpers import atomic_write_json

logger = logging.getLogger(__name__)


class UserStore:
    """JSON-file-backed user store with atomic writes.

    This store maintains two indexes:
    - users: keyed by user_id
    - by_email: keyed by email for fast lookup

    All mutations are atomic (temp file + rename).
    """

    def __init__(self, base_dir: Path | None = None):
        """Initialize the user store.

        Args:
            base_dir: Base directory for user data. Defaults to {DEER_FLOW_HOME}/users
        """
        if base_dir is None:
            from src.config.paths import get_paths
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

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
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
        user_id: str,
        email: str,
        hashed_password: str,
        role: UserRole = UserRole.USER,
        quota_limits: dict | None = None,
    ) -> dict[str, Any]:
        """Create a new user.

        Args:
            user_id: Unique user identifier
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
            if user_id in self._data["users"]:
                raise ValueError(f"User ID {user_id} already exists")
            if email in self._data["by_email"]:
                raise ValueError(f"Email {email} already registered")

            user = {
                "user_id": user_id,
                "email": email,
                "hashed_password": hashed_password,
                "role": role,
                "created_at": datetime.utcnow().isoformat(),
                "quota_limits": quota_limits or self._get_default_quotas(role),
            }

            self._data["users"][user_id] = user
            self._data["by_email"][email] = user
            self._save()

            logger.info("Created user %s (email: %s, role: %s)", user_id, email, role)
            return user

    def update(
        self,
        user_id: str,
        email: str | None = None,
        hashed_password: str | None = None,
        role: UserRole | None = None,
        quota_limits: dict | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing user.

        Args:
            user_id: User to update
            email: New email (optional)
            hashed_password: New password hash (optional)
            role: New role (optional)
            quota_limits: New quota limits (optional)

        Returns:
            Updated user dict or None if user not found
        """
        with self._lock:
            user = self._data["users"].get(user_id)
            if not user:
                return None

            old_email = user["email"]

            # Update email if changed
            if email is not None and email != old_email:
                if email in self._data["by_email"]:
                    raise ValueError(f"Email {email} already registered")
                del self._data["by_email"][old_email]
                user["email"] = email
                self._data["by_email"][email] = user

            # Update other fields
            if hashed_password is not None:
                user["hashed_password"] = hashed_password
            if role is not None:
                user["role"] = role
            if quota_limits is not None:
                user["quota_limits"] = quota_limits

            self._save()
            logger.info("Updated user %s", user_id)
            return user

    def delete(self, user_id: str) -> bool:
        """Delete a user.

        Args:
            user_id: User to delete

        Returns:
            True if user was deleted, False if not found
        """
        with self._lock:
            user = self._data["users"].get(user_id)
            if not user:
                return False

            email = user["email"]
            del self._data["users"][user_id]
            if email in self._data["by_email"]:
                del self._data["by_email"][email]

            self._save()
            logger.info("Deleted user %s", user_id)
            return True

    def list_users(self, role: UserRole | None = None) -> list[dict[str, Any]]:
        """List all users, optionally filtered by role.

        Args:
            role: Optional role filter ("user" or "admin")

        Returns:
            List of user dicts
        """
        users = list(self._data["users"].values())
        if role:
            users = [u for u in users if u.get("role") == role.value]
        return users

    def _get_default_quotas(self, role: UserRole) -> dict[str, Any]:
        """Get default quota limits for a role.

        Args:
            role: User role ("user" or "admin")

        Returns:
            Dict with quota limits (-1 means unlimited)
        """
        if role == UserRole.ADMIN:
            return {
                "max_threads": -1,  # Unlimited
                "max_sandboxes": -1,
                "max_storage_mb": -1,
            }
        return {
            "max_threads": 100,
            "max_sandboxes": 5,
            "max_storage_mb": 1000,
        }

    def check_quota(self, user_id: str, resource: str, current: int) -> bool:
        """Check if a user has exceeded their quota (hard limit).

        This enforces hard limits - returns False if quota would be exceeded.

        Args:
            user_id: User to check
            resource: Resource type ("threads", "sandboxes", "storage_mb")
            current: Current usage count

        Returns:
            True if under quota, False if exceeded
        """
        user = self.get_by_id(user_id)
        if not user:
            return True  # Allow if user not found (shouldn't happen)

        quota_key = f"max_{resource}"
        limits = user.get("quota_limits", {})
        limit = limits.get(quota_key, 0)

        # -1 means unlimited
        if limit == -1:
            return True

        return current < limit
