"""Parse Gateway thread-mapping namespaces (``("user_threads", user_id)`` + thread key)."""

from __future__ import annotations


def parse_user_threads_namespace(namespace: tuple[str, ...], key: str) -> tuple[str, str]:
    """Return ``(user_id, thread_id)`` from store namespace and item key."""
    if len(namespace) >= 2 and namespace[0] == "user_threads":
        return str(namespace[1]), str(key)
    raise ValueError(f"Unsupported thread-mapping namespace {namespace!r} (expected ('user_threads', user_id))")


def user_id_from_search_prefix(namespace_prefix: tuple[str, ...]) -> str:
    """Extract ``user_id`` from ``asearch`` prefix ``('user_threads', user_id)``."""
    if len(namespace_prefix) >= 2 and namespace_prefix[0] == "user_threads":
        return str(namespace_prefix[1])
    raise ValueError(f"Unsupported thread-mapping search prefix {namespace_prefix!r}")
