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
