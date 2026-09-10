"""Logging setup helpers for DeerFlow."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from deerflow.config.app_config import apply_logging_level
from deerflow.trace_context import get_current_trace_id

DEFAULT_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
TRACE_TEXT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [trace_id=%(trace_id)s] - %(message)s"
_TRACE_FILTER_NAME = "deerflow_trace_context_filter"

# httpx logs ``HTTP Request: GET <full URL> HTTP/x.x <status> <duration>`` at
# INFO before any response handling runs. Inbound-media URLs are signed — the
# credentials live in the query string, and the repo-wide inbound-media rule
# is that no part of a media URL beyond its host may reach the logs — so even
# successful downloads would leak unless the record itself is rewritten.
# The authority is split so userinfo (basic-auth ``user:pass@`` credentials,
# accepted by httpx for MCP/extension/community-tool endpoints) is blanked
# too, not just the path and query.
_URL_REDACT_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s@]*@)?(?P<host>[^/?#\s]+)(?P<rest>[/?#]\S*)")


class HttpxUrlQueryRedactionFilter(logging.Filter):
    """Redact inbound URLs in httpx request log records down to scheme + host.

    Path, query, fragment, and any userinfo credentials in the authority are
    replaced; the host (and port) stay for operator debuggability. The record
    is rewritten in place (``msg`` set to the redacted formatted message,
    ``args`` cleared) so every downstream handler and formatter — text or
    JSON — sees the same redacted line, while the method/status/duration
    observability is preserved. Records whose message carries no
    ``scheme://host/<anything>`` URL pass through untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        def _redact(match: re.Match[str]) -> str:
            userinfo = "<redacted>@" if match.group("userinfo") else ""
            return match.group("scheme") + userinfo + match.group("host") + "/<redacted>"

        redacted = _URL_REDACT_RE.sub(_redact, message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_httpx_log_redaction() -> None:
    """Idempotently attach URL-query redaction to the ``httpx`` logger."""
    httpx_logger = logging.getLogger("httpx")
    if not any(isinstance(item, HttpxUrlQueryRedactionFilter) for item in httpx_logger.filters):
        httpx_logger.addFilter(HttpxUrlQueryRedactionFilter())


class TraceContextFilter(logging.Filter):
    """Inject the current request trace id into every log record."""

    name = _TRACE_FILTER_NAME

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_current_trace_id() or "-"
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
            "trace_id": record.trace_id,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
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


def configure_logging(config: object) -> None:
    """Configure DeerFlow logging from an AppConfig-like object.

    With logging enhancement disabled this preserves the previous
    ``basicConfig + apply_logging_level`` behavior. With enhancement enabled,
    root handlers gain a trace-context filter and a formatter that includes
    only the additional ``trace_id`` field.
    """
    _ensure_root_handler()
    install_httpx_log_redaction()

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
