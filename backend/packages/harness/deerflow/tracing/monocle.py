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

    ``monocle_apptrace.setup_monocle_telemetry()`` is itself idempotent and, when another
    library already owns the global OpenTelemetry provider, attaches to it instead of
    overriding it — so this stays a thin, config-gated wrapper. Returns ``True`` when enabled.
    """
    if not is_monocle_tracing_enabled():
        return False

    # Monocle and Langfuse (v4) both use the global OpenTelemetry provider; whichever
    # initializes first owns it, so warn when both are on to avoid surprises.
    if "langfuse" in get_enabled_tracing_providers():
        logger.warning("MONOCLE_TRACING is enabled alongside Langfuse; both use the global OpenTelemetry provider — verify traces export where you expect.")

    exporters = get_tracing_config().monocle.exporters
    from monocle_apptrace import setup_monocle_telemetry

    setup_monocle_telemetry(workflow_name="deer-flow", monocle_exporters_list=exporters)
    logger.info("Monocle telemetry enabled (exporters=%s)", exporters)
    return True
