"""Request trace context helpers.

The value stored here is DeerFlow's request-level correlation id. It is
separate from Langfuse's own trace id and from DeerFlow run ids.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final

TRACE_ID_HEADER: Final[str] = "X-Trace-Id"
DEERFLOW_TRACE_METADATA_KEY: Final[str] = "deerflow_trace_id"
_MAX_TRACE_ID_LENGTH: Final[int] = 512

_current_trace_id: Final[ContextVar[str | None]] = ContextVar("deerflow_current_trace_id", default=None)


def generate_trace_id() -> str:
    """Return a fresh header-safe trace id."""
    return uuid.uuid4().hex


def normalize_trace_id(value: object) -> str | None:
    """Return a safe trace id string, or ``None`` when *value* is unusable.

    Only printable ASCII (0x20-0x7E) is accepted. Codepoints above 0x7E are
    rejected because the trace id round-trips through HTTP response headers,
    which Starlette encodes as latin-1: codepoints > 0xFF raise
    ``UnicodeEncodeError`` inside ``MutableHeaders.__setitem__`` (forcing a
    500 before the response body is even dispatched), and C1 controls
    (0x80-0x9F) technically encode but are stripped or rejected by hardened
    intermediaries (nginx / envoy / cloudfront), silently breaking the
    response. C0 controls (< 0x20) and DEL (0x7F) are rejected for the same
    header-safety reason plus log-injection defense.
    """
    if not isinstance(value, str):
        return None
    trace_id = value.strip()
    if not trace_id or len(trace_id) > _MAX_TRACE_ID_LENGTH:
        return None
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in trace_id):
        return None
    return trace_id


def set_current_trace_id(trace_id: str) -> Token[str | None]:
    """Bind *trace_id* to the current execution context."""
    normalized = normalize_trace_id(trace_id)
    if normalized is None:
        normalized = generate_trace_id()
    return _current_trace_id.set(normalized)


def reset_current_trace_id(token: Token[str | None]) -> None:
    """Restore the trace context captured by *token*."""
    _current_trace_id.reset(token)


def get_current_trace_id() -> str | None:
    """Return the current request trace id, if one is bound."""
    return _current_trace_id.get()


@contextmanager
def request_trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Bind a request trace id for the duration of a request or entry point."""
    normalized = normalize_trace_id(trace_id) or generate_trace_id()
    token = _current_trace_id.set(normalized)
    try:
        yield normalized
    finally:
        _current_trace_id.reset(token)


@contextmanager
def ensure_trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Bind *trace_id*, inherit the current trace, or create a fresh one."""
    normalized = normalize_trace_id(trace_id) or get_current_trace_id() or generate_trace_id()
    token = _current_trace_id.set(normalized)
    try:
        yield normalized
    finally:
        _current_trace_id.reset(token)
