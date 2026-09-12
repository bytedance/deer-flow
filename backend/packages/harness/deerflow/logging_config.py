"""Logging setup helpers for DeerFlow."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
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
# ``rest`` stops at quote characters: URLs wrapped in surrounding prose or a
# format's own quoting (urllib3's ``Incremented Retry for (url='…')``) keep
# their closing punctuation instead of having it swallowed into ``rest``
# (mirroring the quote exclusion in the request-line pattern below).
_URL_REDACT_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s@]*@)?(?P<host>[^/?#\s]+)(?P<rest>[/?#][^\s'\"]*)?")

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
# target collapsed to ``/<redacted>``. The method class is case-tolerant:
# HTTP methods are case-sensitive tokens, and callers may pass lowercase
# custom methods through to urllib3.
_URLLIB3_REQUEST_LINE_RE = re.compile(r'(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s"@]*@)?(?P<host>[^/?#\s"]+) "(?P<method>[A-Za-z]+) (?P<target>/[^"\s]*) (?P<version>HTTP/[0-9.]+)"')

# urllib3's retry sites log the request target with NO scheme and NO request-
# line scaffolding, so neither pattern above can see it (installed 2.7.0):
# - ``Retry: %s`` — connectionpool.py:954, DEBUG, origin-form target.
# - ``Incremented Retry for (url='%s'): %r`` — util/retry.py:545, DEBUG via
#   the ``urllib3.util.retry`` logger; the target is origin-form on the
#   request path and absolute on the redirect path (poolmanager resolves the
#   Location before retrying). Absolute targets are left for the generic
#   absolute-URL pass — ``rest`` stops at the closing quote — while
#   origin-form targets collapse to ``/<redacted>``.
# - ``Retrying (%r) after connection broken by '%r': %s`` —
#   connectionpool.py:869, **WARNING**, so it passes the Gateway's INFO root
#   without DEBUG being enabled; the greedy prefix groups pin the split to
#   the final ``': `` so an error repr containing quotes cannot shift it.
_URLLIB3_RETRY_TARGET_RE = re.compile(r"^Retry: (?P<target>/\S+)$")
_URLLIB3_INCREMENT_RETRY_RE = re.compile(r"Incremented Retry for \(url='(?P<url>[^']*)'\)")
_URLLIB3_RETRYING_RE = re.compile(r"^(?P<head>Retrying \(.*\) after connection broken by .*'): (?P<target>/\S+)$")

# urllib3's ``Redirecting %s -> %s`` (poolmanager.py:500 at INFO,
# connectionpool.py:922 at DEBUG) can carry an origin-form target in either
# slot: connectionpool passes the origin-form request target, and the Location
# header may itself be a relative reference (RFC 9110 allows it). The generic
# absolute-URL pass only sees scheme-bearing halves, so origin-form slots
# collapse to ``/<redacted>`` here; absolute halves are left for that pass.
_URLLIB3_REDIRECTING_ORIGIN_RE = re.compile(r"(?P<pre>^Redirecting |(?<=-> ))(?P<target>/[^\s]*)")

# The two scheme-bearing patterns start with a character class, so re.sub
# retries the match at every position of a long token — a letter run with no
# ``://`` makes each attempt walk to the end of the run, which is quadratic
# overall (a 64K-character path or error body costs seconds per record, and
# this filter runs synchronously in every root handler). Both are instead
# driven from the literal ``://`` occurrences: each one walks back over the
# scheme charset to the first letter of its maximal run, and the pattern is
# attempted only there. A regex match can only start at such a position, and
# if it fails at the run's first letter it fails identically at every other
# letter of the run (the scheme group is the only part that differs), so this
# reproduces re.sub's leftmost-non-overlapping result in linear time. The
# span-skip below is safe for the same reason: a match of either pattern
# always ends at a character outside the scheme charset (whitespace, quote,
# ``/``, ``?``, ``#``, or end of string — never a letter/digit/``+``/``-``/
# ``.``), so a scheme run — and with it a candidate start — can never
# straddle a previous match's end; re.sub likewise never re-enters a
# consumed span.
_SCHEME_TAIL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+.-")
_SCHEME_HEAD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _scheme_starts(message: str) -> Iterator[int]:
    pos = message.find("://")
    while pos != -1:
        start = pos
        while start > 0 and message[start - 1] in _SCHEME_TAIL_CHARS:
            start -= 1
        # Leading non-letters (digits, +, -, .) are valid scheme TAIL
        # characters but cannot start the scheme, so the match starts at the
        # run's first letter; a run with none cannot start a match at all.
        while start < pos and message[start] not in _SCHEME_HEAD_CHARS:
            start += 1
        if start < pos:
            yield start
        pos = message.find("://", pos + 1)


def _redact_scheme_bearing(pattern: re.Pattern[str], rewrite, message: str) -> str:
    parts: list[str] = []
    last = 0
    for start in _scheme_starts(message):
        if start < last:  # inside the span of the previous match
            continue
        match = pattern.match(message, start)
        if match is None:
            continue
        parts.append(message[last:start])
        parts.append(rewrite(match))
        last = match.end()
    if not parts:
        return message
    parts.append(message[last:])
    return "".join(parts)


class UrlRedactionFilter(logging.Filter):
    """Redact URLs in httpx/urllib3 request log records down to scheme + host.

    Path, query, fragment, and any userinfo credentials in the authority are
    replaced; the host (and port) stay for operator debuggability. urllib3
    splits or disassembles the URL across several of its own log formats, and
    the generic absolute-URL pattern only sees a scheme-bearing URL in one
    piece, so each remaining shape gets its own rewrite anchored to the
    exact urllib3 format — ``^``-anchored for whole-message lines, literal-
    prefix-anchored otherwise: the
    per-request ``scheme://host:port "METHOD target HTTP/x.x"`` line, the
    retry lines that log a bare origin-form target (``Retry: <target>``,
    ``Incremented Retry for (url='<target>')``, ``Retrying (…) after
    connection broken by '…': <target>``), and origin-form halves of
    ``Redirecting <target> -> <target>``. The record is rewritten in place
    (``msg`` set to the redacted formatted message, ``args`` cleared) so
    every downstream handler and formatter — text or JSON — sees the same
    redacted line, while the method/status/error observability is preserved.
    The scheme-bearing patterns are attempted only at ``://``-anchored
    scheme starts, so filtering a record costs linear time in its message
    length. A URL is rewritten only when it carries something to hide
    (userinfo, path, query, or fragment); a bare credential-free origin and
    records without any URL pass through untouched.
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

        def _redact_increment(match: re.Match[str]) -> str:
            url = match.group("url")
            if _URL_REDACT_RE.fullmatch(url):
                # Absolute target (redirect path): the generic absolute-URL
                # pass rewrites it, and its rest stops at the closing quote.
                return match.group(0)
            return "Incremented Retry for (url='/<redacted>')"

        def _redact_retry_target(match: re.Match[str]) -> str:
            return "Retry: /<redacted>"

        def _redact_retrying(match: re.Match[str]) -> str:
            return match.group("head") + ": /<redacted>"

        def _redact_redirecting_origin(match: re.Match[str]) -> str:
            return match.group("pre") + "/<redacted>"

        # The urllib3 shape passes run before the absolute-URL pass: their
        # rewrites either leave scheme-bearing text for that pass to handle
        # or collapse the target before it could interact with surrounding
        # punctuation, while the reverse order would already have rewritten
        # an authority into shapes the urllib3 patterns no longer match. The
        # two scheme-bearing passes scan from ``://`` occurrences (see
        # _scheme_starts) instead of re.sub, so long letter runs in any
        # record — URL paths or URL-free error bodies — stay linear-time.
        redacted = _redact_scheme_bearing(_URLLIB3_REQUEST_LINE_RE, _redact_request_line, message)
        redacted = _URLLIB3_INCREMENT_RETRY_RE.sub(_redact_increment, redacted)
        redacted = _URLLIB3_RETRY_TARGET_RE.sub(_redact_retry_target, redacted)
        redacted = _URLLIB3_RETRYING_RE.sub(_redact_retrying, redacted)
        redacted = _URLLIB3_REDIRECTING_ORIGIN_RE.sub(_redact_redirecting_origin, redacted)
        redacted = _redact_scheme_bearing(_URL_REDACT_RE, _redact, redacted)
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
#   redirect lines, the per-request authority/quoted-target line, and the
#   ``Retry:``/``Retrying`` lines at DEBUG/WARNING, and ``urllib3.util.retry``
#   logs ``Incremented Retry for (url=…)`` at DEBUG), so a filter on bare
#   ``urllib3`` is dead code. Handler-level filters DO see propagated
#   records, so the filter is also attached to every root handler — covering
#   urllib3 and any future library without knowing its logger names.
# The enumeration of urllib3's URL-bearing lines is closed against the
# installed source (2.7.0): every other emitter logs host:port only
# (connection establishment/reset) or an absolute URL in one piece
# (``connection.py``'s header-parse warning), which the generic absolute-URL
# pass rewrites without a dedicated shape.
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
