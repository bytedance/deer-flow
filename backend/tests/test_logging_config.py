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
