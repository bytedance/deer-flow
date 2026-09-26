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
# ``rest`` treats a quote as a closing mark only at a boundary — followed by
# whitespace, a closing parenthesis, or end of string — so URLs wrapped in
# surrounding prose or a format's own quoting (urllib3's
# ``Incremented Retry for (url='…')``) keep their closing punctuation, while
# a quote EMBEDDED in the URL (``/path'quoted'?token=…``) is consumed and
# everything after it stays redacted.
_URL_REDACT_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s@]*@)?(?P<host>[^/?#\s]+)(?P<rest>[/?#](?:[^\s'\"]|['\"](?!$|\s|\)))*)?")

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
# custom methods through to urllib3. The target may contain spaces for the
# same reason ``Redirecting``'s slots may: on the recursive redirect frame it
# is the raw ``Location`` field value, whose grammar admits interior spaces,
# and a whitespace-strict target class let the signed path survive. Its scan
# still stops at the closing quote, so the pass stays linear-time.
_URLLIB3_REQUEST_LINE_RE = re.compile(r'(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/?#\s"@]*@)?(?P<host>[^/?#\s"]+) "(?P<method>[A-Za-z]+) (?P<target>/[^"]*) (?P<version>HTTP/[0-9.]+)"')

# urllib3's retry sites log the request target with NO scheme and NO request-
# line scaffolding, so neither pattern above can see it (installed 2.7.0):
# - ``Retry: %s`` — connectionpool.py:954, DEBUG, origin-form target.
# - ``Incremented Retry for (url='%s'): %r`` — util/retry.py:545, DEBUG via
#   the ``urllib3.util.retry`` logger; the target is origin-form on the
#   request path and absolute on the redirect path (poolmanager resolves the
#   Location before retrying). The url capture applies the same boundary
#   idea as ``rest``, narrowed to this format's fixed ``')`` closer: an
#   embedded quote is consumed, the closing quote is the one directly
#   followed by ``)``. Absolute targets are left for the generic absolute-
#   URL pass — its ``rest`` stops at the closing quote — while origin-form
#   targets collapse to ``/<redacted>``.
# - ``Retrying (%r) after connection broken by '%r': %s`` —
#   connectionpool.py:869, **WARNING**, so it passes the Gateway's INFO root
#   without DEBUG being enabled; the greedy prefix groups pin the split to
#   the final ``': `` so an error repr containing quotes cannot shift it.
# Both trailing-target shapes take a target that runs to the end of the
# message rather than to the first space, because ``url`` is the caller's raw
# request target and, on the recursive redirect frame, the raw ``Location``
# field value (connectionpool.py:923-925) — whose grammar admits interior
# spaces, exactly as ``Redirecting``'s slots do (round 13). A whitespace-strict
# target left ``Retry: /download a file.pdf?sig=...`` and the same signed
# target on the WARNING line unredacted, while the two sibling passes that
# already take a loose tail redacted it. The target still has to start with
# ``/``, so prose that merely begins with ``Retry: `` keeps passing through.
_URLLIB3_RETRY_TARGET_RE = re.compile(r"^Retry: (?P<target>/\S.*)$")
_URLLIB3_INCREMENT_RETRY_RE = re.compile(r"Incremented Retry for \(url='(?P<url>(?:[^']|'(?!\)))*)'\)")
_URLLIB3_RETRYING_RE = re.compile(r"^(?P<head>Retrying \(.*\) after connection broken by .*'): (?P<target>/\S.*)$")

# urllib3's ``Redirecting %s -> %s`` (poolmanager.py:500 at INFO,
# connectionpool.py:922 at DEBUG) can carry an origin-form target in either
# slot: connectionpool passes the origin-form request target, and the Location
# header may itself be a relative reference (RFC 9110 allows it). The generic
# absolute-URL pass only sees scheme-bearing halves, so origin-form slots
# collapse to ``/<redacted>`` here; a slot is left for that pass only when
# the pass consumes it whole (see _url_pass_consumes_slot).
# The pattern keeps the ``^Redirecting `` prefix anchor — the urllib3-owned
# literal — because an ``-> /path`` arrow is not urllib3-owned shape:
# non-URL logs render it too (sandbox mount mappings log
# ``sandbox.mounts entry <host_path> -> <container_path>``), and a substring
# match rewrote the container path in that actionable error (CI round 11).
# The tail is deliberately loose: ``redirect_location`` is the raw Location
# header string, and interior spaces are legal field syntax a misbehaving
# server can emit — a whitespace-strict tail would void the pass entirely
# and leak the origin-form request target in the first slot (round 13). A
# space-carrying slot collapses whole whether or not it starts with ``/``:
# the generic pass stops its ``rest`` at whitespace, so an absolute
# space-carrying slot kept its signed tail (round 16). The
# first slot gets the same grammar treatment: the recursive urlopen frame
# passes the previous raw Location as its url, so t1 can carry interior
# spaces too — it is lazy, splitting at the FIRST `` -> `` the way the
# line was constructed left to right.
_URLLIB3_REDIRECTING_ORIGIN_RE = re.compile(r"^Redirecting (?P<t1>\S.*?) -> (?P<t2>\S.*)$")


# A Redirecting slot is kept only when the generic absolute-URL pass consumes
# it WHOLE, so the rule is asked of that pass itself rather than of an
# approximation that can drift from it. The pass leaves a tail in the clear
# whenever its match stops early: ``rest`` halts at whitespace and at a quote
# that reads as a closing mark (``https://h/a')b?sig=…`` keeps ``')b?sig=…``),
# and an empty host before the first ``/?#`` (``https:///path?sig=…``) matches
# nothing at all because ``host`` needs one character. Both are legal absolute
# URLs, so a hand-written "is it absolute and whitespace-free" test cannot see
# them. Everything the pass does not consume whole collapses.
def _url_pass_consumes_slot(slot: str) -> bool:
    match = _URL_REDACT_RE.match(slot)
    return match is not None and match.end() == len(slot)


# urllib3's header-parse warning (connection.py:575-581, WARNING, so it clears
# the Gateway's INFO root) renders "Failed to parse headers (url=%s): %s". In
# the pinned 2.7.0 the second argument stringifies as ``<defects>, unparsed
# data: <payload!r>`` (exceptions.py:324) — there is no ``headers_received``.
# The raw header block arrives through ``unparsed_data``: assert_header_parsing
# sets it to ``headers.get_payload()``, and the email parser routes everything
# after the FIRST malformed line into that payload, so the credential fields
# that leak are the ones trailing the break — repr-escaped onto ONE physical
# line whose logical breaks are the four characters ``\r\n``, not real newlines.
# A pattern that ignores that shape cannot hold: with a ``[^\r\n]*`` value class
# the first anchorable field swallowed the rest of the message, so exactly one
# field ever collapsed while a signed ``Location`` ahead of it stayed whole (its
# ``\b`` never fired at all, since the escape's literal ``n`` leaves no word
# boundary before ``Location``). So this pass splits the dump on its logical
# breaks and anchors one field per segment: every credential-bearing name
# collapses, the names stay for operator legibility, a non-sensitive field keeps
# its value, and a header-looking line in any other log is untouched, because
# the pass runs only on text carrying urllib3's own literals. ``location`` is in
# the list because that field value is the same origin-form signed target the
# Redirecting and retry passes collapse. The anchor is applied past a segment's
# obs-fold marker (see _OBS_FOLD_RE) rather than written into the pattern,
# because a folded value is one header value under RFC 7230 unfolding: a bearer
# token folded under a field this list does not name is still a bearer token.
_CREDENTIAL_FIELD_RE = re.compile(r"(?i)(?P<name>set-cookie2?|cookie|authorization|proxy-authorization|www-authenticate|proxy-authenticate|authentication-info|proxy-authentication-info|location)[ \t]*:[ \t]*(?P<value>.*)$")
# The payload's line breaks as they appear in the log: escaped inside a repr,
# and real if a future format ever stops quoting the block. The repr's opening
# quote is a break too — the dump's first field follows ``unparsed data: `` and
# its ``b?`` bytes form on the same segment as the warning's own scaffolding, so
# without it that first field would never start a segment and never be anchored.
# Every break spelling needs both forms. A bare CR is a separator to
# ``parse_headers`` even though RFC 9112 only defines CRLF, so a payload can be
# split on ``\r`` alone; in the repr that is the two characters ``\\r``, which
# ``\\r\\n`` and ``\\n`` never match. Missing it leaves the whole dump in one
# segment, so the leading field name is not at a segment start, no anchor fires,
# and every credential in the block is logged verbatim. ``\\r\\n`` must stay
# ahead of ``\\r``: alternation is leftmost-first, so leading with ``\\r`` splits
# every CRLF escape into two breaks, and the empty segment between them ends an
# obs-fold walk early — a credential folded under a ``\r\n`` break plus a
# ``\t`` continuation then leaks whole.
_DUMP_LOGICAL_BREAK_RE = re.compile(r"(\\r\\n|\\r|\\n|\r\n|\r|\n|unparsed data: b?['\"])")
_HEADER_DUMP_PREFIX = "Failed to parse headers (url="
# An RFC 5322 obs-fold continuation keeps the field's value on the next line and
# is marked by a leading SP/HTAB. This warning exists to dump malformed upstream
# bytes, so a folded credential cannot be assumed absent: the rest of a collapsed
# field's value — or the whole of it, when the field's first segment is empty —
# lives in the segments that follow its break. The marker has two spellings in
# the logged copy, because the payload reaches the record through ``!r``: a real
# tab is the two characters backslash-t, while a space is never escaped.
_OBS_FOLD_RE = re.compile(r"^(?:[ \t]|\\t)+")
# HeaderParsingError's own message, so a record's exception text — which repeats
# the dump verbatim — is recognised as the same shape rather than as free text.
_HEADER_DUMP_MARKER = "unparsed data: "


def _redact_credential_headers(message: str) -> str:
    parts = _DUMP_LOGICAL_BREAK_RE.split(message)
    # A capturing split returns [text, break, text, break, ...]; only the
    # even-indexed segments are header lines.
    for index in range(0, len(parts), 2):
        segment = parts[index]
        fold = _OBS_FOLD_RE.match(segment)
        lead = fold.group(0) if fold else ""
        match = _CREDENTIAL_FIELD_RE.match(segment, len(lead))
        if match is None:
            continue
        # An empty value hides nothing on its own line, and rewriting it would
        # claim a redaction that never happened — but the field is still the one
        # its continuation belongs to, so the walk below runs either way.
        if match.group("value"):
            parts[index] = lead + match.group("name") + ": <redacted>"
        walk = index + 2
        while walk < len(parts) and _OBS_FOLD_RE.match(parts[walk]):
            parts[walk] = "<redacted>"
            walk += 2
    return "".join(parts)


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
    connection broken by '…': <target>``), and every ``Redirecting <target>
    -> <target>`` slot the generic pass would not consume whole
    (see _url_pass_consumes_slot). The record is rewritten in place
    (``msg`` set to the redacted formatted message, ``args`` cleared) so
    every downstream handler and formatter — text or JSON — sees the same
    redacted line, while the method/status/error observability is preserved.
    Where a record's exception repeats a secret the message pass collapsed
    (urllib3's header-parse warning logs with ``exc_info=True``), ``exc_text``
    is produced through the same passes, because a formatter appends that text
    to the output whatever the format string says.
    The scheme-bearing patterns are attempted only at ``://``-anchored
    scheme starts, so filtering a record costs linear time in its message
    length. A URL is rewritten only when it carries something to hide
    (userinfo, path, query, or fragment); a bare credential-free origin and
    records without any URL pass through untouched.
    """

    def _redact_message(self, message: str) -> str:
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
            # A slot stays verbatim ONLY when the generic absolute-URL pass
            # — which runs after this one — consumes it whole; that pass is
            # asked directly (see _url_pass_consumes_slot).
            # Everything else collapses: the Location field-value grammar
            # (RFC 3986 relative-part) also admits slash-less relative
            # references (``download?sign=…``, ``?sign=…``, ``#frag``),
            # network-path references (``//host/x``, whose userinfo
            # collapses with it), and non-hierarchical schemes
            # (``data:…``) — none of which either pass could otherwise see,
            # and the slash-less forms kept their signed queries verbatim
            # (round 15). A space-carrying slot is legal Location syntax
            # too, and the generic pass stops its ``rest`` at whitespace,
            # so the signed tail after the first space survived the same
            # way (round 16).
            def _slot(target: str) -> str:
                return target if _url_pass_consumes_slot(target) else "/<redacted>"

            return "Redirecting " + _slot(match.group("t1")) + " -> " + _slot(match.group("t2"))

        # The urllib3 shape passes run before the absolute-URL pass: their
        # rewrites either leave scheme-bearing text for that pass to handle
        # or collapse the target before it could interact with surrounding
        # punctuation, while the reverse order would already have rewritten
        # an authority into shapes the urllib3 patterns no longer match. The
        # two scheme-bearing passes scan from ``://`` occurrences (see
        # _scheme_starts) instead of re.sub, so long letter runs in any
        # record — URL paths or URL-free error bodies — stay linear-time.
        redacted = message
        # Runs before the URL passes: the absolute-URL rewrite consumes the
        # ``): `` closer and the repr scaffolding that separate the url
        # argument from the header dump, which would blur the two together and
        # leave a value whose only boundary was the consumed closer behind.
        if message.startswith(_HEADER_DUMP_PREFIX) or _HEADER_DUMP_MARKER in message:
            # The record's own second argument, not a URL line: the response
            # header block that urllib3 echoes when it could not parse it. The
            # marker branch covers the exception text, whose last line repeats
            # that block outside the warning's prefix.
            redacted = _redact_credential_headers(redacted)
        redacted = _redact_scheme_bearing(_URLLIB3_REQUEST_LINE_RE, _redact_request_line, redacted)
        redacted = _URLLIB3_INCREMENT_RETRY_RE.sub(_redact_increment, redacted)
        redacted = _URLLIB3_RETRY_TARGET_RE.sub(_redact_retry_target, redacted)
        redacted = _URLLIB3_RETRYING_RE.sub(_redact_retrying, redacted)
        redacted = _URLLIB3_REDIRECTING_ORIGIN_RE.sub(_redact_redirecting_origin, redacted)
        redacted = _redact_scheme_bearing(_URL_REDACT_RE, _redact, redacted)
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._redact_message(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and _HEADER_DUMP_MARKER in message:
            # urllib3 emits the header-parse warning with exc_info=True, and
            # Formatter.format appends formatException() to any record carrying
            # one — independently of the format string — so the traceback's last
            # line is a second whole copy of the dump the message pass just
            # collapsed. Pre-populating exc_text is what wins, because the
            # Formatter recomputes it only when unset. The gate reads the
            # already-formatted message rather than the exception: that warning
            # interpolates the exception into it, so the marker is the same
            # signal, and no other error record pays for formatting a traceback
            # this filter would leave untouched anyway.
            record.exc_text = self._redact_message(logging.Formatter().formatException(record.exc_info))
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
# (``connection.py``'s header-parse warning, whose second argument is a raw
# response header block rather than a URL, and goes through
# _redact_credential_headers). The closure is version-anchored:
# a urllib3 upgrade can change these format strings and silently reopen it —
# re-run the emitter enumeration when bumping the dependency.
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
            # Follow logging.Formatter in caching and reusing exc_text: a filter
            # that already redacted it (UrlRedactionFilter, for urllib3's
            # header-parse warning) would otherwise be recomputed here and its
            # result discarded, re-emitting the exception's own text in full.
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            payload["exc_info"] = record.exc_text
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
