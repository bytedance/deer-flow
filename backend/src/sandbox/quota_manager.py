"""User quota manager for enforcing hard resource limits."""

from typing import Dict, Optional

from src.gateway.users.store import UserStore


class UserQuotaManager:
    """User quota manager with hard limit enforcement.

    This manager tracks runtime resource usage per user and enforces
    hard limits - when a quota is exceeded, new resource creation is
    immediately rejected with an error.
    """

    def __init__(self):
        """Initialize the quota manager."""
        self._user_store = UserStore()
        # Runtime quota usage tracking: {user_id: {resource_type: count}}
        self._runtime_usage: Dict[str, Dict[str, int]] = {}

    def can_create_thread(self, user_id: str) -> bool:
        """Check if a user can create a new thread (hard limit).

        Args:
            user_id: The user ID.

        Returns:
            True if under quota, False if exceeded.
        """
        user = self._user_store.get_by_id(user_id)
        if not user:
            # Allow default user
            return True

        quota = user.get('quota_limits', {})
        max_threads = quota.get('max_threads', 100)

        # -1 means unlimited
        if max_threads == -1:
            return True

        current = self._runtime_usage.get(user_id, {}).get('threads', 0)
        return current < max_threads

    def can_create_sandbox(self, user_id: str) -> bool:
        """Check if a user can create a new sandbox (hard limit).

        Args:
            user_id: The user ID.

        Returns:
            True if under quota, False if exceeded.
        """
        user = self._user_store.get_by_id(user_id)
        if not user:
            # Allow default user
            return True

        quota = user.get('quota_limits', {})
        max_sandboxes = quota.get('max_sandboxes', 5)

        # -1 means unlimited
        if max_sandboxes == -1:
            return True

        current = self._runtime_usage.get(user_id, {}).get('sandboxes', 0)
        return current < max_sandboxes

    def can_use_storage(self, user_id: str, requested_mb: int) -> bool:
        """Check if a user can use additional storage (hard limit).

        Args:
            user_id: The user ID.
            requested_mb: Requested storage in MB.

        Returns:
            True if under quota, False if exceeded.
        """
        user = self._user_store.get_by_id(user_id)
        if not user:
            # Allow default user
            return True

        quota = user.get('quota_limits', {})
        max_storage_mb = quota.get('max_storage_mb', 1000)

        # -1 means unlimited
        if max_storage_mb == -1:
            return True

        current = self._runtime_usage.get(user_id, {}).get('storage_mb', 0)
        return (current + requested_mb) <= max_storage_mb

    def track_thread(self, user_id: str, action: str) -> None:
        """Track thread creation/deletion.

        Args:
            user_id: The user ID.
            action: Either 'create' or 'delete'.
        """
        if user_id not in self._runtime_usage:
            self._runtime_usage[user_id] = {}

        if action == 'create':
            self._runtime_usage[user_id]['threads'] = \
                self._runtime_usage[user_id].get('threads', 0) + 1
        elif action == 'delete':
            self._runtime_usage[user_id]['threads'] = \
                max(0, self._runtime_usage[user_id].get('threads', 0) - 1)

        # Clean up if no resources left
        self._cleanup_user_if_empty(user_id)

    def track_sandbox(self, user_id: str, action: str) -> None:
        """Track sandbox creation/deletion.

        Args:
            user_id: The user ID.
            action: Either 'create' or 'delete'.
        """
        if user_id not in self._runtime_usage:
            self._runtime_usage[user_id] = {}

        if action == 'create':
            self._runtime_usage[user_id]['sandboxes'] = \
                self._runtime_usage[user_id].get('sandboxes', 0) + 1
        elif action == 'delete':
            self._runtime_usage[user_id]['sandboxes'] = \
                max(0, self._runtime_usage[user_id].get('sandboxes', 0) - 1)

        # Clean up if no resources left
        self._cleanup_user_if_empty(user_id)

    def track_storage(self, user_id: str, size_mb: int) -> None:
        """Track storage usage.

        Args:
            user_id: The user ID.
            size_mb: Storage size in MB (positive for allocation, negative for deallocation).
        """
        if user_id not in self._runtime_usage:
            self._runtime_usage[user_id] = {}

        self._runtime_usage[user_id]['storage_mb'] = \
            max(0, self._runtime_usage[user_id].get('storage_mb', 0) + size_mb)

    def get_usage(self, user_id: str) -> dict:
        """Get current resource usage for a user.

        Args:
            user_id: The user ID.

        Returns:
            Dictionary with current usage counts.
        """
        return self._runtime_usage.get(user_id, {})

    def _cleanup_user_if_empty(self, user_id: str) -> None:
        """Clean up user from runtime tracking if they have no resources.

        Args:
            user_id: The user ID to check and potentially clean up.
        """
        if user_id in self._runtime_usage:
            # Check if all resource counts are zero
            if all(v == 0 for v in self._runtime_usage[user_id].values()):
                del self._runtime_usage[user_id]

    def get_quota_info(self, user_id: str) -> dict:
        """Get quota limits and current usage for a user.

        Args:
            user_id: The user ID.

        Returns:
            Dictionary with quota limits and current usage.
        """
        user = self._user_store.get_by_id(user_id)
        if not user:
            return {
                'user_id': user_id,
                'quotas': {
                    'max_threads': 100,
                    'max_sandboxes': 5,
                    'max_storage_mb': 1000,
                },
                'usage': self.get_usage(user_id),
            }

        quota = user.get('quota_limits', {})
        usage = self.get_usage(user_id)

        return {
            'user_id': user_id,
            'quotas': {
                'max_threads': quota.get('max_threads', 100),
                'max_sandboxes': quota.get('max_sandboxes', 5),
                'max_storage_mb': quota.get('max_storage_mb', 1000),
            },
            'usage': usage,
        }


# Global singleton instance
_quota_manager: UserQuotaManager | None = None


def get_quota_manager() -> UserQuotaManager:
    """Get the global quota manager singleton.

    Returns:
        The quota manager instance.
    """
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = UserQuotaManager()
    return _quota_manager
