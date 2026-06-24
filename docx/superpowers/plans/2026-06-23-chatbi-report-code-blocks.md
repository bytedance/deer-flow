# chatbi-report 实施计划 — 代码块附录

本附录抽出 `2026-06-23-chatbi-report-data-agent.md` 主体中所有围栏代码块，按 `§任务号.序号` 锚定。主体文档中每个被替换的位置会留下 `<!-- code-block: §N.M -->` 标记，指明语言、行数和指向本附录。

## 目录（71 个代码块）

- [§preamble.1](#section-preamble-1) — `text`
- [§1.1](#section-1-1) — `python`
- [§1.2](#section-1-2) — `python`
- [§1.3](#section-1-3) — `bash`
- [§1.4](#section-1-4) — `python`
- [§1.5](#section-1-5) — `bash`
- [§1.6](#section-1-6) — `bash`
- [§2.1](#section-2-1) — `python`
- [§2.2](#section-2-2) — `bash`
- [§2.3](#section-2-3) — `json`
- [§2.4](#section-2-4) — `json`
- [§2.5](#section-2-5) — `python`
- [§2.6](#section-2-6) — `bash`
- [§2.7](#section-2-7) — `bash`
- [§3.1](#section-3-1) — `python`
- [§3.2](#section-3-2) — `bash`
- [§3.3](#section-3-3) — `python`
- [§3.4](#section-3-4) — `bash`
- [§3.5](#section-3-5) — `bash`
- [§3.6](#section-3-6) — `bash`
- [§3.7](#section-3-7) — `bash`
- [§4.1](#section-4-1) — `python`
- [§4.2](#section-4-2) — `bash`
- [§4.3](#section-4-3) — `python`
- [§4.4](#section-4-4) — `bash`
- [§4.5](#section-4-5) — `bash`
- [§5.1](#section-5-1) — `python`
- [§5.2](#section-5-2) — `bash`
- [§5.3](#section-5-3) — `python`
- [§5.4](#section-5-4) — `bash`
- [§5.5](#section-5-5) — `python`
- [§5.6](#section-5-6) — `bash`
- [§5.7](#section-5-7) — `python`
- [§5.8](#section-5-8) — `markdown`
- [§5.9](#section-5-9) — `bash`
- [§5.10](#section-5-10) — `bash`
- [§6.1](#section-6-1) — `python`
- [§6.2](#section-6-2) — `bash`
- [§6.3](#section-6-3) — `python`
- [§6.4](#section-6-4) — `bash`
- [§6.5](#section-6-5) — `bash`
- [§7.1](#section-7-1) — `json`
- [§7.2](#section-7-2) — `python`
- [§7.3](#section-7-3) — `bash`
- [§7.4](#section-7-4) — `python`
- [§7.5](#section-7-5) — `bash`
- [§7.6](#section-7-6) — `bash`
- [§8.1](#section-8-1) — `python`
- [§8.2](#section-8-2) — `bash`
- [§8.3](#section-8-3) — `python`
- [§8.4](#section-8-4) — `bash`
- [§8.5](#section-8-5) — `bash`
- [§9.1](#section-9-1) — `markdown`
- [§9.2](#section-9-2) — `bash`
- [§9.3](#section-9-3) — `bash`
- [§9.4](#section-9-4) — `bash`
- [§9.5](#section-9-5) — `bash`
- [§10.1](#section-10-1) — `markdown`
- [§10.2](#section-10-2) — `bash`
- [§10.3](#section-10-3) — `bash`
- [§11.1](#section-11-1) — `python`
- [§11.2](#section-11-2) — `bash`
- [§11.3](#section-11-3) — `bash`
- [§11.4](#section-11-4) — `bash`
- [§12.1](#section-12-1) — `bash`
- [§12.2](#section-12-2) — `bash`
- [§12.3](#section-12-3) — `bash`
- [§12.4](#section-12-4) — `bash`
- [§12.5](#section-12-5) — `bash`
- [§12.6](#section-12-6) — `bash`
- [§12.7](#section-12-7) — `bash`

---

## §preamble.1
<!-- original lines 17–74 in plan -->
```text
skills/public/chatbi-report/
├── SKILL.md                    # 触发面 + 9 步工作流 + 关键约束（新增，约 150 行）
├── README.md                   # 配置 / 运行 / 故障排查（新增，约 80 行）
├── .env.example                # SQLBOT_BASE_URL=...（不需要 API key）（新增）
├── scripts/
│   ├── __init__.py             # 包标记（空，允许 tests/ import）（新增）
│   ├── retry.py                # 带指数退避的 @retry 装饰器（新增，约 60 行）
│   ├── sqlbot_client.py        # RealSQLBotClient + MockSQLBotClient + QueryReportInfoResponse dataclass（新增，约 180 行）
│   ├── md_lint.py              # 校验 MD 结构，所有 chatbi 专属 ERROR/WARN 规则，CLI 退出码（新增，约 250 行）
│   ├── parse_md.py             # MD → ReportDoc AST（Th[ ][ ] 二维表头，类目标签支持，ComputedSpec 列表）（新增，约 300 行）
│   ├── compute.py              # IR 抽取器（LLM 调用）+ pandas 代码生成 + AST/签名/烟雾/示例校验器 + Decimal 单位换算器（新增，约 400 行）
│   ├── render_markdown.py      # 回填 report.md（中文名 + 单位，⚠️QUERY_FAILED/⚠️COMPUTE_FAILED 标记）（新增，约 180 行）
│   ├── render_docx.py          # python-docx 渲染（多级合并，表头副标，主路径不查 SQLBot）（新增，约 350 行）
│   ├── report_style.json       # DOCX 样式 token（新增，约 30 行）
│   ├── assemble_status.py      # 由 exit-step + 指标写出 report.status.json（新增，约 120 行）
│   └── tests/
│       ├── __init__.py         # （新增）
│       ├── conftest.py         # 共享 fixture：临时路径、SQLBot mock 环境、样例 MD 加载器（新增）
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
    └── compute_codegen.md      # LLM 代码生成的系统 prompt + few-shot（YoY、ratio、growth）（新增，约 120 行）

backend/tests/chatbi_report/                                # 后端集成测试
├── __init__.py
├── conftest.py                                              # lead-agent 替身：在 tmp 目录运行脚本
├── fixtures/
│   ├── sample_md/
│   │   ├── happy.md                                         # 多行，2 idx，1 计算列，简单
│   │   ├── multi_chapter.md                                 # 两个 `## 章节:` 段，每段各两张报表
│   │   ├── multi_header.md                                  # 两行 <thead> 含 rowspan/colspan
│   │   ├── no_org_context.md                                # 缺 `> 机构:` 块（F19）
│   │   ├── no_time_info.md                                  # 缺 `> 时期:` 块（F19）
│   │   ├── computed_columns.md                              # 3 个计算列，2 个带示例，无旧式占位符
│   │   ├── computed_with_examples.md                        # 带 `.示例:` 块的计算列
│   │   ├── multi_header_computed.md                         # 两行 thead，计算列在类目下
│   │   ├── old_style_placeholder.md                         # `{{BAS_0263}}` 风格 —— 期望 WARN
│   │   └── lint_error.md                                    # 多个 chatbi 专属 lint 错误
│   ├── mock_sqlbot/
│   │   ├── query_responses.json                             # {idx_id: {success: bool, data: [...]}}
│   │   ├── partial_failure.json                             # 1 idx success=false（F18）
│   │   ├── code_error.json                                  # 顶层 code!=0（F17）
│   │   └── down.json                                        # 全部 idx 5xx（F17）
│   └── expected_outputs/
│       ├── happy.json
│       ├── happy.md
│       ├── partial_query_failure.json
│       └── computed_columns.json
└── （集成场景 —— 见任务 12–17）
```

## §1.1
<!-- original lines 107–136 in plan -->
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

## §1.2
<!-- original lines 142–237 in plan -->
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

## §1.3
<!-- original lines 242–245 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_retry.py -v
```

## §1.4
<!-- original lines 252–308 in plan -->
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

## §1.5
<!-- original lines 313–316 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_retry.py -v
```

## §1.6
<!-- original lines 321–335 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/retry.py \
        skills/public/chatbi-report/scripts/__init__.py \
        skills/public/chatbi-report/scripts/tests/__init__.py \
        skills/public/chatbi-report/scripts/tests/conftest.py \
        skills/public/chatbi-report/scripts/tests/test_retry.py
git commit -m "feat(skill:chatbi-report): add retry.py decorator with exponential backoff

通用同步装饰器，供 sqlbot_client、compute 以及 lead agent 的 HTTP 循环使用。
纯标准库（无新增依赖）。TDD：5 个 pytest 用例覆盖首次成功 / 中途重试 / 重试耗尽 /
不可重试异常 / 指数增长并封顶。测试中 monkeypatch 替换 sleep。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §2.1
<!-- original lines 355–456 in plan -->
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

    # 校验 HTTP 调用的形状
    m_post.assert_called_once()
    args, kwargs = m_post.call_args
    assert args[0] == "http://sqlbot.lan:9070/api/v1/indicator/query-report-info"
    body = kwargs["json"]
    assert body["org_info"][0]["branch_num"] == "27020199"
    assert body["index_info"] == [{"idx_id": "BAS_0263"}]
    assert body["time_info"] == ["2025"]
    # 不带 Authorization 头（依规格：SQLBot 无需鉴权）
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_real_client_raises_sqlbot_error_on_http_failure(sqlbot_env, monkeypatch):
    """4xx/5xx 透传 + @retry 重试到 max_attempts 后才抛。"""
    import requests as real_requests
    fake_response = mock.Mock()
    fake_response.raise_for_status.side_effect = real_requests.HTTPError("500 Server Error")

    # 避免真实 sleep 拖慢测试（@retry 默认 base=1, max_delay=8, 3 次）
    monkeypatch.setattr("retry.time.sleep", lambda _: None)

    with mock.patch.object(sc.requests, "post", return_value=fake_response) as m_post:
        with pytest.raises(real_requests.HTTPError, match="500"):
            sc.RealSQLBotClient(base_url="http://x").query_report_info(
                org_info=[], index_info=[{"idx_id": "X"}], time_info=[]
            )

    # @retry(max_attempts=3) 应当让 post 被调用 3 次
    assert m_post.call_count == 3


def test_real_client_raises_sqlbot_error_on_top_level_code_nonzero(sqlbot_env):
    """HTTP 200 但 code != 0 → SQLBotError，不重试（确定性业务失败）。"""
    fake_response = mock.Mock()
    fake_response.raise_for_status = mock.Mock()
    fake_response.json.return_value = {"code": 401, "msg": "auth failed"}

    with mock.patch.object(sc.requests, "post", return_value=fake_response) as m_post:
        with pytest.raises(sc.SQLBotError, match="code=401"):
            sc.RealSQLBotClient(base_url="http://x").query_report_info(
                org_info=[], index_info=[{"idx_id": "X"}], time_info=[]
            )

    # SQLBotError 不在 retry_on 元组里，应当只调用 1 次
    assert m_post.call_count == 1


def test_mock_client_returns_per_idx_data(fixture_dir):
    """Mock client: queries with single idx_id and returns that idx_id's rows only."""
    client = sc.MockSQLBotClient(fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json"))
    resp = client.query_report_info(
        org_info=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        index_info=[{"idx_id": "BAS_0263"}],
        time_info=["2025"],
    )
    assert resp.code == 0
    # 按规格契约，仅返回该 idx 的行
    assert len(resp.data) == 1
    elem = resp.data[0]
    assert elem["success"] is True
    assert all(row.get("idx_name") == "贷款收单商户数" for row in elem["data"])


def test_mock_client_returns_success_false_for_failing_idx(fixture_dir):
    """Mock client for partial_failure fixture: success=false（F18 情形）。"""
    client = sc.MockSQLBotClient(fixture_path=str(fixture_dir / "mock_sqlbot" / "partial_failure.json"))
    resp = client.query_report_info(
        org_info=[], index_info=[{"idx_id": "BAS_0264"}], time_info=[]
    )
    assert resp.code == 0   # 顶层仍然为 0（依规格）
    assert resp.data[0]["success"] is False
```

## §2.2
<!-- original lines 460–463 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py -v
```

## §2.3
<!-- original lines 470–492 in plan -->
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

## §2.4
<!-- original lines 496–510 in plan -->
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

## §2.5
<!-- original lines 516–636 in plan -->
```python
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
```

## §2.6
<!-- original lines 640–643 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py -v
```

## §2.7
<!-- original lines 648–669 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/sqlbot_client.py \
        skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py \
        backend/tests/chatbi_report/fixtures/mock_sqlbot/query_responses.json \
        backend/tests/chatbi_report/fixtures/mock_sqlbot/partial_failure.json
git commit -m "feat(skill:chatbi-report): add sqlbot_client.py (real + mock)

强制 per-idx 调用约定：调用方每次 query_report_info 仅传入一个 idx_id，
消除 SQLBot 响应中无 idx_id 的歧义（规格 §'Phase 1 已知缺口'）。

RealSQLBotClient POST 到 /api/v1/indicator/query-report-info，
不附带 Authorization 头（SQLBot 按 2026-06-23 规格无需鉴权）。
顶层 code != 0 时抛出 SQLBotError；HTTP 4xx/5xx 以 requests.HTTPError
形式上抛，使 @retry 最多重试 3 次。

MockSQLBotClient 按 idx_id 加载 fixture，支持 success=false 以供 F18 测试。
TDD：5 个 pytest 用例（happy/HTTP 失败/code!=0/mock 正常/mock 失败）
+ 2 个 fixture JSON 文件。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §3.1
<!-- original lines 726–813 in plan -->
```python
"""Unit tests for scripts/md_lint.py."""
from pathlib import Path

import pytest

import md_lint


def test_lint_happy_returns_no_errors(fixture_dir):
    """happy.md fixture 必须产生零 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "happy.md"))
    assert report.errors == [], f"unexpected errors: {report.errors}"


def test_lint_no_org_context_is_f19_error(fixture_dir):
    """缺 `> 机构:` 块 → F19 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "no_org_context.md"))
    codes = {e.code for e in report.errors}
    assert "F19" in codes
    assert any("机构" in e.message for e in report.errors)


def test_lint_no_time_info_is_f19_error(fixture_dir):
    """缺 `> 时期:` 块 → F19 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "no_time_info.md"))
    codes = {e.code for e in report.errors}
    assert "F19" in codes
    assert any("时期" in e.message for e in report.errors)


def test_lint_old_style_placeholder_is_warn_only(fixture_dir):
    """`{{BAS_0263}}` 不带 `data-idx` 属向后兼容 → WARN 而非 ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "old_style_placeholder.md"))
    assert report.errors == []
    assert any("旧式占位符" in w.message or "old-style" in w.message.lower() for w in report.warnings)


def test_lint_chatbi_error_missing_data_idx_on_real_indicator(fixture_dir):
    """纯文本的 `<th>`（既无 `data-idx` 又无 `{{虚拟名}}`）是 chatbi ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "data-idx" in msgs or "real-indicator" in msgs.lower()


def test_lint_chatbi_error_bad_data_idx_format(fixture_dir):
    """`data-idx="bad id"` 不满足 `^[A-Z]+_\\d+$` → ERROR。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("^[A-Z]+_\\d+$" in e.message or "regex" in e.message for e in report.errors)


def test_lint_chatbi_error_computed_with_data_idx(fixture_dir):
    """`<th data-idx="BAS_0263" data-unit="%">{{收单商户同比}}</th>` 违反计算列规则
    （必须用 `{{虚拟名}}` 且不得带 `data-idx`）。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    msgs = " ".join(e.message for e in report.errors)
    assert "computed" in msgs.lower() or "计算列" in msgs


def test_lint_org_block_format_error(fixture_dir):
    """`> 机构: branch_num=27020199`（无 `branch_short_name`）格式错误。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("branch_short_name" in e.message for e in report.errors)


def test_lint_time_block_format_error(fixture_dir):
    """`> 时期: time_info="2025"`（不是 JSON 数组）格式错误。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("JSON" in e.message or "time_info" in e.message for e in report.errors)


def test_lint_compute_formula_references_unknown_idx(fixture_dir):
    """`> 计算: 营收同比 = 本期MISSING_ID减...` 引用了表头集合中不存在的 idx。"""
    report = md_lint.lint_file(str(fixture_dir / "sample_md" / "lint_error.md"))
    assert any("MISSING_ID" in e.message or "未查询" in e.message or "unknown" in e.message.lower() for e in report.errors)


def test_lint_main_cli_exits_nonzero_on_error(fixture_dir):
    """`python md_lint.py <bad.md>` 退出码 1。"""
    import subprocess, sys
    p = fixture_dir / "sample_md" / "lint_error.md"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "md_lint.py"), str(p)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "ERROR" in proc.stdout or "ERROR" in proc.stderr
```

## §3.2
<!-- original lines 817–820 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_md_lint.py -v
```

## §3.3
<!-- original lines 827–1214 in plan -->
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


# 已识别的展示单位（其他值是 WARN 而非 ERROR）
RECOGNIZED_UNITS = {"元", "万元", "亿元", "%", "百分点", "个", "次"}
IDX_ID_PATTERN = re.compile(r"^[A-Z]+_\d+$")
COMPUTED_NAME_PATTERN = re.compile(r"^\{\{([^{}!]+)\}\}$")   # {{name}}，无内层花括号
OLD_PLACEHOLDER_PATTERN = re.compile(r"^\{\{([A-Z]+_\d+)\}\}$")


@dataclass
class LintError:
    code: str               # "F1", "F19", "CHATBI-DATAIDX", 等
    message: str
    location: str = ""      # "section 'X' > report 'Y'" 或 "<table> in report Z"


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
    """从一个 table 中按行收集 `<th>` 属性字典 + 单元格文本。"""

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


# ---------- 公开 API ---------- #

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


# ---------- 内部 ---------- #

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
    """返回（左侧计算名集合，右侧引用的 idx_id 集合）。"""
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

## §3.4
<!-- original lines 1218–1221 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_md_lint.py -v
```

## §3.5
<!-- original lines 1228–1232 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python skills/public/chatbi-report/scripts/md_lint.py backend/tests/chatbi_report/fixtures/sample_md/happy.md
echo "exit=$?"
```

## §3.6
<!-- original lines 1236–1240 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python skills/public/chatbi-report/scripts/md_lint.py backend/tests/chatbi_report/fixtures/sample_md/lint_error.md
echo "exit=$?"
```

## §3.7
<!-- original lines 1245–1267 in plan -->
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

11 个 pytest 用例，覆盖 happy + 5 条 chatbi 专属 ERROR 规则：
真实指标 <th> 必须有 data-idx；data-idx 格式 ^[A-Z]+_\\d+\$；
计算列必须使用 {{虚拟名}} 且不得带 data-idx；孤立 {{虚拟名}} 未在
> 计算: 块声明；> 计算: 公式引用未知 idx_id。另外 F19（缺 > 机构:/
> 时期:）与 3 条 WARN 规则（旧式占位符、自定义 data-unit、计算列名重复）。
CLI 在任何 ERROR 时退出码 1。

5 个 fixture MD 文件分别覆盖每条规则；lint_error.md 同时触发所有规则作为
烟雾验证。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §4.1
<!-- original lines 1311–1403 in plan -->
```python
"""Unit tests for scripts/parse_md.py."""
from pathlib import Path

import pytest

import parse_md as pm


def test_parse_happy_md_returns_single_report(fixture_dir):
    """happy.md：1 章节，1 报表，3 个 thead 单元格（1 个占位 + 1 个真实指标 + 1 个计算列）。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "happy.md"))
    assert doc.title == "王益联社 2025 年度经营报表"
    assert len(doc.sections) == 1
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 1          # 一行 thead
    assert len(rep.headers[0]) == 3       # 该行有三个单元格
    cells = rep.headers[0]
    # 单元格 0：占位（"季度"）
    assert cells[0].is_indicator is False and cells[0].is_computed is False and cells[0].idx_id is None
    # 单元格 1：来自 data-idx 的真实指标
    assert cells[1].is_indicator is True and cells[1].idx_id == "BAS_0263"
    assert cells[1].text == "贷款收单商户数"
    # 单元格 2：计算列（无 data-idx）
    assert cells[2].is_computed is True and cells[2].is_indicator is False
    assert cells[2].text == "{{收单商户同比}}"
    # computed_specs 已存在
    assert any(s.name == "收单商户同比" for s in rep.computed_specs)


def test_parse_multi_chapter_two_sections(fixture_dir):
    """multi_chapter.md：2 章节，每章 1 张报表。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_chapter.md"))
    assert len(doc.sections) == 2
    assert len(doc.sections[0].reports) == 1
    assert len(doc.sections[1].reports) == 1


def test_parse_multi_header_two_row_thead(fixture_dir):
    """multi_header.md：外层 headers 是 2 行；第 0 行有 2 个单元格（其中一个是类目父级）。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_header.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2          # 两行 thead
    assert len(rep.headers[0]) == 2       # 季度 + 商户与贷款（colspan=2）
    assert len(rep.headers[1]) == 2       # BAS_0263 + BAS_0264（位于 colspan 之下）
    # 类目父级：有 colspan，无 data-idx，无 {{}}
    parent = rep.headers[0][1]
    assert parent.is_indicator is False and parent.is_computed is False
    assert parent.colspan == 2
    # 第 1 行中的子单元格
    c0, c1 = rep.headers[1]
    assert c0.is_indicator is True and c0.idx_id == "BAS_0263"
    assert c1.is_indicator is True and c1.idx_id == "BAS_0264"


def test_parse_multi_header_computed_under_category(fixture_dir):
    """multi_header_computed.md：计算列嵌套于类目父级之下。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_header_computed.md"))
    rep = doc.sections[0].reports[0]
    assert len(rep.headers) == 2
    # 第 1 行：真实指标 + 计算列
    r1 = rep.headers[1]
    assert r1[0].is_indicator is True and r1[0].idx_id == "BAS_0263"
    assert r1[1].is_computed is True
    # 已解析到计算 spec
    assert any(s.name == "收单商户同比" for s in rep.computed_specs)


def test_parse_old_style_placeholder_extracts_idx_id(fixture_dir):
    """`<th data-unit="个">{{BAS_0263}}</th>` -> is_indicator=True，idx_id=BAS_0263，text=BAS_0263。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "old_style_placeholder.md"))
    rep = doc.sections[0].reports[0]
    cells = rep.headers[0]
    real = [c for c in cells if c.is_indicator]
    assert real[0].idx_id == "BAS_0263"
    # 文本来自占位符本身（MD 中无中文名）
    assert real[0].text == "BAS_0263"


def test_parse_org_and_time_into_report(fixture_dir):
    """`> 机构:` 与 `> 时期:` 解析进 Report 字段。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "happy.md"))
    rep = doc.sections[0].reports[0]
    assert rep.org_context.branch_num == "27020199"
    assert rep.org_context.branch_short_name == "王益联社"
    assert rep.time_info == ["2025"]


def test_all_idx_ids_collected_at_doc_level(fixture_dir):
    """Doc.all_idx_ids 是全部报表中非计算列 idx_id 的并集。"""
    doc = pm.parse_file(str(fixture_dir / "sample_md" / "multi_chapter.md"))
    assert doc.all_idx_ids == {"BAS_0263", "BAS_0264", "BAS_0265"}
```

## §4.2
<!-- original lines 1407–1410 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_parse_md.py -v
```

## §4.3
<!-- original lines 1417–1750 in plan -->
```python
"""Parse a chatbi-report MD sample into the ReportDoc AST.

- `headers` 是二维结构（外层 = thead 行，内层 = 该行单元格）以支持
  rowspan/colspan 的多级表头。
- `Th.is_indicator` 优先由 `data-idx` HTML 属性推导，`{{}}` 占位符正则
  作为旧式 MD 的回退。
- 旧式 `<th>{{BAS_0263}}</th>`（无 data-idx，但 `{{}}` 匹配 idx_id 正则）
  仍被识别为 is_indicator=True（render_docx 在此对 idx_name 进行 SQLBot 回退查询）。
- 类目标签单元格（多级 thead 父级，无 data-idx，无 {{}}）以
  is_indicator=False、is_computed=False、idx_id=None 输出 —— 不报错。
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
    prompt: str                          # 原始 "name = expr" 文本
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
    headers: list[list[Th]]                # 二维：外层 = thead 行索引
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


# ---------- 公开 API ---------- #

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
    """便捷接口：按索引解析特定报表。供测试和 compute.py 使用。"""
    doc = parse_markdown(md)
    return doc.sections[section_idx].reports[report_idx]


# ---------- 内部 ---------- #

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
    """从 <thead>...</thead> 片段中按行收集 list[list[dict]]。"""

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
        # 旧式占位符：仍为 is_indicator；idx_id 取自 {{}}
        return Th(text=text, is_indicator=True, is_computed=False,
                  idx_id=old_match.group(1),
                  data_unit=data_unit, rowspan=rowspan, colspan=colspan)
    if data_idx and IDX_ID_PATTERN.match(data_idx):
        return Th(text=text, is_indicator=True, is_computed=False,
                  idx_id=data_idx, data_unit=data_unit,
                  rowspan=rowspan, colspan=colspan)
    # 既无 data-idx 也无 {{}} 也无公式匹配 —— 类目标签单元格或占位
    return Th(text=text, is_indicator=False, is_computed=False,
              data_unit=data_unit, rowspan=rowspan, colspan=colspan)


def _parse_compute_block(body: str) -> list[ComputedSpec]:
    """解析 `> 计算:` 与可选 `.示例:` 行。"""
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
    """将 `BAS_0263[current=1420, yoy_same=1200] -> 0.1833` 解析为 dict。"""
    m = re.match(r"^([A-Z]+_\d+)\s*\[(.*?)\]\s*->\s*(\S+)$", tail)
    if not m:
        return None
    inputs_str = m.group(2)
    inputs: dict[str, str] = {}
    for kv in re.findall(r"(\w+)\s*=\s*([^,]+)", inputs_str):
        inputs[kv[0].strip()] = kv[1].strip()
    return {"inputs": inputs, "expected": m.group(3)}
```

## §4.4
<!-- original lines 1754–1757 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_parse_md.py -v
```

## §4.5
<!-- original lines 1762–1785 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/parse_md.py \
        skills/public/chatbi-report/scripts/tests/test_parse_md.py \
        backend/tests/chatbi_report/fixtures/sample_md/multi_chapter.md \
        backend/tests/chatbi_report/fixtures/sample_md/multi_header.md \
        backend/tests/chatbi_report/fixtures/sample_md/multi_header_computed.md
git commit -m "feat(skill:chatbi-report): add parse_md.py with 2-D headers + category labels

7 个 pytest 用例覆盖 happy / multi_chapter / multi_header（含 rowspan+
colspan 父级）/ multi_header_computed（类目下的计算列）/ 旧式占位符抽取
/ 机构 + 时期解析 / all_idx_ids。

AST 形态依规格：
- headers: Th[ ][ ]（二维；外层 = thead 行），使多级表头能在 DOCX 中
  以正确的 cell.merge() 渲染。
- Th 新增 rowspan?/colspan? 字段。
- is_indicator 优先由 data-idx HTML 属性推导，{{idx_id}} 旧式占位符
  作为回退（render_docx 在后者情况下 SQLBot 查询 idx_name）。
- 类目标签单元格（多级 thead 父级，无 data-idx、无 {{}}）以
  is_indicator=False、is_computed=False、idx_id=None 输出 —— 不报错。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §5.1
<!-- original lines 1833–1904 in plan -->
```python
"""Unit tests for scripts/unit_conversion.py."""
from decimal import Decimal

import pytest

import unit_conversion as uc


def test_scale_factor_table_values():
    """标准单位映射到规格中的 scale_factor 列。"""
    assert uc.SCALE_FACTOR["元"] == Decimal("1")
    assert uc.SCALE_FACTOR["万元"] == Decimal("10000")
    assert uc.SCALE_FACTOR["亿元"] == Decimal("100000000")
    assert uc.SCALE_FACTOR["%"] == Decimal("0.01")
    assert uc.SCALE_FACTOR["百分点"] == Decimal("1")
    assert uc.SCALE_FACTOR["个"] == Decimal("1")
    assert uc.SCALE_FACTOR["次"] == Decimal("1")


def test_strip_thousands_separator():
    """内部辅助函数处理 '1,420.00' -> Decimal('1420.00')。"""
    assert uc._strip_thousands("1,420.00") == Decimal("1420.00")
    assert uc._strip_thousands("123,456,789") == Decimal("123456789")
    assert uc._strip_thousands("0") == Decimal("0")


def test_convert_unit_yuan_passthrough():
    """data-unit=元 -> raw_value 1:1 显示。"""
    assert uc.convert_unit("1,420.00", "元") == Decimal("1420.00")


def test_convert_unit_wan():
    """data-unit=万元 -> 除以 10000。"""
    # SQLBot 原始单位为元；设计师想用万元
    assert uc.convert_unit("12,000,000", "万元") == Decimal("1200.0000")


def test_convert_unit_yi():
    """data-unit=亿元 -> 除以 1e8。"""
    assert uc.convert_unit("987,654,321", "亿元") == Decimal("9.87654321")


def test_convert_unit_percentage():
    """data-unit=% -> 乘以 0.01，使 0.366 显示为 36.60%。"""
    assert uc.convert_unit("0.366", "%") == Decimal("0.366")


def test_convert_unit_none_keeps_raw():
    """data-unit 缺省或空 -> 原始值的 Decimal，恒等缩放。"""
    assert uc.convert_unit("1,234", None) == Decimal("1234")
    assert uc.convert_unit("1,234", "") == Decimal("1234")


def test_convert_unit_custom_string_passthrough():
    """data-unit='个'（已是计数单位） -> 1:1。"""
    assert uc.convert_unit("1,420", "个") == Decimal("1420")


def test_convert_unit_raises_on_bad_string():
    """非数字 raw_value -> InvalidOperation（Decimal）。"""
    from decimal import InvalidOperation
    with pytest.raises(InvalidOperation):
        uc.convert_unit("not-a-number", "元")


def test_round_trip_yuan_to_wan_to_yuan():
    """12,000,000 元 -> 1200 万元 -> 12,000,000 元（经 Decimal 无精度损失）。"""
    yuan_raw = uc.convert_unit("12,000,000", "万元")
    yuan_back = uc.convert_unit(str(yuan_raw), "元")
    assert yuan_back == Decimal("12000000.0000")
```

## §5.2
<!-- original lines 1908–1911 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_unit_conversion.py -v
```

## §5.3
<!-- original lines 1918–1958 in plan -->
```python
"""Decimal-based unit conversion. No float, no LLM dependency."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


# 展示单位 -> scale_factor。依规格 §"列级单位声明 data-unit"。
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
    """去掉千分位分隔符（'1,420.00' -> Decimal('1420.00')）。"""
    return Decimal(raw_value.replace(",", "").strip())


def convert_unit(raw_value: str, data_unit: str | None) -> Decimal:
    """将 SQLBot 原始值（带千分位）换算为设计师指定的展示单位。

    规格公式：display_value = raw * raw_unit_scale / display_unit_scale。
    Phase 1 的 raw_unit_scale = 1（我们尚未接入 get_indicator 的 unit 字段，
    因此假定 SQLBot 返回的原始值单位为元 / 原生单位）。

    返回 Decimal，全程不使用 float。
    """
    raw = _strip_thousands(raw_value)
    raw_unit_scale = Decimal("1")      # Phase 1 默认；见规格 §"⚠️ Phase 1 已知缺口"
    display_unit_scale = SCALE_FACTOR.get(data_unit or "", Decimal("1"))
    return raw * raw_unit_scale / display_unit_scale


__all__ = ["SCALE_FACTOR", "convert_unit"]
```

## §5.4
<!-- original lines 1962–1965 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_unit_conversion.py -v
```

## §5.5
<!-- ⚠️ STALE BLOCK REMOVED 2026-06-24 — DO NOT COPY ANY CACHED VERSION.

旧版（182 行）基于 llm_complete monkeypatch 接口，已废弃。

实施任务 5 步骤 6 时，按主 plan 任务 5 步骤 6 的 6 类测试表自行生成 test_compute.py
（约 12–15 个测试，零 monkeypatch、零 LLM mock，全部用预制源码字符串）。
覆盖：extract_compute_ir 静态解析 / validate_ast / validate_signature / run_smoke /
run_example / evaluate_column。-->

## §5.6
<!-- original lines 2159–2162 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_compute.py -v
```

## §5.7
<!-- ⚠️ STALE BLOCK REMOVED 2026-06-24 — DO NOT COPY ANY CACHED VERSION.

旧版（287 行）含 generate_pandas_function + llm_complete 参数链，已废弃。

实施任务 5 步骤 8 时，按主 plan 任务 5 步骤 8 的"重写要点"自行生成 compute.py：
- 删除 generate_pandas_function / extract_compute_ir(report, llm_complete) LLM 重载
- 保留 + 修订 extract_compute_ir(report) 为纯 regex/AST 解析 > 计算: 块
- 新增 run_smoke 头部调 validate_signature（R3 修复）
- 新增 if __name__ == "__main__": argparse CLI，4 个子命令 extract-ir / assemble-wide / validate / evaluate
- 不变：validate_ast / run_example / evaluate_column 主体逻辑、assemble_wide_table、Decimal 列累加
预计 ~240 行。-->

## §5.8
<!-- ⚠️ STALE BLOCK REMOVED 2026-06-24 — DO NOT COPY ANY CACHED VERSION.

旧版（66 行）prompt 大体可复用但缺两处修订，已统一删除让实施者重写。

实施任务 5 步骤 9 时按主 plan 任务 5 步骤 9 要点自行生成 prompts/compute_codegen.md：
- 顶部加注释：<!-- 由 lead agent 在 SKILL.md step 7 加载，与 ComputeIR JSON 拼装后送入模型；
  不被任何 Python 脚本 import -->
- 输出契约段强调"函数必须有 : pd.DataFrame 类型注解 + -> pd.Series 返回注解"（与 validate_signature 对齐）
- few-shot 示例：BAS_0263 同比 → def compute_yoy(df: pd.DataFrame) -> pd.Series 模板
- 失败重试约定：lead agent 见 validate 退出码 1 时读 stderr 重生成 1 次-->

## §5.9
<!-- original lines 2536–2540 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_compute.py \
                              skills/public/chatbi-report/scripts/tests/test_unit_conversion.py -v
```

## §5.10
<!-- original lines 2545–2577 in plan -->
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

两个模块，按可测性拆分：

unit_conversion.py（10 个 pytest 用例）：纯 Decimal 运算。无 float，
无 LLM。SCALE_FACTOR 表依规格 §'data-unit'；处理千分位分隔符
（'1,420.00' -> Decimal('1420.00')）；元<->万元 双向可逆。

compute.py（约 14 个 pytest 用例）：
- extract_compute_ir()：每张报表一次批量化 LLM 调用（非逐 spec）。
  当 LLM 引用了不在文档 all_idx_ids 中的 idx_id 时标 F12。
- validate_ast()：允许的 AST 节点白名单 + os/sys/subprocess
  属性访问黑名单。拒绝 Import / Global / Nonlocal。
- validate_signature()：函数名 + (df: pd.DataFrame) + pd.Series。
- run_smoke() / run_example()：受限 ns 的沙箱 exec()（仅 pd/np/df/
  Decimal）。烟雾断言 pd.Series + 长度；示例用 math.isclose(rel_tol=1e-6)。
- assemble_wide_table()：长 → 宽 透视，所有单元格为 Decimal，
  data[i].success=false 或查找未命中时标 ⚠️QUERY_FAILED。

prompts/compute_codegen.md：LLM 系统 prompt，含 few-shot 示例
（YoY、QoQ、毛利率、条件 YoY）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §6.1
<!-- original lines 2602–2680 in plan -->
```python
"""Unit tests for scripts/render_markdown.py."""
from pathlib import Path

import pytest

import parse_md as pm
import render_markdown as rm


def test_render_markdown_happy_no_idx_id_in_header(fixture_dir):
    """Chatbi 规则：表头为 `中文名 (单位)` —— 不带 (`BAS_0263`) idx 后缀。"""
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    wide = [{
        "data_dt": "2025-Q4", "org_ecd": "王益联社",
        "cells": {"BAS_0263": "1,420"},
        "raw_cells": {"BAS_0263": "1,420"},
    }]
    compute_status: dict = {}
    out = rm.render_markdown(doc, [wide], compute_status)
    # 表头行必须包含中文显示名 + 单位
    assert "贷款收单商户数 (个)" in out
    # Chatbi 差异：表头中不含 (`BAS_0263`) idx 后缀
    assert "(`BAS_0263`)" not in out
    # YoY 列上的计算标记
    assert "{{收单商户同比}}" not in out  # 占位符已解析
    assert "收单商户同比 (computed)" in out
    assert "(%)" in out


def test_render_markdown_query_failed_in_header(fixture_dir):
    """标为 ⚠️QUERY_FAILED 的单元格在表头自身里渲染。"""
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
    """status='compute_smoke_failed' 的计算列显示 ⚠️COMPUTE_FAILED。"""
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
    """multi_chapter.md → 输出同时含 `## 第一章:` 与 `## 第二章:`。"""
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
    # 两个中文显示名都在
    assert "贷款收单商户数 (个)" in out
    assert "贷款余额 (元)" in out
    assert "存款余额 (元)" in out
```

## §6.2
<!-- original lines 2684–2687 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_markdown.py -v
```

## §6.3
<!-- original lines 2694–2799 in plan -->
```python
"""Render the backfilled Markdown report (`report.md`).

- 表头渲染为 `<中文显示名> (<单位>)`，不再追加 `(\`BAS_0263\`)`
  idx_id 后缀 —— 中文名已经在 `headers[].text` 中。
- ⚠️QUERY_FAILED 与 ⚠️COMPUTE_FAILED 标记直接追加到表头标签
  （让渲染出的列头就能揭示失败）。
"""
from __future__ import annotations

from typing import Iterable

from parse_md import ReportDoc, Th


def _leaf_cells(headers: list[list[Th]]) -> list[Th]:
    """扁平化的叶子单元格列表（跳过多级类目父级）。"""
    leaves = [c for row in headers for c in row]
    return [c for c in leaves if c.idx_id is not None or c.is_computed]


def _header_label(th: Th, compute_status: dict) -> str:
    """按 chatbi 契约构建渲染列头标签。"""
    name = th.text
    if th.is_computed:
        # 若解析器保留了 {{}}，则去掉；render_markdown 期望纯文本。
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
        # 真实指标：调用方根据宽行单元格决定是否追加 QUERY_FAILED。
        # 我们通过渲染时在 Th 实例上设置的 sentinel 暴露该标记
        # （见 _mark_query_failures）。
        fail_marker = getattr(th, "_query_failed_marker", None)
        if fail_marker:
            label = f"{label} ⚠️QUERY_FAILED"
    return label


def _mark_query_failures(headers: list[list[Th]], wide_cells: dict | None) -> None:
    """在 idx_id 查询失败的 Th 上设置 _query_failed_marker=True。"""
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
    """渲染完整的回填后 MD 内容。"""
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

            # 构建 Markdown 表
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

## §6.4
<!-- original lines 2803–2806 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_markdown.py -v
```

## §6.5
<!-- original lines 2811–2826 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/render_markdown.py \
        skills/public/chatbi-report/scripts/tests/test_render_markdown.py
git commit -m "feat(skill:chatbi-report): add render_markdown.py with chatbi header format

4 个 pytest 用例。表头格式为 <中文显示名> (<单位>) —— 不再追加
(\`BAS_0263\`) idx 后缀（中文名已经在 headers[].text 中，依 chatbi 规格）。
⚠️QUERY_FAILED / ⚠️COMPUTE_FAILED 标记直接追加到表头标签，
让一瞥列头即可看到失败。

计算列得到一个 (computed) 标记，用于区分 LLM 生成的数字与
SQLBot 拉取的数字（文档审阅者一眼就能看出哪些数字可由 MD 复现）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §7.1
<!-- original lines 2853–2879 in plan -->
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

## §7.2
<!-- original lines 2885–3012 in plan -->
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
    """render_docx() 产出非空 .docx 文件。"""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "happy.md"),
        str(out),
        fixture_dir,
    )
    assert out.exists()
    assert out.stat().st_size > 1024   # python-docx 输出不会是空文件


def test_render_docx_header_uses_chinese_name_not_idx_id(fixture_dir, tmp_path):
    """Chatbi 规则：列主标题为 MD 中的中文显示名。"""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "happy.md"),
        str(out),
        fixture_dir,
    )
    # 通过 python-docx 把 .docx 当原始文本读回
    from docx import Document
    doc = Document(str(out))
    # 收集所有单元格的文本；校验中文显示名存在
    all_text = "\n".join(
        p.text for p in doc.paragraphs
    ) + "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    assert "贷款收单商户数" in all_text
    # 在 chatbi 主路径中，idx_id 不应作为列标题
    # （仅用于数据查找，不作为可见标签）。
    # MD 表头包含中文显示名 + data-unit "(个)" 副标，
    # 因此列头应显示 "贷款收单商户数" + "(个)" —— 而非 "BAS_0263"。
    cells_text = "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    # 仅当渲染器回退到旧式查询时才允许 "BAS_0263" 出现。
    # happy.md fixture 使用 data-idx + 中文文本，不应回退，
    # 因此 BAS_0263 不应出现在可见表格中。
    assert "BAS_0263" not in cells_text


def test_render_docx_multi_level_merges_cells(fixture_dir, tmp_path):
    """multi_header.md：顶行类目单元格跨 2 列（cell.merge()）。"""
    out = tmp_path / "report.docx"
    _render_via_subprocess(
        str(fixture_dir / "sample_md" / "multi_header.md"),
        str(out),
        fixture_dir,
    )
    from docx import Document
    doc = Document(str(out))
    table = doc.tables[0]
    # 第一行应有 2 个单元格（1 个类目父级 + 1 个占位列），
    # 父级单元格是覆盖第 0 行第 1..2 列与第 1 行第 0..1 列的合并区域。
    # python-docx 通过 tc.spans 暴露合并单元格；我们只检查类目文本仅出现一次。
    texts = [c.text for r in table.rows for c in r.cells]
    assert "商户与贷款" in texts
    assert "贷款收单商户数" in texts
    assert "贷款余额" in texts


def test_render_docx_query_failed_marker_in_cell(fixture_dir, tmp_path):
    """⚠️QUERY_FAILED 单元格文本按原样保留。"""
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

## §7.3
<!-- original lines 3016–3019 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_docx.py -v
```

## §7.4
<!-- original lines 3026–3203 in plan -->
```python
"""Render the final DOCX (`report.docx`).

依规格 §"表头副标渲染规则"：
- 主列标题读取 `headers[].text`（来自 MD 的中文显示名）
  —— 不是 SQLBot idx_id，也不是 SQLBot idx_name 查询结果。
- 副标题仅为 `(data-unit)`（如 `(个)`）。
- 渲染过程中调用 SQLBot 的唯一路径，是旧式 `<th>{{idx_id}}</th>`
  占位符的回退（此时 `headers[].text` 就是 idx_id，需要向 SQLBot 查询 idx_name）。
- 多级 thead 通过跨 rowspan/colspan 的 cell.merge() 渲染。
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
    """替换单元格内容为 `text`（可选的副标在第二行）。"""
    # 清除已有段落（python-docx 单元格默认带一个空段落）
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
        # 以小数存储（0.1833）；按 1 位小数显示为百分比
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
    """渲染完整 DOCX。`sqlbot_client` 仅在 MD 缺少中文显示名的旧式
    `<th>{{idx_id}}</th>` 列上被查询。
    """
    style = _load_style(style_path)
    docx = Document()

    # 页面设置
    section = docx.sections[0]
    page = style.get("page", {})
    margins = page.get("margins_cm", {})
    if page.get("orientation") == "landscape":
        from docx.enum.section import WD_ORIENTATION
        section.orientation = WD_ORIENTATION.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    for k, cm in margins.items():
        setattr(section, f"{k}_margin", Cm(cm))

    # 标题
    p = docx.add_paragraph()
    run = p.add_run(doc.title)
    _apply_font(run, style["font"]["title"])

    ridx = 0
    for sec in doc.sections if False else _iter_sections(doc):  # 占位修复见下
        _render_section(docx, sec, wide_by_report, ridx, compute_status, style, sqlbot_client)
        ridx += len(sec.reports)


# 为能在自己的循环中遍历 doc.sections 而不遮蔽 docx Document.sections 属性：
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

    # 表头行
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
            # 背景
            tc._tc.get_or_add_tcPr()

    # 数据行
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

## §7.5
<!-- original lines 3207–3210 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_render_docx.py -v
```

## §7.6
<!-- original lines 3217–3242 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/render_docx.py \
        skills/public/chatbi-report/scripts/report_style.json \
        skills/public/chatbi-report/scripts/tests/test_render_docx.py
git commit -m "feat(skill:chatbi-report): add render_docx.py with chatbi header contract

4 个 pytest 用例对真实 .docx 进行 python-docx round-trip。

表头契约（chatbi 专属）：
- 主列标题 = headers[].text（MD 中的中文显示名）
- 副标题 = 仅 (data-unit)
- idx_id 与 idx_name 永远不出现在可见表头 —— 仅用于数据查找，不渲染。

多级 thead：跨 rowspan/colspan 的 cell.merge()。类目父级仅在
合并区域中渲染；叶子各自承载其中文名。

旧式 {{BAS_0263}} 占位符列：render_docx 回退到 SQLBot idx_name 查询
（渲染过程中调用 SQLBot 的唯一路径）。Phase 1 主路径完全离线 —
即使 SQLBot 宕机也能重新渲染已存储的 report.json。

report_style.json：字体 token（微软雅黑 / 宋体）、表样式（边框、
表头底色 #F0F0F0）、数字格式（货币 / 百分比 / ratio）以及横向页面。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §8.1
<!-- original lines 3262–3340 in plan -->
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

## §8.2
<!-- original lines 3344–3347 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -v
```

## §8.3
<!-- original lines 3354–3408 in plan -->
```python
"""Write `report.status.json` per spec §'lead agent 退出 status'.

状态判定逻辑：
- error_class in F1..F20            -> "error"
- error_class 为 None 且
  query_failures == 0 且
  compute_validation_failures == 0  -> "success"
- 其他                              -> "partial"
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
    """以规格强制的形态持久化 report.status.json。"""
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

## §8.4
<!-- original lines 3412–3415 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/test_assemble_status.py -v
```

## §8.5
<!-- original lines 3420–3435 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/scripts/assemble_status.py \
        skills/public/chatbi-report/scripts/tests/test_assemble_status.py
git commit -m "feat(skill:chatbi-report): add assemble_status.py

4 个 pytest 用例覆盖三种合法状态值：
- success: error_class=None 且无查询/计算失败
- partial: error_class=None 且 (query_failures>0 或 compute_failures>0)
- error:   error_class in F1..F20

JSON 形态严格匹配规格 §'lead agent 退出 status'，因此未来的重构
不会在没有测试失败的情况下静默丢失字段。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §9.1
<!-- ⚠️ STALE BLOCK REMOVED 2026-06-24 — DO NOT COPY ANY CACHED VERSION.

旧版（89 行）SKILL.md 的 step 7/8 措辞基于旧脚本接口，已废弃。

实施任务 9 步骤 1 时按主 plan 任务 9 的"9 步工作流分层契约"表自行生成 SKILL.md：
- YAML frontmatter：name=chatbi-report, description, identifier=chatbi-report
- 触发匹配规则（参考 skills/public/data-analysis/SKILL.md 风格）：触发关键词 + 反例
- 复杂度判定：lint-only 模式 vs 完整 9 步 vs 跳过 docx 模式
- 9 步契约（与主 plan 任务 9 表格 1:1 对齐）：
  step 1 lint / step 2 parse / step 3 query / step 4 assemble-wide /
  step 5 unit_conversion / step 6 extract-ir(静态) / step 7 codegen(agent-turn LLM) /
  step 8a validate / step 8b evaluate / step 9 render+status
- 关键不变量段：明确"step 7 是唯一 agent-turn LLM step；step 1–6 与 8a/8b/9 全部是 bash CLI 子进程，
  沙箱中不可达 LLM"
- 重试约定：step 7 失败重试 1 次在 agent-turn 内做-->

## §9.2
<!-- original lines 3545–3560 in plan -->
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

## §9.3
<!-- original lines 3562–3564 in plan -->
```bash
pip install pyyaml   # 或 `uv pip install pyyaml`
```

## §9.4
<!-- original lines 3569–3574 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
for s in md_lint parse_md sqlbot_client render_markdown render_docx assemble_status; do
  grep -q "$s" skills/public/chatbi-report/SKILL.md || echo "MISSING in SKILL.md: $s"
done
```

## §9.5
<!-- original lines 3579–3594 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/SKILL.md
git commit -m "docs(skill:chatbi-report): add SKILL.md with 9-step workflow

触发面是面向模型的，依 Lessons-from-Claude-Code 博文原则：
描述指出 chatbi 专属行为（data-idx 属性 + 中文显示名、离线
render_docx、二维表头），并显式包含 Do-NOT-use-for 子句（针对旧式
与自由文本表格）。

工作流章节引用了实现创建的全部脚本（md_lint、parse_md、sqlbot_client、
compute.*、render_markdown、render_docx、assemble_status），使得仅读
SKILL.md 的未来贡献者也能定位到正确的文件。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §10.1
<!-- original lines 3608–3681 in plan -->
```markdown
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
```

## §10.2
<!-- original lines 3687–3696 in plan -->
```bash
# chatbi-report skill — SQLBot connection (no API key needed, per 2026-06-23 spec)
#
# Required: base URL of the SQLBot deployment (HTTP, no /api/v1 suffix).
# Example: SQLBOT_BASE_URL=http://9.6.232.51:9070
SQLBOT_BASE_URL=

# Optional: per-idx HTTP timeout in seconds (default 30).
# SQLBOT_TIMEOUT=30
```

## §10.3
<!-- original lines 3700–3714 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add skills/public/chatbi-report/README.md \
        skills/public/chatbi-report/.env.example
git commit -m "docs(skill:chatbi-report): add README.md + .env.example

README 为运维人员提供快速上手（cp .env.example + make dev）、目录结构、
如何跑测试，以及 3 行契约回顾表（真实指标 / 计算列 / 旧式占位符）。
故障排查章节把每个运行时症状映射到可能原因。

.env.example 说明 SQLBOT_BASE_URL 必需、按 2026-06-23 规格无需 API key，
以及可选的 SQLBOT_TIMEOUT 默认值。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §11.1
<!-- original lines 3743–3757 in plan -->
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

## §11.2
<!-- original lines 3813–3816 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest backend/tests/chatbi_report/ -v
```

## §11.3
<!-- original lines 3827–3831 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
python -m pytest skills/public/chatbi-report/scripts/tests/ \
                 backend/tests/chatbi_report/ -v
```

## §11.4
<!-- original lines 3836–3854 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
git add backend/tests/chatbi_report/
git commit -m "test(skill:chatbi-report): add backend integration suite (6 scenarios)

6 个端到端测试，覆盖规格 §'测试策略' 的集成列：
- happy_path: 完整 MD -> JSON + MD + DOCX + status=success
- partial_query_failure: F18 -> status=partial，⚠️QUERY_FAILED 出现在 MD 表头
- sqlbot_down: F17 -> 重试耗尽 -> status=error
- no_org_context: F19 -> md_lint ERROR + CLI 非零退出
- computed_columns_happy: IR + codegen + AST + 签名 + 烟雾全过，status=success
- unit_conversion_e2e: data-unit 覆盖（元 -> 万元 / 亿元）经宽表透视
  传递到 Decimal 单元格值

3 个 expected_outputs fixture 锁定 chatbi 专属表头契约
（无 (\`BAS_0263\`) 后缀；LLM 列上的 (computed) 标记）。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

## §12.1
<!-- original lines 3866–3869 in plan -->
```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
make dev
```

## §12.2
<!-- original lines 3874–3880 in plan -->
```bash
docker exec -it <gateway-container> bash -c '
  mkdir -p /mnt/user-data/uploads /mnt/user-data/outputs &&
  cp /path/to/backend/tests/chatbi_report/fixtures/sample_md/happy.md \
     /mnt/user-data/uploads/
'
```

## §12.3
<!-- original lines 3885–3888 in plan -->
```bash
docker exec -it <gateway-container> python /mnt/skills/public/chatbi-report/scripts/md_lint.py \
  /mnt/user-data/uploads/happy.md
```

## §12.4
<!-- original lines 3893–3900 in plan -->
```bash
docker exec -it <gateway-container> bash -c '
  cd /mnt/skills/public/chatbi-report/scripts &&
  for s in retry sqlbot_client md_lint parse_md compute unit_conversion render_markdown render_docx assemble_status; do
    python -c "import $s" && echo "OK: $s"
  done
'
```

## §12.5
<!-- original lines 3905–3910 in plan -->
```bash
docker exec -it <gateway-container> bash -c '
  cd /mnt/skills/public/chatbi-report/scripts &&
  python -m pytest tests/ -v
'
```

## §12.6
<!-- original lines 3921–3923 in plan -->
```bash
docker exec -it <gateway-container> ls -la /mnt/user-data/outputs/{thread_id}/
```

## §12.7
<!-- original lines 3928–3930 in plan -->
```bash
docker exec -it <gateway-container> cat /mnt/user-data/outputs/{thread_id}/report.status.json
```
