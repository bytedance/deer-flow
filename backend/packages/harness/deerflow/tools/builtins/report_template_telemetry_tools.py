"""Telemetry helper tool for the report template platform (Phase 7).

Provides a single LLM-callable tool ``report_template_record_fallback`` that
``ai-report--daily/SOUL.md`` invokes whenever it chooses the legacy hardcoded
path instead of the DSL path. This is the only piece of telemetry that needs
LLM cooperation — the rest (validator outcome, run outcome, storage usage,
skill unavailability) is captured automatically inside the platform code.

Per design §11.4.4 the allowed reasons are:

  - ``tool_error``           : a ``report_template_*`` tool raised an error
  - ``builtin_missing``      : the builtin DSL template was not found
  - ``validator_regression`` : the builtin DSL no longer passes the validator
  - ``skill_disabled``       : the supporting skill / script registry vanished
"""

from __future__ import annotations

import json
import logging

from langchain.tools import tool

from deerflow.report_templates.telemetry import get_telemetry

logger = logging.getLogger(__name__)


_VALID_REASONS = {
    "tool_error",
    "builtin_missing",
    "validator_regression",
    "skill_disabled",
}


@tool("report_template_record_fallback", parse_docstring=True)
def report_template_record_fallback_tool(agent_name: str, reason: str) -> str:
    """Record that a report agent fell back to its legacy hardcoded path.

    Call this **once per fallback decision** in the LLM's flow, immediately
    before continuing on the legacy path. Telemetry is observability only —
    failure to record never blocks the run.

    Args:
        agent_name: The agent that triggered fallback (e.g. ``ai-report--daily``).
            Required, non-empty.
        reason: One of ``tool_error`` / ``builtin_missing`` /
            ``validator_regression`` / ``skill_disabled``. Required.

    Returns:
        JSON string ``{"recorded": true, "reason": "..."}``, or
        ``{"error": {"code": ..., "message": ...}}`` on invalid input.
    """
    try:
        if not agent_name:
            return json.dumps(
                {"error": {"code": "INVALID_AGENT_NAME", "message": "agent_name is required"}}
            )
        if reason not in _VALID_REASONS:
            return json.dumps(
                {
                    "error": {
                        "code": "INVALID_REASON",
                        "message": f"reason must be one of {sorted(_VALID_REASONS)}",
                    }
                }
            )
        get_telemetry().record_fallback(agent_name=agent_name, reason=reason)
        return json.dumps({"recorded": True, "agent_name": agent_name, "reason": reason})
    except Exception:  # noqa: BLE001
        logger.exception("report_template_record_fallback crashed")
        return json.dumps(
            {"error": {"code": "INTERNAL", "message": "telemetry failed"}}
        )
