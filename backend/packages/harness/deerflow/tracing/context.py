"""W3C trace parent propagation for host-managed execution."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import context, trace
from opentelemetry.trace import StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

TRACE_PARENT_KEY = "deerflow_traceparent"
TRACE_ORIGIN_RUN_KEY = "deerflow_trace_run_id"
TRACE_METADATA_KEYS = frozenset({TRACE_PARENT_KEY, TRACE_ORIGIN_RUN_KEY})
_PROPAGATOR = TraceContextTextMapPropagator()
logger = logging.getLogger(__name__)


def _extract(header: object) -> context.Context:
    if isinstance(header, str) and len(header) <= 512:
        return _PROPAGATOR.extract({"traceparent": header})
    return context.Context()


def _inject(span_context: context.Context | None = None) -> str | None:
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier, context=span_context)
    return carrier.get("traceparent")


def normalize_traceparent(header: object) -> str | None:
    """Validate and canonicalize a parent before storing or restoring it."""
    return _inject(_extract(header))


def current_traceparent() -> str | None:
    """Serialize just the active span identity and trace flags."""
    return _inject()


@contextmanager
def traceparent_scope(header: object, *, prefer_current: bool = False) -> Iterator[None]:
    """Bind a remote parent for this task, restoring the previous span on exit."""
    current = current_traceparent()
    if current == header or (prefer_current and current is not None):
        yield
        return

    parent = trace.get_current_span(_extract(header))
    token = context.attach(trace.set_span_in_context(parent))
    try:
        yield
    finally:
        context.detach(token)


@contextmanager
def execution_span(name: str, attributes: dict[str, str]) -> Iterator[trace.Span]:
    """Use the operator's tracer provider, with the OTel no-op default."""
    try:
        span = trace.get_tracer(__name__).start_span(name, attributes=attributes)
    except Exception:
        logger.warning("Could not start %s span", name)
        yield trace.INVALID_SPAN
        return

    with trace.use_span(span, record_exception=False, set_status_on_exception=False):
        try:
            yield span
        finally:
            try:
                span.end()
            except Exception:
                logger.warning("Could not finish %s span", name)


def annotate_execution(span: trace.Span, attribute: str, value: str, *, failed: bool = False) -> None:
    try:
        span.set_attribute(attribute, value)
        if failed:
            span.set_status(StatusCode.ERROR)
    except Exception:
        logger.warning("Could not annotate execution span")
