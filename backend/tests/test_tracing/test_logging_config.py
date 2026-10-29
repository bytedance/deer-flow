import io
import logging
from types import SimpleNamespace

import httpx

from deerflow.logging_config import TraceContextFilter, configure_logging
from deerflow.trace_context import request_trace_context


def test_trace_context_filter_injects_current_trace_id() -> None:
    record = logging.LogRecord("deerflow.test", logging.INFO, __file__, 1, "hello", (), None)

    with request_trace_context("trace-log-1"):
        assert TraceContextFilter().filter(record) is True

    assert record.trace_id == "trace-log-1"


def test_configure_logging_enhanced_text_includes_trace_id() -> None:
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)

    try:
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        config = SimpleNamespace(
            log_level="info",
            logging=SimpleNamespace(enhance=SimpleNamespace(enabled=True, format="text")),
        )
        configure_logging(config)

        with request_trace_context("trace-log-2"):
            logging.getLogger("deerflow.test").info("hello")

        assert "[trace_id=trace-log-2]" in stream.getvalue()
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)


# The installed httpx (0.28.1) emits this exact record from _client.py:
# logger.info('HTTP Request: %s %s "%s %d %s"', method, url, version, status, reason)
_HTTPX_REQUEST_FORMAT = 'HTTP Request: %s %s "%s %d %s"'


def _httpx_record(url: str, method: str = "GET", status: int = 200) -> logging.LogRecord:
    return logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        _HTTPX_REQUEST_FORMAT,
        (method, httpx.URL(url), "HTTP/1.1", status, "OK"),
        None,
    )


def test_url_redaction_filter_rewrites_request_records() -> None:
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    # Records are built with the real httpx format string and httpx.URL args
    # (verified against httpx/_client.py on the installed version), so the
    # unit test pins the production format. Redaction runs on the formatted
    # message and clears args; path AND query disappear — only scheme + host
    # may remain (the repo-wide inbound-media log rule).
    record = _httpx_record("https://host.example/private/BearerSecret?token=QuerySecret")
    assert filt.filter(record) is True
    formatted = record.getMessage()
    assert "host.example/<redacted>" in formatted
    assert "BearerSecret" not in formatted
    assert "token=" not in formatted
    assert "GET" in formatted and "200" in formatted  # observability preserved

    # Same class of leak, different secret location: the Telegram Bot API
    # carries the bot token in the PATH (api.telegram.org/bot<token>/method),
    # and python-telegram-bot's HTTPXRequest rides the same httpx logger —
    # redacting down to scheme + host is what keeps telegram.py's promise
    # that the token-bearing URL never reaches the logs.
    telegram = _httpx_record("https://api.telegram.org/bot123456:AAE-token-secret/sendMessage", method="POST")
    assert filt.filter(telegram) is True
    telegram_formatted = telegram.getMessage()
    assert "api.telegram.org/<redacted>" in telegram_formatted
    assert "AAE-token-secret" not in telegram_formatted
    assert "bot123456" not in telegram_formatted

    # Userinfo credentials in the authority (basic-auth style endpoints that
    # httpx accepts, e.g. MCP/extension proxies) must be blanked too — the
    # authority is split so only <redacted>@ survives in front of the host.
    userinfo = _httpx_record("https://user:token123@internal-proxy.corp:8080/v1/secret-endpoint")
    assert filt.filter(userinfo) is True
    userinfo_formatted = userinfo.getMessage()
    assert "https://<redacted>@internal-proxy.corp:8080/<redacted>" in userinfo_formatted
    assert "token123" not in userinfo_formatted
    assert "user:" not in userinfo_formatted

    # Authority-ONLY URL (no path/query): rest is optional in the regex, so a
    # userinfo credential with nowhere else to hide is still blanked.
    authority_only = _httpx_record("https://user:tok@internal-proxy.corp")
    assert filt.filter(authority_only) is True
    authority_formatted = authority_only.getMessage()
    assert "https://<redacted>@internal-proxy.corp" in authority_formatted
    assert "tok" not in authority_formatted.replace("<redacted>", "")

    # A bare credential-free origin without path/query is left as-is.
    bare = _httpx_record("https://host.example")
    assert filt.filter(bare) is True
    assert "https://host.example" in bare.getMessage()
    assert "<redacted>" not in bare.getMessage()

    # Records without a URL pass through untouched (message + args kept).
    plain = logging.LogRecord("httpx", logging.INFO, __file__, 1, "keep %s", ("this",), None)
    assert filt.filter(plain) is True
    assert plain.getMessage() == "keep this"


def test_url_redaction_filter_covers_urllib3_redirect_records() -> None:
    """Real-emitter wiring: urllib3 logs through CHILD loggers, and a filter on
    the bare ``urllib3`` logger never sees propagated records (logger filters
    are not inherited). Verified against the installed urllib3 2.7.0:
    ``urllib3.poolmanager`` logs ``Redirecting %s -> %s`` at INFO
    (poolmanager.py:500) and ``urllib3.connectionpool`` logs the same shape at
    DEBUG (connectionpool.py:922). Both must come out redacted through the
    real emit path with configure_logging's handler-level installation."""
    from deerflow.logging_config import configure_logging

    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)

    try:
        root.handlers = [handler]
        root.setLevel(logging.DEBUG)
        configure_logging(SimpleNamespace(log_level="debug", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))

        logging.getLogger("urllib3.poolmanager").info(
            "Redirecting %s -> %s",
            "https://cdn.example/private/BearerSecret?token=QuerySecret",
            "https://mirror.example/private/BearerSecret?sig=OtherSecret",
        )
        logging.getLogger("urllib3.connectionpool").debug(
            "Redirecting %s -> %s",
            "https://cdn.example/private/BearerSecret?token=QuerySecret",
            "https://mirror.example/private/BearerSecret?sig=OtherSecret",
        )

        out = stream.getvalue()
        assert "BearerSecret" not in out
        assert "QuerySecret" not in out
        assert "OtherSecret" not in out
        assert out.count("cdn.example/<redacted>") == 2
        assert out.count("mirror.example/<redacted>") == 2
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)


def test_url_redaction_filter_covers_urllib3_request_line_records() -> None:
    """urllib3's per-request DEBUG line splits the URL across its format
    string, so the absolute-URL regex alone cannot catch it. The installed
    urllib3 (2.7.0) emits this exact record from
    HTTPConnectionPool._make_request (connectionpool.py:545):
    log.debug('%s://%s:%s "%s %s %s" %s %s', scheme, host, port, method,
    url, response.version_string, response.status,
    response.length_remaining) — the authority ends at a space (bare-origin
    early return) and the quoted origin-form target has no scheme, which is
    why the request line needs its own redaction shape."""
    from deerflow.logging_config import UrlRedactionFilter

    format_string = '%s://%s:%s "%s %s %s" %s %s'
    filt = UrlRedactionFilter()

    def _record(target: str, version: str = "HTTP/1.1", method: str = "GET") -> logging.LogRecord:
        return logging.LogRecord(
            "urllib3.connectionpool",
            logging.DEBUG,
            __file__,
            1,
            format_string,
            ("https", "cdn.example", 443, method, target, version, 200, None),
            None,
        )

    # The reviewer's repro shape: host:port, then a quoted request line whose
    # origin-form target carries the signed path+query. The rewrite keeps
    # scheme + host + method + version for observability and collapses the
    # target to /<redacted>.
    record = _record("/private/BearerSecret?token=QuerySecret")
    assert filt.filter(record) is True
    formatted = record.getMessage()
    assert formatted == 'https://cdn.example:443 "GET /<redacted> HTTP/1.1" 200 None'
    assert "BearerSecret" not in formatted
    assert "token=" not in formatted

    # A target with no query still hides the path: the inbound-media rule is
    # host-only visibility, not query-only.
    path_only = _record("/private/photo.jpg")
    assert filt.filter(path_only) is True
    assert '"GET /<redacted> HTTP/1.1"' in path_only.getMessage()
    assert "photo.jpg" not in path_only.getMessage()

    # HTTP/2 responses keep version_string in the quoted line; the shape must
    # still match and rewrite.
    http2 = _record("/private/BearerSecret?token=QuerySecret", version="HTTP/2")
    assert filt.filter(http2) is True
    assert '"GET /<redacted> HTTP/2"' in http2.getMessage()
    assert "BearerSecret" not in http2.getMessage()


def test_url_redaction_filter_covers_urllib3_request_line_through_real_emit() -> None:
    """Real-emitter wiring for the per-request line: urllib3 logs through the
    ``urllib3.connectionpool`` child logger at DEBUG, so only the
    handler-level filters installed by configure_logging can rewrite the
    record. Emits with the connectionpool.py:545 format string at root
    DEBUG."""
    from deerflow.logging_config import configure_logging

    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)

    try:
        root.handlers = [handler]
        root.setLevel(logging.DEBUG)
        configure_logging(SimpleNamespace(log_level="debug", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))

        logging.getLogger("urllib3.connectionpool").debug(
            '%s://%s:%s "%s %s %s" %s %s',
            "https",
            "cdn.example",
            443,
            "GET",
            "/private/BearerSecret?token=QuerySecret",
            "HTTP/1.1",
            200,
            None,
        )

        out = stream.getvalue()
        assert "BearerSecret" not in out
        assert "QuerySecret" not in out
        assert 'https://cdn.example:443 "GET /<redacted> HTTP/1.1"' in out
        assert "200" in out  # status observability preserved
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)


def test_url_redaction_filter_covers_urllib3_retry_lines() -> None:
    """urllib3's retry sites log the request target with no scheme and no
    quoting, so neither the absolute-URL nor the quoted request-line pattern
    can see it. Verified against the installed urllib3 (2.7.0):
    ``Retry: %s`` (connectionpool.py:954, DEBUG),
    ``Incremented Retry for (url='%s'): %r`` (util/retry.py:545, DEBUG —
    origin-form target on the request path), and
    ``Retrying (%r) after connection broken by '%r': %s``
    (connectionpool.py:869, WARNING — above the Gateway's INFO root). Each
    collapses the target to ``/<redacted>`` while keeping the surrounding
    format (status counts, error text) for observability."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    def _record(name: str, fmt: str, args: tuple) -> logging.LogRecord:
        return logging.LogRecord(name, logging.DEBUG, __file__, 1, fmt, args, None)

    # connectionpool.py:954 — bare origin-form target after "Retry: ".
    retry_target = _record("urllib3.connectionpool", "Retry: %s", ("/private/BearerSecret?token=QuerySecret",))
    assert filt.filter(retry_target) is True
    assert retry_target.getMessage() == "Retry: /<redacted>"

    # An absolute target on the same line is the generic pass's job.
    retry_absolute = _record("urllib3.connectionpool", "Retry: %s", ("https://cdn.example/private/BearerSecret?token=QuerySecret",))
    assert filt.filter(retry_absolute) is True
    assert retry_absolute.getMessage() == "Retry: https://cdn.example/<redacted>"

    # util/retry.py:545 — origin-form target inside the quoted url slot; the
    # ``'): `` closer must survive the rewrite byte-for-byte.
    increment = _record(
        "urllib3.util.retry",
        "Incremented Retry for (url='%s'): %r",
        ("/private/BearerSecret?token=QuerySecret", "Retry(total=1, connect=2, read=None, redirect=None, status=None, other=None, allowed_methods=None)"),
    )
    assert filt.filter(increment) is True
    assert increment.getMessage() == "Incremented Retry for (url='/<redacted>'): 'Retry(total=1, connect=2, read=None, redirect=None, status=None, other=None, allowed_methods=None)'"

    # The same line on the redirect path carries an ABSOLUTE target. The
    # round-8 review repro: the generic pass's ``rest`` swallowed the
    # ``'): `` closer and mangled the line — ``rest`` now stops at quotes, so
    # the absolute URL is rewritten in place with the closer intact.
    increment_absolute = _record(
        "urllib3.util.retry",
        "Incremented Retry for (url='%s'): %r",
        ("https://cdn.example/private/BearerSecret?token=QuerySecret", "Retry(total=1, connect=2)"),
    )
    assert filt.filter(increment_absolute) is True
    assert increment_absolute.getMessage() == "Incremented Retry for (url='https://cdn.example/<redacted>'): 'Retry(total=1, connect=2)'"

    # Userinfo in the absolute increment target is blanked like everywhere
    # else, with the closing quote intact.
    increment_userinfo = _record(
        "urllib3.util.retry",
        "Incremented Retry for (url='%s'): %r",
        ("https://user:tok@internal-proxy.corp:8080/private/BearerSecret", "Retry(total=1)"),
    )
    assert filt.filter(increment_userinfo) is True
    assert increment_userinfo.getMessage() == "Incremented Retry for (url='https://<redacted>@internal-proxy.corp:8080/<redacted>'): 'Retry(total=1)'"

    # connectionpool.py:869 — WARNING level, so it passes an INFO root. The
    # error repr keeps its own quotes; the greedy split still pins the target
    # to the final ``': `` and the error text survives for observability.
    # Args are real objects, matching how urlopen calls the site.
    import urllib3

    retries_obj = urllib3.Retry(total=2, redirect=0)
    timeout_err = urllib3.exceptions.ReadTimeoutError(None, None, "Read timed out.")
    retrying = _record(
        "urllib3.connectionpool",
        "Retrying (%r) after connection broken by '%r': %s",
        (retries_obj, timeout_err, "/private/BearerSecret?token=QuerySecret"),
    )
    assert filt.filter(retrying) is True
    # Exact line equality: only the target changed; retry state and error
    # text (observability) survive verbatim.
    assert retrying.getMessage() == f"Retrying ({retries_obj!r}) after connection broken by '{timeout_err!r}': /<redacted>"
    assert "BearerSecret" not in retrying.getMessage()
    assert "Read timed out" in retrying.getMessage()

    # Redirecting (poolmanager.py:500 INFO / connectionpool.py:922 DEBUG):
    # either slot may be an origin-form target — connectionpool passes the
    # origin-form request target, and a relative Location header has no
    # scheme. Origin-form slots collapse; absolute slots are the generic
    # pass's job.
    redirect_origin = logging.LogRecord("urllib3.connectionpool", logging.DEBUG, __file__, 1, "Redirecting %s -> %s", ("/private/BearerSecret?token=QuerySecret", "/other/BearerSecret?sig=OtherSecret"), None)
    assert filt.filter(redirect_origin) is True
    assert redirect_origin.getMessage() == "Redirecting /<redacted> -> /<redacted>"

    redirect_mixed = logging.LogRecord("urllib3.poolmanager", logging.INFO, __file__, 1, "Redirecting %s -> %s", ("/private/BearerSecret?token=QuerySecret", "https://mirror.example/other?sig=OtherSecret"), None)
    assert filt.filter(redirect_mixed) is True
    assert redirect_mixed.getMessage() == "Redirecting /<redacted> -> https://mirror.example/<redacted>"

    # A raw Location field from a misbehaving server can contain interior
    # whitespace. It must not disable the source-target redaction.
    redirect_spaced_location = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        "Redirecting %s -> %s",
        ("/private/BearerSecret?token=QuerySecret", "/bad location"),
        None,
    )
    assert filt.filter(redirect_spaced_location) is True
    assert redirect_spaced_location.getMessage() == "Redirecting /<redacted> -> /<redacted>"

    # Lowercase custom methods ride the same request-line shape (methods are
    # case-sensitive tokens; callers may pass any case).
    lowercase = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        '%s://%s:%s "%s %s %s" %s %s',
        ("https", "cdn.example", 443, "patch", "/private/BearerSecret?token=QuerySecret", "HTTP/1.1", 200, None),
        None,
    )
    assert filt.filter(lowercase) is True
    assert lowercase.getMessage() == 'https://cdn.example:443 "patch /<redacted> HTTP/1.1" 200 None'

    # Adjacent non-URL lines must pass through untouched: the shapes are
    # anchored to the exact urllib3 formats, not to the word "Retry".
    plain_retry = _record("some.other.lib", "Retry: attempt scheduled soon", ())
    assert filt.filter(plain_retry) is True
    assert plain_retry.getMessage() == "Retry: attempt scheduled soon"
    plain_conn = _record("urllib3.connectionpool", "Starting new HTTP connection (%d): %s:%s", (1, "cdn.example", 443))
    assert filt.filter(plain_conn) is True
    assert plain_conn.getMessage() == "Starting new HTTP connection (1): cdn.example:443"


def test_url_redaction_filter_covers_urllib3_retry_lines_through_real_emit() -> None:
    """Real-emitter wiring for the retry lines: the increment line is produced
    by actually calling ``Retry.increment`` (retry.py:545 logs through the
    ``urllib3.util.retry`` child logger at DEBUG), and the connectionpool
    shapes are emitted through the real child logger with the exact installed
    format strings. Only the handler-level filters installed by
    configure_logging can rewrite propagated records."""
    import urllib3
    from urllib3.util.retry import Retry

    from deerflow.logging_config import configure_logging

    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)

    try:
        root.handlers = [handler]
        root.setLevel(logging.DEBUG)
        configure_logging(SimpleNamespace(log_level="debug", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))

        # retry.py:545 via the library's own code path (no-args increment
        # takes the generic-response branch and logs without raising).
        Retry(total=2).increment(method="GET", url="/private/BearerSecret?token=QuerySecret")

        logging.getLogger("urllib3.connectionpool").debug("Retry: %s", "/private/BearerSecret?token=QuerySecret")
        logging.getLogger("urllib3.connectionpool").warning(
            "Retrying (%r) after connection broken by '%r': %s",
            Retry(total=2, redirect=0),
            urllib3.exceptions.ReadTimeoutError(None, None, "Read timed out."),
            "/private/BearerSecret?token=QuerySecret",
        )
        logging.getLogger("urllib3.connectionpool").debug(
            "Redirecting %s -> %s",
            "/private/BearerSecret?token=QuerySecret",
            "https://mirror.example/other/BearerSecret?sig=OtherSecret",
        )

        out = stream.getvalue()
        assert "BearerSecret" not in out
        assert "QuerySecret" not in out
        assert "OtherSecret" not in out
        # Redacted, not suppressed: every line still renders with its shape
        # and the parts that carry no URL (retry state, error text, hosts).
        assert "Incremented Retry for (url='/<redacted>')" in out
        assert "Retry: /<redacted>" in out
        assert "after connection broken by" in out and "Read timed out" in out and "': /<redacted>" in out
        assert "Redirecting /<redacted> -> https://mirror.example/<redacted>" in out
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)


def test_configure_logging_installs_url_redaction_on_httpx_logger_and_root_handlers() -> None:
    from deerflow.logging_config import UrlRedactionFilter, _has_url_redaction_filter, configure_logging, install_url_log_redaction

    httpx_logger = logging.getLogger("httpx")
    root = logging.getLogger()
    old_filters = httpx_logger.filters[:]
    old_handlers = root.handlers[:]
    handler = logging.StreamHandler(io.StringIO())

    try:
        root.handlers = [handler]
        httpx_logger.filters = [f for f in old_filters if not isinstance(f, UrlRedactionFilter)]
        install_url_log_redaction()
        install_url_log_redaction()  # idempotent
        assert sum(isinstance(f, UrlRedactionFilter) for f in httpx_logger.filters) == 1
        assert all(_has_url_redaction_filter(h) for h in root.handlers)

        # Handlers added later are covered by the configure_logging loop, not
        # by the one-shot installer.
        late = logging.StreamHandler(io.StringIO())
        root.handlers.append(late)
        configure_logging(SimpleNamespace(log_level="info", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))
        assert _has_url_redaction_filter(late)
        assert _has_url_redaction_filter(root.handlers[0])
    finally:
        httpx_logger.filters = old_filters
        root.handlers = old_handlers


def test_url_redaction_filter_long_input_stays_linear_time() -> None:
    """Long-input regression (round-9 review finding): both scheme-bearing
    patterns start with a character class, so re.sub-style scanning retries
    every suffix of a long token — the reviewer measured ~1.79 s for a 64K
    path and ~3.10 s for a URL-free 64K error body, per filter call, and the
    filter runs synchronously in every root handler. The scheme passes are
    driven from "://" occurrences instead, so the same inputs cost
    milliseconds. The bound is generous (the quadratic path at 256K would
    take tens of seconds) to stay robust on slow CI runners, while still
    going red against any regression to per-position rescanning."""
    import time

    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    # Ordinary HTTPX URL whose path is a 256K letter run. httpx.URL rejects
    # URLs this long, so the record is built directly with the URL as a
    # plain string arg — the rendered message shape is identical.
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        _HTTPX_REQUEST_FORMAT,
        ("GET", "https://cdn.weixin.qq.com/private/" + "A" * 262144, "HTTP/1.1", 200, "OK"),
        None,
    )
    started = time.perf_counter()
    assert filt.filter(record) is True
    elapsed_url = time.perf_counter() - started
    assert elapsed_url < 5.0, f"URL-bearing record took {elapsed_url:.2f}s"
    formatted = record.getMessage()
    assert "cdn.weixin.qq.com/<redacted>" in formatted  # still redacted, and
    assert "A" * 64 not in formatted  # the long path itself did not survive

    # A URL-free 64K letter error body through the real wiring: the filter
    # runs in the root handler, and the message must pass through verbatim.
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    try:
        root.handlers = [handler]
        root.setLevel(logging.INFO)
        configure_logging(SimpleNamespace(log_level="info", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))
        body = "E" * 65536
        started = time.perf_counter()
        logging.getLogger("some.error.reporter").error("payload too large: %s", body)
        elapsed_plain = time.perf_counter() - started
        assert elapsed_plain < 5.0, f"URL-free record took {elapsed_plain:.2f}s"
        assert stream.getvalue().endswith("payload too large: " + body + "\n")
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)


def test_url_redaction_filter_nested_scheme_in_path_keeps_both_passes() -> None:
    """The scheme-bearing passes run per "://" start, so a scheme-shaped
    target NESTED inside another URL's path still gets its own pass attempt:
    the outer absolute URL is rewritten first (its rest swallows the inner
    scheme text), and the inner request-line shape — if the path is followed
    by urllib3 quoting — is rewritten by the request-line pass that ran
    before it. Pins the leftmost-non-overlapping equivalence with the old
    two-pass re.sub behavior on overlapping candidates."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()
    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "fetch failed for %s and %s",
        ("https://gateway.example/redirect?to=https://evil.example/sink", 'https://evil.example "GET /private/BearerSecret?token=QuerySecret HTTP/1.1" 200 None'),
        None,
    )
    assert filt.filter(record) is True
    formatted = record.getMessage()
    assert "BearerSecret" not in formatted
    assert "token=" not in formatted
    assert "gateway.example/<redacted>" in formatted
    # The nested request line kept its quoted target redacted too.
    assert 'https://evil.example "GET /<redacted> HTTP/1.1"' in formatted


def test_url_redaction_filter_scheme_start_skips_non_letter_run_head() -> None:
    """The linear scan walks back over the full scheme charset (letters,
    digits, +, -, .) but a regex match can only start at the run's first
    LETTER — digits are valid scheme tail characters, never the head. A
    digit glued in front of a URL shifts the match start past it, exactly
    like re.sub's leftmost scan; a run with no letter at all ("123://x")
    cannot start any match and passes through with nothing rewritten."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()
    glued = logging.LogRecord("httpx", logging.INFO, __file__, 1, "fetch %s", ("9https://host.example/private/x?token=QuerySecret",), None)
    assert filt.filter(glued) is True
    assert glued.getMessage() == "fetch 9https://host.example/<redacted>"

    digits_only = logging.LogRecord("httpx", logging.INFO, __file__, 1, "fetch %s", ("123://host.example/private/x?token=QuerySecret",), None)
    assert filt.filter(digits_only) is True
    # "123" is not a scheme head, so no scheme starts at this "://" — the
    # text is left as-is by the scheme passes (no URL rewrite, no signal
    # loss; the record itself is not a valid URL shape).
    assert digits_only.getMessage() == "fetch 123://host.example/private/x?token=QuerySecret"


def test_url_redaction_filter_embedded_quotes_stay_inside_rest() -> None:
    """Boundary rule for the rest quote-stop (round-10 residual): a quote is
    a closing mark only when whitespace, ``)``, or end of string follows —
    the shapes that actually close a quoted URL (urllib3's
    ``Incremented Retry for (url='…')`` scaffolding, surrounding prose). A
    quote EMBEDDED in the URL itself (``/path'quoted'?token=…``) must be
    consumed so the whole path+query stays redacted; the earlier
    quote-stop-at-any-quote behavior kept the suffix after the quote
    verbatim."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    # The review repro, through the real httpx record shape: httpx.URL keeps
    # an apostrophe raw, so the embedded quote is present verbatim in the
    # rendered message. rest must consume it — the credential-bearing suffix
    # does not survive. (The httpx format quotes "version status reason"
    # together.)
    embedded = _httpx_record("https://host.example/path'quoted'?token=QuerySecret")
    assert filt.filter(embedded) is True
    assert embedded.getMessage() == 'HTTP Request: GET https://host.example/<redacted> "HTTP/1.1 200 OK"'
    assert "quoted" not in embedded.getMessage()
    assert "token=" not in embedded.getMessage()

    # A raw embedded DOUBLE quote (httpx.URL would percent-encode %22, so
    # this rides a plain string arg — MCP/extension riders may log
    # pre-rendered URLs).
    embedded_double = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        _HTTPX_REQUEST_FORMAT,
        ("GET", 'https://host.example/pa"th?token=QuerySecret', "HTTP/1.1", 200, "OK"),
        None,
    )
    assert filt.filter(embedded_double) is True
    assert embedded_double.getMessage() == 'HTTP Request: GET https://host.example/<redacted> "HTTP/1.1 200 OK"'
    assert "token=" not in embedded_double.getMessage()

    # Boundary quotes still close rest: prose quoting keeps its punctuation.
    prose_double = logging.LogRecord("some.lib", logging.INFO, __file__, 1, "see %s in the docs", ('"https://host.example/private/x?tok=1"',), None)
    assert filt.filter(prose_double) is True
    assert prose_double.getMessage() == 'see "https://host.example/<redacted>" in the docs'
    prose_single = logging.LogRecord("some.lib", logging.INFO, __file__, 1, "see %s please", ("'https://host.example/private/x?tok=1'",), None)
    assert filt.filter(prose_single) is True
    assert prose_single.getMessage() == "see 'https://host.example/<redacted>' please"

    # The increment line's url capture applies the same rule with its fixed
    # ``')`` closer: an embedded quote inside the target no longer truncates
    # the capture, so the whole origin-form target collapses.
    increment = logging.LogRecord(
        "urllib3.util.retry",
        logging.DEBUG,
        __file__,
        1,
        "Incremented Retry for (url='%s'): %r",
        ("/a'b?tok=QuerySecret", "Retry(total=1)"),
        None,
    )
    assert filt.filter(increment) is True
    assert increment.getMessage() == "Incremented Retry for (url='/<redacted>'): 'Retry(total=1)'"
    assert "tok=" not in increment.getMessage()


def test_url_redaction_filter_leaves_arrow_paths_in_other_logs_alone() -> None:
    """The Redirecting origin pass is anchored to the WHOLE ``Redirecting
    <t> -> <t>`` message because an ``-> /path`` arrow is not urllib3-owned
    shape: the sandbox provider's actionable mount error renders
    ``sandbox.mounts entry <host_path> -> <container_path>`` and a substring
    match rewrote the container path to ``/<redacted>``, breaking the error's
    instructions (backend-unit-tests shard 3 on CI, round 11)."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()
    sandbox_error = (
        "sandbox.mounts entry /srv/deer-flow/knowledge -> /mnt/knowledge ignored: host_path "
        "/srv/deer-flow/knowledge does not exist from the perspective of the gateway process. "
        "In Docker deployments (make up / docker-compose), this path must also be bind-mounted "
        "into the gateway container — add a matching volume entry under services.gateway.volumes "
        "in docker/docker-compose.yaml (and use the in-container path here), or run in local mode "
        "(make dev) where the gateway sees the host filesystem directly."
    )
    record = logging.LogRecord("deerflow.sandbox.local.local_sandbox_provider", logging.ERROR, "provider.py", 1, "%s", (sandbox_error,), None)
    assert filt.filter(record) is True
    assert record.getMessage() == sandbox_error  # byte-for-byte passthrough
    assert "/mnt/knowledge" in record.getMessage()
    assert "<redacted>" not in record.getMessage()


def test_url_redaction_filter_redirecting_survives_spacey_location() -> None:
    """Round-13 P3: the Redirecting anchor keeps the ``^Redirecting `` prefix
    (the urllib3-owned literal that stops the sandbox false positive) but the
    tail must be loose — ``redirect_location`` is the raw Location header
    string, and interior spaces are legal field syntax a misbehaving server
    can emit. A whitespace-strict tail voided the pass entirely and leaked
    the origin-form request target in the first slot; a space-carrying
    second slot now collapses whole."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    # The reviewer's repro: both credentials must go, shape kept.
    spacey = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        "Redirecting %s -> %s",
        ("/private/BearerSecret?token=QuerySecret", "/bad location"),
        None,
    )
    assert filt.filter(spacey) is True
    assert spacey.getMessage() == "Redirecting /<redacted> -> /<redacted>"
    assert "BearerSecret" not in spacey.getMessage()

    # The FIRST slot gets the same grammar treatment: the recursive urlopen
    # frame passes the previous raw Location as its url, so t1 can carry
    # interior spaces too.
    spacey_t1 = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        "Redirecting %s -> %s",
        ("/bad target?token=QuerySecret", "/private/x"),
        None,
    )
    assert filt.filter(spacey_t1) is True
    assert spacey_t1.getMessage() == "Redirecting /<redacted> -> /<redacted>"
    assert "QuerySecret" not in spacey_t1.getMessage()

    # An absolute Location with an interior space must NOT be handed to the
    # generic absolute-URL pass: that pass stops its ``rest`` at whitespace,
    # so the signed tail after the first space used to survive (round 16).
    # The slot collapses whole instead, like any other non-whole-coverable
    # slot shape.
    spacey_absolute = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        "Redirecting %s -> %s",
        ("/private/BearerSecret?token=QuerySecret", "https://mirror.example/other page?sig=OtherSecret"),
        None,
    )
    assert filt.filter(spacey_absolute) is True
    assert spacey_absolute.getMessage() == "Redirecting /<redacted> -> /<redacted>"
    assert "BearerSecret" not in spacey_absolute.getMessage()
    assert "OtherSecret" not in spacey_absolute.getMessage()
    assert "QuerySecret" not in spacey_absolute.getMessage()

    # Same in the first slot, where the recursive urlopen frame carries the
    # previous raw Location.
    spacey_absolute_t1 = logging.LogRecord(
        "urllib3.connectionpool",
        logging.DEBUG,
        __file__,
        1,
        "Redirecting %s -> %s",
        ("https://mirror.example/other page?sig=OtherSecret", "/private/x"),
        None,
    )
    assert filt.filter(spacey_absolute_t1) is True
    assert spacey_absolute_t1.getMessage() == "Redirecting /<redacted> -> /<redacted>"
    assert "OtherSecret" not in spacey_absolute_t1.getMessage()

    # The sandbox arrow false positive stays excluded: the prefix anchor,
    # not a strict tail, is what keeps non-Redirecting messages untouched.
    sandbox = logging.LogRecord("deerflow.sandbox.local.local_sandbox_provider", logging.ERROR, "p.py", 1, "sandbox.mounts entry /srv/knowledge -> /mnt/knowledge ignored: missing", (), None)
    assert filt.filter(sandbox) is True
    assert sandbox.getMessage() == "sandbox.mounts entry /srv/knowledge -> /mnt/knowledge ignored: missing"


def _emit_real_header_parse_warning(url: str, raw: bytes, *, json_format: bool = False) -> str:
    """Drive urllib3's own header-parse warning end to end and return the log line.

    ``http.client.parse_headers`` + ``assert_header_parsing`` build the real
    ``HeaderParsingError``, and the emission copies ``connection.py`` including
    ``exc_info=True``, so the result is what a handler's formatter writes - not
    just ``record.getMessage()``.
    """
    import http.client
    import io

    from urllib3.exceptions import HeaderParsingError
    from urllib3.util.response import assert_header_parsing

    from deerflow.logging_config import UrlRedactionFilter

    headers = http.client.parse_headers(io.BytesIO(raw))
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    if json_format:
        from deerflow.logging_config import JsonTraceFormatter

        handler.setFormatter(JsonTraceFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(UrlRedactionFilter())
    root.handlers = [handler]
    root.setLevel(logging.WARNING)
    try:
        try:
            assert_header_parsing(headers)
            raise AssertionError("expected HeaderParsingError")
        except (HeaderParsingError, TypeError) as hpe:
            logging.getLogger("urllib3.connection").warning("Failed to parse headers (url=%s): %s", url, hpe, exc_info=True)
        return stream.getvalue()
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_url_redaction_filter_collapses_credentials_in_a_header_parse_dump() -> None:
    """urllib3's header-parse warning embeds the raw response header block.

    ``connection.py:575-581`` logs ``Failed to parse headers (url=%s): %s`` at
    WARNING with ``exc_info=True``, and the pinned 2.7.0 ``HeaderParsingError``
    stringifies as ``"<defects>, unparsed data: <payload!r>"`` - the payload
    being everything after the FIRST malformed line of the response. Every
    credential-bearing field therefore sits behind that break, repr-escaped onto
    one physical line whose breaks are the literal four characters ``\\r\\n``.
    Field order is the response's choice, so both a leading ``Location`` and a
    leading ``Set-Cookie`` must collapse, and the emitted traceback must not
    re-carry the block the message line just lost.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    secrets = ("SignedPathSecret", "CookieSecret", "TokenSecret", "UrlSecret", "session=", "Bearer ")
    blocks = (
        # Location first: the signed origin-form target leads the payload.
        b"bad line\r\nLocation: /tenant-42/reports/q1?sig=SignedPathSecret\r\nSet-Cookie: session=CookieSecret; Path=/\r\nWWW-Authenticate: Bearer TokenSecret\r\nContent-Type: application/json\r\n\r\n",
        # Set-Cookie first: the credentials trail it.
        b"bad line\r\nSet-Cookie: session=CookieSecret; Path=/\r\nWWW-Authenticate: Bearer TokenSecret\r\nLocation: /tenant-42/reports/q1?sig=SignedPathSecret\r\nContent-Type: application/json\r\n\r\n",
    )

    for raw in blocks:
        formatted = _emit_real_header_parse_warning(url, raw)
        for secret in secrets:
            assert secret not in formatted, secret
        # Field names, the non-sensitive field and the defect itself stay.
        assert "Set-Cookie: <redacted>" in formatted
        assert "WWW-Authenticate: <redacted>" in formatted
        assert "Location: <redacted>" in formatted
        assert "Content-Type: application/json" in formatted
        assert "bad line" in formatted


def test_url_redaction_filter_collapses_credentials_behind_escaped_bare_cr_separators() -> None:
    """A payload separated on bare CR alone must collapse too.

    ``http.client`` accepts ``\\r`` as a line terminator even though RFC 9112
    defines only CRLF, so ``parse_headers`` + ``assert_header_parsing`` yield a
    ``HeaderParsingError`` whose payload carries every field after a bare-CR
    break. That block reaches the record through ``!r``, so its separators are
    the two characters ``\\r`` rather than the four of ``\\r\\n``: a splitter
    that knows escaped CRLF and escaped LF but not escaped bare CR keeps the
    whole dump in one segment. No field name then sits at a segment start, the
    anchor never fires, and the cookie and the signed ``Location`` are logged
    verbatim in both the message and the ``exc_text`` that repeats it, and the
    deployed JSON format renders the same repr, so it must collapse there too.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    raw = b"bad line\rSet-Cookie: session=BareCRSecret\rLocation: /p?sig=LocationSecret\r\r"

    formatted = _emit_real_header_parse_warning(url, raw)
    # ``logging.enhance.format=json`` is the Gateway's setting, and its formatter
    # renders the exception itself rather than the filter's redacted exc_text.
    for out in (formatted, _emit_real_header_parse_warning(url, raw, json_format=True)):
        for secret in ("BareCRSecret", "LocationSecret", "session=", "UrlSecret"):
            assert secret not in out, secret
    # The names survive for operator legibility, and so does the malformed line.
    assert "Set-Cookie: <redacted>" in formatted
    assert "Location: <redacted>" in formatted
    assert "bad line" in formatted


def test_url_redaction_filter_collapses_folded_continuations_and_proxy_auth_info() -> None:
    """A collapsed field's value can continue on the following line, and
    ``Proxy-Authentication-Info`` is the proxy-side twin of a field already on
    the list.

    RFC 5322 obs-fold marks a continuation with a leading SP/HTAB, and this
    warning dumps malformed upstream bytes, so folded lines cannot be assumed
    absent: replacing only the matched segment would log ``Set-Cookie:
    <redacted>`` followed by the still-plain ``CookieSecret; Path=/``. A
    non-sensitive field keeps its own continuation, which is what bounds the
    rewrite to the fields this pass actually collapses.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    raw = b'bad line\r\nSet-Cookie: session=\r\n CookieSecret; Path=/\r\nProxy-Authentication-Info: nextnonce="ProxySecret"\r\nContent-Type: application/json\r\n\tcharset=utf-8\r\n\r\n'

    formatted = _emit_real_header_parse_warning(url, raw)
    for secret in ("CookieSecret", "ProxySecret", "session=", "UrlSecret"):
        assert secret not in formatted, secret
    assert "Set-Cookie: <redacted>" in formatted
    assert "Proxy-Authentication-Info: <redacted>" in formatted
    # The continuation is part of the collapsed field, so it goes too.
    assert "Set-Cookie: <redacted>\\r\\n<redacted>" in formatted
    assert "Content-Type: application/json" in formatted
    assert "charset=utf-8" in formatted


def test_url_redaction_filter_collapses_a_credential_folded_under_an_unlisted_field() -> None:
    """A folded credential is still that header's value, whatever field it folds under.

    Under RFC 7230 unfolding ``X-Trace: keep\\r\\n Authorization: Bearer …`` is one
    header whose value carries the bearer token, so the fold is a credential leak
    even though the field it attaches to is not on the list. Anchoring the field
    name only at the segment start let exactly this segment through while the
    unindented ``Set-Cookie`` right after it collapsed, which is the proof the
    pass ran rather than that a name matched.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    raw = b"bad line\r\nX-Trace: keep\r\n Authorization: Bearer FoldSecret\r\nSet-Cookie: session=CookieSecret\r\n\r\n"

    formatted = _emit_real_header_parse_warning(url, raw)
    for secret in ("FoldSecret", "CookieSecret", "Bearer", "UrlSecret"):
        assert secret not in formatted, secret
    # The fold marker and the name stay for operator legibility, and the
    # non-sensitive field the credential folded under keeps its own value.
    assert " Authorization: <redacted>" in formatted
    assert "X-Trace: keep" in formatted
    assert "Set-Cookie: <redacted>" in formatted


def test_url_redaction_filter_collapses_an_escaped_htab_continuation() -> None:
    """A tab continuation reaches the log as ``\\t``, not as a real HTAB.

    ``HeaderParsingError`` renders the payload with ``!r``, so the RFC 5322
    marker in front of a folded value survives into the record as the two
    characters backslash-t. A fold test that uses a space for the sensitive
    continuation therefore never asks the walk about that spelling, and a
    bearer token sitting behind it is logged whole.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    raw = b"bad line\r\nSet-Cookie: session=AlphaSecret\r\n\tBetaSecret; Path=/\r\nContent-Type: application/json\r\n\tcharset=utf-8\r\n\r\n"

    formatted = _emit_real_header_parse_warning(url, raw)
    for secret in ("AlphaSecret", "BetaSecret", "session=", "UrlSecret"):
        assert secret not in formatted, secret
    assert "Set-Cookie: <redacted>\\r\\n<redacted>" in formatted
    # The asymmetry holds under the escaped spelling: a continuation that names
    # no credential field stays, so this pass cannot be replaced by "fold
    # everything whitespace-led".
    assert "Content-Type: application/json" in formatted
    assert "\\tcharset=utf-8" in formatted


def test_url_redaction_filter_collapses_a_credential_entirely_inside_the_fold() -> None:
    """An empty first segment does not mean the folded field has no value.

    ``Set-Cookie:\\r\\n CookieSecret`` puts the whole value on the continuation.
    Gating the fold walk on the matched segment having a non-empty value
    skipped the walk for exactly this shape, so the credential was logged
    while a same-shaped field with a value collapsed. The field itself stays
    as written — nothing on that segment was redacted.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    raw = b"bad line\r\nSet-Cookie:\r\n GammaSecret; Path=/\r\nX-Other: keep\r\n\r\n"

    formatted = _emit_real_header_parse_warning(url, raw)
    for secret in ("GammaSecret", "UrlSecret"):
        assert secret not in formatted, secret
    assert "Set-Cookie:\\r\\n<redacted>" in formatted
    assert "X-Other: keep" in formatted


def test_url_redaction_filter_collapses_dump_credentials_in_json_logging_too() -> None:
    """JSON output must not reopen the leak the text path closes.

    ``JsonTraceFormatter`` renders the exception itself rather than going
    through ``logging.Formatter.format``, so it can discard a filter's redacted
    ``exc_text`` and re-emit the payload; the Gateway runs with
    ``logging.enhance.format=json``, which makes that the deployed path.
    """
    url = "https://cdn.example.com:443/tenant-42/reports/q1?sig=UrlSecret"
    raw = b"bad line\r\nSet-Cookie: session=CookieSecret; Path=/\r\nLocation: /tenant-42/reports/q1?sig=SignedPathSecret\r\n\r\n"

    formatted = _emit_real_header_parse_warning(url, raw, json_format=True)
    for secret in ("SignedPathSecret", "CookieSecret", "UrlSecret", "session="):
        assert secret not in formatted, secret
    assert "Set-Cookie: <redacted>" in formatted
    assert "unparsed data:" in formatted  # the shape stays diagnosable


def test_url_redaction_filter_collapses_credentials_carried_by_the_traceback() -> None:
    """The warning's traceback text is a second copy of the dump.

    ``logging.Formatter.format`` appends ``formatException`` to any record that
    carries ``exc_info``, independently of the format string, and that text ends
    with the exception's own ``unparsed data: '<payload>'`` line. Redacting the
    message alone leaves the credentials in the log whole, so the filter
    pre-populates ``exc_text`` - the Formatter only recomputes it when unset.
    """
    from urllib3.exceptions import HeaderParsingError

    from deerflow.logging_config import UrlRedactionFilter

    payload = "Set-Cookie: session=CookieSecret\r\n"
    record = logging.LogRecord("urllib3.connection", logging.WARNING, __file__, 1, "Failed to parse headers (url=%s): %s", ("https://cdn.example.com/tenant-42/x?sig=UrlSecret", HeaderParsingError([], payload)), None)
    record.exc_info = (HeaderParsingError, HeaderParsingError([], "Set-Cookie: session=CookieSecret\r\n"), None)

    assert UrlRedactionFilter().filter(record) is True
    assert record.exc_text is not None
    assert "CookieSecret" not in record.getMessage() + record.exc_text
    assert "Set-Cookie: <redacted>" in record.exc_text
    assert "unparsed data:" in record.exc_text


def test_url_redaction_filter_does_not_format_exceptions_of_other_records() -> None:
    """The traceback pass is gated on urllib3's own literal, like the dump pass.

    Formatting an arbitrary record's exception to scan it would cost every error
    log a ``linecache`` read for no redaction benefit, so a record that is not
    urllib3's header-parse warning keeps its ``exc_text`` unset.
    """
    from deerflow.logging_config import UrlRedactionFilter

    record = logging.LogRecord("deerflow.something", logging.ERROR, __file__, 1, "upstream call failed", (), None)
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record.exc_info = sys.exc_info()

    assert UrlRedactionFilter().filter(record) is True
    assert record.exc_text is None


def test_url_redaction_filter_anchors_every_repr_form_of_the_payload() -> None:
    """The dump pass anchors on the payload's own delimiters, not on guesses.

    ``HeaderParsingError`` renders ``unparsed_data`` through ``!r``, so the field
    lines are separated by the four characters ``\\r\\n`` and the first field
    follows the repr's opening quote - which is ``'``, ``"``, ``b'`` or ``b"``
    depending on the payload's type and on whether the value holds a quote. Each
    of those is an anchor this pass must recognise, or the field glued to it
    stays whole.
    """
    from deerflow.logging_config import UrlRedactionFilter

    cases = [
        # First field glued to the repr's opening quote.
        (
            """Failed to parse headers (url=https://h/p): [D], unparsed data: 'Set-Cookie: session=CookieSecret\\r\\nContent-Type: text/plain\\r\\n'""",
            "Set-Cookie: <redacted>",
            "Content-Type: text/plain",
        ),
        # The payload holds an apostrophe, so repr switches to double quotes.
        (
            '''Failed to parse headers (url=https://h/p): [D], unparsed data: "Set-Cookie: it's-CookieSecret\\r\\n"''',
            "Set-Cookie: <redacted>",
            None,
        ),
        # Bytes payload.
        (
            """Failed to parse headers (url=https://h/p): [D], unparsed data: b'Set-Cookie: session=CookieSecret\\r\\n'""",
            "Set-Cookie: <redacted>",
            None,
        ),
        # A later field carries an absolute URL: its secret is the credential
        # field's own, and the field collapses before the URL pass could need it.
        (
            """Failed to parse headers (url=https://h/p): [D], unparsed data: 'bad\\r\\nLocation: https://cdn.example/tenant-42/x?sig=SignedPathSecret\\r\\n'""",
            "Location: <redacted>",
            None,
        ),
        # Single-character escape break instead of the CRLF pair.
        (
            """Failed to parse headers (url=https://h/p): [D], unparsed data: 'bad\\nWWW-Authenticate: Bearer TokenSecret\\n'""",
            "WWW-Authenticate: <redacted>",
            None,
        ),
    ]
    secrets = ("CookieSecret", "SignedPathSecret", "TokenSecret")

    for message, collapsed, kept_field in cases:
        record = logging.LogRecord("urllib3.connection", logging.WARNING, __file__, 1, message, (), None)
        assert UrlRedactionFilter().filter(record) is True
        formatted = record.getMessage()
        for secret in secrets:
            assert secret not in formatted, (message, secret)
        assert "unparsed data:" in formatted
        assert collapsed in formatted, formatted
        if kept_field:
            assert kept_field in formatted, formatted


def test_url_redaction_filter_leaves_header_looking_text_outside_the_dump_alone() -> None:
    """The dump pass is gated on urllib3's own literal, not on header syntax.

    A ``Set-Cookie:`` shaped line in some other component's log is that
    component's data, and rewriting it here would silently widen a URL
    redactor into a general PII filter.
    """
    from deerflow.logging_config import UrlRedactionFilter

    record = logging.LogRecord(
        "deerflow.something",
        logging.INFO,
        __file__,
        1,
        "parsed upstream reply: Set-Cookie: session=OtherCookieSecret",
        (),
        None,
    )

    assert UrlRedactionFilter().filter(record) is True
    assert "OtherCookieSecret" in record.getMessage()


def test_url_redaction_filter_redirecting_covers_all_relative_ref_forms() -> None:
    """Round-15 residual: a Redirecting slot stayed verbatim unless it
    started with "/", but the Location field-value grammar (RFC 3986
    relative-part) also admits slash-less relative references —
    ``download?sign=…`` and ``?sign=…`` kept their signed queries verbatim,
    and neither the slot rule nor the generic absolute-URL pass (which
    needs a scheme) could see them. A slot is now kept ONLY when the generic
    pass itself consumes it whole, so every relative-reference form collapses,
    non-hierarchical schemes (``data:…``) collapse, a space-carrying
    absolute slot collapses instead of leaking its signed tail (round 16),
    and so does a slot the pass stops early on — a quote that reads as a
    closing mark, or an empty host the ``host`` group never matches;
    network-path references collapse with any
    userinfo credentials they carry."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    cases = [
        # (t1, t2, expected t2 rendering after the generic pass runs)
        ("/private/BearerSecret?token=QuerySecret", "download?sign=LeakedSig", "Redirecting /<redacted> -> /<redacted>"),  # round-15 repro
        ("/private/BearerSecret?token=QuerySecret", "?sign=LeakedSig", "Redirecting /<redacted> -> /<redacted>"),  # query-only
        ("/private/x", "#frag", "Redirecting /<redacted> -> /<redacted>"),  # fragment-only
        ("/private/x", "data:application/json;base64,SECRET", "Redirecting /<redacted> -> /<redacted>"),  # non-hierarchical scheme
        ("/private/x", "//cdn.example/private/x?sig=OtherSecret", "Redirecting /<redacted> -> /<redacted>"),  # network-path
        ("/private/x", "//user:tok@cdn.example/private/x?sig=OtherSecret", "Redirecting /<redacted> -> /<redacted>"),  # network-path + userinfo
        # Absolute URLs are still kept whole for the generic absolute-URL pass.
        ("/private/BearerSecret?token=QuerySecret", "https://mirror.example/other?sig=OtherSecret", "Redirecting /<redacted> -> https://mirror.example/<redacted>"),
        # ... but only when the generic pass consumes the slot WHOLE. Its
        # ``host``/``rest`` groups stop at whitespace, so a space-carrying
        # absolute slot leaks its signed tail if it is handed over (round 16).
        ("/private/BearerSecret?token=QuerySecret", "https://mirror.example/other page?sig=OtherSecret", "Redirecting /<redacted> -> /<redacted>"),
        ("https://mirror.example/other page?sig=OtherSecret", "/private/x", "Redirecting /<redacted> -> /<redacted>"),
        ("/private/x", "https://mirror.example/a\tb?sig=OtherSecret", "Redirecting /<redacted> -> /<redacted>"),  # any whitespace, not just a space
        ("/private/x", "https://mirror.example/a%20b?sig=Ok", "Redirecting /<redacted> -> https://mirror.example/<redacted>"),  # percent-encoded space stays absolute
        # The pass also stops early INSIDE a whitespace-free absolute slot, so
        # the "is it absolute" test alone was still not sufficient (review of
        # #5687): a quote that reads as a closing mark ends ``rest`` there,
        # and an empty host before the first ``/?#`` matches nowhere at all.
        ("/private/x", "https://mirror.example/a')b?sig=LeakedSigQuote", "Redirecting /<redacted> -> /<redacted>"),
        ("https://mirror.example/a')b?sig=LeakedSigQuote", "/private/x", "Redirecting /<redacted> -> /<redacted>"),
        ("/private/x", "https:///path?sig=LeakedSigEmptyHost", "Redirecting /<redacted> -> /<redacted>"),
        ("https:///path?sig=LeakedSigEmptyHost", "/private/x", "Redirecting /<redacted> -> /<redacted>"),
        ("/private/x", 'https://mirror.example/a")b?sig=LeakedSigDQuote', "Redirecting /<redacted> -> /<redacted>"),
        # A quote embedded mid-path is NOT a closing mark, so that slot is
        # still consumed whole and keeps its host for debuggability.
        ("/private/x", "https://mirror.example/a'b?sig=Ok", "Redirecting /<redacted> -> https://mirror.example/<redacted>"),
    ]
    for t1, t2, expected in cases:
        record = logging.LogRecord("urllib3.connectionpool", logging.DEBUG, __file__, 1, "Redirecting %s -> %s", (t1, t2), None)
        assert filt.filter(record) is True
        assert record.getMessage() == expected, (t1, t2)
        assert "LeakedSig" not in record.getMessage()
        assert "token=QuerySecret" not in record.getMessage()


def test_url_redaction_filter_collapses_space_carrying_targets_in_every_retry_shape() -> None:
    """Every urllib3 shape that carries a raw request target has to tolerate
    interior spaces, not only ``Redirecting``.

    On the recursive redirect frame urllib3 hands the raw ``Location`` field
    value on as ``url`` (connectionpool.py:923-925), and that field grammar
    admits interior spaces — the same fact rounds 13 and 16 rest on. The three
    shapes pinned here bounded their target at the first space, so a signed
    path survived all of them while the two sibling passes that never did
    (``Incremented Retry for (url='…')`` and ``Redirecting``) redacted it.
    """
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()

    def _formatted(fmt: str, args: tuple) -> str:
        record = logging.LogRecord("urllib3.connectionpool", logging.DEBUG, __file__, 1, fmt, args, None)
        assert filt.filter(record) is True
        return record.getMessage()

    signed = "/private/a b?sig=LeakedSig"

    # connectionpool.py:954 — bare target after the "Retry: " literal.
    assert _formatted("Retry: %s", (signed,)) == "Retry: /<redacted>"

    # connectionpool.py:869 — WARNING, so it clears the Gateway's INFO root.
    retries_repr = "Retry(total=0, connect=None, read=None, redirect=None, status=None)"
    error_repr = "ProtocolError('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
    retrying = _formatted("Retrying (%r) after connection broken by '%r': %s", (retries_repr, error_repr, signed))
    assert retrying == f"Retrying ({retries_repr!r}) after connection broken by '{error_repr!r}': /<redacted>"

    # connectionpool.py:545 — the quoted per-request line.
    request_line = _formatted('%s://%s:%s "%s %s %s" %s %s', ("https", "cdn.example", 443, "GET", signed, "HTTP/1.1", 200, None))
    assert request_line == 'https://cdn.example:443 "GET /<redacted> HTTP/1.1" 200 None'

    for formatted in (retrying, request_line, _formatted("Retry: %s", (signed,))):
        assert "LeakedSig" not in formatted
        assert "sig=" not in formatted

    # The looser tails trade reach for one class of prose: a line that opens
    # with urllib3's own ``Retry: `` literal AND a slash-initial tail collapses
    # whole even when it is not a request target. Prose after ``Retry: `` that
    # does not start with ``/`` keeps passing through untouched, which
    # test_url_redaction_filter_covers_urllib3_retry_lines already pins.
    assert _formatted("Retry: /tmp/build.sock went away", ()) == "Retry: /<redacted>"
