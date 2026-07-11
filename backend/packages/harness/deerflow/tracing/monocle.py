"""Monocle telemetry: initialized once from the Gateway lifespan when ``MONOCLE_TRACING`` is set."""

from __future__ import annotations

import logging

from deerflow.config import (
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

    monocle = get_tracing_config().monocle
    # Fail fast on an unknown MONOCLE_EXPORTERS value or a missing OKAHU_API_KEY,
    # with a clear message, before instrumenting. Validated here (not in the
    # per-run callback path) so a config typo never breaks agent runs.
    monocle.validate()

    # Coexistence with Langfuse (v4, also OTel-based) is verified: whichever
    # library initializes second reuses the existing global TracerProvider and
    # attaches its own span processor, so neither side loses spans (see
    # test_coexists_with_langfuse). Both processors see all spans, so Monocle's
    # exporters also capture Langfuse's spans when both are enabled.
    exporters = monocle.exporters

    # Any exporter other than `file` moves trace data (prompts, tool inputs and
    # outputs, completions) beyond the local .monocle/ directory, e.g. to an
    # external collector (okahu, s3, ...). Warn loudly so it can't happen
    # unnoticed.
    non_file = [e.strip() for e in exporters.split(",") if e.strip() and e.strip() != "file"]
    if non_file:
        logger.warning(
            "Monocle is exporting trace data (prompts, tool inputs/outputs, completions) beyond the local .monocle/ file via: %s. Make sure that destination is trusted.",
            ", ".join(non_file),
        )

    try:
        from monocle_apptrace import setup_monocle_telemetry
    except ImportError as exc:
        raise RuntimeError("MONOCLE_TRACING is enabled but monocle_apptrace is not installed. Install the 'monocle' extra: `uv sync --extra monocle` in backend/, or `pip install 'deerflow-harness[monocle]'`.") from exc

    # monocle_exporters_list takes the comma-separated string as-is (monocle_apptrace's API).
    setup_monocle_telemetry(workflow_name="deer-flow", monocle_exporters_list=exporters)
    logger.info("Monocle telemetry enabled (exporters=%s)", exporters)
    return True
