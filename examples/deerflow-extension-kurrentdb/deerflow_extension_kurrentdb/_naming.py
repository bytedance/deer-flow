"""Stream names for the primary KurrentDB streams.

KurrentDB treats everything before the first dash as a stream's category, so
encoded ids never contain a dash: every byte outside ``[A-Za-z0-9_]`` (including
``%`` itself) becomes ``%XX``. The encoding is injective, so distinct ids, and the
global scope, always map to distinct streams.
"""

from __future__ import annotations

DELETIONS_STREAM = "deerflow.kurrent-deletions"

_SAFE = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def enc(raw: str) -> str:
    return "".join(chr(byte) if byte in _SAFE else f"%{byte:02X}" for byte in raw.encode("utf-8"))


def memory_stream(user_id: str | None) -> str:
    return "deerflow.memory-global" if user_id is None else f"deerflow.memory-user.{enc(user_id)}"


def memory_meta_stream(user_id: str | None) -> str:
    return "deerflow.memory-meta-global" if user_id is None else f"deerflow.memory-meta-user.{enc(user_id)}"


def run_events_stream(thread_id: str) -> str:
    return f"deerflow.run-events-{enc(thread_id)}"
