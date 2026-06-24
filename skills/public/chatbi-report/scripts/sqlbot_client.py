"""SQLBot REST client (real) + test double (mock). No authentication required."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from retry import exponential, retry


class SQLBotError(Exception):
    """Raised on top-level code != 0 (HTTP 200 but business-level failure)."""


@dataclass
class OrgContext:
    branch_num: str
    branch_short_name: str


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
        entry = self._fixture.get(idx_id, {"success": False, "data": []})
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
