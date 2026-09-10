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
    """urllib3 logs ``Redirecting %s -> %s`` at INFO with full URLs on both sides."""
    from deerflow.logging_config import UrlRedactionFilter

    filt = UrlRedactionFilter()
    record = logging.LogRecord(
        "urllib3",
        logging.INFO,
        __file__,
        1,
        "Redirecting %s -> %s",
        (
            "https://cdn.example/private/BearerSecret?token=QuerySecret",
            "https://mirror.example/private/BearerSecret?sig=OtherSecret",
        ),
        None,
    )
    assert filt.filter(record) is True
    formatted = record.getMessage()
    assert "BearerSecret" not in formatted
    assert "QuerySecret" not in formatted
    assert "OtherSecret" not in formatted
    assert "cdn.example/<redacted>" in formatted
    assert "mirror.example/<redacted>" in formatted


def test_configure_logging_installs_url_redaction_on_both_loggers() -> None:
    from deerflow.logging_config import UrlRedactionFilter, install_url_log_redaction

    saved = {name: logging.getLogger(name).filters[:] for name in ("httpx", "urllib3")}
    try:
        for filters in saved.values():
            filters[:] = [f for f in filters if not isinstance(f, UrlRedactionFilter)]
        install_url_log_redaction()
        install_url_log_redaction()  # idempotent
        for name in ("httpx", "urllib3"):
            target = logging.getLogger(name)
            assert sum(isinstance(f, UrlRedactionFilter) for f in target.filters) == 1

        configure_logging(SimpleNamespace(log_level="info", logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False, format="text"))))
        for name in ("httpx", "urllib3"):
            assert any(isinstance(f, UrlRedactionFilter) for f in logging.getLogger(name).filters)
    finally:
        for name, filters in saved.items():
            logging.getLogger(name).filters = filters
