"""In-memory cache for view_image payloads used between tool and middleware.

This keeps base64 image bytes out of ToolMessage content so SSE streams do not
carry large data URLs, while still allowing the middleware to inject images for
the immediate next model call.
"""

from __future__ import annotations

from threading import Lock
from typing import TypedDict


class ViewImagePayload(TypedDict):
    image_path: str
    base64: str
    mime_type: str


_payloads: dict[str, ViewImagePayload] = {}
_lock = Lock()


def store_view_image_payload(tool_call_id: str, payload: ViewImagePayload) -> None:
    """Store payload for a single tool call id."""
    with _lock:
        _payloads[tool_call_id] = payload


def pop_view_image_payload(tool_call_id: str) -> ViewImagePayload | None:
    """Pop payload for a single tool call id."""
    with _lock:
        return _payloads.pop(tool_call_id, None)
