"""Monocle telemetry: initialized once from the Gateway lifespan when ``MONOCLE_TRACING`` is set."""

from __future__ import annotations

import logging

from deerflow.config import (
    get_enabled_tracing_providers,
    get_tracing_config,
    is_monocle_tracing_enabled,
)

logger = logging.getLogger(__name__)


def setup_monocle_tracing_if_enabled() -> bool:
    """Initialize Monocle telemetry when ``MONOCLE_TRACING`` is enabled; a no-op otherwise.

    ``monocle_apptrace.setup_monocle_telemetry()`` is idempotent, so this stays a thin,
    config-gated wrapper. Returns ``True`` when enabled.
    """
    if not is_monocle_tracing_enabled():
        return False

    # Only one OpenTelemetry provider can own the process. Monocle initializes here (at
    # startup), before Langfuse's per-run handler, so enabling both means Langfuse loses
    # its spans — warn so the operator turns one off.
    if "langfuse" in get_enabled_tracing_providers():
        logger.warning("MONOCLE_TRACING is enabled alongside Langfuse; both need the global OpenTelemetry provider and only one can win. Enable only one of them.")

    exporters = get_tracing_config().monocle.exporters
    from monocle_apptrace import setup_monocle_telemetry

    setup_monocle_telemetry(workflow_name="deer-flow", monocle_exporters_list=exporters)
    logger.info("Monocle telemetry enabled (exporters=%s)", exporters)
    return True
