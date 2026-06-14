"""Lightweight identifiers for the run runtime domain."""

from __future__ import annotations

from typing import NewType

RunId = NewType("RunId", str)
ThreadId = NewType("ThreadId", str)
AssistantId = NewType("AssistantId", str)
UserId = NewType("UserId", str)


def require_non_empty(value: str, *, field_name: str) -> str:
    """Return a stripped identifier value, rejecting empty identifiers."""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


__all__ = [
    "AssistantId",
    "RunId",
    "ThreadId",
    "UserId",
    "require_non_empty",
]
