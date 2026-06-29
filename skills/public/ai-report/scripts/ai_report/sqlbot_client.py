from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from ai_report.models import MetricFact, SENTINEL_VALUE
from ai_report.sqlbot_transport import QueryReportInfoResponse, SQLBotError


class SqlbotTransport(Protocol):
    def query_report_info(
        self,
        org_info: list[dict[str, Any]],
        index_info: list[dict[str, Any]],
        time_info: list[str],
    ) -> QueryReportInfoResponse:
        ...


def _to_decimal(value: str) -> Decimal | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _normalize_name(value: object) -> str:
    text = str(value or "").strip()
    return text.removesuffix("联社") if text.endswith("联社") else text


def _org_lookup(org_scope: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for org in org_scope:
        branch_num = str(org.get("branch_num", "")).strip()
        short_name = str(org.get("branch_short_name", "")).strip()
        if not branch_num or not short_name:
            continue
        lookup[short_name] = branch_num
        lookup[_normalize_name(short_name)] = branch_num
    return lookup


def _response_element(resp: QueryReportInfoResponse) -> dict[str, Any]:
    elem = resp.data[0] if resp.data else {"success": False, "data": []}
    return elem if isinstance(elem, dict) else {"success": False, "data": []}


def _facts_for_failure(run_id: str, request: dict[str, Any], message: str) -> list[MetricFact]:
    return [
        MetricFact(
            run_id=run_id,
            table_id=request["table_id"],
            branch_num=str(org.get("branch_num", "")),
            branch_short_name=str(org.get("branch_short_name", "")),
            idx_id=request["idx_id"],
            period_alias=request["period_alias"],
            period_value=request["period_value"],
            raw_value=SENTINEL_VALUE,
            numeric_value=None,
            data_unit=request.get("data_unit"),
            status="query_failed",
            error_message=message,
        )
        for org in request.get("org_scope", [])
    ]


def query_metric_facts(
    run_id: str,
    metric_requests: list[dict[str, Any]],
    transport: SqlbotTransport,
    table_policies: dict[str, str] | None = None,
) -> list[MetricFact]:
    """Query SQLBot for each metric_request and return MetricFact rows.

    table_policies maps table_id -> query_failure_policy. When the policy is
    "stop_on_failure" and a table's overall query returns success=false, this
    function raises SQLBotError so the caller can short-circuit the run. With
    "continue_with_sentinel" (the default), each branch gets a MetricFact with
    status="query_failed" and raw_value="" so downstream compute can still run
    with sentinel inputs.
    """
    table_policies = table_policies or {}
    facts: list[MetricFact] = []
    for request in metric_requests:
        org_scope = request.get("org_scope", [])
        resp = transport.query_report_info(
            org_info=org_scope,
            index_info=[{"idx_id": request["idx_id"]}],
            time_info=[request["period_value"]],
        )
        elem = _response_element(resp)
        if not elem.get("success"):
            message = str(elem.get("error") or elem.get("msg") or "SQLBot query failed")
            policy = table_policies.get(request["table_id"], "continue_with_sentinel")
            if policy == "stop_on_failure":
                raise SQLBotError(
                    f"Query failure for table {request['table_id']} "
                    f"idx_id {request['idx_id']} period {request['period_value']}: {message}"
                )
            facts.extend(_facts_for_failure(run_id, request, message))
            continue

        branch_by_name = _org_lookup(org_scope)
        value_by_branch: dict[str, str] = {}
        for item in elem.get("data", []):
            if not isinstance(item, dict):
                continue
            branch_num = branch_by_name.get(str(item.get("org_ecd", "")).strip())
            if branch_num:
                value_by_branch[branch_num] = str(item.get("value", ""))

        for org in org_scope:
            branch_num = str(org.get("branch_num", ""))
            branch_short_name = str(org.get("branch_short_name", ""))
            raw_value = value_by_branch.get(branch_num, "")
            if raw_value == "":
                facts.append(MetricFact(
                    run_id=run_id,
                    table_id=request["table_id"],
                    branch_num=branch_num,
                    branch_short_name=branch_short_name,
                    idx_id=request["idx_id"],
                    period_alias=request["period_alias"],
                    period_value=request["period_value"],
                    raw_value=SENTINEL_VALUE,
                    numeric_value=None,
                    data_unit=request.get("data_unit"),
                    status="missing",
                    error_message="SQLBot returned no row for branch",
                ))
            else:
                numeric_value = _to_decimal(raw_value)
                status = "ok" if numeric_value is not None else "parse_failed"
                facts.append(MetricFact(
                    run_id=run_id,
                    table_id=request["table_id"],
                    branch_num=branch_num,
                    branch_short_name=branch_short_name,
                    idx_id=request["idx_id"],
                    period_alias=request["period_alias"],
                    period_value=request["period_value"],
                    raw_value=raw_value,
                    numeric_value=numeric_value,
                    data_unit=request.get("data_unit"),
                    status=status,
                    error_message=None if status == "ok" else f"Could not parse {raw_value!r} as Decimal",
                ))
    return facts
