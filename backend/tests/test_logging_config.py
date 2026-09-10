import io
import logging
from types import SimpleNamespace

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


def test_httpx_url_query_redaction_filter_rewrites_request_records() -> None:
    from deerflow.logging_config import HttpxUrlQueryRedactionFilter

    filt = HttpxUrlQueryRedactionFilter()

    # The real httpx shape: "HTTP Request: %s %s HTTP/1.1 %d %d" with the URL
    # as a lazy %-arg (httpx.URL object), so redaction must run on the
    # formatted message and clear args. Path AND query disappear: only
    # scheme + host may remain (the repo-wide inbound-media log rule).
    class _UrlLike:
        def __str__(self) -> str:
            return "https://host.example/private/BearerSecret?token=QuerySecret"

    record = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "HTTP Request: %s %s HTTP/1.1 %d %d",
        ("GET", _UrlLike(), 200, 25),
        None,
    )
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
    telegram = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "HTTP Request: %s %s HTTP/1.1 %d %d",
        ("POST", "https://api.telegram.org/bot123456:AAE-token-secret/sendMessage", 200, 142),
        None,
    )
    assert filt.filter(telegram) is True
    telegram_formatted = telegram.getMessage()
    assert "api.telegram.org/<redacted>" in telegram_formatted
    assert "AAE-token-secret" not in telegram_formatted
    assert "bot123456" not in telegram_formatted

    # Userinfo credentials in the authority (basic-auth style endpoints that
    # httpx accepts, e.g. MCP/extension proxies) must be blanked too — the
    # authority is split so only <redacted>@ survives in front of the host.
    userinfo = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "HTTP Request: %s %s HTTP/1.1 %d %d",
        ("GET", "https://user:token123@internal-proxy.corp:8080/v1/secret-endpoint", 200, 9),
        None,
    )
    assert filt.filter(userinfo) is True
    userinfo_formatted = userinfo.getMessage()
    assert "https://<redacted>@internal-proxy.corp:8080/<redacted>" in userinfo_formatted
    assert "token123" not in userinfo_formatted
    assert "user:" not in userinfo_formatted

    # A bare origin without path/query is left as-is.
    bare = logging.LogRecord(
        "httpx",
        logging.INFO,
        __file__,
        1,
        "HTTP Request: %s %s HTTP/1.1 %d %d",
        ("GET", "https://host.example", 200, 25),
        None,
    )
    assert filt.filter(bare) is True
    assert "https://host.example" in bare.getMessage()
    assert "<redacted>" not in bare.getMessage()

    # Records without a URL pass through untouched (message + args kept).
    plain = logging.LogRecord("httpx", logging.INFO, __file__, 1, "keep %s", ("this",), None)
    assert filt.filter(plain) is True
    assert plain.getMessage() == "keep this"


def test_configure_logging_installs_httpx_redaction() -> None:
    from deerflow.logging_config import HttpxUrlQueryRedactionFilter, install_httpx_log_redaction

    httpx_logger = logging.getLogger("httpx")
    old_filters = httpx_logger.filters[:]
    try:
        httpx_logger.filters = [f for f in old_filters if not isinstance(f, HttpxUrlQueryRedactionFilter)]
        install_httpx_log_redaction()
        install_httpx_log_redaction()  # idempotent
        assert sum(isinstance(f, HttpxUrlQueryRedactionFilter) for f in httpx_logger.filters) == 1

        configure_logging(SimpleNamespace(log_level="info", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))
        assert any(isinstance(f, HttpxUrlQueryRedactionFilter) for f in httpx_logger.filters)
    finally:
        httpx_logger.filters = old_filters
