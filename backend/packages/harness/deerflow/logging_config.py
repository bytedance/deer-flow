"""Logging setup helpers for DeerFlow."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from deerflow.config.app_config import apply_logging_level
from deerflow.redaction import redact_share_tokens
from deerflow.trace_context import get_current_trace_id

DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
TRACE_TEXT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [trace_id=%(trace_id)s] - %(message)s"
_TRACE_FILTER_NAME = "deerflow_trace_context_filter"


def _redact_log_value(value: Any) -> Any:
    """Redact string leaves while preserving logging argument structure."""
    if isinstance(value, str):
        return redact_share_tokens(value)
    if isinstance(value, tuple):
        return tuple(_redact_log_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_log_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_log_value(item) for key, item in value.items()}
    return value


class TraceContextFilter(logging.Filter):
    """Inject the current request trace id into every log record."""

    name = _TRACE_FILTER_NAME

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_current_trace_id() or "-"
        return True


class ShareTokenRedactionFilter(logging.Filter):
    """Mask raw share tokens (``dfs_…``) in any rendered log message."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_share_tokens(record.msg)
        record.args = _redact_log_value(record.args)

        try:
            message = record.getMessage()
        except (TypeError, ValueError):  # malformed %-args: leave the record alone
            pass
        else:
            redacted_message = redact_share_tokens(message)
            # Uvicorn's AccessFormatter unconditionally unpacks its original
            # five-value args tuple. Its path string was already redacted
            # above, so never collapse that record into a pre-rendered msg.
            if redacted_message != message and record.name != "uvicorn.access":
                record.msg = redacted_message
                record.args = None

        trace_id = getattr(record, "trace_id", None)
        if isinstance(trace_id, str):
            record.trace_id = redact_share_tokens(trace_id)

        if record.exc_info:
            exception_text = record.exc_text or logging.Formatter().formatException(record.exc_info)
            redacted_exception = redact_share_tokens(exception_text)
            if redacted_exception != exception_text:
                record.exc_text = redacted_exception
        return True


class JsonTraceFormatter(logging.Formatter):
    """Small JSON formatter used when ``logging.enhance.format=json``."""

    _deerflow_trace_formatter = True

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "trace_id"):
            record.trace_id = get_current_trace_id() or "-"
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
            "level": record.levelname,
            "trace_id": redact_share_tokens(str(record.trace_id)),
            "message": record.getMessage(),
        }
        if record.exc_info:
            exception_text = record.exc_text or self.formatException(record.exc_info)
            payload["exc_info"] = redact_share_tokens(exception_text)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False)


class TraceTextFormatter(logging.Formatter):
    """Marker subclass so trace formatting can be reverted cleanly in tests."""

    _deerflow_trace_formatter = True


def _ensure_root_handler() -> None:
    if logging.root.handlers:
        return
    logging.basicConfig(level=logging.INFO, format=DEFAULT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def _has_trace_filter(handler: logging.Handler) -> bool:
    return any(getattr(f, "name", None) == _TRACE_FILTER_NAME or isinstance(f, TraceContextFilter) for f in handler.filters)


def _install_trace_filter(handler: logging.Handler) -> None:
    if not _has_trace_filter(handler):
        handler.addFilter(TraceContextFilter())


def _remove_trace_filter(handler: logging.Handler) -> None:
    handler.filters = [f for f in handler.filters if not (getattr(f, "name", None) == _TRACE_FILTER_NAME or isinstance(f, TraceContextFilter))]


def _default_formatter() -> logging.Formatter:
    return logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def _trace_formatter(format_name: str | None) -> logging.Formatter:
    if (format_name or "text").strip().lower() == "json":
        return JsonTraceFormatter()
    return TraceTextFormatter(TRACE_TEXT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def install_share_token_redaction() -> None:
    """Attach share-token redaction across the logging tree.

    ``uvicorn.access`` logs the full request path — share token included —
    with ``propagate=False`` and its own handler, and the rest of uvicorn's
    logger tree terminates at ``uvicorn``'s own handlers. Python does not run
    an ancestor logger's filters for descendant records (for example,
    ``uvicorn.asgi``), so both the known logger objects and every current
    uvicorn handler need the filter. Every other logger reaches the root
    handlers, where the same filter is installed. Idempotent, so it is safe
    to call at app import time and again from ``configure_logging`` after a
    logging configuration has replaced handlers.
    """
    _ensure_root_handler()
    for handler in logging.root.handlers:
        if not any(isinstance(existing, ShareTokenRedactionFilter) for existing in handler.filters):
            handler.addFilter(ShareTokenRedactionFilter())
    for logger_name in ("uvicorn.access", "uvicorn", "uvicorn.error"):
        target = logging.getLogger(logger_name)
        if not any(isinstance(existing, ShareTokenRedactionFilter) for existing in target.filters):
            target.addFilter(ShareTokenRedactionFilter())
        for handler in target.handlers:
            if not any(isinstance(existing, ShareTokenRedactionFilter) for existing in handler.filters):
                handler.addFilter(ShareTokenRedactionFilter())


def configure_logging(config: object) -> None:
    """Configure DeerFlow logging from an AppConfig-like object.

    With logging enhancement disabled this preserves the previous
    ``basicConfig + apply_logging_level`` behavior. With enhancement enabled,
    root handlers gain a trace-context filter and a formatter that includes
    only the additional ``trace_id`` field.
    """
    _ensure_root_handler()
    install_share_token_redaction()

    logging_config = getattr(config, "logging", None)
    enhance = getattr(logging_config, "enhance", None)
    enhanced = bool(getattr(enhance, "enabled", False))

    for handler in logging.root.handlers:
        if enhanced:
            _install_trace_filter(handler)
            handler.setFormatter(_trace_formatter(getattr(enhance, "format", "text")))
        else:
            _remove_trace_filter(handler)
            if getattr(handler.formatter, "_deerflow_trace_formatter", False):
                handler.setFormatter(_default_formatter())

    apply_logging_level(getattr(config, "log_level", None))
