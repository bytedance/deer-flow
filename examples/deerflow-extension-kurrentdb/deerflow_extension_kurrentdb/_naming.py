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


def dec(encoded: str) -> str:
    """The inverse of ``enc``."""
    raw = bytearray()
    index = 0
    while index < len(encoded):
        if encoded[index] == "%":
            raw.append(int(encoded[index + 1 : index + 3], 16))
            index += 3
        else:
            raw.append(ord(encoded[index]))
            index += 1
    return raw.decode("utf-8")


def memory_stream(user_id: str | None) -> str:
    return "deerflow.memory-global" if user_id is None else f"deerflow.memory-user.{enc(user_id)}"


def memory_meta_stream(user_id: str | None) -> str:
    return "deerflow.memory-meta-global" if user_id is None else f"deerflow.memory-meta-user.{enc(user_id)}"


def memory_meta_stream_of(primary: str) -> str | None:
    """The sidecar stream of a primary memory stream name, or ``None`` when ``primary`` is not one."""
    if primary == "deerflow.memory-global":
        return "deerflow.memory-meta-global"
    if primary.startswith("deerflow.memory-user."):
        return "deerflow.memory-meta-" + primary.removeprefix("deerflow.memory-")
    return None


MEMORY_USER_PREFIX = "deerflow.memory-user."


def memory_user_of(primary: str) -> tuple[bool, str | None]:
    """``(True, user_id)`` for a primary memory stream (``user_id`` ``None`` for the global scope), else ``(False, None)``."""
    if primary == "deerflow.memory-global":
        return True, None
    if primary.startswith(MEMORY_USER_PREFIX):
        return True, dec(primary.removeprefix(MEMORY_USER_PREFIX))
    return False, None


RUN_EVENTS_PREFIX = "deerflow.run-events-"


def run_events_stream(thread_id: str) -> str:
    return f"{RUN_EVENTS_PREFIX}{enc(thread_id)}"
