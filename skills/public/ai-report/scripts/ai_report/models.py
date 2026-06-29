from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


JsonDict = dict[str, Any]

# Failure policy enum values.
FAILURE_POLICIES = ("continue_with_sentinel", "stop_on_failure")

# Sentinel value used for missing/failed cells when policy == "continue_with_sentinel".
SENTINEL_VALUE = "—"


@dataclass(frozen=True)
class RunParams:
    period_bindings: dict[str, str]
    org_scope: list[JsonDict]
    output_formats: list[str] = field(default_factory=lambda: ["md"])

    def resolve_period(self, period_alias: str) -> str:
        if period_alias not in self.period_bindings:
            raise KeyError(f"Missing period binding: {period_alias}")
        return self.period_bindings[period_alias]


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    report_name: str
    report_title: str
    status: str = "draft"
    version: int = 1
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class SectionRecord:
    section_id: str
    report_id: str
    section_key: str
    section_title: str
    section_order: int
    description_prompt: str | None = None
    enabled: bool = True
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class TableRecord:
    table_id: str
    report_id: str
    section_id: str
    table_title: str
    table_order: int
    source_md_path: str | None = None
    source_md_hash: str | None = None
    parsed_payload: JsonDict = field(default_factory=dict)
    headers: list[list[JsonDict]] = field(default_factory=list)
    orgs: list[JsonDict] = field(default_factory=list)
    time_info: list[str] = field(default_factory=list)
    description_prompt: str | None = None
    approval_status: str = "draft"
    query_failure_policy: str = "continue_with_sentinel"
    compute_failure_policy: str = "stop_on_failure"
    description_failure_policy: str = "continue_with_sentinel"
    last_design_run_id: str | None = None


@dataclass(frozen=True)
class MetricRecord:
    table_id: str
    idx_id: str
    period_alias: str
    data_unit: str | None = None
    header_text: str | None = None
    metric_order: int = 0
    approval_status: str = "draft"
    last_design_run_id: str | None = None
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class ComputeRecord:
    compute_id: str
    table_id: str
    compute_name: str
    formula_text: str
    compute_sql: str
    dependencies: list[str] = field(default_factory=list)
    examples: list[JsonDict] = field(default_factory=list)
    approval_status: str = "draft"
    last_design_run_id: str | None = None


@dataclass(frozen=True)
class MetricFact:
    run_id: str
    table_id: str
    branch_num: str
    branch_short_name: str
    idx_id: str
    period_alias: str
    period_value: str
    raw_value: str
    numeric_value: Decimal | None
    data_unit: str | None
    status: str = "ok"
    error_message: str | None = None


@dataclass(frozen=True)
class ComputedFact:
    run_id: str
    table_id: str
    branch_num: str
    compute_name: str
    value: str
    numeric_value: Decimal | None
    status: str = "ok"
    error_message: str | None = None


@dataclass(frozen=True)
class RenderPayload:
    report: JsonDict
    sections: list[JsonDict]