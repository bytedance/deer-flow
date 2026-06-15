"""Direct execution tool for builtin reports.

Single tool that bypasses DSL state machine and directly orchestrates
Skill script calls for daily/weekly/monthly reports.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from langchain.tools import tool
from langgraph.config import get_config
from pydantic import BaseModel, Field

from deerflow.report_executor import DirectExecutionError, DirectReportExecutor

logger = logging.getLogger(__name__)


class ReportDirectExecuteInput(BaseModel):
    """Input schema for report_direct_execute tool."""

    report_type: Annotated[
        str,
        Field(description="Report type: 'daily', 'weekly', or 'monthly'"),
    ]
    scope: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Scope parameters. For daily: {report_date: 'YYYY-MM-DD'}. "
                "For weekly: {week_start: 'YYYY-MM-DD', date_end: 'YYYY-MM-DD'}. "
                "For monthly: {report_month: 'YYYY-MM'}."
            )
        ),
    ]
    equipment_type: Annotated[
        str,
        Field(
            default="all",
            description=(
                "Equipment type: 'all', 'static_equipment', 'rotating_machinery', "
                "'pump', or 'reciprocating_machinery'"
            ),
        ),
    ]
    compare_with: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Comparison baseline: 'previous_day', 'previous_week', 'previous_month', "
                "'previous_year', or 'none'. None uses default."
            ),
        ),
    ]
    equipment_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="List of equipment IDs. None means all equipment.",
        ),
    ]
    equipment_labels: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="List of equipment names (parallel to equipment_ids).",
        ),
    ]
    kpi_keys: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="List of KPI keys to compute. None uses template defaults.",
        ),
    ]
    equipment_meta: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description=(
                "Equipment metadata for org tree passthrough: {id: {id, name, ...}}. "
                "Skips internal org tree queries when provided."
            ),
        ),
    ]


@tool("report_direct_execute", args_schema=ReportDirectExecuteInput)
def report_direct_execute(
    report_type: str,
    scope: dict[str, Any],
    equipment_type: str = "all",
    compare_with: str | None = None,
    equipment_ids: list[str] | None = None,
    equipment_labels: list[str] | None = None,
    kpi_keys: list[str] | None = None,
    equipment_meta: dict[str, Any] | None = None,
) -> str:
    """Execute a builtin report (daily/weekly/monthly) directly.

    This tool bypasses the DSL template engine state machine and directly
    orchestrates Skill script calls. Use this for builtin reports instead of
    report_template_* tools.

    Args:
        report_type: "daily", "weekly", or "monthly"
        scope: Scope parameters (report_date / week_start+date_end / report_month)
        equipment_type: Equipment type filter
        compare_with: Comparison baseline (previous_day/week/month/year or none)
        equipment_ids: List of equipment IDs (None = all)
        equipment_labels: List of equipment names (parallel to equipment_ids)
        kpi_keys: List of KPI keys to compute (None = defaults)

    Returns:
        JSON string with {report_run_id, artifacts, status} on success,
        or {error: {code, message, step}, status: "failed"} on failure.
    """
    try:
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id", "unknown")
        output_dir = _get_output_dir(thread_id)

        executor = DirectReportExecutor(output_dir=output_dir)

        result = executor.execute(
            report_type=report_type,
            scope=scope,
            equipment_type=equipment_type,
            compare_with=compare_with,
            equipment_ids=equipment_ids,
            equipment_labels=equipment_labels,
            kpi_keys=kpi_keys,
            equipment_meta=equipment_meta,
        )

        return json.dumps(result, ensure_ascii=False)

    except DirectExecutionError as e:
        logger.error(f"Direct execution failed: {e}", exc_info=True)
        error_result = {
            "error": e.to_dict(),
            "status": "failed",
        }
        return json.dumps(error_result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Unexpected error in report_direct_execute: {e}", exc_info=True)
        error_result = {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(e),
            },
            "status": "failed",
        }
        return json.dumps(error_result, ensure_ascii=False)


def _get_output_dir(thread_id: str) -> str:
    """Get thread-scoped output directory."""
    from deerflow.config.paths import get_paths

    paths = get_paths()
    outputs_dir = paths.sandbox_outputs_dir(thread_id)
    return str(outputs_dir)
