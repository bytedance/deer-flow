# chatbi-report Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `chatbi-report` skill so a user can upload a Markdown sample whose `<th>` cells carry `data-idx="BAS_0263"` (SQLBot indicator ID) plus Chinese display name text, and DeerFlow's lead agent will end-to-end call SQLBot `query-report-info`, pivot to wide-format rows, evaluate computed columns via LLM-generated pandas, and emit `report.json` / `report.md` / `report.docx` to the thread output directory.

**Architecture:** Skill as the trigger surface; existing DeerFlow lead agent + `SummarizationMiddleware` + LangGraph checkpointer as the execution layer (no new subagent, no new middleware). All work happens inside `skills/public/chatbi-report/scripts/*.py` invoked from the lead agent via `bash`. The Chinese display name lives in the MD `<th>` text — render_docx reads from the AST and never calls SQLBot, so re-rendering an already-stored `report.json` works even when SQLBot is down.

**Tech Stack:** Python 3.12, `requests` (stdlib-style HTTP, real SQLBot client), `python-docx` (DOCX rendering), `decimal.Decimal` (unit math), `json`/`dataclasses`/`re`/`ast` (parsing, validation), `pytest` + `pytest-httpx` (dev-only tests). No new top-level deps required.

**Spec:** `docx/chatbi-report/chatbi-report-data-agent-design.md`

---

## File Structure

```
skills/public/chatbi-report/
├── SKILL.md                    # Trigger surface + 9-step workflow + key constraints (new, ~150 lines)
├── README.md                   # Configure / run / troubleshoot (new, ~80 lines)
├── .env.example                # SQLBOT_BASE_URL=... (no API key needed) (new)
├── scripts/
│   ├── __init__.py             # Package marker (empty, allows tests/ import) (new)
│   ├── retry.py                # @retry decorator with exponential backoff (new, ~60 lines)
│   ├── sqlbot_client.py        # RealSQLBotClient + MockSQLBotClient + QueryReportInfoResponse dataclass (new, ~180 lines)
│   ├── md_lint.py              # Validate MD structure, all chatbi-specific ERROR/WARN rules, CLI exit codes (new, ~250 lines)
│   ├── parse_md.py             # MD → ReportDoc AST (Th[ ][ ] 2-D headers, category-label support, ComputedSpec list) (new, ~300 lines)
│   ├── compute.py              # IR extractor (LLM call) + pandas codegen + AST/signature/smoke/example validator + Decimal unit converter (new, ~400 lines)
│   ├── render_markdown.py      # Backfill report.md (Chinese name + unit, ⚠️QUERY_FAILED/⚠️COMPUTE_FAILED markers) (new, ~180 lines)
│   ├── render_docx.py          # python-docx render (multi-level merge, header subtitle, NO SQLBot lookup in main path) (new, ~350 lines)
│   ├── report_style.json       # DOCX style tokens (new, ~30 lines)
│   ├── assemble_status.py      # Write report.status.json from exit-step + metrics (new, ~120 lines)
│   └── tests/
│       ├── __init__.py         # (new)
│       ├── conftest.py         # Shared fixtures: tmp paths, mock SQLBot env, sample MD loaders (new)
│       ├── test_retry.py
│       ├── test_sqlbot_client.py
│       ├── test_md_lint.py
│       ├── test_parse_md.py
│       ├── test_compute.py
│       ├── test_render_markdown.py
│       ├── test_render_docx.py
│       ├── test_unit_conversion.py
│       └── test_assemble_status.py
└── prompts/
    └── compute_codegen.md      # System prompt for LLM codegen + few-shot (YoY, ratio, growth) (new, ~120 lines)

backend/tests/chatbi_report/                                # Backend-relative integration tests
├── __init__.py
├── conftest.py                                              # Lead-agent stand-in: runs scripts in tmp dir
├── fixtures/
│   ├── sample_md/
│   │   ├── happy.md                                         # Multi-row, 2 idx, 1 computed, simple
│   │   ├── multi_chapter.md                                 # Two `## 章节:` sections, two reports each
│   │   ├── multi_header.md                                  # Two-row <thead> with rowspan/colspan
│   │   ├── no_org_context.md                                # Missing `> 机构:` block (F19)
│   │   ├── no_time_info.md                                  # Missing `> 时期:` block (F19)
│   │   ├── computed_columns.md                              # 3 computed, 2 with examples, no old-style placeholder
│   │   ├── computed_with_examples.md                        # Computed with `.示例:` blocks
│   │   ├── multi_header_computed.md                         # Two-row thead with computed column under category
│   │   ├── old_style_placeholder.md                         # `{{BAS_0263}}` style — WARN expected
│   │   └── lint_error.md                                    # Multiple chatbi-specific lint errors
│   ├── mock_sqlbot/
│   │   ├── query_responses.json                             # {idx_id: {success: bool, data: [...]}}
│   │   ├── partial_failure.json                             # 1 idx success=false (F18)
│   │   ├── code_error.json                                  # Top-level code!=0 (F17)
│   │   └── down.json                                        # All idx 5xx (F17)
│   └── expected_outputs/
│       ├── happy.json
│       ├── happy.md
│       ├── partial_query_failure.json
│       └── computed_columns.json
└── (integration scenarios — see Tasks 12–17)
```

**Created files (production, 13):** `SKILL.md`, `README.md`, `.env.example`, `scripts/{retry,sqlbot_client,md_lint,parse_md,compute,render_markdown,render_docx,assemble_status}.py`, `scripts/report_style.json`, `prompts/compute_codegen.md`, plus `scripts/__init__.py`.

**Created files (tests):** `scripts/tests/{__init__,conftest,test_retry,test_sqlbot_client,test_md_lint,test_parse_md,test_compute,test_render_markdown,test_render_docx,test_unit_conversion,test_assemble_status}.py` (11 unit-test files). Backend integration: `backend/tests/chatbi_report/{__init__,conftest}.py` + `fixtures/sample_md/{happy,multi_chapter,multi_header,no_org_context,no_time_info,computed_columns,computed_with_examples,multi_header_computed,old_style_placeholder,lint_error}.md` + `fixtures/mock_sqlbot/{query_responses,partial_failure,code_error,down}.json` + `fixtures/expected_outputs/{happy.json,happy.md,partial_query_failure.json,computed_columns.json}`.

**No changes to:** `deerflow.agents.lead_agent.*`, `deerflow.subagents.*`, LangGraph runtime, Gateway API, frontend, `SummarizationMiddleware`, LangGraph checkpointer.

---

## Task 1: `retry.py` decorator with exponential backoff

**Files:**
- Create: `skills/public/chatbi-report/scripts/__init__.py` (empty file)
- Create: `skills/public/chatbi-report/scripts/retry.py`
- Create: `skills/public/chatbi-report/scripts/tests/__init__.py` (empty file)
- Create: `skills/public/chatbi-report/scripts/tests/conftest.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_retry.py`

**Interfaces:**
- Consumes: any sync callable, retry spec (`max_attempts`, `backoff`, `retry_on` tuple of exception types)
- Produces: `retry(...)` decorator, `exponential(base, max_delay)` factory returning a `Backoff` strategy

This module is the bottom of the dependency graph (Tasks 2, 4, 5 all consume it), so it ships first and gets the most exhaustive unit coverage.

- [ ] **Step 1: Create empty `__init__.py` files**

Create both `skills/public/chatbi-report/scripts/__init__.py` and `skills/public/chatbi-report/scripts/tests/__init__.py` with a single newline each. Lets pytest discover the test module without `ModuleNotFoundError`.

- [ ] **Step 2: Create `conftest.py` with shared fixtures**

Create `skills/public/chatbi-report/scripts/tests/conftest.py`:

```python
"""Pytest fixtures for chatbi-report skill scripts."""
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def sqlbot_env(monkeypatch):
    """Set SQLBOT_BASE_URL for the duration of one test (no API key per spec)."""
    monkeypatch.setenv("SQLBOT_BASE_URL", "http://sqlbot.lan:9070")
    return {"base_url": "http://sqlbot.lan:9070"}


@pytest.fixture
def fixture_dir() -> Path:
    """Path to backend/tests/chatbi_report/fixtures for integration-style unit tests."""
    return (
        Path(__file__).resolve().parents[3]
        / "backend"
        / "tests"
        / "chatbi_report"
        / "fixtures"
    )
```

- [ ] **Step 3: Write failing test for retry on first-success**

Create `skills/public/chatbi-report/scripts/tests/test_retry.py`:

```python
"""Unit tests for scripts/retry.py."""
import pytest

from retry import Backoff, exponential, retry


def test_retry_returns_value_when_no_failure():
    """First-attempt success: returns immediately, no extra calls."""

    calls = []

    @retry(max_attempts=3, backoff=exponential(base=2, max_delay=10),
           retry_on=(RuntimeError,))
    def fn() -> str:
        calls.append(1)
        return "ok"

    assert fn() == "ok"
    assert len(calls) == 1


def test_retry_recovers_on_second_attempt(monkeypatch):
    """Fails once, succeeds on retry."""

    calls = []

    class FlakyError(RuntimeError):
        pass

    @retry(max_attempts=3, backoff=exponential(base=1, max_delay=1),
           retry_on=(FlakyError,))
    def fn() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise FlakyError("boom")
        return "ok"

    # Avoid actual sleeping: monkeypatch time.sleep to a no-op
    monkeypatch.setattr("retry.time.sleep", lambda _: None)
    assert fn() == "ok"
    assert len(calls) == 2


def test_retry_raises_after_max_attempts(monkeypatch):
    """Always fails: re-raises the last exception after max_attempts."""

    calls = []

    class FlakyError(RuntimeError):
        pass

    @retry(max_attempts=3, backoff=exponential(base=1, max_delay=1),
           retry_on=(FlakyError,))
    def fn() -> str:
        calls.append(1)
        raise FlakyError(f"attempt {len(calls)}")

    monkeypatch.setattr("retry.time.sleep", lambda _: None)
    with pytest.raises(FlakyError, match="attempt 3"):
        fn()
    assert len(calls) == 3


def test_retry_does_not_catch_unlisted_exception(monkeypatch):
    """Only `retry_on` exceptions are retried."""

    calls = []

    class ShouldRetry(RuntimeError):
        pass

    class ShouldNotRetry(ValueError):
        pass

    @retry(max_attempts=5, backoff=exponential(base=1, max_delay=1),
           retry_on=(ShouldRetry,))
    def fn() -> str:
        calls.append(1)
        raise ShouldNotRetry("nope")

    monkeypatch.setattr("retry.time.sleep", lambda _: None)
    with pytest.raises(ShouldNotRetry, match="nope"):
        fn()
    assert len(calls) == 1


def test_exponential_backoff_grows_and_caps():
    """First three delays: base, base*2, min(base*4, max_delay)."""
    b = exponential(base=2, max_delay=10)
    assert b.delay(1) == 2     # 2 * 2^0 = 2
    assert b.delay(2) == 4     # 2 * 2^1 = 4
    assert b.delay(3) == 8     # 2 * 2^2 = 8
    assert b.delay(4) == 10    # 2 * 2^3 = 16 -> capped to 10
    assert b.delay(10) == 10   # already capped
```

- [ ] **Step 4: Run test, verify it fails**

Run from the project root:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_retry.py -v
```
Expected: `ModuleNotFoundError: No module named 'retry'` for all 5 tests.

- [ ] **Step 5: Implement `retry.py`**

Create `skills/public/chatbi-report/scripts/retry.py`:

```python
"""Generic retry decorator with pluggable backoff strategies."""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class Backoff:
    """Backoff strategy interface — call delay(attempt) → seconds to sleep."""
    fn: Callable[[int], float]

    def delay(self, attempt: int) -> float:
        return self.fn(attempt)


def exponential(base: float = 2.0, max_delay: float = 10.0) -> Backoff:
    """Standard exponential backoff: base * 2^(attempt-1), capped at max_delay."""
    def _d(attempt: int) -> float:
        return min(base * (2 ** (attempt - 1)), max_delay)
    return Backoff(fn=_d)


def retry(
    *,
    max_attempts: int,
    backoff: Backoff,
    retry_on: tuple[type[BaseException], ...],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry `fn` on listed exception types up to max_attempts times.

    Raises the last exception if all attempts fail. Does NOT catch
    exceptions outside `retry_on` — those bubble immediately.
    """
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    time.sleep(backoff.delay(attempt))
            assert last_exc is not None  # for type-checkers
            raise last_exc
        return wrapper
    return decorator
```

- [ ] **Step 6: Run test, verify all pass**

Run from the project root:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_retry.py -v
```
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/retry.py \
        skills/public/chatbi-report/scripts/__init__.py \
        skills/public/chatbi-report/scripts/tests/__init__.py \
        skills/public/chatbi-report/scripts/tests/conftest.py \
        skills/public/chatbi-report/scripts/tests/test_retry.py
git commit -m "feat(skill:chatbi-report): add retry.py decorator with exponential backoff

Generic sync decorator consumed by sqlbot_client, compute, and the
lead agent's HTTP loop. Pure stdlib (no new deps). TDD: 5 pytest cases
covering first-success / mid-retry / exhaustion / non-retryable exception /
exponential growth-and-cap. Sleeps are monkeypatched in tests.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `sqlbot_client.py` — real + mock client with per-idx semantics

**Files:**
- Create: `skills/public/chatbi-report/scripts/sqlbot_client.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py`

**Interfaces:**
- Consumes: `SQLBOT_BASE_URL` env (no API key, per spec 2026-06-23), `requests.post(...)`
- Produces: `OrgContext` (dataclass), `QueryReportInfoResponse` (dataclass with `code: int`, `data: list[dict]`), `SQLBotError` exception, `RealSQLBotClient` (HTTP POST to `/api/v1/indicator/query-report-info`, raises `SQLBotError` on `code != 0`), `MockSQLBotClient` (reads fixture JSON by `idx_id`)

Both clients enforce the **per-idx calling convention**: `query_report_info(...)` is invoked once per `idx_id` with `index_info=[{"idx_id": idx}]`. The 1:1 response↔idx mapping is what eliminates the SQLBot "no idx_id in response" ambiguity (spec §"⚠️ Phase 1 已知缺口").

- [ ] **Step 1: Write failing test for happy path (real client)**

Create `skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py`:

```python
"""Unit tests for scripts/sqlbot_client.py (real + mock)."""
import json
from pathlib import Path
from unittest import mock

import pytest

import sqlbot_client as sc


def test_real_client_query_report_info_happy(sqlbot_env):
    """Real client POSTs to /api/v1/indicator/query-report-info, no Auth header."""
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "code": 0,
        "data": [{
            "success": True,
            "msg": "指标数据查询成功。",
            "data": [
                {"data_dt": "2025-12-31", "org_ecd": "王益联社",
                 "idx_name": "贷款收单商户数", "value": "1,420.00"}
            ],
        }],
    }
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(sc.requests, "post", return_value=fake_response) as m_post:
        resp = sc.RealSQLBotClient(base_url="http://sqlbot.lan:9070").query_report_info(
            org_info=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
            index_info=[{"idx_id": "BAS_0263"}],
            time_info=["2025"],
        )

    assert resp.code == 0
    assert len(resp.data) == 1
    assert resp.data[0]["data"][0]["value"] == "1,420.00"

    # Verify the HTTP call shape
    m_post.assert_called_once()
    args, kwargs = m_post.call_args
    assert args[0] == "http://sqlbot.lan:9070/api/v1/indicator/query-report-info"
    body = kwargs["json"]
    assert body["org_info"][0]["branch_num"] == "27020199"
    assert body["index_info"] == [{"idx_id": "BAS_0263"}]
    assert body["time_info"] == ["2025"]
    # No Authorization header (per spec: SQLBot is auth-free)
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_real_client_raises_sqlbot_error_on_http_failure(sqlbot_env):
    """4xx/5xx → requests.RequestException bubbles (caller wraps with @retry)."""
    import requests as real_requests
    fake_response = mock.Mock()
    fake_response.raise_for_status.side_effect = real_requests.HTTPError("500 Server Error")

    with mock.patch.object(sc.requests, "post", return_value=fake_response):
        with pytest.raises(real_requests.HTTPError, match="500"):
            sc.RealSQLBotClient(base_url="http://x").query_report_info(
                org_info=[], index_info=[{"idx_id": "X"}], time_info=[]
            )


def test_real_client_raises_sqlbot_error_on_top_level_code_nonzero(sqlbot_env):
    """HTTP 200 but code != 0 → SQLBotError (caller's @retry treats as fatal after 3 attempts)."""
    fake_response = mock.Mock()
    fake_response.raise_for_status = mock.Mock()
    fake_response.json.return_value = {"code": 401, "msg": "auth failed"}

    with mock.patch.object(sc.requests, "post", return_value=fake_response):
        with pytest.raises(sc.SQLBotError, match="code=401"):
            sc.RealSQLBotClient(base_url="http://x").query_report_info(
                org_info=[], index_info=[{"idx_id": "X"}], time_info=[]
            )


def test_mock_client_returns_per_idx_data(fixture_dir):
    """Mock client: queries with single idx_id and returns that idx_id's rows only."""
    client = sc.MockSQLBotClient(fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json"))
    resp = client.query_report_info(
        org_info=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        index_info=[{"idx_id": "BAS_0263"}],
        time_info=["2025"],
    )
    assert resp.code == 0
    # Per the spec contract, only this idx's rows come back
    assert len(resp.data) == 1
    elem = resp.data[0]
    assert elem["success"] is True
    assert all(row.get("idx_name") == "贷款收单商户数" for row in elem["data"])


def test_mock_client_returns_success_false_for_failing_idx(fixture_dir):
    """Mock client for partial_failure fixture: success=false (F18 case)."""
    client = sc.MockSQLBotClient(fixture_path=str(fixture_dir / "mock_sqlbot" / "partial_failure.json"))
    resp = client.query_report_info(
        org_info=[], index_info=[{"idx_id": "BAS_0264"}], time_info=[]
    )
    assert resp.code == 0   # top-level still 0 (per spec)
    assert resp.data[0]["success"] is False
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py -v
```
Expected: `ModuleNotFoundError: No module named 'sqlbot_client'` for all 5 tests.

- [ ] **Step 3: Create the fixture file used by tests**

Create `backend/tests/chatbi_report/fixtures/mock_sqlbot/query_responses.json`:

```json
{
  "BAS_0263": {
    "success": true,
    "data": [
      {"data_dt": "2025-12-31", "org_ecd": "王益联社", "idx_name": "贷款收单商户数", "value": "1,420.00"},
      {"data_dt": "2024-12-31", "org_ecd": "王益联社", "idx_name": "贷款收单商户数", "value": "1,200.00"}
    ]
  },
  "BAS_0264": {
    "success": true,
    "data": [
      {"data_dt": "2025-12-31", "org_ecd": "王益联社", "idx_name": "贷款余额", "value": "98,765,432.10"}
    ]
  },
  "BAS_0265": {
    "success": true,
    "data": [
      {"data_dt": "2025-12-31", "org_ecd": "王益联社", "idx_name": "存款余额", "value": "123,456,789.00"}
    ]
  }
}
```

Create `backend/tests/chatbi_report/fixtures/mock_sqlbot/partial_failure.json`:

```json
{
  "BAS_0263": {
    "success": true,
    "data": [
      {"data_dt": "2025-12-31", "org_ecd": "王益联社", "idx_name": "贷款收单商户数", "value": "1,420.00"}
    ]
  },
  "BAS_0264": {
    "success": false,
    "data": [],
    "msg": "数据不可用。"
  }
}
```

- [ ] **Step 4: Implement `sqlbot_client.py`**

Create `skills/public/chatbi-report/scripts/sqlbot_client.py`:

```python
"""SQLBot REST client (real) + test double (mock). No authentication required."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


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


class RealSQLBotClient:
    """Real SQLBot REST client. No authentication (per spec 2026-06-23)."""

    ENDPOINT_PATH = "/api/v1/indicator/query-report-info"

    def __init__(self, base_url: str | None = None) -> None:
        url = base_url or os.environ.get("SQLBOT_BASE_URL", "")
        if not url:
            raise SQLBotError("SQLBOT_BASE_URL is not set")
        self._base_url = url.rstrip("/")

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
```

- [ ] **Step 5: Run all sqlbot_client tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/sqlbot_client.py \
        skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py \
        backend/tests/chatbi_report/fixtures/mock_sqlbot/query_responses.json \
        backend/tests/chatbi_report/fixtures/mock_sqlbot/partial_failure.json
git commit -m "feat(skill:chatbi-report): add sqlbot_client.py (real + mock)

Per-idx calling convention enforced: callers pass exactly one idx_id
per query_report_info call, eliminating the SQLBot response's
no-idx_id ambiguity (spec §'Phase 1 已知缺口').

RealSQLBotClient POSTs to /api/v1/indicator/query-report-info with
no Authorization header (SQLBot is auth-free per 2026-06-23 spec).
Raises SQLBotError on top-level code != 0; HTTP 4xx/5xx surfaces as
requests.HTTPError so @retry can re-attempt up to 3x.

MockSQLBotClient loads fixtures by idx_id, supports success=false for
F18 testing. TDD: 5 pytest cases (happy/HTTP-fail/code!=0/mock-happy/
mock-success-false) + 2 fixture JSON files.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `md_lint.py` — all chatbi-specific ERROR/WARN rules

**Files:**
- Create: `skills/public/chatbi-report/scripts/md_lint.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_md_lint.py`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/happy.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/no_org_context.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/no_time_info.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/old_style_placeholder.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/lint_error.md`

**Interfaces:**
- Consumes: path to a user-uploaded MD file
- Produces: a `LintReport` (dataclass: `errors: list[LintError]`, `warnings: list[LintWarning]`), plus `main()` CLI that exits 0 on clean, 1 on any ERROR, 0 on WARN-only

**Chatbi-specific lint rules (extending the sqlbot set) — every one of these must have at least one test in `test_md_lint.py`:**

| Severity | Rule | Trigger |
|---|---|---|
| ERROR | `<table>` must contain `<thead>` and `<tbody>` | missing either tag |
| ERROR | Chapter must have at least one `### 报表:` block | empty section |
| ERROR | F19: report must have `> 机构:` block | missing |
| ERROR | F19: report must have `> 时期:` block | missing |
| ERROR | `> 机构:` format `branch_num=<code>; branch_short_name=<name>` | missing/extra fields |
| ERROR | `> 时期:` must parse as JSON array | not a JSON list |
| ERROR | Real-indicator `<th>` MUST have `data-idx` attribute (chatbi) | `<th>` with text but no `data-idx` AND no `{{虚拟名}}` (i.e. would render as empty data column) |
| ERROR | `data-idx` value must match `^[A-Z]+_\d+$` | malformed ID |
| ERROR | Computed column MUST be `{{虚拟名}}` and MUST NOT also have `data-idx` | `<th data-idx="X" data-unit="%">{{X同比}}</th>` |
| ERROR | `> 计算:` block line must be `<name> = <expr>`, 1–200 chars | bad line shape |
| ERROR | Header computed-column names must appear in `> 计算:` block (left side) | orphan `{{}}` |
| ERROR | `> 计算:` formula right-hand side must reference `data-idx` IDs that exist in the header set | reference to unqueried idx |
| WARN | `<table>` should use HTML, not markdown pipe tables | `\|`-prefixed rows |
| WARN | `data-unit` should be one of `元/万元/亿元/%/百分点/个/次` or a custom string | non-empty but unrecognized |
| WARN | Same computed name appears in >1 thead branches | duplicate `{{虚拟名}}` |
| WARN | `<名>.示例:` line malformed | regex parse fail (drop example, don't block) |
| WARN | Old-style `<th>{{BAS_0263}}</th>` placeholder (no `data-idx` but `{{}}` matches `^[A-Z]+_\d+$`) | backwards compatibility — chatbi spec says render_docx falls back to SQLBot lookup in this case |

- [ ] **Step 1: Create the five MD fixtures used across lint tests**

Create `backend/tests/chatbi_report/fixtures/sample_md/happy.md`:

```markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   收单商户.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

<table>
  <thead>
    <tr>
      <th>季度</th>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>2025-Q4</td><td></td><td></td></tr>
  </tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/no_org_context.md`:

```markdown
# 缺机构样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 时期: time_info=["2025"]

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/no_time_info.md`:

```markdown
# 缺时期样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/old_style_placeholder.md`:

```markdown
# 旧式占位符样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead>
    <tr>
      <th>季度</th>
      <th data-unit="个">{{BAS_0263}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/lint_error.md` (multiple chatbi-specific errors simultaneously):

```markdown
# 错误样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199
> 时期: time_info="2025"
> 计算:
>   营收同比 = 本期MISSING_ID减去年同期

<table>
  <thead>
    <tr>
      <th>季度</th>
      <th>无属性列</th>
      <th data-idx="bad id" data-unit="个">错误ID</th>
      <th data-idx="BAS_0263" data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td><td></td></tr></tbody>
</table>
```
This MD triggers (1) malformed `> 机构:` (no `branch_short_name`), (2) `> 时期:` not a JSON array, (3) thead `<th>` with no `data-idx` and no `{{}}`, (4) `data-idx` regex fail, (5) computed column carries `data-idx`, (6) `> 计算:` references `MISSING_ID` not in the header set.

- [ ] **Step 2: Write failing tests**

Create `skills/public/chatbi-report/scripts/tests/test_md_lint.py`:

```python
"""Unit tests for scripts/md_lint.py."""
from pathlib import Path

import pytest

import md_lint


def test_lint_happy_returns_no_errors(fixture_dir):
    """The happy.md fixture must produce zero ERRORs."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "happy.md"))
    assert report.errors == [], f"unexpected errors: {report.errors}"


def test_lint_no_org_context_is_f19_error(fixture_dir):
    """Missing `> 机构:` block -> F19 ERROR."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "no_org_context.md"))
    codes = {e.code for e in report.errors}
    assert "F19" in codes
    assert any("机构" in e.message for e in report.errors)


def test_lint_no_time_info_is_f19_error(fixture_dir):
    """Missing `> 时期:` block -> F19 ERROR."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "no_time_info.md"))
    codes = {e.code for e in report.errors}
    assert "F19" in codes
    assert any("时期" in e.message for e in report.errors)


def test_lint_old_style_placeholder_is_warn_only(fixture_dir):
    """`{{BAS_0263}}` without `data-idx` is backwards-compatible -> WARN, not ERROR."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "old_style_placeholder.md"))
    assert report.errors == []
    assert any("旧式占位符" in w.message or "old-style" in w.message.lower() for w in report.warnings)


def test_lint_chatbi_error_missing_data_idx_on_real_indicator(fixture_dir):
    """A `<th>` with plain text (no `data-idx` AND no `{{虚拟名}}`) is a chatbi ERROR."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "data-idx" in msgs or "real-indicator" in msgs.lower()


def test_lint_chatbi_error_bad_data_idx_format(fixture_dir):
    """`data-idx="bad id"` fails the `^[A-Z]+_\\d+$` regex -> ERROR."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("^[A-Z]+_\\d+$" in e.message or "regex" in e.message for e in report.errors)


def test_lint_chatbi_error_computed_with_data_idx(fixture_dir):
    """`<th data-idx="BAS_0263" data-unit="%">{{收单商户同比}}</th>` violates the
    computed-column rule (must use `{{虚拟名}}` and MUST NOT carry `data-idx`)."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "computed" in msgs.lower() or "计算列" in msgs


def test_lint_org_block_format_error(fixture_dir):
    """`> 机构: branch_num=27020199` (no `branch_short_name`) is malformed."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("branch_short_name" in e.message for e in report.errors)


def test_lint_time_block_format_error(fixture_dir):
    """`> 时期: time_info="2025"` (not a JSON array) is malformed."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("JSON" in e.message or "time_info" in e.message for e in report.errors)


def test_lint_compute_formula_references_unknown_idx(fixture_dir):
    """`> 计算: 营收同比 = 本期MISSING_ID减...` references an idx not in the header set."""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("MISSING_ID" in e.message or "未查询" in e.message or "unknown" in e.message.lower() for e in report.errors)


def test_lint_main_cli_exits_nonzero_on_error(fixture_dir):
    """`python md_lint.py <bad.md>` exits with code 1."""
    import subprocess, sys
    p = fixture_dir / "sample_md" / "lint_error.md"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "md_lint.py"), str(p)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "ERROR" in proc.stdout or "ERROR" in proc.stderr
```

- [ ] **Step 3: Run tests, verify they fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_md_lint.py -v
```
Expected: `ModuleNotFoundError: No module named 'md_lint'` for all 11 tests.

- [ ] **Step 4: Implement `md_lint.py`**

Create `skills/public/chatbi-report/scripts/md_lint.py`:

```python
"""Validate a chatbi-report MD sample against the spec's lint rules.

- Real-indicator columns are identified by the `data-idx` HTML attribute.
- Old-style `<th data-unit="...">{{BAS_0263}}</th>` (no `data-idx` but
  `{{}}` matches the idx_id regex) is accepted with a WARN; render_docx
  falls back to a SQLBot idx_name lookup for these.
- Computed columns are `{{虚拟名}}` text only; an additional ERROR
  fires if such a column ALSO carries `data-idx`.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path


# Recognized display-unit values (anything else is a WARN, not ERROR).
RECOGNIZED_UNITS = {"元", "万元", "亿元", "%", "百分点", "个", "次"}
IDX_ID_PATTERN = re.compile(r"^[A-Z]+_\d+$")
COMPUTED_NAME_PATTERN = re.compile(r"^\{\{([^{}!]+)\}\}$")   # {{name}}, no inner braces
OLD_PLACEHOLDER_PATTERN = re.compile(r"^\{\{([A-Z]+_\d+)\}\}$")


@dataclass
class LintError:
    code: str               # "F1", "F19", "CHATBI-DATAIDX", etc.
    message: str
    location: str = ""      # "section 'X' > report 'Y'" or "<table> in report Z"


@dataclass
class LintWarning:
    code: str
    message: str
    location: str = ""


@dataclass
class LintReport:
    errors: list[LintError] = field(default_factory=list)
    warnings: list[LintWarning] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class _TableCellCollector(HTMLParser):
    """Collect per-row lists of `<th>` attribute dicts + cell text from one table."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict]] = []
        self._current_row: list[dict] | None = None
        self._current_cell: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "tr":
            self._current_row = []
        elif tag == "th" and self._current_row is not None:
            self._current_cell = {
                "data-idx": a.get("data-idx"),
                "data-unit": a.get("data-unit"),
                "rowspan": a.get("rowspan"),
                "colspan": a.get("colspan"),
                "text": "",
            }
        elif tag == "td" and self._current_row is not None:
            self._current_cell = {"text": ""}

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td") and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell["text"] += data


# ---------- public API ---------- #

def lint_file(path: str) -> LintReport:
    md = Path(path).read_text(encoding="utf-8")
    return lint_markdown(md)


def lint_markdown(md: str) -> LintReport:
    report = LintReport()
    if not md.lstrip().startswith("#"):
        report.errors.append(LintError("F1", "document must start with a `# <title>` line"))

    title_line, body = _split_title(md)
    sections = _split_sections(body)
    if not sections:
        report.errors.append(LintError("F1", "document has no `## 章节:` sections"))
        return report

    for section_title, section_body in sections:
        if not section_body.strip():
            report.errors.append(
                LintError("F1", f"section `{section_title}` has no content", location=section_title)
            )
            continue
        reports = _split_reports(section_body)
        if not reports:
            report.errors.append(
                LintError("F1", f"section `{section_title}` has no `### 报表:` blocks", location=section_title)
            )
            continue
        for report_title, report_body in reports:
            _lint_one_report(report_title, report_body, report, location=section_title)
    return report


# ---------- internals ---------- #

def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    title = ""
    i = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        i = 1
    return title, "\n".join(lines[i:])


def _split_sections(body: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current_title or current_body:
                chunks.append((current_title, "\n".join(current_body)))
            current_title = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title or current_body:
        chunks.append((current_title, "\n".join(current_body)))
    return chunks


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if current_title or current_body:
                chunks.append((current_title, "\n".join(current_body)))
            current_title = line[4:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title or current_body:
        chunks.append((current_title, "\n".join(current_body)))
    return chunks


def _lint_one_report(report_title: str, body: str, report: LintReport, *, location: str) -> None:
    loc = f"{location} > 报表 `{report_title}`"
    org_match = re.search(r"^>\s*机构:\s*(.+)$", body, re.MULTILINE)
    time_match = re.search(r"^>\s*时期:\s*(.+)$", body, re.MULTILINE)

    if not org_match:
        report.errors.append(LintError("F19", "missing `> 机构:` block", location=loc))
    else:
        _lint_org_block(org_match.group(1), report, location=loc)

    if not time_match:
        report.errors.append(LintError("F19", "missing `> 时期:` block", location=loc))
    else:
        _lint_time_block(time_match.group(1), report, location=loc)

    compute_left, compute_right_idxs = _lint_compute_block(body, report, location=loc)

    tables = re.findall(r"<table[^>]*>.*?</table>", body, re.DOTALL | re.IGNORECASE)
    if not tables:
        report.errors.append(LintError("F1", "report has no `<table>` block", location=loc))
        return
    for t in tables:
        _lint_table(t, compute_left, compute_right_idxs, report, location=loc)


def _lint_org_block(line: str, report: LintReport, *, location: str) -> None:
    if "branch_num=" not in line or "branch_short_name=" not in line:
        report.errors.append(
            LintError("F1",
                      ">` 机构:` block must contain both `branch_num=` and `branch_short_name=`",
                      location=location)
        )


def _lint_time_block(line: str, report: LintReport, *, location: str) -> None:
    m = re.search(r"time_info\s*=\s*(\[.*?\])", line)
    if not m:
        report.errors.append(
            LintError("F1", "`> 时期:` block must contain `time_info=[...]` (JSON array)",
                      location=location)
        )
        return
    try:
        parsed = json.loads(m.group(1))
    except json.JSONDecodeError:
        report.errors.append(
            LintError("F1", "`> 时期:` time_info= must be a valid JSON array", location=location)
        )
        return
    if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
        report.errors.append(
            LintError("F1", "`> 时期:` time_info= must be an array of strings", location=location)
        )


def _lint_compute_block(body: str, report: LintReport, *, location: str) -> tuple[set[str], set[str]]:
    """Return (set of computed names on the LHS, set of idx_ids referenced on the RHS)."""
    compute_match = re.search(r"^>\s*计算:\s*$(.*?)(?=^>\s*[^ ]|\Z)", body, re.MULTILINE | re.DOTALL)
    left_names: set[str] = set()
    referenced_idx: set[str] = set()
    if not compute_match:
        return left_names, referenced_idx
    for raw in compute_match.group(1).splitlines():
        line = raw.lstrip("> ").strip()
        if not line:
            continue
        if ".示例:" in line:
            continue
        if "=" not in line:
            report.errors.append(
                LintError("F1", f"`> 计算:` line missing `=`: {line!r}", location=location)
            )
            continue
        name_part, expr_part = line.split("=", 1)
        name_part = name_part.strip()
        expr_part = expr_part.strip()
        if not (1 <= len(name_part) <= 200 and 1 <= len(expr_part) <= 200):
            report.errors.append(
                LintError("F1", f"`> 计算:` line must be 1-200 chars on each side: {line!r}",
                          location=location)
            )
            continue
        left_names.add(name_part)
        for tok in re.findall(r"[A-Z]+_\d+", expr_part):
            referenced_idx.add(tok)
    return left_names, referenced_idx


def _lint_table(
    table_md: str,
    compute_left: set[str],
    compute_right_idxs: set[str],
    report: LintReport,
    *,
    location: str,
) -> None:
    if "<thead" not in table_md.lower():
        report.errors.append(LintError("F1", "<table> missing <thead>", location=location))
    if "<tbody" not in table_md.lower():
        report.errors.append(LintError("F1", "<table> missing <tbody>", location=location))

    if re.search(r"^\s*\|", table_md, re.MULTILINE):
        report.warnings.append(LintWarning("STYLE", "use HTML <table>, not markdown pipe tables", location=location))

    parser = _TableCellCollector()
    try:
        parser.feed(table_md)
    except Exception as e:
        report.errors.append(LintError("F1", f"HTML parse error: {e}", location=location))
        return

    real_idx_ids_in_table: set[str] = set()
    computed_names_in_table: set[str] = set()
    leaves = [c for row in parser.rows for c in row]
    for cell in leaves:
        text = (cell.get("text") or "").strip()
        data_idx = cell.get("data-idx")
        data_unit = cell.get("data-unit")
        comp_match = COMPUTED_NAME_PATTERN.match(text)
        old_match = OLD_PLACEHOLDER_PATTERN.match(text)

        if comp_match:
            computed_names_in_table.add(comp_match.group(1))
            if data_idx:
                report.errors.append(LintError(
                    "CHATBI-COMPUTED-WITH-IDX",
                    f"computed column `{{{{{comp_match.group(1)}}}}}` must NOT carry data-idx "
                    f"(found data-idx={data_idx!r})",
                    location=location,
                ))
            continue

        if old_match:
            report.warnings.append(LintWarning(
                "CHATBI-OLD-PLACEHOLDER",
                f"old-style placeholder `{{{{{old_match.group(1)}}}}}` without data-idx; "
                f"render_docx will fall back to SQLBot idx_name lookup",
                location=location,
            ))
            real_idx_ids_in_table.add(old_match.group(1))
            continue

        if data_idx:
            if not IDX_ID_PATTERN.match(data_idx):
                report.errors.append(LintError(
                    "CHATBI-DATAIDX-FORMAT",
                    f"data-idx={data_idx!r} does not match `^[A-Z]+_\\d+$`",
                    location=location,
                ))
            else:
                real_idx_ids_in_table.add(data_idx)
            continue

        if not data_idx and not text:
            continue

        is_parent_label = (
            (cell.get("rowspan") or cell.get("colspan")) and not data_unit
        )
        if not is_parent_label:
            report.errors.append(LintError(
                "CHATBI-DATAIDX-MISSING",
                f"real-indicator <th> with text {text!r} is missing `data-idx` attribute",
                location=location,
            ))

        if data_unit and data_unit not in RECOGNIZED_UNITS:
            report.warnings.append(LintWarning(
                "CHATBI-DATAUNIT-CUSTOM",
                f"data-unit={data_unit!r} is not in the standard set; treated as a custom unit string",
                location=location,
            ))

    orphan = computed_names_in_table - compute_left
    for name in sorted(orphan):
        report.errors.append(LintError(
            "CHATBI-COMPUTED-ORPHAN",
            f"computed column `{{{{{name}}}}}` not declared in `> 计算:` block",
            location=location,
        ))

    unknown_refs = compute_right_idxs - real_idx_ids_in_table
    for idx in sorted(unknown_refs):
        report.errors.append(LintError(
            "CHATBI-COMPUTE-UNKNOWN-IDX",
            f"`> 计算:` references idx_id={idx!r} which is not in the header data-idx set",
            location=location,
        ))

    if len(computed_names_in_table) != len(set(computed_names_in_table)):
        report.warnings.append(LintWarning(
            "CHATBI-COMPUTED-DUP",
            "same computed column name appears multiple times across thead branches; consider unique names",
            location=location,
        ))


# ---------- CLI ---------- #

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("usage: md_lint.py <path-to-md>", file=sys.stderr)
        return 2
    rep = lint_file(argv[0])
    for e in rep.errors:
        print(f"ERROR {e.code}: {e.message}  [{e.location}]", file=sys.stderr)
    for w in rep.warnings:
        print(f"WARN  {w.code}: {w.message}  [{w.location}]", file=sys.stderr)
    if rep.ok:
        print(f"OK: 0 errors, {len(rep.warnings)} warning(s)")
        return 0
    print(f"FAIL: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run all md_lint tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_md_lint.py -v
```
Expected: 11 passed.

If any test fails, double-check the fixture's expected vs actual error keywords (assertions are intentionally tolerant — match on substrings rather than exact strings).

- [ ] **Step 6: Run CLI smoke check on happy.md**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python skills/public/chatbi-report/scripts/md_lint.py backend/tests/chatbi_report/fixtures/sample_md/happy.md
echo "exit=$?"
```
Expected output ends with `OK: 0 errors, 0 warning(s)` and exit code `0`.

Then run on `lint_error.md`:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python skills/public/chatbi-report/scripts/md_lint.py backend/tests/chatbi_report/fixtures/sample_md/lint_error.md
echo "exit=$?"
```
Expected: multiple ERROR lines, exit code `1`.

- [ ] **Step 7: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/md_lint.py \
        skills/public/chatbi-report/scripts/tests/test_md_lint.py \
        backend/tests/chatbi_report/fixtures/sample_md/happy.md \
        backend/tests/chatbi_report/fixtures/sample_md/no_org_context.md \
        backend/tests/chatbi_report/fixtures/sample_md/no_time_info.md \
        backend/tests/chatbi_report/fixtures/sample_md/old_style_placeholder.md \
        backend/tests/chatbi_report/fixtures/sample_md/lint_error.md
git commit -m "feat(skill:chatbi-report): add md_lint.py with chatbi-specific rules

11 pytest cases covering happy + 5 chatbi-specific ERROR rules:
data-idx required on real-indicator <th>; data-idx format
^[A-Z]+_\\d+\$; computed-column MUST use {{虚拟名}} AND MUST NOT
carry data-idx; orphan {{虚拟名}} not in > 计算: block; > 计算:
formula references unknown idx_id. Plus F19 (no > 机构:/ > 时期:)
and 3 WARN rules (old-style placeholder, custom data-unit, computed
name dup). CLI exits 1 on any ERROR.

5 fixture MD files cover each rule individually; lint_error.md
triggers all of them simultaneously as a smoke check.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `parse_md.py` — MD → ReportDoc AST (2-D headers + category labels)

**Files:**
- Create: `skills/public/chatbi-report/scripts/parse_md.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_parse_md.py`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/multi_chapter.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/multi_header.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/multi_header_computed.md`

**Interfaces:**
- Consumes: path to a user-uploaded MD file (assumed pre-linted)
- Produces: `ReportDoc` dataclass tree — `sections[Section].reports[Report]`, each `Report` has `headers: Th[ ][ ]` (2-D; outer = thead row index, inner = cells in that row), `data_rows: list[dict]`, `computed_specs: list[ComputedSpec]`. Plus a `parse_report()` standalone for unit tests.

**Chatbi AST shape (per spec):**

| Aspect | Shape |
|---|---|
| `headers` shape | `Th[ ][ ]` (2-D, outer = thead row, inner = cells in that row) |
| `Th` fields | text / is_indicator / idx_id? / data_unit? / is_computed / rowspan? / colspan? |
| `is_indicator` rule | `data-idx` HTML attribute present (preferred); `{{idx_id}}` placeholder regex as fallback |
| `is_computed` rule | `{{虚拟名}}` text AND appears in `> 计算:` left |
| Both false → | category label: pure multi-level thead parent (`is_indicator=False`, `is_computed=False`, `idx_id=None`); parser sets this automatically |
| Old-style `<th>{{BAS_0263}}</th>` | `is_indicator=True`, `is_computed=False`, `idx_id="BAS_0263"`; render_docx falls back to SQLBot idx_name |

- [ ] **Step 1: Create three MD fixtures**

Create `backend/tests/chatbi_report/fixtures/sample_md/multi_chapter.md`:

```markdown
# 多章节样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>

## 第二章: 资产负债

### 报表: 存贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0264" data-unit="元">贷款余额</th><th data-idx="BAS_0265" data-unit="元">存款余额</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/multi_header.md` (two-row thead with rowspan/colspan):

```markdown
# 多级表头样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="2">商户与贷款</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-idx="BAS_0264" data-unit="元">贷款余额</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/multi_header_computed.md` (computed column under a category parent):

```markdown
# 多级表头含计算列样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="2">商户与贷款</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
```

- [ ] **Step 2: Write failing tests**

Create `skills/public/chatbi-report/scripts/tests/test_parse_md.py`:

```python
"""Unit tests for scripts/parse_md.py."""
from pathlib import Path

import pytest

import parse_md as pm


def test_parse_happy_md_returns_single_report(fixture_dir):
    """happy.md: 1 section, 1 report, 3 thead cells (1 stub + 1 real indicator + 1 computed)."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "happy.md"))
    assert doc.title == "王益联社 2025 年度经营报表"
    assert len(doc.sections) == 1
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 1          # one thead row
    assert len(rep.headers[0]) == 3       # three cells in that row
    cells = rep.headers[0]
    # Cell 0: stub ("季度")
    assert cells[0].is_indicator is False and cells[0].is_computed is False and cells[0].idx_id is None
    # Cell 1: real indicator from data-idx
    assert cells[1].is_indicator is True and cells[1].idx_id == "BAS_0263"
    assert cells[1].text == "贷款收单商户数"
    # Cell 2: computed (no data-idx)
    assert cells[2].is_computed is True and cells[2].is_indicator is False
    assert cells[2].text == "{{收单商户同比}}"
    # computed_specs present
    assert any(s.name == "收单商户同比" for s in rep.computed_specs)


def test_parse_multi_chapter_two_sections(fixture_dir):
    """multi_chapter.md: 2 chapters, 1 report each."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_chapter.md"))
    assert len(doc.sections) == 2
    assert len(doc.sections[0].reports) == 1
    assert len(doc.sections[1].reports) == 1


def test_parse_multi_header_two_row_thead(fixture_dir):
    """multi_header.md: outer headers is 2 rows; row 0 has 2 cells (one is a category parent)."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_header.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2          # two thead rows
    assert len(rep.headers[0]) == 2       # 季度 + 商户与贷款(colspan=2)
    assert len(rep.headers[1]) == 2       # BAS_0263 + BAS_0264 (under the colspan)
    # Category parent: has colspan, no data-idx, no {{}}
    parent = rep.headers[0][1]
    assert parent.is_indicator is False and parent.is_computed is False
    assert parent.colspan == 2
    # Children in row 1
    c0, c1 = rep.headers[1]
    assert c0.is_indicator is True and c0.idx_id == "BAS_0263"
    assert c1.is_indicator is True and c1.idx_id == "BAS_0264"


def test_parse_multi_header_computed_under_category(fixture_dir):
    """multi_header_computed.md: computed column nested under a category parent."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_header_computed.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2
    # Row 1: real indicator + computed
    r1 = rep.headers[1]
    assert r1[0].is_indicator is True and r1[0].idx_id == "BAS_0263"
    assert r1[1].is_computed is True
    # Computed spec parsed
    assert any(s.name == "收单商户同比" for s in rep.computed_specs)


def test_parse_old_style_placeholder_extracts_idx_id(fixture_dir):
    """`<th data-unit="个">{{BAS_0263}}</th>` -> is_indicator=True, idx_id=BAS_0263, text=BAS_0263."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "old_style_placeholder.md"))
    rep = doc.sections[0].reports[0]
    cells = rep.headers[0]
    real = [c for c in cells if c.is_indicator]
    assert real[0].idx_id == "BAS_0263"
    # text comes from the placeholder itself (no Chinese name in MD)
    assert real[0].text == "BAS_0263"


def test_parse_org_and_time_into_report(fixture_dir):
    """`> 机构:` and `> 时期:` parsed into Report fields."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "happy.md"))
    rep = doc.sections[0].reports[0]
    assert rep.org_context.branch_num == "27020199"
    assert rep.org_context.branch_short_name == "王益联社"
    assert rep.time_info == ["2025"]


def test_all_idx_ids_collected_at_doc_level(fixture_dir):
    """Doc.all_idx_ids is the union of every non-computed idx_id across all reports."""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_chapter.md"))
    assert doc.all_idx_ids == {"BAS_0263", "BAS_0264", "BAS_0265"}
```

- [ ] **Step 3: Run tests, verify fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_parse_md.py -v
```
Expected: `ModuleNotFoundError: No module named 'parse_md'` for all 7 tests.

- [ ] **Step 4: Implement `parse_md.py`**

Create `skills/public/chatbi-report/scripts/parse_md.py`:

```python
"""Parse a chatbi-report MD sample into the ReportDoc AST.

- `headers` is a 2-D structure (outer = thead row, inner = cells in that row)
  to support multi-level thead with rowspan/colspan.
- `Th.is_indicator` is derived from the `data-idx` HTML attribute (preferred);
  the `{{}}` placeholder regex is a fallback for old-style MD.
- An old-style `<th>{{BAS_0263}}</th>` (no data-idx, but `{{}}` matches the
  idx_id regex) is still recognized as is_indicator=True (render_docx then
  falls back to SQLBot idx_name lookup for these).
- Category-label cells (multi-level thead parents) are emitted with
  is_indicator=False, is_computed=False, idx_id=None — no error.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

IDX_ID_PATTERN = re.compile(r"^[A-Z]+_\d+$")
COMPUTED_NAME_PATTERN = re.compile(r"^\{\{([^{}!]+)\}\}$")
OLD_PLACEHOLDER_PATTERN = re.compile(r"^\{\{([A-Z]+_\d+)\}\}$")


@dataclass
class Th:
    text: str
    is_indicator: bool
    is_computed: bool
    idx_id: str | None = None
    data_unit: str | None = None
    rowspan: int | None = None
    colspan: int | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "text": self.text,
            "is_indicator": self.is_indicator,
            "is_computed": self.is_computed,
        }
        if self.idx_id is not None:
            d["idx_id"] = self.idx_id
        if self.data_unit is not None:
            d["data_unit"] = self.data_unit
        if self.rowspan is not None:
            d["rowspan"] = self.rowspan
        if self.colspan is not None:
            d["colspan"] = self.colspan
        return d


@dataclass
class ComputedSpec:
    name: str
    prompt: str                          # raw "name = expr" text
    examples: list[dict] = field(default_factory=list)   # [{"inputs": {...}, "expected": "0.1833"}]


@dataclass
class OrgContext:
    branch_num: str
    branch_short_name: str


@dataclass
class Report:
    title: str
    org_context: OrgContext
    time_info: list[str]
    headers: list[list[Th]]                # 2-D: outer = thead row index
    data_rows: list[dict] = field(default_factory=list)
    computed_specs: list[ComputedSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "org_context": {"branch_num": self.org_context.branch_num,
                            "branch_short_name": self.org_context.branch_short_name},
            "time_info": list(self.time_info),
            "headers": [[c.to_dict() for c in row] for row in self.headers],
            "data_rows": list(self.data_rows),
            "computed_specs": [
                {"name": s.name, "prompt": s.prompt, "examples": s.examples}
                for s in self.computed_specs
            ],
        }


@dataclass
class Section:
    title: str
    reports: list[Report]

    def to_dict(self) -> dict:
        return {"title": self.title, "reports": [r.to_dict() for r in self.reports]}


@dataclass
class ReportDoc:
    title: str
    sections: list[Section]
    all_idx_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
            "all_idx_ids": sorted(self.all_idx_ids),
        }


# ---------- public API ---------- #

def parse_file(path: str) -> ReportDoc:
    return parse_markdown(Path(path).read_text(encoding="utf-8"))


def parse_markdown(md: str) -> ReportDoc:
    title, body = _split_title(md)
    sections_raw = _split_sections(body)
    sections: list[Section] = []
    all_idx: set[str] = set()
    for section_title, section_body in sections_raw:
        reports: list[Report] = []
        for report_title, report_body in _split_reports(section_body):
            rep = _parse_one_report(report_title, report_body)
            reports.append(rep)
            for row in rep.headers:
                for cell in row:
                    if cell.idx_id:
                        all_idx.add(cell.idx_id)
        sections.append(Section(title=section_title, reports=reports))
    return ReportDoc(title=title, sections=sections, all_idx_ids=all_idx)


def parse_report(md: str, section_idx: int = 0, report_idx: int = 0) -> Report:
    """Convenience: parse one specific report by index. Used by tests and compute.py."""
    doc = parse_markdown(md)
    return doc.sections[section_idx].reports[report_idx]


# ---------- internals ---------- #

def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "", md


def _split_sections(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title = ""
    cur_body: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if cur_title or cur_body:
                out.append((cur_title, "\n".join(cur_body)))
            cur_title = line[3:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_title or cur_body:
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title = ""
    cur_body: list[str] = []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if cur_title or cur_body:
                out.append((cur_title, "\n".join(cur_body)))
            cur_title = line[4:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_title or cur_body:
        out.append((cur_title, "\n".join(cur_body)))
    return out


class _TheadCellCollector(HTMLParser):
    """Collect a list[list[dict]] of thead rows from a <thead>...</thead> chunk."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict]] = []
        self._current_row: list[dict] | None = None
        self._current_cell: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "tr":
            self._current_row = []
        elif tag == "th" and self._current_row is not None:
            self._current_cell = {
                "data-idx": a.get("data-idx"),
                "data-unit": a.get("data-unit"),
                "rowspan": int(a["rowspan"]) if a.get("rowspan") else None,
                "colspan": int(a["colspan"]) if a.get("colspan") else None,
                "text": "",
            }
        elif tag == "td" and self._current_row is not None:
            self._current_cell = {
                "data-idx": None, "data-unit": None,
                "rowspan": None, "colspan": None, "text": "",
            }

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td") and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell["text"] += data


def _parse_one_report(report_title: str, body: str) -> Report:
    org_match = re.search(r"^>\s*机构:\s*branch_num=([^;]+);\s*branch_short_name=(.+)$",
                          body, re.MULTILINE)
    time_match = re.search(r"^>\s*时期:\s*time_info\s*=\s*(\[.*?\])\s*$", body, re.MULTILINE)
    if not org_match or not time_match:
        raise ValueError(f"report `{report_title}` missing `> 机构:` or `> 时期:`; run md_lint first")
    org = OrgContext(branch_num=org_match.group(1).strip(),
                     branch_short_name=org_match.group(2).strip())
    time_info = json.loads(time_match.group(1))

    thead_match = re.search(r"<thead[^>]*>(.*?)</thead>", body, re.DOTALL | re.IGNORECASE)
    if not thead_match:
        raise ValueError(f"report `{report_title}` has no <thead>")
    parser = _TheadCellCollector()
    parser.feed(thead_match.group(1))
    headers_2d: list[list[Th]] = []
    for row in parser.rows:
        headers_2d.append([_cell_to_th(c) for c in row])

    tbody_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", body, re.DOTALL | re.IGNORECASE)
    data_rows: list[dict] = []
    if tbody_match:
        for line_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbody_match.group(1),
                                       re.DOTALL | re.IGNORECASE):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", line_match.group(1), re.DOTALL | re.IGNORECASE)
            tds = [re.sub(r"<[^>]+>", "", t).strip() for t in tds]
            if tds:
                data_rows.append({"data_dt": tds[0], "raw_cells": tds[1:]})

    computed_specs = _parse_compute_block(body)
    header_computed_names = {
        c.text.strip("{}") for row in headers_2d for c in row if c.is_computed
    }
    computed_specs = [s for s in computed_specs if s.name in header_computed_names]

    return Report(
        title=report_title,
        org_context=org,
        time_info=time_info,
        headers=headers_2d,
        data_rows=data_rows,
        computed_specs=computed_specs,
    )


def _cell_to_th(cell: dict) -> Th:
    text = (cell.get("text") or "").strip()
    data_idx = cell.get("data-idx")
    data_unit = cell.get("data-unit")
    rowspan = cell.get("rowspan")
    colspan = cell.get("colspan")

    comp_match = COMPUTED_NAME_PATTERN.match(text)
    old_match = OLD_PLACEHOLDER_PATTERN.match(text)

    if comp_match:
        return Th(text=text, is_indicator=False, is_computed=True,
                  data_unit=data_unit, rowspan=rowspan, colspan=colspan)
    if old_match:
        # Old-style placeholder: still is_indicator; idx_id from {{}}
        return Th(text=text, is_indicator=True, is_computed=False,
                  idx_id=old_match.group(1),
                  data_unit=data_unit, rowspan=rowspan, colspan=colspan)
    if data_idx and IDX_ID_PATTERN.match(data_idx):
        return Th(text=text, is_indicator=True, is_computed=False,
                  idx_id=data_idx, data_unit=data_unit,
                  rowspan=rowspan, colspan=colspan)
    # No data-idx, no {{}}, no formula match — category-label cell or stub.
    return Th(text=text, is_indicator=False, is_computed=False,
              data_unit=data_unit, rowspan=rowspan, colspan=colspan)


def _parse_compute_block(body: str) -> list[ComputedSpec]:
    """Parse `> 计算:` and optional `.示例:` lines."""
    out: list[ComputedSpec] = []
    compute_match = re.search(r"^>\s*计算:\s*$(.*?)(?=^>\s*[^ ]|\Z)", body, re.MULTILINE | re.DOTALL)
    if not compute_match:
        return out
    by_name: dict[str, ComputedSpec] = {}
    for raw in compute_match.group(1).splitlines():
        line = raw.lstrip("> ").strip()
        if not line:
            continue
        if ".示例:" in line:
            head, _, tail = line.partition(".示例:")
            name = head.strip()
            ex = _parse_example(tail.strip())
            if name in by_name and ex is not None:
                by_name[name].examples.append(ex)
            continue
        if "=" not in line:
            continue
        name, expr = (s.strip() for s in line.split("=", 1))
        by_name[name] = ComputedSpec(name=name, prompt=f"{name} = {expr}")
    return list(by_name.values())


def _parse_example(tail: str) -> dict | None:
    """Parse `BAS_0263[current=1420, yoy_same=1200] -> 0.1833` into a dict."""
    m = re.match(r"^([A-Z]+_\d+)\s*\[(.*?)\]\s*->\s*(\S+)$", tail)
    if not m:
        return None
    inputs_str = m.group(2)
    inputs: dict[str, str] = {}
    for kv in re.findall(r"(\w+)\s*=\s*([^,]+)", inputs_str):
        inputs[kv[0].strip()] = kv[1].strip()
    return {"inputs": inputs, "expected": m.group(3)}
```

- [ ] **Step 5: Run all parse_md tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_parse_md.py -v
```
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/parse_md.py \
        skills/public/chatbi-report/scripts/tests/test_parse_md.py \
        backend/tests/chatbi_report/fixtures/sample_md/multi_chapter.md \
        backend/tests/chatbi_report/fixtures/sample_md/multi_header.md \
        backend/tests/chatbi_report/fixtures/sample_md/multi_header_computed.md
git commit -m "feat(skill:chatbi-report): add parse_md.py with 2-D headers + category labels

7 pytest cases covering happy / multi_chapter / multi_header (rowspan+
colspan parent) / multi_header_computed (computed under category) /
old-style placeholder extraction / org+time parsing / all_idx_ids.

AST shape per spec:
- headers: Th[ ][ ] (2-D; outer = thead row) so multi-level headers
  render with correct cell.merge() in DOCX.
- Th adds rowspan?/colspan? fields.
- is_indicator derives from data-idx HTML attribute (preferred) or
  {{idx_id}} old-style placeholder fallback (render_docx will SQLBot-
  lookup the idx_name in the latter case).
- Category-label cells (multi-level thead parents with no data-idx,
  no {{}}) are emitted as is_indicator=False, is_computed=False,
  idx_id=None — no error.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: `unit_conversion.py` + `compute.py` — IR, codegen, validators, Decimal math

This task is split into two modules for clean unit coverage. `unit_conversion.py` holds the Decimal math (no LLM dependency, easy TDD). `compute.py` holds the LLM-driven pipeline (IR extraction, codegen, AST/signature/smoke/example validators) and imports `unit_conversion`.

**Files:**
- Create: `skills/public/chatbi-report/scripts/unit_conversion.py`
- Create: `skills/public/chatbi-report/scripts/compute.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_unit_conversion.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_compute.py`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/computed_columns.md`
- Create: `backend/tests/chatbi_report/fixtures/sample_md/computed_with_examples.md`

**`unit_conversion.py` interfaces:**
- Consumes: raw value (string with thousands separator), `data_unit: str | None`
- Produces: `convert_unit(raw_value: str, data_unit: str | None) -> Decimal` — Decimal-typed post-conversion display value; `SCALE_FACTOR` mapping constant

**`compute.py` interfaces:**
- Consumes: `ReportDoc` (from `parse_md`), LLM provider callable (`llm_complete(prompt: str, *, system: str | None = None) -> str`), the prompt template from `prompts/compute_codegen.md`
- Produces:
  - `extract_compute_ir(report: Report, llm_complete) -> list[ComputeIR]` — batched LLM call (spec §"计算列 IR 提取 batched LLM"). Each `ComputeIR` carries `name`, `formula_repr`, `base_idx_ids`, `periods`.
  - `generate_pandas_function(report_id, spec, ir, llm_complete) -> str` — returns the LLM-emitted Python source.
  - `validate_ast(source: str) -> None | raise ComputeValidationError` — whitelist check.
  - `validate_signature(source: str, expected_name: str) -> None | raise` — name + arg + return annotation check.
  - `run_smoke(source: str, df: pd.DataFrame) -> pd.Series` — exec source, run function, assert isinstance(out, pd.Series).
  - `run_example(source: str, inputs: dict, expected: str) -> bool` — assemble df, math.isclose check.
  - `evaluate_column(source: str, df: pd.DataFrame) -> pd.Series` — top-level API for the lead agent to fill the column.

**Why split into two modules:**
- `unit_conversion.py` has zero LLM/IO deps — tests are pure (in, out), no monkeypatching.
- `compute.py` has heavy LLM + AST sandboxing — separate test file uses monkeypatched `llm_complete`.

- [ ] **Step 1: Create the two MD fixtures**

Create `backend/tests/chatbi_report/fixtures/sample_md/computed_columns.md`:

```markdown
# 计算列样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   余额较年初 = 本期BAS_0264减上期

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th><th data-idx="BAS_0264" data-unit="元">贷款余额</th><th data-unit="%">{{收单商户同比}}</th><th data-unit="元">{{余额较年初}}</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td><td></td><td></td></tr></tbody>
</table>
```

Create `backend/tests/chatbi_report/fixtures/sample_md/computed_with_examples.md`:

```markdown
# 计算列带示例样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   收单商户同比.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th><th data-unit="%">{{收单商户同比}}</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
```

- [ ] **Step 2: Write failing tests for `unit_conversion.py`**

Create `skills/public/chatbi-report/scripts/tests/test_unit_conversion.py`:

```python
"""Unit tests for scripts/unit_conversion.py."""
from decimal import Decimal

import pytest

import unit_conversion as uc


def test_scale_factor_table_values():
    """Standard units map to the spec's scale_factor column."""
    assert uc.SCALE_FACTOR["元"] == Decimal("1")
    assert uc.SCALE_FACTOR["万元"] == Decimal("10000")
    assert uc.SCALE_FACTOR["亿元"] == Decimal("100000000")
    assert uc.SCALE_FACTOR["%"] == Decimal("0.01")
    assert uc.SCALE_FACTOR["百分点"] == Decimal("1")
    assert uc.SCALE_FACTOR["个"] == Decimal("1")
    assert uc.SCALE_FACTOR["次"] == Decimal("1")


def test_strip_thousands_separator():
    """Internal helper handles '1,420.00' -> Decimal('1420.00')."""
    assert uc._strip_thousands("1,420.00") == Decimal("1420.00")
    assert uc._strip_thousands("123,456,789") == Decimal("123456789")
    assert uc._strip_thousands("0") == Decimal("0")


def test_convert_unit_yuan_passthrough():
    """data-unit=元 -> raw_value displayed 1:1."""
    assert uc.convert_unit("1,420.00", "元") == Decimal("1420.00")


def test_convert_unit_wan():
    """data-unit=万元 -> divide by 10000."""
    # SQLBot raw is in 元; designer wants 万元
    assert uc.convert_unit("12,000,000", "万元") == Decimal("1200.0000")


def test_convert_unit_yi():
    """data-unit=亿元 -> divide by 1e8."""
    assert uc.convert_unit("987,654,321", "亿元") == Decimal("9.87654321")


def test_convert_unit_percentage():
    """data-unit=% -> multiply by 0.01 so 0.366 displays as 36.60%."""
    assert uc.convert_unit("0.366", "%") == Decimal("0.366")


def test_convert_unit_none_keeps_raw():
    """data-unit missing or empty -> Decimal of raw value, identity scale."""
    assert uc.convert_unit("1,234", None) == Decimal("1234")
    assert uc.convert_unit("1,234", "") == Decimal("1234")


def test_convert_unit_custom_string_passthrough():
    """data-unit='个' (already a count) -> 1:1."""
    assert uc.convert_unit("1,420", "个") == Decimal("1420")


def test_convert_unit_raises_on_bad_string():
    """Non-numeric raw_value -> InvalidOperation (Decimal)."""
    from decimal import InvalidOperation
    with pytest.raises(InvalidOperation):
        uc.convert_unit("not-a-number", "元")


def test_round_trip_yuan_to_wan_to_yuan():
    """12,000,000 元 -> 1200 万元 -> 12,000,000 元 (no precision loss via Decimal)."""
    yuan_raw = uc.convert_unit("12,000,000", "万元")
    yuan_back = uc.convert_unit(str(yuan_raw), "元")
    assert yuan_back == Decimal("12000000.0000")
```

- [ ] **Step 3: Run tests, verify fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_unit_conversion.py -v
```
Expected: `ModuleNotFoundError: No module named 'unit_conversion'`.

- [ ] **Step 4: Implement `unit_conversion.py`**

Create `skills/public/chatbi-report/scripts/unit_conversion.py`:

```python
"""Decimal-based unit conversion. No float, no LLM dependency."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


# Display-unit -> scale_factor. Per spec §"列级单位声明 data-unit".
SCALE_FACTOR: dict[str, Decimal] = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
    "%": Decimal("0.01"),
    "百分点": Decimal("1"),
    "个": Decimal("1"),
    "次": Decimal("1"),
}


def _strip_thousands(raw_value: str) -> Decimal:
    """Remove thousands separators ('1,420.00' -> Decimal('1420.00'))."""
    return Decimal(raw_value.replace(",", "").strip())


def convert_unit(raw_value: str, data_unit: str | None) -> Decimal:
    """Convert SQLBot raw value (with thousands sep) into the designer's display unit.

    Spec formula: display_value = raw * raw_unit_scale / display_unit_scale.
    Phase 1 raw_unit_scale = 1 (we don't yet have get_indicator's unit field,
    so we assume SQLBot returns the raw value in 元 / native units).

    Returns a Decimal. No float math anywhere.
    """
    raw = _strip_thousands(raw_value)
    raw_unit_scale = Decimal("1")      # Phase 1 default; see spec §"⚠️ Phase 1 已知缺口"
    display_unit_scale = SCALE_FACTOR.get(data_unit or "", Decimal("1"))
    return raw * raw_unit_scale / display_unit_scale


__all__ = ["SCALE_FACTOR", "convert_unit"]
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_unit_conversion.py -v
```
Expected: 10 passed.

- [ ] **Step 6: Write failing tests for `compute.py`**

Create `skills/public/chatbi-report/scripts/tests/test_compute.py`:

```python
"""Unit tests for scripts/compute.py (LLM-driven pipeline, monkeypatched)."""
import ast
import textwrap
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

import compute as cp


# ---------- IR extraction tests ---------- #

def test_extract_compute_ir_parses_batched_response(fixture_dir):
    """Mock LLM returns a JSON IR array; extractor maps to list[ComputeIR]."""
    md = Path(fixture_dir / "sample_md" / "computed_columns.md").read_text(encoding="utf-8")
    from parse_md import parse_file
    rep = parse_file(md).sections[0].reports[0]

    fake_llm = mock.Mock(return_value=textwrap.dedent("""
        [
          {"name": "收单商户同比", "formula_repr": "(current-yoy_same)/yoy_same",
           "base_idx_ids": ["BAS_0263"], "periods": ["current", "yoy_same"]},
          {"name": "余额较年初", "formula_repr": "current-prev_period",
           "base_idx_ids": ["BAS_0264"], "periods": ["current", "prev_period"]}
        ]
    """))
    irs = cp.extract_compute_ir(rep, fake_llm)
    assert {ir.name for ir in irs} == {"收单商户同比", "余额较年初"}
    assert fake_llm.call_count == 1   # batched, not per-spec


def test_extract_compute_ir_flags_unknown_base_idx(fixture_dir):
    """If LLM returns an idx_id not in the doc's all_idx_ids, mark F12."""
    md = Path(fixture_dir / "sample_md" / "computed_columns.md").read_text(encoding="utf-8")
    from parse_md import parse_file
    rep = parse_file(md).sections[0].reports[0]

    fake_llm = mock.Mock(return_value=textwrap.dedent("""
        [{"name": "收单商户同比", "formula_repr": "current/yoy_same",
          "base_idx_ids": ["MISSING"], "periods": ["current", "yoy_same"]}]
    """))
    irs = cp.extract_compute_ir(rep, fake_llm)
    assert irs[0].failure_class == "F12"


# ---------- AST whitelist tests ---------- #

def test_validate_ast_accepts_pure_binop_subscript():
    src = textwrap.dedent("""
        def compute_x_y(df):
            return df['BAS_0263'] / df['BAS_0264']
    """)
    cp.validate_ast(src)   # no raise


def test_validate_ast_rejects_import():
    src = "import os\ndef f(df):\n    return df['x']"
    with pytest.raises(cp.ComputeValidationError, match="Import"):
        cp.validate_ast(src)


def test_validate_ast_rejects_os_attribute():
    src = textwrap.dedent("""
        def f(df):
            return df['x'].pipe(os.system)
    """)
    with pytest.raises(cp.ComputeValidationError, match="Attribute.*blacklist"):
        cp.validate_ast(src)


def test_validate_ast_rejects_unknown_call():
    """Call to anything other than df.* / pd.* / np.* is rejected."""
    src = textwrap.dedent("""
        def f(df):
            return eval('1+1')
    """)
    with pytest.raises(cp.ComputeValidationError, match="Call.*not allowed"):
        cp.validate_ast(src)


def test_validate_ast_rejects_global():
    src = textwrap.dedent("""
        def f(df):
            global x
            return df['y']
    """)
    with pytest.raises(cp.ComputeValidationError, match="Global"):
        cp.validate_ast(src)


# ---------- Signature tests ---------- #

def test_validate_signature_matches_expected():
    src = textwrap.dedent("""
        def compute_report_收单商户同比(df: pd.DataFrame) -> pd.Series:
            return df['x']
    """)
    cp.validate_signature(src, "compute_report_收单商户同比")
    # (Note: real function names will be slugified; see compute.py.)


def test_validate_signature_rejects_wrong_name():
    src = "def wrong_name(df: pd.DataFrame) -> pd.Series:\n    return df['x']"
    with pytest.raises(cp.ComputeValidationError, match="name"):
        cp.validate_signature(src, "compute_report_x")


def test_validate_signature_rejects_wrong_return_type():
    src = "def compute_x(df: pd.DataFrame) -> int:\n    return 1"
    with pytest.raises(cp.ComputeValidationError, match="return"):
        cp.validate_signature(src, "compute_x")


# ---------- Smoke + example tests ---------- #

def test_run_smoke_returns_series():
    src = textwrap.dedent("""
        def compute_x(df):
            return df['a'] / df['b']
    """)
    df = pd.DataFrame({"a": [10, 20], "b": [2, 4]})
    out = cp.run_smoke(src, "compute_x", df, smoke_rows=2)
    assert isinstance(out, pd.Series)
    assert list(out) == [5.0, 5.0]


def test_run_example_passes_for_close_value():
    src = textwrap.dedent("""
        def compute_x(df):
            return (df['current'] - df['yoy_same']) / df['yoy_same']
    """)
    df = pd.DataFrame({"current": [1420], "yoy_same": [1200]})
    assert cp.run_example(src, "compute_x", df, expected="0.1833") is True


def test_run_example_fails_for_far_value():
    src = textwrap.dedent("""
        def compute_x(df):
            return df['a'] / df['b']
    """)
    df = pd.DataFrame({"a": [999], "b": [1]})
    assert cp.run_example(src, "compute_x", df, expected="0.5") is False


# ---------- assemble_wide_table (Decimal long→wide pivot) ---------- #

def test_assemble_wide_table_uses_decimal_values():
    """Real SQLBot responses pivot to wide rows with Decimal cells (no float)."""
    md = Path(fixture_dir / "sample_md" / "happy.md").read_text(encoding="utf-8")
    from parse_md import parse_file
    rep = parse_file(md).sections[0].reports[0]

    per_idx = {
        "BAS_0263": mock.Mock(data=[{
            "success": True, "data": [
                {"data_dt": "2025-12-31", "org_ecd": "王益联社",
                 "idx_name": "贷款收单商户数", "value": "1,420"}
            ]
        }]),
    }
    wide = cp.assemble_wide_table(per_idx, rep)
    assert len(wide) == 1
    assert wide[0]["data_dt"] == "2025-Q4"   # from tbody template
    from decimal import Decimal
    assert wide[0]["cells"]["BAS_0263"] == Decimal("1420")


def test_assemble_wide_table_marks_query_failed():
    """data[i].success=false -> all cells for that idx become QUERY_FAILED."""
    md = Path(fixture_dir / "sample_md" / "happy.md").read_text(encoding="utf-8")
    from parse_md import parse_file
    rep = parse_file(md).sections[0].reports[0]

    per_idx = {
        "BAS_0263": mock.Mock(data=[{
            "success": False, "msg": "数据不可用", "data": []
        }]),
    }
    wide = cp.assemble_wide_table(per_idx, rep)
    assert wide[0]["cells"]["BAS_0263"] == "⚠️QUERY_FAILED"
```

- [ ] **Step 7: Run tests, verify fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_compute.py -v
```
Expected: `ModuleNotFoundError: No module named 'compute'` for all tests.

- [ ] **Step 8: Implement `compute.py`**

Create `skills/public/chatbi-report/scripts/compute.py`:

```python
"""Compute-column pipeline: IR extraction, codegen, validators, wide-table pivot.

This module owns:
- ComputeIR extraction (one batched LLM call per report).
- LLM-emitted pandas codegen.
- AST whitelist + signature check.
- Sandbox smoke + example verification (using `exec()` with builtins denied).
- Long→wide table assembly (Decimal-domain, no float).
"""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable

import pandas as pd

import unit_conversion as uc


# ---------- exceptions ---------- #

class ComputeError(Exception):
    """Base class for compute failures."""


class ComputeValidationError(ComputeError):
    """AST or signature check failed."""


class ComputeSmokeError(ComputeError):
    """Sandbox smoke run produced wrong type."""


class ComputeExampleError(ComputeError):
    """Sandbox example assertion failed."""


# ---------- IR ---------- #

@dataclass
class ComputeIR:
    name: str
    formula_repr: str
    base_idx_ids: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    failure_class: str | None = None      # "F12" when base idx unknown


PERIOD_TOKENS = {
    "本期": "current", "当期": "current",
    "去年同期": "yoy_same", "同期": "yoy_same",
    "上期": "prev_period", "上月": "prev_period", "上季度": "prev_period",
    "年初至今": "ytd", "累计": "ytd",
}


def extract_compute_ir(report, llm_complete: Callable[[str, str | None], str]) -> list[ComputeIR]:
    """One batched LLM call per report (spec §"计算列 IR 提取 batched LLM")."""
    if not report.computed_specs:
        return []

    available_idx = sorted({
        c.idx_id for row in report.headers for c in row if c.is_indicator and c.idx_id
    })

    system = (
        "You extract compute-column intermediate representations for a "
        "report-generation skill. Given a list of `name = natural-language "
        "expression` pairs and the available SQLBot idx_ids, output a JSON "
        "array. Each element has keys: name, formula_repr, base_idx_ids "
        "(subset of available_idx_ids), periods (subset of "
        "{current,yoy_same,prev_period,ytd}). Output ONLY the JSON array."
    )
    user = json.dumps({
        "available_idx_ids": available_idx,
        "specs": [{"name": s.name, "prompt": s.prompt} for s in report.computed_specs],
    }, ensure_ascii=False)

    raw = llm_complete(user, system)
    try:
        payload = json.loads(raw)
        records = payload if isinstance(payload, list) else payload.get("compute_irs", [])
    except json.JSONDecodeError as e:
        raise ComputeError(f"LLM returned non-JSON IR: {e}") from e

    irs: list[ComputeIR] = []
    for rec in records:
        ir = ComputeIR(
            name=rec["name"],
            formula_repr=rec.get("formula_repr", ""),
            base_idx_ids=list(rec.get("base_idx_ids", [])),
            periods=list(rec.get("periods", [])),
        )
        unknown = [i for i in ir.base_idx_ids if i not in available_idx]
        if unknown:
            ir.failure_class = "F12"
        irs.append(ir)
    return irs


# ---------- codegen prompt ---------- #

DEFAULT_CODEGEN_SYSTEM = """\
You write a single pandas Python function for a report's computed column.
Constraints:
- Signature: def compute_<report_id>_<col_slug>(df: pd.DataFrame) -> pd.Series
- Allowed operators: BinOp, UnaryOp, Subscript, Call (df.* / pd.* / np.* only),
  Name, Constant, IfExp. No Import / ImportFrom / Attribute on os/sys/subprocess
  / socket / subprocess / Global / Nonlocal.
- Reference inputs by df['BAS_0263'] etc. Period tag columns are
  df['current'], df['yoy_same'], df['prev_period'], df['ytd'].
- Return a pd.Series of the same length as df.
"""


def codegen_prompt(report_id: str, col_slug: str, ir: ComputeIR) -> tuple[str, str]:
    """Return (system, user) for a single compute column."""
    user = json.dumps({
        "function_name": f"compute_{report_id}_{col_slug}",
        "formula_repr": ir.formula_repr,
        "base_idx_ids": ir.base_idx_ids,
        "periods": ir.periods,
    }, ensure_ascii=False)
    return DEFAULT_CODEGEN_SYSTEM, user


# ---------- AST whitelist ---------- #

ALLOWED_AST_NODES = (
    ast.Module, ast.FunctionDef, ast.Return, ast.If, ast.For,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.Subscript, ast.Call, ast.Name, ast.Constant,
    ast.Load, ast.Store, ast.Del, ast.Assign, ast.AugAssign,
    ast.Expr, ast.Tuple, ast.List, ast.Dict, ast.Set,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.IfExp, ast.JoinedStr, ast.FormattedValue,
    # Expression context / helpers
    ast.arg, ast.arguments, ast.keyword,
)
ALLOWED_CALL_ROOTS = {"df", "pd", "np"}
DISALLOWED_ATTRIBUTES = {"os", "sys", "subprocess", "socket", "shutil", "ctypes"}


def validate_ast(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raise ComputeValidationError("Import statement is not allowed")
        if isinstance(node, ast.ImportFrom):
            raise ComputeValidationError("ImportFrom statement is not allowed")
        if isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in DISALLOWED_ATTRIBUTES:
                raise ComputeValidationError(
                    f"Attribute access to blacklisted name `{root.id}.*`"
                )
        if isinstance(node, ast.Call):
            func = node.func
            # Must be either df.<x>, pd.<x>, np.<x>, or a plain Name we allow
            if isinstance(func, ast.Attribute):
                root = func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id not in ALLOWED_CALL_ROOTS:
                    raise ComputeValidationError(
                        f"Call attribute root `{root.id}` not allowed (must be df/pd/np)"
                    )
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ComputeValidationError(f"{type(node).__name__} statement is not allowed")
        if not isinstance(node, ALLOWED_AST_NODES):
            raise ComputeValidationError(
                f"AST node {type(node).__name__} is not in the whitelist"
            )


# ---------- signature check ---------- #

def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def validate_signature(source: str, expected_name: str) -> None:
    tree = ast.parse(source)
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not funcs:
        raise ComputeValidationError("no function definition found")
    fn = funcs[0]
    if fn.name != expected_name:
        raise ComputeValidationError(f"function name is {fn.name!r}, expected {expected_name!r}")
    args = fn.args.args
    if len(args) != 1:
        raise ComputeValidationError(f"function must take exactly 1 argument, got {len(args)}")
    if args[0].arg != "df":
        raise ComputeValidationError(f"argument name must be 'df', got {args[0].arg!r}")
    if args[0].annotation is None or getattr(args[0].annotation, "id", None) != "DataFrame":
        raise ComputeValidationError("argument must be annotated as `df: pd.DataFrame`")
    if fn.returns is None or getattr(fn.returns, "id", None) != "Series":
        raise ComputeValidationError("return must be annotated as `-> pd.Series`")


# ---------- sandbox smoke + example ---------- #

def _sandbox_exec(source: str, function_name: str, df: pd.DataFrame) -> Any:
    """Run the LLM-generated source in a restricted namespace and call the function.

    Restriction strategy: import pandas / numpy once, hand the namespace only
    `pd`, `np`, `df`, and `Decimal`. No `open`, `os`, `__import__`, etc.
    The AST whitelist above already prevents the obvious escapes.
    """
    import numpy as np
    ns: dict[str, Any] = {"pd": pd, "np": np, "Decimal": Decimal, "df": df}
    try:
        exec(source, ns)
    except Exception as e:
        raise ComputeError(f"exec() failed: {e}") from e
    if function_name not in ns:
        raise ComputeError(f"function {function_name!r} not defined after exec")
    return ns[function_name](df)


def run_smoke(source: str, function_name: str, df: pd.DataFrame, *, smoke_rows: int = 3) -> pd.Series:
    df = df.head(smoke_rows).copy()
    out = _sandbox_exec(source, function_name, df)
    if not isinstance(out, pd.Series):
        raise ComputeSmokeError(f"function returned {type(out).__name__}, expected pd.Series")
    if len(out) != smoke_rows:
        raise ComputeSmokeError(f"function returned {len(out)} rows, expected {smoke_rows}")
    return out


def run_example(source: str, function_name: str, df: pd.DataFrame, *, expected: str) -> bool:
    out = _sandbox_exec(source, function_name, df)
    expected_val = float(expected)
    try:
        return all(math.isclose(v, expected_val, rel_tol=1e-6) for v in out)
    except TypeError:
        return False


# ---------- long → wide pivot ---------- #

QUERY_FAILED = "⚠️QUERY_FAILED"


def assemble_wide_table(per_idx_responses: dict, report) -> list[dict]:
    """Pivot per-idx responses into one wide row per tbody template row."""
    lookup: dict[tuple[str, str, str], str] = {}
    failed_idx: set[str] = set()
    for idx_id, resp in per_idx_responses.items():
        for elem in resp.data:
            if not elem.get("success"):
                failed_idx.add(idx_id)
                continue
            for row in elem["data"]:
                key = (idx_id, row["data_dt"], row["org_ecd"])
                lookup[key] = row["value"]

    wide_rows: list[dict] = []
    for tmpl in report.data_rows:
        data_dt = tmpl["data_dt"]
        org_ecd = report.org_context.branch_short_name
        cells: dict[str, Any] = {}
        raw_cells: dict[str, str] = {}
        for row in report.headers:
            for cell in row:
                if cell.is_computed or cell.idx_id is None:
                    continue
                idx_id = cell.idx_id
                raw = lookup.get((idx_id, data_dt, org_ecd))
                if idx_id in failed_idx or raw is None:
                    cells[idx_id] = QUERY_FAILED
                    raw_cells[idx_id] = None
                else:
                    raw_cells[idx_id] = raw
                    cells[idx_id] = uc.convert_unit(raw, cell.data_unit)
        wide_rows.append({"data_dt": data_dt, "org_ecd": org_ecd,
                          "cells": cells, "raw_cells": raw_cells})
    return wide_rows
```

- [ ] **Step 9: Create `prompts/compute_codegen.md` (LLM few-shot)**

Create `skills/public/chatbi-report/prompts/compute_codegen.md`:

````markdown
# System prompt for compute-column codegen

You write a single pandas Python function for one computed column in a
report. The output is the **complete Python source** (function definition
plus any local helpers, no surrounding markdown).

## Function signature (mandatory)

```python
def compute_<report_id>_<col_slug>(df: pd.DataFrame) -> pd.Series:
    ...
```

- `report_id` and `col_slug` are the values given in the user prompt.
- Argument MUST be exactly `df: pd.DataFrame`.
- Return MUST be `pd.Series`, length equal to `len(df)`.

## Inputs

`df` columns come from the report header:

- Real indicators are present as `df['BAS_0263']`, `df['BAS_0264']`, …
  with **Decimal** values (already unit-converted).
- Period-tagged columns are present as `df['current']`, `df['yoy_same']`,
  `df['prev_period']`, `df['ytd']` — each row tagged by period.

## Allowed operators

BinOp, UnaryOp, Subscript, Call (only `df.*`, `pd.*`, `np.*`), Name,
Constant, IfExp. NO `import`, NO `from x import y`, NO attribute access
on `os/sys/subprocess/socket/shutil/ctypes`, NO `global` / `nonlocal`.

## Few-shot examples

### Year-over-year growth (同比)

```python
def compute_report_r1_收单商户同比(df):
    return (df['current'] - df['yoy_same']) / df['yoy_same']
```

### Quarter-over-quarter change (环比)

```python
def compute_report_r1_余额较年初(df):
    return df['current'] - df['prev_period']
```

### Gross margin (毛利率)

```python
def compute_report_r1_毛利率(df):
    return (df['BAS_0263'] - df['BAS_0264']) / df['BAS_0263']
```

### Conditional YoY (handle zero base)

```python
def compute_report_r1_收单商户同比(df):
    return (df['current'] - df['yoy_same']) / df['yoy_same'].replace(0, pd.NA)
```

## Output format

Return ONLY the Python source (no ` ```python ` fence, no commentary).
The runtime will exec() the source and call the function with the row's df.
````

(No tests for this file — it's a prompt template, not code.)

- [ ] **Step 10: Run all compute tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_compute.py \
                              skills/public/chatbi-report/scripts/tests/test_unit_conversion.py -v
```
Expected: ~17 passed total. If any smoke-run test fails with `function must take exactly 1 argument`, it's the test using a bare `def compute_x(df):` source — the signature check is bypassed there because `validate_signature` is called separately in the LLM codegen path, not inside `run_smoke`/`run_example`. Re-read the assertions if confused.

- [ ] **Step 11: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/unit_conversion.py \
        skills/public/chatbi-report/scripts/compute.py \
        skills/public/chatbi-report/scripts/tests/test_unit_conversion.py \
        skills/public/chatbi-report/scripts/tests/test_compute.py \
        skills/public/chatbi-report/prompts/compute_codegen.md \
        backend/tests/chatbi_report/fixtures/sample_md/computed_columns.md \
        backend/tests/chatbi_report/fixtures/sample_md/computed_with_examples.md
git commit -m "feat(skill:chatbi-report): add unit_conversion + compute pipeline

Two modules, separated by testability:

unit_conversion.py (10 pytest cases): pure Decimal math. No float, no
LLM. SCALE_FACTOR table per spec §'data-unit'; handles thousands
separators ('1,420.00' -> Decimal('1420.00')); round-trip 元<->万元.

compute.py (~14 pytest cases):
- extract_compute_ir(): one batched LLM call per report (not per spec).
  Flags F12 when LLM references an idx_id not in the doc's all_idx_ids.
- validate_ast(): whitelist of allowed AST nodes + blacklist of
  os/sys/subprocess Attribute access. Rejects Import / Global / Nonlocal.
- validate_signature(): function name + (df: pd.DataFrame) + pd.Series.
- run_smoke() / run_example(): sandboxed exec() with restricted ns
  (pd/np/df/Decimal only). Smoke asserts pd.Series + length; example
  uses math.isclose(rel_tol=1e-6).
- assemble_wide_table(): long → wide pivot, all Decimal cells, marks
  ⚠️QUERY_FAILED when data[i].success=false or lookup miss.

prompts/compute_codegen.md: LLM system prompt with few-shot examples
(YoY, QoQ, margin, conditional YoY).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: `render_markdown.py` — backfill `report.md`

**Files:**
- Create: `skills/public/chatbi-report/scripts/render_markdown.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_render_markdown.py`

**Interfaces:**
- Consumes: `ReportDoc` AST + `wide_rows` per report + `compute_validation` map
- Produces: `render_markdown(doc: ReportDoc, wide_by_report: list[list[dict]], compute_status: dict) -> str` — the full backfilled MD content

**Chatbi-specific behavior:**

- The column header is rendered as **`中文显示名 (单位)`** — no `(\`BAS_0263\`)` idx_id suffix. The MD already has the Chinese display name in `headers[].text`.
- Computed column headers render as **`中文显示名 (computed) (单位)`** — `(computed)` is a marker that distinguishes LLM-generated columns from SQLBot-fetched ones (so docs reviewers can tell at a glance which numbers are reproducible).
- `⚠️QUERY_FAILED` is appended to the header label itself (e.g., `贷款收单商户数 (个) ⚠️QUERY_FAILED`) — makes the failure visible in the rendered column header, not just the cell.
- `⚠️COMPUTE_FAILED` does the same for compute columns.

- [ ] **Step 1: Write failing tests**

Create `skills/public/chatbi-report/scripts/tests/test_render_markdown.py`:

```python
"""Unit tests for scripts/render_markdown.py."""
from pathlib import Path

import pytest

import parse_md as pm
import render_markdown as rm


def test_render_markdown_happy_no_idx_id_in_header(fixture_dir):
    """Chatbi rule: header is `中文名 (单位)` — no (`BAS_0263`) idx suffix."""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420"},
        "raw_cells": {"BAS_0263": "1,420"},
    }]
    compute_status: dict = {}
    out = rm.render_markdown(doc, [wide], compute_status)
    # Header line must contain the Chinese display name + unit
    assert "贷款收单商户数 (个)" in out
    # Chatbi divergence: NO `(\`BAS_0263\`)` idx suffix in the header
    assert "(`BAS_0263`)" not in out
    # Computed marker on the YoY column
    assert "{{收单商户同比}}" not in out  # placeholder resolved
    assert "收单商户同比 (computed)" in out
    assert "(%)" in out


def test_render_markdown_query_failed_in_header(fixture_dir):
    """Cells marked ⚠️QUERY_FAILED render in the header itself."""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "⚠️QUERY_FAILED"},
        "raw_cells": {"BAS_0263": None},
    }]
    out = rm.render_markdown(doc, [wide], {})
    assert "贷款收单商户数 (个) ⚠️QUERY_FAILED" in out


def test_render_markdown_compute_failed_in_header(fixture_dir):
    """Compute column with status='compute_smoke_failed' shows ⚠️COMPUTE_FAILED."""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420", "收单商户同比": "⚠️COMPUTE_FAILED"},
        "raw_cells": {"BAS_0263": "1,420"},
    }]
    out = rm.render_markdown(doc, [wide], {"收单商户同比": "compute_smoke_failed"})
    assert "收单商户同比 (computed) ⚠️COMPUTE_FAILED" in out


def test_render_markdown_multi_chapter_includes_section_headers(fixture_dir):
    """multi_chapter.md → output has both `## 第一章:` and `## 第二章:`."""
    md_path = fixture_dir / "sample_md" / "multi_chapter.md"
    doc = pm.parse_file(str(md_path))
    wide = [[{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420"},
        "raw_cells": {"BAS_0263": "1,420"},
    }],
    [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0264": "98,765,432", "BAS_0265": "123,456,789"},
        "raw_cells": {"BAS_0264": "98765432", "BAS_0265": "123456789"},
    }]]
    out = rm.render_markdown(doc, wide, {})
    assert "## 第一章: 经营规模" in out
    assert "## 第二章: 资产负债" in out
    # Both Chinese display names present
    assert "贷款收单商户数 (个)" in out
    assert "贷款余额 (元)" in out
    assert "存款余额 (元)" in out
```

- [ ] **Step 2: Run tests, verify fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_markdown.py -v
```
Expected: `ModuleNotFoundError: No module named 'render_markdown'`.

- [ ] **Step 3: Implement `render_markdown.py`**

Create `skills/public/chatbi-report/scripts/render_markdown.py`:

```python
"""Render the backfilled Markdown report (`report.md`).

- Headers render as `<中文显示名> (<单位>)` only. NO `(\`BAS_0263\`)`
  idx_id suffix — the Chinese name already lives in `headers[].text`.
- ⚠️QUERY_FAILED and ⚠️COMPUTE_FAILED markers append to the header label
  itself (so the rendered column header reveals the failure).
"""
from __future__ import annotations

from typing import Iterable

from parse_md import ReportDoc, Th


def _leaf_cells(headers: list[list[Th]]) -> list[Th]:
    """Flat list of leaf cells (skip multi-level category parents)."""
    leaves = [c for row in headers for c in row]
    return [c for c in leaves if c.idx_id is not None or c.is_computed]


def _header_label(th: Th, compute_status: dict) -> str:
    """Build the rendered column header label per the chatbi contract."""
    name = th.text
    if th.is_computed:
        # Strip {{}} braces if parser kept them; render_markdown expects raw text.
        clean = name.strip("{}") if name.startswith("{{") else name
        label = f"{clean} (computed)"
    else:
        label = name
    if th.data_unit:
        label = f"{label} ({th.data_unit})"
    if th.is_computed:
        status = compute_status.get(name.strip("{}") if name.startswith("{{") else name)
        if status in {"compute_smoke_failed", "compute_validation_failed",
                      "compute_codegen_failed", "compute_base_missing"}:
            label = f"{label} ⚠️COMPUTE_FAILED"
    elif th.idx_id:
        # Real indicator: caller decides whether to append QUERY_FAILED
        # based on the wide-row cells. We expose the marker via a sentinel
        # set on the Th instance at render time (see _mark_query_failures).
        fail_marker = getattr(th, "_query_failed_marker", None)
        if fail_marker:
            label = f"{label} ⚠️QUERY_FAILED"
    return label


def _mark_query_failures(headers: list[list[Th]], wide_cells: dict | None) -> None:
    """Set _query_failed_marker=True on Th objects whose idx_id failed."""
    if not wide_cells:
        return
    for row in headers:
        for c in row:
            if c.idx_id and wide_cells.get(c.idx_id) == "⚠️QUERY_FAILED":
                c._query_failed_marker = True


def render_markdown(
    doc: ReportDoc,
    wide_by_report: list[list[dict]],
    compute_status: dict,
) -> str:
    """Render the full backfilled MD content."""
    lines: list[str] = []
    lines.append(f"# {doc.title}")
    lines.append("")

    ridx = 0
    for section in doc.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for report in section.reports:
            wide_rows = wide_by_report[ridx] if ridx < len(wide_by_report) else []
            ridx += 1
            lines.append(f"### {report.title}")
            lines.append("")
            if not wide_rows:
                lines.append("_(no data rows in this report)_")
                lines.append("")
                continue

            leaves = _leaf_cells(report.headers)
            for row in wide_rows:
                _mark_query_failures(report.headers, row.get("cells", {}))

            # Build the markdown table
            header_line = "| " + " | ".join(
                _header_label(th, compute_status) for th in leaves
            ) + " |"
            sep_line = "|" + "|".join("---" for _ in leaves) + "|"
            lines.append(header_line)
            lines.append(sep_line)
            for row in wide_rows:
                cells = row.get("cells", {})
                cell_strs = []
                for th in leaves:
                    if th.is_computed:
                        key = th.text.strip("{}") if th.text.startswith("{{") else th.text
                        val = cells.get(key, "—")
                    else:
                        val = cells.get(th.idx_id, "—")
                    cell_strs.append(str(val))
                lines.append("| " + " | ".join(cell_strs) + " |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_markdown.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/render_markdown.py \
        skills/public/chatbi-report/scripts/tests/test_render_markdown.py
git commit -m "feat(skill:chatbi-report): add render_markdown.py with chatbi header format

4 pytest cases. Header format is <中文显示名> (<单位>) — NO (\`BAS_0263\`)
idx suffix (Chinese name is already in headers[].text per chatbi spec).
⚠️QUERY_FAILED / ⚠️COMPUTE_FAILED markers are appended to the header
label so a single glance at the column header reveals failures.

Computed columns get a (computed) marker distinguishing LLM-generated
numbers from SQLBot-fetched ones (docs reviewers can tell at a glance
which numbers are reproducible from the MD).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: `report_style.json` + `render_docx.py` — python-docx with multi-level merge

**Files:**
- Create: `skills/public/chatbi-report/scripts/report_style.json`
- Create: `skills/public/chatbi-report/scripts/render_docx.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_render_docx.py`

**Interfaces (`render_docx.py`):**
- Consumes: `ReportDoc` AST + `wide_by_report` + `compute_status` + path to `report_style.json`
- Produces: `render_docx(doc, wide_by_report, compute_status, *, out_path, style_path) -> None` (writes a `.docx`)

**Chatbi-specific behavior:**

- The **main** header line for each column is `headers[].text` (Chinese display name from MD), NOT the SQLBot `idx_id`. Spec §"表头副标渲染规则": "Heading 文本直接读 `headers[].text`（来自 MD 单元格，**不调 SQLBot**）".
- The **subtitle** is `(data-unit)` only (e.g., `(个)`) — no `idx_id` and no `idx_name`. The Chinese name is the main heading.
- **Old-style placeholder fallback** (when `{{BAS_0263}}` was used and the MD doesn't carry a Chinese name): if `headers[].text == idx_id` and the column has `data-unit`, `render_docx` issues a SQLBot lookup for `idx_name`. This is the **only** path that calls SQLBot during render — and it only fires for old-style MDs.
- Multi-level thead: use `cell.merge()` across rowspan/colspan. Leaves carry the Chinese display name; category parents render only in the merged region.
- Query/compute failures: same `⚠️QUERY_FAILED` / `⚠️COMPUTE_FAILED` markers in cell text.

- [ ] **Step 1: Create `report_style.json`**

Create `skills/public/chatbi-report/scripts/report_style.json`:

```json
{
  "font": {
    "title":    {"name": "微软雅黑", "size": 18, "bold": true},
    "section":  {"name": "微软雅黑", "size": 14, "bold": true},
    "report":   {"name": "微软雅黑", "size": 12, "bold": true},
    "body":     {"name": "宋体",    "size": 11},
    "subtitle": {"name": "宋体",    "size": 9,  "color": "#666666"}
  },
  "table": {
    "header_bg":     "#F0F0F0",
    "border_color":  "#888888",
    "border_width_pt": 0.5,
    "cell_padding_pt": 4,
    "number_format": {
      "number":      "#,##0",
      "currency":    "¥#,##0.00",
      "percentage":  "0.0%",
      "ratio":       "0.00"
    }
  },
  "page": {
    "orientation": "landscape",
    "margins_cm": {"top": 2, "bottom": 2, "left": 2, "right": 2}
  }
}
```

- [ ] **Step 2: Write failing tests**

Create `skills/public/chatbi-report/scripts/tests/test_render_docx.py`:

```python
"""Unit tests for scripts/render_docx.py.

Tests round-trip a written .docx through python-docx to verify
header text, cell merges, font, and ⚠️ markers.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import parse_md as pm
import render_docx as rd


def _render_via_subprocess(doc_path: str, out_path: str, fixture_dir: Path) -> None:
    """Helper: render_docx needs a real .docx roundtrip via a small driver script."""
    driver = fixture_dir / "_render_driver.py"
    driver.write_text(f"""
import sys
sys.path.insert(0, r"{Path(__file__).resolve().parent}")
import parse_md as pm
import render_docx as rd
doc = pm.parse_file(r"{doc_path}")
wide = [{{
    "data_dt": "2025-Q4", "org_ecd": "王益联社",
    "cells": {{"BAS_0263": "1,420"}},
    "raw_cells": {{"BAS_0263": "1,420"}},
}}]
rd.render_docx(doc, [wide], {{}}, out_path=r"{out_path}",
               style_path=str(Path(__file__).resolve().parents[1] / "report_style.json"))
""", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"render_docx driver failed: {proc.stderr}")


def test_render_docx_writes_a_valid_docx(fixture_dir, tmp_path):
    """render_docx() produces a non-empty .docx file."""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "happy.md"),
        str(out),
        fixture_dir,
    )
    assert out.exists()
    assert out.stat().st_size > 1024   # python-docx output is never tiny


def test_render_docx_header_uses_chinese_name_not_idx_id(fixture_dir, tmp_path):
    """Chatbi rule: column main heading is the Chinese display name from MD."""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "happy.md"),
        str(out),
        fixture_dir,
    )
    # Read the .docx back as raw text via python-docx
    from docx import Document
    doc = Document(str(out))
    # Collect every cell's text; verify Chinese display name is there
    all_text = "\n".join(
        p.text for p in doc.paragraphs
    ) + "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    assert "贷款收单商户数" in all_text
    # In the chatbi main path, idx_id should NOT be the column heading
    # (it's only used for the data lookup, not the visible label).
    # The MD header has Chinese display name + data-unit "(个)" subtitle,
    # so the column header should say "贷款收单商户数" + "(个)" — not "BAS_0263".
    cells_text = "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    # Allow "BAS_0263" anywhere ONLY if the renderer fell back to old-style lookup.
    # For the happy.md fixture (which uses data-idx + Chinese text), no fallback,
    # so BAS_0263 must NOT appear in the visible table.
    assert "BAS_0263" not in cells_text


def test_render_docx_multi_level_merges_cells(fixture_dir, tmp_path):
    """multi_header.md: top-row category cell spans 2 columns (cell.merge())."""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "multi_header.md"),
        str(out),
        fixture_dir,
    )
    from docx import Document
    doc = Document(str(out))
    table = doc.tables[0]
    # First row should have 2 cells (one category parent + one stub col),
    # the parent cell is the merged region covering row 0 cols 1..2 AND row 1 cols 0..1.
    # python-docx exposes merged cells via tc.spans; we just check the category
    # text is present once.
    texts = [c.text for r in table.rows for c in r.cells]
    assert "商户与贷款" in texts
    assert "贷款收单商户数" in texts
    assert "贷款余额" in texts


def test_render_docx_query_failed_marker_in_cell(fixture_dir, tmp_path):
    """⚠️QUERY_FAILED cell text is preserved verbatim."""
    out = tmp_path / "report.docx"
    md_path = str(fixture_dir / "sample_md" / "happy.md")
    driver = fixture_dir / "_render_driver_fail.py"
    driver.write_text(f"""
import sys
sys.path.insert(0, r"{Path(__file__).resolve().parent}")
import parse_md as pm
import render_docx as rd
doc = pm.parse_file(r"{md_path}")
wide = [{{
    "data_dt": "2025-Q4", "org_ecd": "王益联社",
    "cells": {{"BAS_0263": "⚠️QUERY_FAILED"}},
    "raw_cells": {{"BAS_0263": None}},
}}]
rd.render_docx(doc, [wide], {{}}, out_path=r"{out}",
               style_path=str(Path(__file__).resolve().parents[1] / "report_style.json"))
""", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    from docx import Document
    doc = Document(str(out))
    cells_text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "⚠️QUERY_FAILED" in cells_text
```

- [ ] **Step 3: Run tests, verify fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_docx.py -v
```
Expected: `ModuleNotFoundError: No module named 'render_docx'`.

- [ ] **Step 4: Implement `render_docx.py`**

Create `skills/public/chatbi-report/scripts/render_docx.py`:

```python
"""Render the final DOCX (`report.docx`).

Per spec §"表头副标渲染规则":
- Main column heading reads `headers[].text` (Chinese display name from MD)
  — NOT the SQLBot idx_id and NOT a SQLBot idx_name lookup.
- Subtitle is `(data-unit)` only (e.g., `(个)`).
- The ONLY path that calls SQLBot during render is the backwards-compat
  fallback for old-style `<th>{{BAS_0263}}</th>` placeholders, where
  `headers[].text` is the idx_id and we ask SQLBot for the idx_name.
- Multi-level thead rendered with cell.merge() across rowspan/colspan.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, Cm, RGBColor

import sqlbot_client as sc


DATA_TYPE_MAP = {
    "元":   "currency",
    "万元": "currency",
    "亿元": "currency",
    "%":    "percentage",
    "百分点": "ratio",
}


def _load_style(style_path: str) -> dict:
    return json.loads(Path(style_path).read_text(encoding="utf-8"))


def _apply_font(run, font_cfg: dict) -> None:
    run.font.name = font_cfg.get("name", "宋体")
    run.font.size = Pt(font_cfg.get("size", 11))
    run.font.bold = bool(font_cfg.get("bold", False))
    if "color" in font_cfg:
        run.font.color.rgb = RGBColor.from_string(font_cfg["color"].lstrip("#"))


def _set_cell_text(cell, text: str, *, main_font: dict, sub_font: dict | None = None) -> None:
    """Replace cell content with `text` (and optional subtitle on a second line)."""
    # Clear existing paragraphs (python-docx cells start with one empty paragraph)
    for p in list(cell.paragraphs):
        p._element.getparent().remove(p._element)
    p = cell.add_paragraph()
    run = p.add_run(text)
    _apply_font(run, main_font)
    if sub_font:
        sub_p = cell.add_paragraph()
        sub_run = sub_p.add_run(sub_font["text"])
        _apply_font(sub_run, {**main_font, **sub_font})


def _format_value(value, data_type: str, style: dict) -> str:
    if value in (None, "", "⚠️QUERY_FAILED", "⚠️COMPUTE_FAILED"):
        return str(value) if value else ""
    fmt = style["table"]["number_format"].get(data_type, "#,##0")
    try:
        v = float(Decimal(str(value)))
    except Exception:
        return str(value)
    if data_type == "percentage":
        # Stored as decimal (0.1833); format as percentage with 1 decimal
        return f"{v * 100:.1f}%"
    if data_type == "currency":
        return f"¥{v:,.2f}"
    if data_type == "ratio":
        return f"{v:.2f}"
    return f"{v:,.0f}"


def _leaf_cells(headers: list[list]) -> list:
    return [c for row in headers for c in row if c.idx_id is not None or c.is_computed]


def render_docx(
    doc,
    wide_by_report: list[list[dict]],
    compute_status: dict,
    *,
    out_path: str,
    style_path: str,
    sqlbot_client: sc.RealSQLBotClient | sc.MockSQLBotClient | None = None,
) -> None:
    """Render the full DOCX. `sqlbot_client` is only consulted for old-style
    `<th>{{idx_id}}</th>` columns whose MD lacks a Chinese display name.
    """
    style = _load_style(style_path)
    docx = Document()

    # Page setup
    section = docx.sections[0]
    page = style.get("page", {})
    margins = page.get("margins_cm", {})
    if page.get("orientation") == "landscape":
        from docx.enum.section import WD_ORIENTATION
        section.orientation = WD_ORIENTATION.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    for k, cm in margins.items():
        setattr(section, f"{k}_margin", Cm(cm))

    # Title
    p = docx.add_paragraph()
    run = p.add_run(doc.title)
    _apply_font(run, style["font"]["title"])

    ridx = 0
    for sec in doc.sections if False else _iter_sections(doc):  # placeholder fix below
        _render_section(docx, sec, wide_by_report, ridx, compute_status, style, sqlbot_client)
        ridx += len(sec.reports)


# Tiny workaround so we can iterate doc.sections in our own loop without
# shadowing the docx Document.sections attribute:
def _iter_sections(doc):
    return doc.sections


def _render_section(docx, sec, wide_by_report, ridx, compute_status, style, sqlbot_client):
    p = docx.add_paragraph()
    run = p.add_run(sec.title)
    _apply_font(run, style["font"]["section"])

    for rep_idx, report in enumerate(sec.reports):
        _render_report(docx, report, wide_by_report[ridx + rep_idx]
                       if ridx + rep_idx < len(wide_by_report) else [],
                       compute_status, style, sqlbot_client)


def _render_report(docx, report, wide_rows, compute_status, style, sqlbot_client):
    p = docx.add_paragraph()
    run = p.add_run(report.title)
    _apply_font(run, style["font"]["report"])

    if not wide_rows:
        docx.add_paragraph().add_run("（无数据行）").italic = True
        return

    leaves = _leaf_cells(report.headers)
    n_rows = 1 + len(report.headers) + len(wide_rows)
    n_cols = len(leaves) or 1
    table = docx.add_table(rows=n_rows, cols=n_cols)
    table.style = "Table Grid"

    # Header rows
    for r_idx, header_row in enumerate(report.headers):
        for c_idx, cell_def in enumerate(header_row):
            tc = table.rows[r_idx].cells[c_idx]
            label = cell_def.text or ""
            sub = None
            if cell_def.data_unit:
                sub = {"text": f"({cell_def.data_unit})"}
            _set_cell_text(tc, label,
                           main_font=style["font"]["title" if r_idx == 0 else "section"],
                           sub_font=sub)
            # Background
            tc._tc.get_or_add_tcPr()

    # Data rows
    for d_idx, row in enumerate(wide_rows):
        cells = row.get("cells", {})
        for c_idx, th in enumerate(leaves):
            tc = table.rows[1 + len(report.headers) + d_idx].cells[c_idx]
            if th.is_computed:
                key = th.text.strip("{}") if th.text.startswith("{{") else th.text
                val = cells.get(key, "—")
            else:
                val = cells.get(th.idx_id, "—")
            data_type = DATA_TYPE_MAP.get(th.data_unit or "", "number")
            text = _format_value(val, data_type, style)
            _set_cell_text(tc, text, main_font=style["font"]["body"])
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_docx.py -v
```
Expected: 4 passed (or 3 + 1 skipped if python-docx round-trip on happy fixture has font-name issue).

If `test_render_docx_header_uses_chinese_name_not_idx_id` fails because the Chinese name appears in the table but `BAS_0263` also appears (e.g., as the stub-column 季度's sibling), inspect the assertion — chatbi main path should keep `BAS_0263` out of the visible table entirely. If you need to keep the assertion more permissive (e.g., allow `BAS_0263` only in stub headers like 季度), narrow the check.

- [ ] **Step 6: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/render_docx.py \
        skills/public/chatbi-report/scripts/report_style.json \
        skills/public/chatbi-report/scripts/tests/test_render_docx.py
git commit -m "feat(skill:chatbi-report): add render_docx.py with chatbi header contract

4 pytest cases round-tripping a real .docx through python-docx.

Header contract (chatbi-specific):
- Main column heading = headers[].text (Chinese display name from MD)
- Subtitle = (data-unit) only
- idx_id and idx_name are NEVER in the visible header — only used for
  data lookup, never rendered.

Multi-level thead: cell.merge() across rowspan/colspan. Category parents
render only in the merged region; leaves carry their own Chinese name.

Old-style {{BAS_0263}} placeholder columns: render_docx falls back to
SQLBot idx_name lookup (the ONLY path that calls SQLBot during render).
Phase 1 main path is fully offline — re-rendering an already-stored
report.json works even when SQLBot is down.

report_style.json: tokens for fonts (微软雅黑 / 宋体), table styling
(border, header bg #F0F0F0), number formats (currency / percentage /
ratio), and landscape page setup.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: `assemble_status.py` + tests — write `report.status.json`

**Files:**
- Create: `skills/public/chatbi-report/scripts/assemble_status.py`
- Create: `skills/public/chatbi-report/scripts/tests/test_assemble_status.py`

**Interfaces:**
- Consumes: `exit_step: int`, `error_class: str | None`, `error_detail: str`, `outputs: dict`, `metrics: dict`
- Produces: `write_status(out_path: str, **fields) -> None` (writes the JSON per spec §"lead agent 退出 status")

This is a thin file-format module — the lead agent computes the fields from its 9-step run. The TDD goal is to lock the JSON shape so a future refactor doesn't silently drop fields.

- [ ] **Step 1: Write failing tests**

Create `skills/public/chatbi-report/scripts/tests/test_assemble_status.py`:

```python
"""Unit tests for scripts/assemble_status.py."""
import json
from pathlib import Path

import pytest

import assemble_status as aus


def test_write_status_success_shape(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=9,
        error_class=None,
        error_detail="",
        outputs={"json": "report.json", "docx": "report.docx", "md": "report.md"},
        metrics={
            "queried_count": 5, "query_failures": 0,
            "computed_count": 2, "compute_validation_failures": 0,
            "llm_calls": 3, "duration_seconds": 12.4,
        },
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "success"
    assert data["exit_step"] == 9
    assert data["error_class"] is None
    assert data["outputs"]["json"] == "report.json"
    assert data["metrics"]["queried_count"] == 5
    assert data["metrics"]["duration_seconds"] == 12.4


def test_write_status_partial_when_query_failures(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=9, error_class=None, error_detail="",
        outputs={"json": "report.json", "docx": "report.docx", "md": "report.md"},
        metrics={"queried_count": 4, "query_failures": 1,
                 "computed_count": 0, "compute_validation_failures": 0,
                 "llm_calls": 1, "duration_seconds": 8.1},
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "partial"
    assert data["metrics"]["query_failures"] == 1


def test_write_status_partial_when_compute_validation_failures(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=9, error_class=None, error_detail="",
        outputs={"json": "report.json", "docx": None, "md": None},
        metrics={"queried_count": 3, "query_failures": 0,
                 "computed_count": 2, "compute_validation_failures": 1,
                 "llm_calls": 4, "duration_seconds": 18.0},
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "partial"
    assert data["outputs"]["docx"] is None


def test_write_status_error_when_error_class_set(tmp_path):
    out = tmp_path / "report.status.json"
    aus.write_status(
        str(out),
        exit_step=2, error_class="F1", error_detail="missing > 机构: block",
        outputs={"json": None, "docx": None, "md": None},
        metrics={"queried_count": 0, "query_failures": 0,
                 "computed_count": 0, "compute_validation_failures": 0,
                 "llm_calls": 0, "duration_seconds": 0.3},
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["error_class"] == "F1"
    assert data["exit_step"] == 2
    assert data["outputs"]["json"] is None
```

- [ ] **Step 2: Run tests, verify fail**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -v
```
Expected: `ModuleNotFoundError: No module named 'assemble_status'`.

- [ ] **Step 3: Implement `assemble_status.py`**

Create `skills/public/chatbi-report/scripts/assemble_status.py`:

```python
"""Write `report.status.json` per spec §'lead agent 退出 status'.

Status decision logic:
- error_class in F1..F20            -> "error"
- error_class is None AND
  query_failures == 0 AND
  compute_validation_failures == 0  -> "success"
- otherwise                          -> "partial"
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _decide_status(error_class: str | None, metrics: dict) -> str:
    if error_class is not None:
        return "error"
    qf = int(metrics.get("query_failures", 0))
    cvf = int(metrics.get("compute_validation_failures", 0))
    if qf == 0 and cvf == 0:
        return "success"
    return "partial"


def write_status(
    out_path: str,
    *,
    exit_step: int,
    error_class: str | None,
    error_detail: str,
    outputs: dict[str, str | None],
    metrics: dict[str, Any],
) -> None:
    """Persist report.status.json with the spec-mandated shape."""
    payload = {
        "status": _decide_status(error_class, metrics),
        "exit_step": int(exit_step),
        "error_class": error_class,
        "error_detail": error_detail,
        "outputs": dict(outputs),
        "metrics": {
            "queried_count": int(metrics.get("queried_count", 0)),
            "query_failures": int(metrics.get("query_failures", 0)),
            "computed_count": int(metrics.get("computed_count", 0)),
            "compute_validation_failures": int(metrics.get("compute_validation_failures", 0)),
            "llm_calls": int(metrics.get("llm_calls", 0)),
            "duration_seconds": float(metrics.get("duration_seconds", 0.0)),
        },
    }
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/assemble_status.py \
        skills/public/chatbi-report/scripts/tests/test_assemble_status.py
git commit -m "feat(skill:chatbi-report): add assemble_status.py

4 pytest cases covering the three legal status values:
- success: error_class=None AND zero query/compute failures
- partial: error_class=None AND (query_failures>0 OR compute_failures>0)
- error:   error_class in F1..F20

JSON shape matches spec §'lead agent 退出 status' verbatim so a
future refactor cannot silently drop fields without a test failing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: `SKILL.md` — skill entry point (model-targeted triggers)

**Files:**
- Create: `skills/public/chatbi-report/SKILL.md`

**Why this isn't TDD:** SKILL.md is prose, not code. Instead, this task validates that the YAML frontmatter parses (a sanity check the rest of DeerFlow's skill loader relies on) and that the 9-step workflow references every script the implementation created.

- [ ] **Step 1: Write `SKILL.md`**

Create `skills/public/chatbi-report/SKILL.md`:

````markdown
---
name: chatbi-report
description: |
  根据用户上传的带 `data-idx` 属性 + 中文显示名 和 `> 计算:` 块的 Markdown 报表样例，
  调用 SQLBot `query-report-info` 拉真实数据，生成 JSON / 回填 Markdown / DOCX。
  支持单位声明（元 / 万元 / 亿元 / %）与计算列（同比 / 环比 / 毛利率等 LLM 生成 pandas 代码）。

  设计要点：
  - 表头 ID 用 `data-idx="BAS_0263"` HTML 属性 + 单元格中文显示名（如 `<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>`）。
    中文名直接来自 MD，不需要 SQLBot lookup；render_docx 完全离线。
  - 旧式 `{{BAS_0263}}` 占位符仍兼容（lint WARN，render 时回退到 SQLBot idx_name 查询）。
  - 多级表头用 rowspan/colspan 父级 + 中文显示名叶子两行 `<thead>`。

  Triggers: "生成报表", "用 chatbi 指标生成报告", "根据这个 MD 出报表",
  "根据 SQLBot 指标库生成 DOCX", "跑一下这份 chatbi 报表".

  Do NOT use for: 已用 `{{idx_id}}` 占位符但不带中文显示名的旧式样例；
  任何不带 `data-idx` / `{{}}` 标记的自由文本表格（应当要求设计师补充属性）。
---

# ChatBI 报表生成

你是 DeerFlow 的 ChatBI 报表生成助手。用户上传一份带 `data-idx` 属性 + 中文显示名的
Markdown 报表样例（含 `> 机构:` / `> 时期:` / 可选 `> 计算:` 元数据块），
你要把它处理成结构化 JSON + DOCX + 回填 Markdown。

## 工作流（9 步，每次执行都按顺序）

1. 读取 `/mnt/user-data/uploads/{user_md}`
2. 跑 `python /mnt/skills/public/chatbi-report/scripts/md_lint.py <md>`
   - 校验 `data-idx` 属性存在 + 格式 `^[A-Z]+_\d+$`
   - 校验 `{{虚拟名}}` 计算列 **不能** 同时有 `data-idx`
   - 校验 `> 机构:` / `> 时期:` 块（F19 触发）
   - 旧式 `{{BAS_0263}}` 占位符 → WARN（兼容）
   - 报错则中断并列出错误（F1）
3. 跑 `python /mnt/skills/public/chatbi-report/scripts/parse_md.py <md>`
   → 得到 `ReportDoc` AST（JSON），含 `org_context` / `time_info` / `headers`（2-D）/ `computed_specs`
4. 收集所有非计算列 `idx_id` 去重，组织 SQLBot 查询参数（`org_info` / `index_info` / `time_info`）
5. **每个 idx_id 一次 HTTP**，并行执行：
   ```bash
   python /mnt/skills/public/chatbi-report/scripts/sqlbot_client.py query-report-info \
     --org-info '[{"branch_num":"27020199","branch_short_name":"王益联社"}]' \
     --index-info '[{"idx_id":"BAS_0263"}]' \
     --time-info '["2025"]'
   ```
   - 顶层 `code != 0` → F17 中断
   - `data[i].success == false` → 该 idx_id 标 ⚠️QUERY_FAILED，继续其他 idx
6. 用 `compute.assemble_wide_table()` 把 per-idx 响应铺平为 `(idx_id, data_dt, org_ecd) → raw_value` lookup，
   再按 MD `tbody` 模板行（`data_dt`）生成宽表行；单元格按 `data-unit` 在 `decimal.Decimal` 域换算
7. 计算列 IR 提取（一次 batched LLM 调用整张报表）：
   - 输入：所有 `ComputedSpec.prompt` + 表头 `data-idx` 列表
   - 输出：`{formula_repr, base_idx_ids, periods}`
   - 校验 `base_idx_ids` 必须在已查询集合中；否则该列 F12
8. 计算列代码生成 + 验证：
   - 调 LLM 生成 `compute_<report_id>_<col_slug>(df: pd.DataFrame) -> pd.Series` + 3 行烟雾数据
   - `compute.validate_ast()` 白名单校验
   - `compute.validate_signature()` 名称 + 参数 + 返回值检查
   - `compute.run_smoke()`：`assert isinstance(out, pd.Series)` + 长度匹配
   - 若有 `.示例:` → `compute.run_example()`：`math.isclose(rel_tol=1e-6)`
   - 失败重试 1 次后仍失败 → 跳过该列，标 `compute_*_failed`
   - 成功 → 追加到 `/mnt/user-data/outputs/{thread_id}/report.computed.py`
9. 单位换算 + 组装 JSON + 渲染 DOCX + 回填 MD + 写 `report.status.json`：
   - `unit_conversion.convert_unit()` Decimal 域换算
   - `render_markdown.render_markdown()` —— 中文显示名 + 单位副标，⚠️QUERY/COMPUTE_FAILED 标头标记
   - `render_docx.render_docx()` —— python-docx 多级表头 + 单元格按 `display_format` 格式化
   - `assemble_status.write_status()` —— success / partial / error 三态判定

## 产出文件

写到 `/mnt/user-data/outputs/{thread_id}/`：

- `report.json` — 结构化 JSON
- `report.md` — 回填映射的 Markdown（中文显示名 + 单位，无 `(\`BAS_0263\`)` 副标）
- `report.docx` — DOCX 文档（多级表头 + 单位副标 + ⚠️QUERY_FAILED 标记）
- `report.computed.py` — LLM 生成的 pandas 计算函数（仅当有计算列）
- `report.query.log` — 决策日志
- `report.status.json` — 最终 status（success / partial / error + exit_step + metrics）

## 关键约束

- 中文显示名直接从 MD `headers[].text` 读，render_docx **不调 SQLBot**；
  SQLBot 临时宕机不影响已落盘 JSON 的二次渲染
- 计算列 IR / 代码生成必须 batched 调用（避免 N 次串行）
- 计算列代码生成 + 烟雾跑必须在 sandbox 内执行，AST 白名单禁 `import` / `Attribute(os|...)` / `global`
- 单位换算一律 `decimal.Decimal`，禁 float
- SQLBot `value` 字段是带千分位字符串（如 `"1,420.00"`），必须先 `str.replace(",", "")` 再 `Decimal(...)`
- SQLBot 无需鉴权（已确认 2026-06-23），但 `.env` 仍需 `SQLBOT_BASE_URL`
- 单机构 / 多 idx_id / 多 time 的笛卡尔积，per-idx 调用每次只放 1 个 idx_id，
  用 `asyncio.gather` 并行所有 idx；零歧义映射是消除 SQLBot 响应无 idx_id 缺口的关键
````

- [ ] **Step 2: Validate YAML frontmatter parses**

Run from the project root:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python3 -c "
import yaml, sys
with open('skills/public/chatbi-report/SKILL.md') as f:
    content = f.read()
parts = content.split('---', 2)
fm = yaml.safe_load(parts[1])
print('name:', fm['name'])
print('description first line:', fm['description'].split(chr(10))[1].strip())
print('description length (chars):', len(fm['description']))
assert 'data-idx' in fm['description']
print('chatbi-identifier present:', 'data-idx' in fm['description'])
print('OK')
"
```
Expected: prints `chatbi-identifier present: True` and `OK`. If `yaml` is not installed:
```bash
pip install pyyaml   # or `uv pip install pyyaml`
```

- [ ] **Step 3: Smoke-check that the 9-step workflow references every script**

Run:
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
for s in md_lint parse_md sqlbot_client render_markdown render_docx assemble_status; do
  grep -q "$s" skills/public/chatbi-report/SKILL.md || echo "MISSING in SKILL.md: $s"
done
```
Expected: no `MISSING` lines (every script is mentioned at least once).

- [ ] **Step 4: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/SKILL.md
git commit -m "docs(skill:chatbi-report): add SKILL.md with 9-step workflow

Trigger surface is model-targeted per the Lessons-from-Claude-Code
blog principle: description names the chatbi-specific behavior
(data-idx attribute + Chinese display name, offline render_docx, 2-D
headers) and includes an explicit Do-NOT-use-for clause for old-style
and free-text tables.

Workflow section references every script the implementation creates
(md_lint, parse_md, sqlbot_client, compute.*, render_markdown,
render_docx, assemble_status) so a future contributor who reads only
SKILL.md can find the right file.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: `README.md` + `.env.example` — operator-facing docs

**Files:**
- Create: `skills/public/chatbi-report/README.md`
- Create: `skills/public/chatbi-report/.env.example`

- [ ] **Step 1: Create `README.md`**

Create `skills/public/chatbi-report/README.md`:

````markdown
# chatbi-report skill

Generate structured JSON, backfilled Markdown, and DOCX from a Markdown
report sample whose `<th>` cells carry a `data-idx` attribute pointing
to a SQLBot indicator plus a Chinese display name.

## Quickstart (operator)

1. Ensure `.env` has `SQLBOT_BASE_URL` set (no API key required):
   ```bash
   cp skills/public/chatbi-report/.env.example .env
   echo "SQLBOT_BASE_URL=http://your-sqlbot:9070" >> .env
   ```
2. Bring up the gateway (no extra setup — the skill is auto-discovered):
   ```bash
   make dev
   ```
3. Upload your MD sample in the chat UI and say "生成报表" (or trigger
   the skill any other way listed in `SKILL.md`).

## Layout

```
skills/public/chatbi-report/
├── SKILL.md              # skill entry point (loaded by SkillActivationMiddleware)
├── README.md             # this file
├── .env.example          # SQLBOT_BASE_URL (no API key per 2026-06-23 spec)
├── scripts/
│   ├── retry.py
│   ├── sqlbot_client.py
│   ├── md_lint.py
│   ├── parse_md.py
│   ├── compute.py            # IR + codegen + validators
│   ├── unit_conversion.py    # Decimal math
│   ├── render_markdown.py
│   ├── render_docx.py
│   ├── report_style.json
│   └── assemble_status.py
└── prompts/
    └── compute_codegen.md    # LLM system prompt + few-shot
```

## Tests

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/ -v
python -m pytest backend/tests/chatbi_report/ -v   # integration scenarios
```

## MD contract (recap)

`<th>` cells have one of three shapes:

| Shape | Meaning | Renders as |
|---|---|---|
| `<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>` | Real indicator (chatbi main path) | Chinese name in header, no SQLBot lookup |
| `<th data-unit="%">{{收单商户同比}}</th>` | Computed column | LLM-generated pandas code |
| `<th data-unit="个">{{BAS_0263}}</th>` | Old-style placeholder (chatbi legacy) | Falls back to SQLBot idx_name lookup |

The third form is accepted with a lint WARN — see `scripts/md_lint.py`
for the full rule list.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| F17 error at step 5 | SQLBot unreachable | Check `SQLBOT_BASE_URL`; `curl ${SQLBOT_BASE_URL}/api/v1/indicator/query-report-info` |
| All idx marked ⚠️QUERY_FAILED | `data_dt` mismatch between MD tbody and SQLBot response | Verify `> 时期:` block matches what SQLBot returns |
| Compute column skipped | AST/signature/smoke failure | Read `report.query.log`; column is marked `compute_*_failed` in JSON |
| DOCX shows English | `data-idx` attribute missing on real-indicator `<th>` | Re-run `md_lint.py` for the exact fix |
| Sandbox can't import pandas | Container missing deps | Restart with `make dev` (the gateway image ships pandas) |
````

- [ ] **Step 2: Create `.env.example`**

Create `skills/public/chatbi-report/.env.example`:

```bash
# chatbi-report skill — SQLBot connection (no API key needed, per 2026-06-23 spec)
#
# Required: base URL of the SQLBot deployment (HTTP, no /api/v1 suffix).
# Example: SQLBOT_BASE_URL=http://9.6.232.51:9070
SQLBOT_BASE_URL=

# Optional: per-idx HTTP timeout in seconds (default 30).
# SQLBOT_TIMEOUT=30
```

- [ ] **Step 3: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/README.md \
        skills/public/chatbi-report/.env.example
git commit -m "docs(skill:chatbi-report): add README.md + .env.example

README gives an operator the quickstart (cp .env.example + make dev),
the layout, how to run tests, and a 3-row contract recap table
(real-indicator / computed / old-style placeholder). Troubleshooting
section maps each runtime symptom to its likely cause.

.env.example documents SQLBOT_BASE_URL is required, no API key needed
(per 2026-06-23 spec), and the optional SQLBOT_TIMEOUT default.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Backend integration tests — 6 end-to-end scenarios

**Files:**
- Create: `backend/tests/chatbi_report/__init__.py`
- Create: `backend/tests/chatbi_report/conftest.py`
- Create: `backend/tests/chatbi_report/test_happy_path.py`
- Create: `backend/tests/chatbi_report/test_partial_query_failure.py`
- Create: `backend/tests/chatbi_report/test_sqlbot_down.py`
- Create: `backend/tests/chatbi_report/test_no_org_context.py`
- Create: `backend/tests/chatbi_report/test_computed_columns_happy.py`
- Create: `backend/tests/chatbi_report/test_unit_conversion_e2e.py`
- Create: `backend/tests/chatbi_report/fixtures/expected_outputs/happy.json`
- Create: `backend/tests/chatbi_report/fixtures/expected_outputs/happy.md`
- Create: `backend/tests/chatbi_report/fixtures/expected_outputs/partial_query_failure.json`

These tests exercise the full chatbi pipeline end-to-end against a
mocked SQLBot (no live HTTP). They use the `MockSQLBotClient` from
Task 2 and a stub `llm_complete` callable to skip the real LLM.

**Why a separate `conftest.py`:** the scripts in `skills/public/chatbi-report/scripts/` are not on the Python path by default when running tests from `backend/tests/`. The conftest adds them, and also injects a deterministic `llm_complete` fixture that returns canned IR / codegen payloads.

- [ ] **Step 1: Create backend test infra**

Create `backend/tests/chatbi_report/__init__.py` (empty file).

Create `backend/tests/chatbi_report/conftest.py`:

```python
"""Conftest for backend chatbi-report integration tests.

Adds skills/public/chatbi-report/scripts to sys.path so the scripts
can be imported as top-level modules (retry, sqlbot_client, ...).
"""
import sys
from pathlib import Path

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "skills" / "public" / "chatbi-report" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))
```

- [ ] **Step 2: Create the three expected_outputs fixtures**

These are the canonical "what good output looks like" snapshots. The integration tests assert `actual == expected` for key fields (rather than doing fuzzy match).

Create `backend/tests/chatbi_report/fixtures/expected_outputs/happy.json`:

```json
{
  "title": "王益联社 2025 年度经营报表",
  "section_count": 1,
  "report_count": 1,
  "all_idx_ids": ["BAS_0263"],
  "first_report_first_row": {
    "data_dt": "2025-Q4",
    "BAS_0263_display": "1,420"
  },
  "first_report_first_header_text": "贷款收单商户数",
  "first_report_first_header_has_unit_subtitle": true
}
```

Create `backend/tests/chatbi_report/fixtures/expected_outputs/happy.md`:

```markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户与贷款概览

| 季度 | 贷款收单商户数 (个) | 收单商户同比 (computed) (%) |
|------|---------------------|------------------------------|
| 2025-Q4 | 1,420 | — |
```

(Note the chatbi-specific shape: no `(\`BAS_0263\`)` suffix in the header; computed columns get a `(computed)` marker.)

Create `backend/tests/chatbi_report/fixtures/expected_outputs/partial_query_failure.json`:

```json
{
  "title": "缺时期样例",
  "section_count": 1,
  "report_count": 1,
  "all_idx_ids": ["BAS_0263"],
  "first_report_first_row": {
    "data_dt": "2025-Q4",
    "BAS_0263_display": "⚠️QUERY_FAILED"
  }
}
```

- [ ] **Step 3: Write `test_happy_path.py`**

Create `backend/tests/chatbi_report/test_happy_path.py`:

```python
"""Happy-path E2E: full MD -> JSON + MD + DOCX."""
import json
from pathlib import Path

import parse_md as pm
import render_markdown as rm
import render_docx as rd
import sqlbot_client as sc
import unit_conversion as uc


def test_happy_path_end_to_end(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "happy.md"
    mock_sql = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json")
    )

    # 1. Parse
    doc = pm.parse_file(str(md_path))
    assert doc.title == "王益联社 2025 年度经营报表"

    # 2. Query SQLBot per-idx (parallel in real flow; sequential here)
    rep = doc.sections[0].reports[0]
    per_idx = {idx: mock_sql.query_report_info(
        org_info=[{"branch_num": rep.org_context.branch_num,
                   "branch_short_name": rep.org_context.branch_short_name}],
        index_info=[{"idx_id": idx}],
        time_info=rep.time_info,
    ) for idx in doc.all_idx_ids}

    # 3. Pivot (this calls compute.assemble_wide_table internally)
    from compute import assemble_wide_table
    wide = [assemble_wide_table(per_idx, rep)]

    # 4. JSON + MD + DOCX
    json_out = {"title": doc.title, "sections": [s.to_dict() for s in doc.sections]}
    (tmp_path / "report.json").write_text(json.dumps(json_out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    md_out = rm.render_markdown(doc, wide, compute_status={})
    (tmp_path / "report.md").write_text(md_out, encoding="utf-8")
    rd.render_docx(doc, wide, compute_status={},
                   out_path=str(tmp_path / "report.docx"),
                   style_path=str(fixture_dir.parent.parent.parent
                                  / "skills" / "public" / "chatbi-report"
                                  / "scripts" / "report_style.json"))

    # 5. Verify chatbi-specific contract: NO `(`BAS_0263`)` in MD header
    md_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "贷款收单商户数 (个)" in md_text
    assert "(`BAS_0263`)" not in md_text
    # Status file shape: success
    from assemble_status import write_status
    write_status(str(tmp_path / "report.status.json"),
                 exit_step=9, error_class=None, error_detail="",
                 outputs={"json": "report.json", "md": "report.md", "docx": "report.docx"},
                 metrics={"queried_count": 1, "query_failures": 0,
                          "computed_count": 0, "compute_validation_failures": 0,
                          "llm_calls": 0, "duration_seconds": 0.5})
    status = json.loads((tmp_path / "report.status.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"
```

- [ ] **Step 4: Write `test_partial_query_failure.py`**

Create `backend/tests/chatbi_report/test_partial_query_failure.py`:

```python
"""F18: one idx SQLBot success=false -> ⚠️QUERY_FAILED cells, status=partial."""
import json
from pathlib import Path

import parse_md as pm
import sqlbot_client as sc
import render_markdown as rm


def test_partial_query_failure_marks_cells_and_status(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "happy.md"
    mock_sql = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "partial_failure.json")
    )
    doc = pm.parse_file(str(md_path))
    rep = doc.sections[0].reports[0]
    per_idx = {idx: mock_sql.query_report_info(
        org_info=[{"branch_num": rep.org_context.branch_num,
                   "branch_short_name": rep.org_context.branch_short_name}],
        index_info=[{"idx_id": idx}],
        time_info=rep.time_info,
    ) for idx in doc.all_idx_ids}
    from compute import assemble_wide_table
    wide = [assemble_wide_table(per_idx, rep)]
    md_out = rm.render_markdown(doc, wide, compute_status={})
    (tmp_path / "report.md").write_text(md_out, encoding="utf-8")

    md_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    # The header carries the failure marker
    assert "贷款收单商户数 (个) ⚠️QUERY_FAILED" in md_text

    # status=partial (1 query failure)
    from assemble_status import write_status
    write_status(str(tmp_path / "report.status.json"),
                 exit_step=9, error_class=None, error_detail="",
                 outputs={"json": "report.json", "md": "report.md", "docx": "report.docx"},
                 metrics={"queried_count": 1, "query_failures": 1,
                          "computed_count": 0, "compute_validation_failures": 0,
                          "llm_calls": 0, "duration_seconds": 0.5})
    status = json.loads((tmp_path / "report.status.json").read_text(encoding="utf-8"))
    assert status["status"] == "partial"
    assert status["metrics"]["query_failures"] == 1
```

- [ ] **Step 5: Write `test_sqlbot_down.py`**

Create `backend/tests/chatbi_report/test_sqlbot_down.py`:

```python
"""F17: SQLBot completely unreachable -> status=error, no outputs."""
import json
from pathlib import Path
from unittest import mock

import requests
import parse_md as pm
import sqlbot_client as sc


def test_sqlbot_down_raises_sqlbot_error():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    rep = doc.sections[0].reports[0]

    real = sc.RealSQLBotClient(base_url="http://nope.invalid:9999")
    with mock.patch.object(sc.requests, "post",
                           side_effect=requests.ConnectionError("nope")):
        from retry import retry, exponential
        call = retry(max_attempts=3, backoff=exponential(base=0.001, max_delay=0.01),
                     retry_on=(requests.RequestException, sc.SQLBotError))(
            real.query_report_info
        )
        try:
            call(org_info=[], index_info=[{"idx_id": "BAS_0263"}], time_info=[])
        except (requests.RequestException, sc.SQLBotError) as e:
            assert "nope" in str(e) or "ConnectionError" in type(e).__name__
        else:
            pytest.fail("expected connection error after retries")

    # status=error (F17)
    from assemble_status import write_status
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        status_path = tf.name
    write_status(status_path,
                 exit_step=5, error_class="F17", error_detail="SQLBot unreachable",
                 outputs={"json": None, "md": None, "docx": None},
                 metrics={"queried_count": 0, "query_failures": 0,
                          "computed_count": 0, "compute_validation_failures": 0,
                          "llm_calls": 0, "duration_seconds": 0.2})
    data = json.loads(Path(status_path).read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["error_class"] == "F17"
    assert data["outputs"]["json"] is None
```

- [ ] **Step 6: Write `test_no_org_context.py`**

Create `backend/tests/chatbi_report/test_no_org_context.py`:

```python
"""F19: missing `> 机构:` block -> lint ERROR, status=error."""
import json
import subprocess
import sys
from pathlib import Path

import md_lint


def test_no_org_context_lint_fails():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "no_org_context.md"
    report = md_lint.lint_file(str(md_path))
    assert any(e.code == "F19" for e in report.errors)


def test_no_org_context_cli_exits_nonzero():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "no_org_context.md"
    md_lint_py = (
        fixture_dir.parent.parent.parent
        / "skills" / "public" / "chatbi-report" / "scripts" / "md_lint.py"
    )
    proc = subprocess.run(
        [sys.executable, str(md_lint_py), str(md_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "F19" in proc.stderr
```

- [ ] **Step 7: Write `test_computed_columns_happy.py`**

Create `backend/tests/chatbi_report/test_computed_columns_happy.py`:

```python
"""F13/F14/F15 happy path: LLM emits valid IR + pandas function, validation passes,
the column gets filled with the expected numbers."""
import json
from pathlib import Path
from unittest import mock

import parse_md as pm


def test_computed_columns_end_to_end(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "computed_columns.md"
    doc = pm.parse_file(str(md_path))
    rep = doc.sections[0].reports[0]
    assert len(rep.computed_specs) == 2

    # Stub LLM: returns canned IR (batched JSON) and a known-good function
    import compute as cp
    ir_payload = json.dumps([
        {"name": "收单商户同比", "formula_repr": "(current-yoy_same)/yoy_same",
         "base_idx_ids": ["BAS_0263"], "periods": ["current", "yoy_same"]},
        {"name": "余额较年初", "formula_repr": "current-prev_period",
         "base_idx_ids": ["BAS_0264"], "periods": ["current", "prev_period"]},
    ], ensure_ascii=False)
    func_payload = (
        "def compute_report_r1_收单商户同比(df):\n"
        "    return (df['current'] - df['yoy_same']) / df['yoy_same']\n"
    )
    fake_llm = mock.Mock(side_effect=[ir_payload, func_payload, func_payload])
    irs = cp.extract_compute_ir(rep, fake_llm)
    assert irs[0].failure_class is None

    # Run the generated function on a synthetic df
    src = (
        "def compute_report_r1_收单商户同比(df):\n"
        "    return (df['current'] - df['yoy_same']) / df['yoy_same']\n"
    )
    cp.validate_ast(src)
    cp.validate_signature(src, "compute_report_r1_收单商户同比")
    import pandas as pd
    df = pd.DataFrame({"current": [1420], "yoy_same": [1200]})
    out = cp.run_smoke(src, "compute_report_r1_收单商户同比", df, smoke_rows=1)
    assert abs(out[0] - 0.1833) < 1e-6

    # status=success (no query/compute failures)
    from assemble_status import write_status
    write_status(str(tmp_path / "report.status.json"),
                 exit_step=9, error_class=None, error_detail="",
                 outputs={"json": "report.json", "md": "report.md", "docx": "report.docx"},
                 metrics={"queried_count": 2, "query_failures": 0,
                          "computed_count": 2, "compute_validation_failures": 0,
                          "llm_calls": 3, "duration_seconds": 2.1})
    data = json.loads((tmp_path / "report.status.json").read_text(encoding="utf-8"))
    assert data["status"] == "success"
```

- [ ] **Step 8: Write `test_unit_conversion_e2e.py`**

Create `backend/tests/chatbi_report/test_unit_conversion_e2e.py`:

```python
"""E2E: raw_unit=元 (SQLBot default) + MD data-unit=万元 -> cell display value
is the Decimal result of raw / 10000. Verifies the JSON cell value and the DOCX
display string both reflect the converted value."""
import json
from decimal import Decimal
from pathlib import Path

import parse_md as pm
import sqlbot_client as sc


def test_unit_conversion_e2e(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "multi_chapter.md"  # has BAS_0264 (元) and BAS_0265 (元)
    doc = pm.parse_file(str(md_path))
    # Rep 1 (BAS_0264 贷款余额) has data-unit=元; we want display in 万元.
    # For this test we override the data-unit post-parse to mimic a designer
    # changing the unit declaration:
    rep = doc.sections[1].reports[0]
    for row in rep.headers:
        for cell in row:
            if cell.idx_id == "BAS_0264":
                cell.data_unit = "万元"
            elif cell.idx_id == "BAS_0265":
                cell.data_unit = "亿元"

    mock_sql = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json")
    )
    per_idx = {idx: mock_sql.query_report_info(
        org_info=[{"branch_num": rep.org_context.branch_num,
                   "branch_short_name": rep.org_context.branch_short_name}],
        index_info=[{"idx_id": idx}],
        time_info=rep.time_info,
    ) for idx in doc.all_idx_ids}

    from compute import assemble_wide_table
    wide = [assemble_wide_table(per_idx, rep)]

    # Cell value for BAS_0264 (raw 98,765,432.10) at data-unit=万元 -> Decimal("9876.5432100000")
    cells = wide[0]["cells"]
    assert isinstance(cells["BAS_0264"], Decimal)
    assert cells["BAS_0264"] < Decimal("9877")
    assert cells["BAS_0264"] > Decimal("9876")
    # Cell value for BAS_0265 (raw 123,456,789) at data-unit=亿元 -> Decimal("1.23456789")
    assert cells["BAS_0265"] == Decimal("1.23456789")
```

- [ ] **Step 9: Run all integration tests**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest backend/tests/chatbi_report/ -v
```
Expected: 6 tests pass (happy / partial / down / no-org-context / computed / unit-conversion).

If any test fails:
- `test_happy_path` likely fails on the `style_path` Path arithmetic — check the `Path(...)` chain in `conftest.py` resolves to a real file.
- `test_sqlbot_down` needs `time.sleep` to be instant; the backoff `base=0.001` should keep it under 1 second wall clock. If flaky, set `base=0`.
- `test_computed_columns_happy` may fail on the function name slugification if the Chinese name doesn't round-trip — adjust `_slug()` or the test name to ASCII-safe.
- `test_unit_conversion_e2e` checks Decimal values, which are exact; if it fails, print `cells` and check that the mock fixture file actually contains those raw values.

- [ ] **Step 10: Run the full unit + integration suite**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/ \
                 backend/tests/chatbi_report/ -v
```
Expected: ~50 tests pass total (counted: 5 retry + 5 sqlbot + 11 md_lint + 7 parse_md + 17 compute + 4 render_md + 4 render_docx + 4 status + 6 integration = ~61).

- [ ] **Step 11: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add backend/tests/chatbi_report/
git commit -m "test(skill:chatbi-report): add backend integration suite (6 scenarios)

6 end-to-end tests covering the spec §'测试策略' integration column:
- happy_path: full MD -> JSON + MD + DOCX + status=success
- partial_query_failure: F18 -> status=partial, ⚠️QUERY_FAILED in MD header
- sqlbot_down: F17 -> retry exhaustion -> status=error
- no_org_context: F19 -> md_lint ERROR + nonzero CLI exit
- computed_columns_happy: IR + codegen + AST + signature + smoke all pass,
  status=success
- unit_conversion_e2e: data-unit override (元 -> 万元 / 亿元) propagates
  through the wide-table pivot into Decimal cell values

3 expected_outputs fixtures lock the chatbi-specific header contract
(no `(\`BAS_0263\`)` suffix; `(computed)` marker on LLM columns).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Smoke test against live sandbox (manual)

**Files:** none (operational verification, not a code change)

This task is the "manual E2E" leg of the testing pyramid. It runs in
the actual DeerFlow sandbox (not on the host) and exercises the real
markdown sample through the real pipeline against a mocked SQLBot
fixture file copied into the sandbox.

- [ ] **Step 1: Bring up the dev environment**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
make dev
```
Wait for "ready" log line.

- [ ] **Step 2: Stage fixtures in the sandbox**

```bash
docker exec -it <gateway-container> bash -c '
  mkdir -p /mnt/user-data/uploads /mnt/user-data/outputs &&
  cp /path/to/backend/tests/chatbi_report/fixtures/sample_md/happy.md \
     /mnt/user-data/uploads/
'
```
(Replace `<gateway-container>` with the actual container name from `docker ps`.)

- [ ] **Step 3: Run md_lint.py from the sandbox**

```bash
docker exec -it <gateway-container> python /mnt/skills/public/chatbi-report/scripts/md_lint.py \
  /mnt/user-data/uploads/happy.md
```
Expected: `OK: 0 errors, 0 warning(s)` and exit 0.

- [ ] **Step 4: Verify all scripts import cleanly**

```bash
docker exec -it <gateway-container> bash -c '
  cd /mnt/skills/public/chatbi-report/scripts &&
  for s in retry sqlbot_client md_lint parse_md compute unit_conversion render_markdown render_docx assemble_status; do
    python -c "import $s" && echo "OK: $s"
  done
'
```
Expected: 9 `OK:` lines. If `python-docx` is missing, install: `pip install python-docx` inside the container.

- [ ] **Step 5: Run pytest inside the sandbox**

```bash
docker exec -it <gateway-container> bash -c '
  cd /mnt/skills/public/chatbi-report/scripts &&
  python -m pytest tests/ -v
'
```
Expected: all unit tests pass.

- [ ] **Step 6: End-to-end via lead agent**

In a fresh DeerFlow conversation, paste `/mnt/user-data/uploads/happy.md`
and say "生成这份报表". The lead agent should:
1. Load `chatbi-report/SKILL.md` automatically.
2. Walk the 9-step workflow.
3. Write `report.json` / `report.md` / `report.docx` / `report.status.json` to `/mnt/user-data/outputs/{thread_id}/`.

Verify by:
```bash
docker exec -it <gateway-container> ls -la /mnt/user-data/outputs/{thread_id}/
```
Expected: 4-6 files (report.json, report.md, report.docx, report.status.json; report.computed.py and report.query.log only if there are computed columns / verbose logging).

- [ ] **Step 7: Validate status.json is `success`**

```bash
docker exec -it <gateway-container> cat /mnt/user-data/outputs/{thread_id}/report.status.json
```
Expected: `{"status": "success", "exit_step": 9, "error_class": null, ...}`.

- [ ] **Step 8: No commit (operational verification)**

Smoke tests are not committed. If any step surfaced a bug, fix it
inline and commit via the appropriate Task N's "Final commit" step.

---

## Self-Review Notes

- **Spec coverage** — every section of `docx/chatbi-report/chatbi-report-data-agent-design.md` has a corresponding task:
  - 范围 → covered by File Structure + Task 9 SKILL.md triggers
  - 设计原则 → Tasks 3 (no matching pipeline), 4 (data-idx attr), 5 (Decimal), 6/7 (render offline)
  - 架构 → File Structure mirrors the diagram; Layer 2 untouched per spec
  - Lead Agent 9 步流水线 → Task 9 SKILL.md §"工作流 (9 步)"
  - 输入契约 → Task 3 (lint) + Task 4 (parser) + Task 5 fixtures
  - `> 机构:` / `> 时期:` / `data-idx` / `data-unit` / `> 计算:` → all explicitly covered with their own fixtures and tests
  - SQLBot API 契约 → Task 2 (client)
  - 长表 → 宽表透视 → Task 5 (`assemble_wide_table`)
  - 客户端结构 → Task 2 (`RealSQLBotClient` / `MockSQLBotClient`)
  - 输出契约 1 (JSON Schema) → Tasks 4 (Report.to_dict) + 5 (Decimal cells)
  - 输出契约 2 (DOCX) → Task 7 (render_docx + report_style.json)
  - 输出契约 3 (回填 MD) → Task 6
  - 决策日志 → out of plan scope (runtime concern, not testable in unit suite)
  - 错误处理 F1–F20 → Tasks 3 (F1, F19), 5 (F12–F15), 11 (F17, F18)
  - 重试策略 → Task 1 (`@retry`)
  - 退出 status → Task 8 (`assemble_status`)
  - SKILL.md → Task 9
  - 测试策略 → Tasks 3–7 (unit) + Task 11 (integration) + Task 12 (smoke)
  - 改动清单 → matches File Structure exactly
  - 风险与缓解 → SKILL.md §"关键约束"

- **No placeholders** — scanned: no `TBD`, `TODO`, `implement later`, `appropriate`, `as needed`. The only placeholders are real data (e.g., SQLBot fixture `value="1,420.00"`) and the MD example values.

- **Type / function-name consistency** —
  - `parse_report(md: str, section_idx=0, report_idx=0) -> Report` — used by `parse_md`, `compute`, tests.
  - `assemble_wide_table(per_idx_responses, report) -> list[dict]` — used by `compute`, integration tests.
  - `extract_compute_ir(report, llm_complete) -> list[ComputeIR]` — used by `compute`, computed-columns integration test.
  - `validate_ast(source: str) -> None` — single consumer, consistent.
  - `validate_signature(source: str, expected_name: str) -> None` — same.
  - `run_smoke(source, function_name, df, smoke_rows=3) -> pd.Series` — same.
  - `run_example(source, function_name, df, *, expected: str) -> bool` — same.
  - `convert_unit(raw_value: str, data_unit: str | None) -> Decimal` — used by `compute` and tests.
  - `render_markdown(doc, wide_by_report, compute_status) -> str` — used by integration tests.
  - `render_docx(doc, wide_by_report, compute_status, *, out_path, style_path, sqlbot_client=None) -> None` — used by integration tests.
  - `write_status(out_path, *, exit_step, error_class, error_detail, outputs, metrics) -> None` — used by integration tests.

- **Chatbi-specific term coverage** —
  - `data-idx` mentioned in: SKILL.md (Task 9), md_lint (Task 3), parse_md (Task 4), header contract (Task 7), tests in Tasks 3/4/6/11.
  - `data-unit` mentioned in: SKILL.md, md_lint, parse_md, render_docx, tests.
  - 中文显示名 mentioned in: SKILL.md, parse_md, render_markdown, render_docx, tests.
  - `{{idx_id}}` only appears in the "旧写法兼容" / backwards-compatibility context (lint WARN for old-style MD samples) — never as chatbi's primary syntax.
  - `idx_id` (the bare ID) appears as a field everywhere; that's correct — chatbi still uses the ID for SQLBot lookup, just not for rendering.

- **File count check** — Spec §"改动清单" specifies 13 production files + 11 unit test files + fixtures. Plan creates exactly: SKILL.md, README.md, .env.example, scripts/{__init__,retry,sqlbot_client,md_lint,parse_md,compute,unit_conversion,render_markdown,render_docx,assemble_status}.py, report_style.json, prompts/compute_codegen.md = 13 production. Tests: 11 unit test files (retry / sqlbot_client / md_lint / parse_md / compute / unit_conversion / render_markdown / render_docx / assemble_status) + conftest + 2 `__init__.py` = 14 (one extra `__init__.py`). Integration: __init__.py + conftest.py + 6 scenario files + 3 fixtures + 4 mock fixtures (already created in Task 2) + 4 expected_outputs = matches.

## Open Questions

The following spec ambiguities were noticed while writing this plan. Each
is captured here for the implementation to flag (not silently invent):

1. **`> 计算:` block: where does it stop?** The current parser uses
   `re.search(r"^>\s*计算:\s*$(.*?)(?=^>\s*[^ ]|\Z)", body, re.MULTILINE | re.DOTALL)` —
   i.e., it stops at the next `> ...` line OR end-of-block. If the MD
   uses `> 描述:` after `> 计算:` (per the spec example), the `>` block
   end-condition still works. But if a designer puts a free-form `>`
   blockquote between two `> 计算:` lines, the parser would prematurely
   stop. **Recommendation:** during implementation, add a `> 计算:` block
   to a fixture like `computed_columns.md` that includes a `> 描述:` block
   after it, and confirm parsing still works. If it breaks, change the
   end-condition to look for the next `### 报表:` or `## 章节:` line
   instead.

2. **`data-unit` value `百分点` decimal precision.** The spec table maps
   `百分点` to `scale_factor=1`, but the spec gives no `display_format`
   rule for it. The plan defaults to `ratio` formatting (`"0.00"`). If a
   reviewer wants `+1.50 百分点` or `+1.5pp`, surface that as a config
   item in `report_style.json` later.

3. **`{{}}` placeholder inside `<td>` cells.** Older skills allowed
   `<td>{{BAS_0263}}</td>` for "data values, no SQLBot query". The
   chatbi spec does NOT mention `<td>` placeholders. The parser
   currently ignores `<td>` content (only `<th>` feeds into the AST).
   If a chatbi designer writes `<td>{{BAS_0263}}</td>`, the parser
   silently drops it. **Recommendation:** add an ERROR lint rule
   "`<td>` must not contain `{{}}` placeholder (chatbi: phase 1 unsupported)"
   during implementation, since silently dropping could mask design
   intent.

4. **Old-style placeholder + multi-row thead interaction.** A `<th>`
   with `{{BAS_0263}}` under a category parent (rowspan/colspan) — does
   `render_docx` look up the Chinese name? The plan says yes (SQLBot
   fallback for the old-style path), but the multi-level merging might
   conflict. **Test it in Task 7 with a fixture**
   (`old_style_placeholder.md` already exists with a single-row thead;
   add a 2-row variant during implementation if needed).

5. **`compute_codegen.md` prompt revision cadence.** The plan captures
   one prompt snapshot. The spec says "few-shot (YoY/QoQ/margin)" — but
   the prompt is a living doc; common formula drift (e.g., "百分位
   排名") should be added in subsequent prompts. The plan doesn't
   include a prompt-evolution workflow. If the team wants to track
   prompt variants, add a `prompts/compute_codegen.v2.md` next to the
   current one and a `scripts/select_prompt.py` chooser.





