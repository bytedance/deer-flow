"""SQLBot REST client (real) + test double (mock). No authentication required.

新写, 1:1 镜像 chatbi-report scripts/sqlbot_client.py 的接口/字段/契约, 不 import 任何 chatbi-report 代码.
主要差异:
- HTTP 客户端均用 requests (与 chatbi-report 一致)
- mock fixture 路径解析使用 ai-report 自身的 tests/fixtures/
- OrgContext 字段是 ai-report 自身的 org_ecd / org_name (chatbi-report 用
  branch_num / branch_short_name, 我们的 MD 约定是 org_ecd / org_name)
- CLI `query` 子命令的 --out 写 query.json, 供 design_pipeline 或外部
  pipeline 消费
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from retry import exponential, retry


class SQLBotError(Exception):
    """Raised on top-level code != 0 (HTTP 200 but business-level failure)."""


@dataclass
class OrgContext:
    """ai-report 的 org context 字段约定: org_ecd / org_name.

    与 chatbi-report 的 branch_num / branch_short_name 不同 — 我们的 MD
    样张 `> 机构: org_contexts = [{"org_ecd": ..., "org_name": ...}]` 用的
    是这套字段。
    """
    org_ecd: str
    org_name: str


@dataclass
class QueryReportInfoResponse:
    code: int
    data: list[dict] = field(default_factory=list)


# Transient HTTP failures worth retrying. SQLBotError (business-level code != 0)
# is intentionally excluded — it is deterministic and should fail fast.
_TRANSIENT_HTTP = (
    requests.ConnectionError,
    requests.Timeout,
    requests.HTTPError,
)


class RealSQLBotClient:
    """Real SQLBot REST client. No authentication (per spec 2026-06-23)."""

    ENDPOINT_PATH = "/api/v1/indicator/query-report-info"

    def __init__(self, base_url: str | None = None) -> None:
        url = base_url or os.environ.get("SQLBOT_BASE_URL", "")
        if not url:
            raise SQLBotError("SQLBOT_BASE_URL is not set")
        self._base_url = url.rstrip("/")

    @retry(
        max_attempts=3,
        backoff=exponential(base=1.0, max_delay=8.0),
        retry_on=_TRANSIENT_HTTP,
    )
    def query_report_info(
        self,
        org_info: list[dict],
        index_info: list[dict],
        time_info: list[str],
        *,
        timeout: int = 30,
    ) -> QueryReportInfoResponse:
        """POST a single-idx query to SQLBot and return the parsed response.

        Per-idx calling convention: callers should pass `index_info` with
        exactly one element (one HTTP call per idx_id) — see spec
        §"⚠️ Phase 1 已知缺口: idx_id ↔ 数据行关联". This keeps the
        response data rows in 1:1 correspondence with the requested idx_id.

        Retry policy: transient HTTP errors (connection/timeout/5xx via
        raise_for_status) trigger up to 3 attempts with exponential backoff.
        SQLBotError (top-level code != 0) is *not* retried — it is a
        deterministic business-level failure.
        """
        resp = requests.post(
            f"{self._base_url}{self.ENDPOINT_PATH}",
            json={
                "org_info": org_info,
                "index_info": index_info,
                "time_info": time_info,
            },
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        code = payload.get("code")
        if code != 0:
            raise SQLBotError(
                f"query_report_info failed: code={code}, msg={payload.get('msg')}"
            )
        return QueryReportInfoResponse(code=code, data=payload.get("data", []))


class MockSQLBotClient:
    """Test double. Reads `idx_id -> {success, data}` from a fixture JSON file.

    Honors the per-idx calling convention by indexing `index_info[0]`.

    Wide-wide support (2026-06-25): the wide-wide protocol makes one call per
    `(idx_id, period)` tuple. The fixture can be keyed two ways:

    1. Composite: `BAS_0263@2023` — the caller passes
       `index_info[0]={"idx_id": "BAS_0263@2023"}` and `time_info=["2023"]`.
    2. Simple: `BAS_0263` — all periods live in `data`, the mock filters by
       `time_info[0]` prefix-matching `data_dt` (e.g. "2023-12-31" matches
       time_info=["2023"]).
    """

    def __init__(self, fixture_path: str) -> None:
        self._fixture: dict[str, Any] = json.loads(Path(fixture_path).read_text(encoding="utf-8"))

    def query_report_info(
        self,
        org_info: list[dict],
        index_info: list[dict],
        time_info: list[str],
        **_kwargs: Any,
    ) -> QueryReportInfoResponse:
        if not index_info:
            raise SQLBotError("index_info must contain at least one idx_id")
        idx_id = index_info[0]["idx_id"]
        period = time_info[0] if time_info else None
        entry = self._lookup(idx_id, period)
        success = bool(entry.get("success", False))
        elem = {
            "success": success,
            "msg": entry.get("msg", "指标数据查询成功。" if success else "数据不可用。"),
            "record_id": 0,
            "sql": "[mocked]",
            "data": entry.get("data", []),
            "data_interpret": "[mocked]",
            "fields": [
                {"name": "日期", "value": "data_dt"},
                {"name": "机构名称", "value": "org_ecd"},
                {"name": "指标名称", "value": "idx_name"},
                {"name": "指标值", "value": "value"},
            ],
            "chart": {
                "type": "table",
                "title": "columns",
                "columns": [
                    {"name": "日期", "value": "data_dt"},
                    {"name": "机构名称", "value": "org_ecd"},
                    {"name": "指标名称", "value": "idx_name"},
                ],
            },
        }
        return QueryReportInfoResponse(code=0, data=[elem])

    def _lookup(self, idx_id: str, period: str | None) -> dict[str, Any]:
        """Resolve a fixture entry. See class docstring for key formats."""
        # 1. Composite key `BAS_0263@2023` takes priority (explicit period).
        if period:
            composite = f"{idx_id}@{period}"
            if composite in self._fixture:
                return self._fixture[composite]
        # 2. Simple key `BAS_0263` — filter data by data_dt prefix.
        if idx_id in self._fixture:
            entry = dict(self._fixture[idx_id])
            if period and isinstance(entry.get("data"), list):
                entry["data"] = [
                    r for r in entry["data"]
                    if isinstance(r, dict) and str(r.get("data_dt", "")).startswith(period)
                ]
            return entry
        return {"success": False, "data": []}


DEFAULT_MOCK_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "mock_sqlbot"
    / "wangyi_2026_03.json"
)


def _unique_indicator_periods(report: dict) -> list[tuple[str, str | None]]:
    """Iterate report headers, collect (idx_id, period) pairs.

    ai-report 约定: header cell `idx_id` + `period` 共同决定 (idx, period)
    联合键 (chatbi-report 走的是 idx_id + is_indicator 标志, 我们 header
    dataclass 没有 is_indicator — 见 parse_md.OrgContext/Report). 这里
    走 `idx_id` + `period` 双键路径。
    """
    idx_ids: list[str] = []
    header_pairs: list[tuple[str, str | None]] = []
    for row in report.get("headers", []):
        for cell in row:
            idx_id = cell.get("idx_id")
            period = cell.get("period")
            if not idx_id:
                continue
            idx_id = str(idx_id)
            if idx_id not in idx_ids:
                idx_ids.append(idx_id)
            pair = (idx_id, period)
            if pair not in header_pairs:
                header_pairs.append(pair)

    periods = [str(p) for p in report.get("time_info", []) if str(p).strip()]
    if not periods:
        return header_pairs

    pairs: list[tuple[str, str | None]] = []
    for idx_id in idx_ids:
        for period in periods:
            pair = (idx_id, period)
            if pair not in pairs:
                pairs.append(pair)
    for pair in header_pairs:
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def _rows_from_response(resp: QueryReportInfoResponse, org_contexts: list[dict]) -> list[dict]:
    """Convert one SQLBot response to a list of per-org fact rows.

    与 chatbi-report 同形, 区别是 ai-report 用 org_ecd 作 org id (不是
    branch_num). 任何不在 org_contexts 里的 org_ecd 都被过滤掉。
    """
    allowed = {
        str(org.get("org_ecd", "")).strip()
        for org in org_contexts
    }
    allowed.discard("")

    elem = resp.data[0] if resp.data else {"success": False, "data": []}
    success = bool(elem.get("success", False))
    by_org: dict[str, dict] = {}

    if success:
        for item in elem.get("data", []):
            if not isinstance(item, dict):
                continue
            org_ecd = str(item.get("org_ecd", "")).strip()
            if not org_ecd or org_ecd not in allowed:
                continue
            by_org[org_ecd] = {
                "org_ecd": org_ecd,
                "raw_value": str(item.get("value", "")),
                "success": True,
            }

    rows: list[dict] = []
    for org in org_contexts:
        org_ecd = str(org.get("org_ecd", "")).strip()
        if not org_ecd:
            continue
        rows.append(
            by_org.get(
                org_ecd,
                {"org_ecd": org_ecd, "raw_value": "", "success": False},
            )
        )
    return rows


def query_from_parsed(parsed: dict, client: Any) -> dict:
    """Walk parsed.sections[].reports[]; per (idx, period) call SQLBot.

    与 chatbi-report 同形: 每条结果带 section_idx / report_idx, 供
    design_pipeline 或外部 pipeline 按 report 分组消费。
    """
    results: list[dict] = []
    for section_idx, section in enumerate(parsed.get("sections", [])):
        for report_idx, report in enumerate(section.get("reports", [])):
            org_contexts = report.get("org_contexts", [])
            for idx_id, period in _unique_indicator_periods(report):
                resp = client.query_report_info(
                    org_info=org_contexts,
                    index_info=[{"idx_id": idx_id}],
                    time_info=[period] if period else report.get("time_info", []),
                )
                results.append({
                    "section_idx": section_idx,
                    "report_idx": report_idx,
                    "idx_id": idx_id,
                    "period": period,
                    "results": _rows_from_response(resp, org_contexts),
                })
    return {"results": results}


def _cli_query(args: argparse.Namespace) -> int:
    parsed = json.loads(Path(args.parsed).read_text(encoding="utf-8"))
    if args.mock or args.mock_fixture:
        fixture = args.mock_fixture or str(DEFAULT_MOCK_FIXTURE)
        client: Any = MockSQLBotClient(fixture_path=fixture)
    else:
        client = RealSQLBotClient(base_url=args.base_url)

    payload = query_from_parsed(parsed, client)
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    mode = "mock" if (args.mock or args.mock_fixture) else "real"
    print(
        f"OK: queried {len(payload['results'])} indicator-periods via {mode} -> {args.out}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sqlbot_client", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_query = sub.add_parser(
        "query",
        help="Query SQLBot and write a compute-pipeline-compatible query.json",
    )
    p_query.add_argument(
        "--parsed", required=True,
        help="parsed ReportDoc JSON (from parse_md.py --out ...)",
    )
    p_query.add_argument(
        "--out", required=True,
        help="query.json output path (consumed by compute.py / design pipeline)",
    )
    p_query.add_argument(
        "--base-url", default=None,
        help="SQLBot base URL; defaults to env SQLBOT_BASE_URL",
    )
    p_query.add_argument(
        "--mock", action="store_true",
        help="use default example mock fixture",
    )
    p_query.add_argument(
        "--mock-fixture", default=None,
        help="mock fixture path; implies --mock",
    )
    p_query.set_defaults(func=_cli_query)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())