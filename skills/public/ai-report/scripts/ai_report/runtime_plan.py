from __future__ import annotations

import json
from typing import Any

import duckdb

from ai_report.definition_store import load_active_report
from ai_report.models import RunParams


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def build_runtime_plan(con: duckdb.DuckDBPyConnection, report_id: str, params: RunParams) -> dict[str, Any]:
    active = load_active_report(con, report_id)
    tables_by_id = {table["table_id"]: table for table in active["tables"]}
    metric_requests: list[dict[str, Any]] = []
    for metric in active["metrics"]:
        table = tables_by_id[metric["table_id"]]
        org_scope = params.org_scope if params.org_scope is not None else (_json_value(table.get("orgs")) or [])
        metric_requests.append({
            "table_id": metric["table_id"],
            "idx_id": metric["idx_id"],
            "period_alias": metric["period_alias"],
            "period_value": params.resolve_period(metric["period_alias"]),
            "data_unit": metric["data_unit"],
            "org_scope": org_scope,
        })
    return {
        "report": active["report"],
        "sections": active["sections"],
        "tables": active["tables"],
        "metrics": active["metrics"],
        "computes": active["computes"],
        "metric_requests": metric_requests,
        "run_params": params,
    }