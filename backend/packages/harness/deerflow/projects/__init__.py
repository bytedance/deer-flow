"""Project runtime integration — run-start pinned context and request rendering."""

from __future__ import annotations

from deerflow.projects.context import (
    PROJECT_CONTEXT_MESSAGE_ID_PREFIX,
    PROJECT_CONTEXT_MESSAGE_MARKER,
    build_project_context_message,
    is_project_context_message,
    pinned_project_snapshot,
    project_context_insertion_index,
    render_project_block,
    resolve_project_context,
)

__all__ = [
    "PROJECT_CONTEXT_MESSAGE_ID_PREFIX",
    "PROJECT_CONTEXT_MESSAGE_MARKER",
    "build_project_context_message",
    "is_project_context_message",
    "pinned_project_snapshot",
    "project_context_insertion_index",
    "render_project_block",
    "resolve_project_context",
]
