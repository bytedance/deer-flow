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
# INFO before any response handling runs, and urllib3 logs
# ``Redirecting <url> -> <url>`` at INFO when a redirect is followed. Inbound
# media URLs are signed — the credentials live in the query string, and the
# repo-wide inbound-media rule is that no part of a media URL beyond its host
# may reach the logs — so even successful downloads would leak unless the
# record itself is rewritten. The authority is split so userinfo (basic-auth
# ``user:pass@`` credentials, accepted by httpx for MCP/extension/community-
# tool endpoints) is blanked too, not just the path and query. ``rest`` is
# optional so an authority-only URL (``scheme://user:pass@host`` — no path)
# is still rewritten; a bare credential-free origin passes through as-is.
_URL_REDACT_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s@]*@)?(?P<host>[^/?#\s]+)(?P<rest>[/?#]\S*)?")

# urllib3's per-request DEBUG line (connectionpool.py:545 on urllib3 2.7.0)
# splits the URL across the format string:
# ``'%s://%s:%s "%s %s %s" %s %s'`` renders as
# ``scheme://host:port "GET /private/x?token=y HTTP/1.1" 200 None`` — the
# authority and the signed origin-form target are two separate args. The
# absolute-URL regex above cannot see either half: the authority is followed
# by a space (so ``rest`` never matches and the bare-origin early return
# applies) and the quoted target has no scheme. The request line therefore
# gets its own shape — authority immediately followed by a quoted
# ``METHOD target HTTP/x.x`` line — rewritten to scheme + host with the
# target collapsed to ``/<redacted>``.
_URLLIB3_REQUEST_LINE_RE = re.compile(r'(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s"@]*@)?(?P<host>[^/?#\s"]+) "(?P<method>[A-Z]+) (?P<target>/[^"\s]*) (?P<version>HTTP/[0-9.]+)"')


class UrlRedactionFilter(logging.Filter):
    """Redact URLs in httpx/urllib3 request log records down to scheme + host.

    Path, query, fragment, and any userinfo credentials in the authority are
    replaced; the host (and port) stay for operator debuggability. urllib3's
    per-request DEBUG line carries the same data split across its format —
    authority, then a quoted ``METHOD target HTTP/x.x`` request line — which
    the absolute-URL pattern cannot match, so a second shape handles it. The
    record is rewritten in place (``msg`` set to the redacted formatted
    message, ``args`` cleared) so every downstream handler and formatter —
    text or JSON — sees the same redacted line, while the method/status/duration
    observability is preserved. A URL is rewritten only when it carries
    something to hide (userinfo, path, query, or fragment); a bare
    credential-free origin and records without any URL pass through
    untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        def _redact(match: re.Match[str]) -> str:
            if not (match.group("userinfo") or match.group("rest")):
                return match.group(0)  # bare origin: nothing to redact
            userinfo = "<redacted>@" if match.group("userinfo") else ""
            return match.group("scheme") + userinfo + match.group("host") + "/<redacted>"

        def _redact_request_line(match: re.Match[str]) -> str:
            userinfo = "<redacted>@" if match.group("userinfo") else ""
            return match.group("scheme") + userinfo + match.group("host") + ' "' + match.group("method") + " /<redacted> " + match.group("version") + '"'

        # The request-line pass runs first: its rewrite leaves a bare origin
        # that the absolute-URL pass then passes through, while the reverse
        # order would already have rewritten any authority userinfo into a
        # shape the request-line pattern no longer matches.
        redacted = _URLLIB3_REQUEST_LINE_RE.sub(_redact_request_line, message)
        redacted = _URL_REDACT_RE.sub(_redact, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


# The filter class is generic over the formatted message, so it serves any
# HTTP client library whose records embed full URLs. Where it must be
# ATTACHED differs per library, because a logging.Filter on a logger only
# runs for records emitted through that exact logger — it is not inherited
# by child loggers and never sees propagated records:
# - httpx emits via the bare ``httpx`` logger, so a logger filter works.
# - urllib3 emits via children (``urllib3.poolmanager`` logs
#   ``Redirecting <url> -> <url>`` at INFO, ``urllib3.connectionpool`` logs
#   redirect lines plus the per-request authority/quoted-target line at
#   DEBUG), so a filter on bare ``urllib3`` is dead code. Handler-level
#   filters DO see propagated records, so the filter is also attached to
#   every root handler — covering urllib3 and any future library without
#   knowing its logger names.
_REDACTED_LOGGER_NAMES = ("httpx",)


def _has_url_redaction_filter(handler: logging.Handler) -> bool:
    return any(isinstance(item, UrlRedactionFilter) for item in handler.filters)


def _install_url_redaction_filter(handler: logging.Handler) -> None:
    if not _has_url_redaction_filter(handler):
        handler.addFilter(UrlRedactionFilter())


def install_url_log_redaction() -> None:
    """Attach URL redaction to the ``httpx`` logger and to every root handler.

    The httpx logger filter covers records at their emission point (httpx
    logs via the bare ``httpx`` name); the root-handler filters cover
    propagated records from libraries that emit through child loggers, such
    as urllib3's ``urllib3.poolmanager`` / ``urllib3.connectionpool``.
    """
    for logger_name in _REDACTED_LOGGER_NAMES:
        target = logging.getLogger(logger_name)
        if not any(isinstance(item, UrlRedactionFilter) for item in target.filters):
            target.addFilter(UrlRedactionFilter())
    for handler in logging.root.handlers:
        _install_url_redaction_filter(handler)


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
    install_url_log_redaction()

    logging_config = getattr(config, "logging", None)
    enhance = getattr(logging_config, "enhance", None)
    enhanced = bool(getattr(enhance, "enabled", False))

    for handler in logging.root.handlers:
        _install_url_redaction_filter(handler)
        # URL redaction is level-agnostic and applies whether or not the
        # trace enhancement is on; handler filters see propagated records
        # from child loggers (urllib3 et al.), which logger filters cannot.
        if enhanced:
            _install_trace_filter(handler)
            handler.setFormatter(_trace_formatter(getattr(enhance, "format", "text")))
        else:
            _remove_trace_filter(handler)
            if getattr(handler.formatter, "_deerflow_trace_formatter", False):
                handler.setFormatter(_default_formatter())

    apply_logging_level(getattr(config, "log_level", None))
