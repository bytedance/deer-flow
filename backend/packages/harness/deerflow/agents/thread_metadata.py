"""LangGraph thread metadata utilities for multi-tenant user isolation.

This module provides utilities for injecting and retrieving user_id
from LangGraph thread metadata, ensuring thread-level security isolation
in multi-tenant mode.

Thread metadata is stored in the thread's configurable section and persists
across the entire lifetime of the thread, providing:
- User-isolated thread listings
- Permission checks when accessing threads
- Audit trails for thread operations
"""

from typing import Any

from deerflow.config.multi_tenant_config import get_multi_tenant_config


def get_thread_metadata(user_id: str | None = None) -> dict[str, Any]:
    """Get thread metadata with user_id for multi-tenant isolation.

    In multi-tenant mode, injects the user_id into thread metadata.
    In single-tenant mode, uses the default_user_id from config.

    Args:
        user_id: Optional user ID (from JWT token or request context)

    Returns:
        Thread metadata dict with user_id key
    """
    config = get_multi_tenant_config()

    if user_id is None:
        # Use default user when no user_id provided
        user_id = config.default_user_id

    return {
        "user_id": user_id,
    }


def get_user_id_from_metadata(metadata: dict[str, Any] | None) -> str:
    """Extract user_id from thread metadata.

    Args:
        metadata: Thread metadata dict

    Returns:
        User ID from metadata, or default_user_id if not found
    """
    if metadata and "user_id" in metadata:
        return metadata["user_id"]

    # Fallback to default user if no user_id in metadata
    config = get_multi_tenant_config()
    return config.default_user_id


def filter_threads_by_user(
    threads: list[dict[str, Any]],
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Filter threads to only include those belonging to the specified user.

    In multi-tenant mode, this ensures users can only see their own threads.
    In single-tenant mode, all threads are visible.

    Args:
        threads: List of thread dicts with metadata
        user_id: Optional user ID to filter by (from JWT token)

    Returns:
        Filtered list of threads belonging to the user
    """
    config = get_multi_tenant_config()

    if not config.enabled:
        # Single-tenant mode: return all threads
        return threads

    if user_id is None:
        user_id = config.default_user_id

    # Filter threads to only those owned by the user
    return [
        thread
        for thread in threads
        if get_user_id_from_metadata(thread.get("metadata")) == user_id
    ]
