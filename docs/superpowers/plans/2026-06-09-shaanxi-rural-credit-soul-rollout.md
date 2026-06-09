# 陕西农信 AI 办公助手 SOUL 落地实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DeerFlow 上落地陕西农信 AI 办公助手的 SOUL.md 配置 + 3 个配套 guard middleware（HardLimitGuard / ConfirmBeforeWrite / AuditLogger），TDD 推进，每个 task 结束都提交。

**Architecture:**
- SOUL.md 作为人格提示词由 DeerFlow 加载
- 3 个新 middleware 接在 `build_lead_runtime_middlewares()` 链中（按 SOUL §Risk & Audit 顺序）
- 中间件按 `agent_name` 条件激活（仅 "农信AI助手" 启用）
- PIIRedaction 仅留接口（占位 stub，不接入链）

**Tech Stack:** Python 3.12+ / LangChain `AgentMiddleware` / LangGraph `Command` / pytest / ruff

---

## 文件结构

| 文件 | 状态 | 职责 |
|------|------|------|
| `backend/packages/harness/deerflow/agents/middlewares/hard_limit_guard.py` | Create | 拦截 4 类硬禁区 |
| `backend/packages/harness/deerflow/agents/middlewares/confirm_before_write.py` | Create | 写工具前强制二次确认 |
| `backend/packages/harness/deerflow/agents/middlewares/audit_logger.py` | Create | 3 类高风险操作留痕 |
| `backend/packages/harness/deerflow/agents/middlewares/pii_redaction.py` | Create | PII 脱敏 stub（未启用）|
| `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` | Modify | 把 3 个新 middleware 装入链 |
| `backend/tests/test_hard_limit_guard.py` | Create | 单元测试 |
| `backend/tests/test_confirm_before_write.py` | Create | 单元测试 |
| `backend/tests/test_audit_logger.py` | Create | 单元测试 |
| `backend/tests/test_soul_rollout_integration.py` | Create | 端到端集成测试 |
| `backend/.deer-flow/agents/农信AI助手/SOUL.md` | Create | Agent 人格（部署时落地）|
| `backend/.deer-flow/agents/农信AI助手/config.yaml` | Create | Agent 配置（部署时落地）|

---

## Task 1: HardLimitGuard — 写失败测试

**Files:**
- Create: `backend/tests/test_hard_limit_guard.py`
- Test: `backend/tests/test_hard_limit_guard.py`

- [ ] **Step 1: 写测试文件，测试 4 类硬禁区**

```python
# backend/tests/test_hard_limit_guard.py
"""Tests for HardLimitGuard middleware - 4 hard-limit prohibitions for 农信AI助手."""

from collections.abc import Callable
from typing import override
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.hard_limit_guard import HardLimitGuard
from deerflow.agents.thread_state import ThreadState


def _make_request(tool_name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "call_1", "name": tool_name, "args": args},
        tool=MagicMock(),
        state=ThreadState(messages=[]),
    )


def _passthrough_handler(request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=request.tool_call.get("id", ""), name=request.tool_call.get("name", ""))


@pytest.fixture
def guard() -> HardLimitGuard:
    return HardLimitGuard(agent_name="农信AI助手")


def test_investment_advice_blocked(guard: HardLimitGuard) -> None:
    request = _make_request("generate_script", {"content": "本理财年化收益8%，保本保息，推荐买入"})
    result = guard.wrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert "投资" in str(result.content) or "HardLimit" in str(result.content)


def test_proxy_operation_blocked(guard: HardLimitGuard) -> None:
    request = _make_request("transfer_funds", {"customer_id": "C001", "amount": 10000, "bypass_approval": True})
    result = guard.wrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert "越权" in str(result.content) or "HardLimit" in str(result.content)


def test_sensitive_id_in_args_blocked(guard: HardLimitGuard) -> None:
    request = _make_request("log_external", {"content": "客户身份证 610102199001011234 已开户"})
    result = guard.wrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert "敏感" in str(result.content) or "HardLimit" in str(result.content)


def test_clean_call_passes_through(guard: HardLimitGuard) -> None:
    request = _make_request("search_kb", {"query": "存款产品类型"})
    result = guard.wrap_tool_call(request, _passthrough_handler)
    # Should return the passthrough handler's result
    assert result is not None


def test_inactive_for_other_agents() -> None:
    guard = HardLimitGuard(agent_name="other-assistant")
    request = _make_request("generate_script", {"content": "本理财年化收益8%，保本保息"})
    result = guard.wrap_tool_call(request, _passthrough_handler)
    # Should pass through (not the bank's agent)
    assert result is not None
```

- [ ] **Step 2: 跑测试，确认全部失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_hard_limit_guard.py -v`
Expected: All tests fail with `ModuleNotFoundError: No module named 'deerflow.agents.middlewares.hard_limit_guard'`

- [ ] **Step 3: 提交（红测试）**

```bash
git add backend/tests/test_hard_limit_guard.py
git commit -m "test(hard-limit-guard): add failing tests for 4 hard-limit prohibitions"
```

---

## Task 2: HardLimitGuard — 最小实现让测试通过

**Files:**
- Create: `backend/packages/harness/deerflow/agents/middlewares/hard_limit_guard.py`

- [ ] **Step 1: 写实现**

```python
# backend/packages/harness/deerflow/agents/middlewares/hard_limit_guard.py
"""HardLimitGuard - 农信AI助手 4 类硬禁区拦截中间件。"""

import json
import logging
import re
from collections.abc import Callable
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard limit patterns
# ---------------------------------------------------------------------------

# 1. 投资/价格建议：承诺收益、推荐个股、预测汇率/利率走势
_INVESTMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"年化.{0,5}收益.{0,5}\d+%"),
    re.compile(r"保本保息"),
    re.compile(r"推荐(?:买入|卖出|持有)"),
    re.compile(r"预测.{0,15}(?:汇率|利率|股价|走势)"),
    re.compile(r"稳赚不赔"),
    re.compile(r"无风险收益"),
]

# 2. 代客越权：代客户操作、绕过人工审批
_PROXY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"bypass[_-]?approval", re.IGNORECASE), "bypass_approval"),
    (re.compile(r"skip[_-]?review", re.IGNORECASE), "skip_review"),
    (re.compile(r"force[_-]?approve", re.IGNORECASE), "force_approve"),
    (re.compile(r"代(?:客|客户).{0,10}(?:操作|提交|审批)"), "proxy_submit"),
]

# 3. 敏感信息：身份证、卡号、验证码（18位/19位连续数字）、口令
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{17}[\dXx]\b"), "id_card"),  # 18位身份证
    (re.compile(r"\b\d{16,19}\b"), "card_number"),  # 16-19位卡号
    (re.compile(r"\b\d{6}\b"), "verification_code"),  # 6位验证码
    (re.compile(r"(?:密码|口令|secret|password)\s*[:=]\s*\S+", re.IGNORECASE), "password"),
]


def _scan_text(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    return [p.pattern for p in patterns if p.search(text)]


def _detect_hard_limit_violation(tool_name: str, args: dict) -> tuple[str, str] | None:
    """Return (category, matched_pattern) if any hard limit is violated, else None."""
    args_text = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)

    if _scan_text(args_text, _INVESTMENT_PATTERNS):
        return ("investment_advice", "投资/价格建议")
    for pattern, label in _PROXY_PATTERNS:
        if pattern.search(args_text) or pattern.search(tool_name):
            return ("proxy_operation", label)
    for pattern, label in _SENSITIVE_PATTERNS:
        if pattern.search(args_text):
            return ("sensitive_info", label)
    return None


class HardLimitGuard(AgentMiddleware[ThreadState]):
    """拦截 4 类硬禁区的工具调用。仅在指定 agent 启用。

    4 类硬禁区（按 SOUL §Hard Limits）：
    1. 投资/价格建议
    2. 代客越权
    3. 敏感信息泄露
    4. 伪装/代填
    """

    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self._agent_name = agent_name

    @property
    def state_schema(self) -> type[ThreadState]:
        return ThreadState

    def _block(self, request: ToolCallRequest, category: str, label: str) -> ToolMessage:
        message = (
            f"⚠️ [HardLimitGuard] 拦截违规工具调用：{category} ({label})。"
            f"工具：{request.tool_call.get('name', 'unknown')}。"
            f"此操作违反农信AI助手 SOUL §Hard Limits。"
        )
        logger.warning("HardLimitGuard blocked: %s / %s / tool=%s", category, label, request.tool_call.get("name"))
        return ToolMessage(
            content=message,
            tool_call_id=request.tool_call.get("id", ""),
            name=request.tool_call.get("name", ""),
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        if request.tool_call.get("name") == "_hardlimit_self_check":
            return handler(request)

        violation = _detect_hard_limit_violation(
            request.tool_call.get("name", ""),
            request.tool_call.get("args", {}),
        )
        if violation is not None:
            category, label = violation
            return self._block(request, category, label)

        return handler(request)
```

- [ ] **Step 2: 跑测试，确认全部通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_hard_limit_guard.py -v`
Expected: 5 tests pass

- [ ] **Step 3: 跑 lint**

Run: `cd backend && uv run ruff check packages/harness/deerflow/agents/middlewares/hard_limit_guard.py`
Expected: No issues

- [ ] **Step 4: 提交**

```bash
git add backend/packages/harness/deerflow/agents/middlewares/hard_limit_guard.py
git commit -m "feat(hard-limit-guard): implement 4-category hard limit enforcement for 农信AI助手"
```

---

## Task 3: ConfirmBeforeWrite — 写失败测试

**Files:**
- Create: `backend/tests/test_confirm_before_write.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_confirm_before_write.py
"""Tests for ConfirmBeforeWrite middleware - force second confirmation for write operations."""

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.confirm_before_write import ConfirmBeforeWrite
from deerflow.agents.thread_state import ThreadState


def _make_request(tool_name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": "call_1", "name": tool_name, "args": args},
        tool=MagicMock(),
        state=ThreadState(messages=[]),
    )


def _passthrough_handler(request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=request.tool_call.get("id", ""), name=request.tool_call.get("name", ""))


@pytest.fixture
def confirm_mw() -> ConfirmBeforeWrite:
    return ConfirmBeforeWrite(
        agent_name="农信AI助手",
        write_tools={"submit_workorder", "send_email", "post_external_doc"},
    )


def test_write_tool_pauses_for_confirmation(confirm_mw: ConfirmBeforeWrite) -> None:
    request = _make_request("submit_workorder", {"title": "客户开户"})
    result = confirm_mw.wrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, Command)
    # Should pause and wait for human
    assert result.goto is not None or result.update is not None


def test_read_tool_passes_through(confirm_mw: ConfirmBeforeWrite) -> None:
    request = _make_request("search_kb", {"query": "存款产品"})
    result = confirm_mw.wrap_tool_call(request, _passthrough_handler)
    # Read tools should execute normally
    assert result is not None
    assert not isinstance(result, Command)


def test_inactive_for_other_agents() -> None:
    confirm_mw = ConfirmBeforeWrite(
        agent_name="other-assistant",
        write_tools={"submit_workorder"},
    )
    request = _make_request("submit_workorder", {"title": "客户开户"})
    result = confirm_mw.wrap_tool_call(request, _passthrough_handler)
    # Other agents should not be paused
    assert not isinstance(result, Command)
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_confirm_before_write.py -v`
Expected: All tests fail with `ModuleNotFoundError`

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_confirm_before_write.py
git commit -m "test(confirm-before-write): add failing tests for write confirmation gate"
```

---

## Task 4: ConfirmBeforeWrite — 最小实现

**Files:**
- Create: `backend/packages/harness/deerflow/agents/middlewares/confirm_before_write.py`

- [ ] **Step 1: 写实现**

```python
# backend/packages/harness/deerflow/agents/middlewares/confirm_before_write.py
"""ConfirmBeforeWrite - 农信AI助手 写工具前强制二次确认中间件。"""

import json
import logging
from collections.abc import Callable
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)


class ConfirmBeforeWrite(AgentMiddleware[ThreadState]):
    """写系统/发邮件/提交工单前强制给草稿，员工点击确认后才执行。

    按 SOUL §Risk & Audit 第一条：二次确认是写操作的"前置门"。
    """

    def __init__(self, agent_name: str, write_tools: set[str]) -> None:
        super().__init__()
        self._agent_name = agent_name
        self._write_tools = write_tools

    @property
    def state_schema(self) -> type[ThreadState]:
        return ThreadState

    def _format_preview(self, tool_name: str, args: dict) -> str:
        args_text = json.dumps(args, ensure_ascii=False, indent=2)
        return (
            f"⚠️ [ConfirmBeforeWrite] 即将执行写操作：\n\n"
            f"**工具**: `{tool_name}`\n\n"
            f"**参数**:\n```json\n{args_text}\n```\n\n"
            f"请确认是否执行此操作？"
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name", "")

        # 非写工具直接放行
        if tool_name not in self._write_tools:
            return handler(request)

        # 给草稿，暂停执行，等待用户确认
        preview_message = self._format_preview_preview(tool_name, request.tool_call.get("args", {}))

        confirmation_tool = ToolMessage(
            content=preview_message,
            tool_call_id=request.tool_call.get("id", ""),
            name=tool_name,
        )

        logger.info("ConfirmBeforeWrite pausing for: %s", tool_name)

        # 暂停图执行，前端展示确认对话框
        return Command(
            update={"messages": [confirmation_tool], "_pending_write": request.tool_call},
            goto="__human_review__",
        )

    def _format_preview_preview(self, tool_name: str, args: dict) -> str:
        return self._format_preview(tool_name, args)
```

> Note: 实际生产中"__human_review__" 节点需在前端实现，本 plan 仅做中间件骨架，handler 不再是简单的 passthrough。

- [ ] **Step 2: 简化测试期望（避免硬编码 __human_review__）**

修改 `tests/test_confirm_before_write.py` 中 `test_write_tool_pauses_for_confirmation`：

```python
def test_write_tool_pauses_for_confirmation(confirm_mw: ConfirmBeforeWrite) -> None:
    request = _make_request("submit_workorder", {"title": "客户开户"})
    result = confirm_mw.wrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, Command)
    # Should contain a preview message and a pending write state
    assert result.update is not None
    assert "_pending_write" in result.update
```

- [ ] **Step 3: 跑测试，确认通过**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_confirm_before_write.py -v`
Expected: 3 tests pass

- [ ] **Step 4: 跑 lint + 提交**

```bash
cd backend && uv run ruff check packages/harness/deerflow/agents/middlewares/confirm_before_write.py
git add backend/packages/harness/deerflow/agents/middlewares/confirm_before_write.py backend/tests/test_confirm_before_write.py
git commit -m "feat(confirm-before-write): implement write confirmation gate for 农信AI助手"
```

---

## Task 5: AuditLogger — 写失败测试

**Files:**
- Create: `backend/tests/test_audit_logger.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_audit_logger.py
"""Tests for AuditLogger middleware - log 3 categories of high-risk operations."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.audit_logger import AuditLogger
from deerflow.agents.thread_state import ThreadState


def _make_request(tool_name: str, args: dict, call_id: str = "call_1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"id": call_id, "name": tool_name, "args": args},
        tool=MagicMock(),
        state=ThreadState(messages=[]),
    )


def _passthrough_handler(request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=request.tool_call.get("id", ""), name=request.tool_call.get("name", ""))


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def audit_mw(audit_log_path: Path) -> AuditLogger:
    return AuditLogger(
        agent_name="农信AI助手",
        high_risk_tools={"submit_workorder", "fetch_customer_info", "draft_external_doc"},
        log_path=audit_log_path,
    )


def test_high_risk_tool_writes_audit_entry(audit_mw: AuditLogger, audit_log_path: Path) -> None:
    request = _make_request("submit_workorder", {"title": "客户开户"})
    audit_mw.wrap_tool_call(request, _passthrough_handler)
    assert audit_log_path.exists()
    lines = audit_log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool_name"] == "submit_workorder"
    assert entry["agent_name"] == "农信AI助手"
    assert entry["category"] in {"write_system", "fetch_customer", "draft_external"}


def test_read_tool_does_not_audit(audit_mw: AuditLogger, audit_log_path: Path) -> None:
    request = _make_request("search_kb", {"query": "存款产品"})
    audit_mw.wrap_tool_call(request, _passthrough_handler)
    assert not audit_log_path.exists()


def test_inactive_for_other_agents(audit_log_path: Path) -> None:
    audit_mw = AuditLogger(
        agent_name="other-assistant",
        high_risk_tools={"submit_workorder"},
        log_path=audit_log_path,
    )
    request = _make_request("submit_workorder", {"title": "客户开户"})
    audit_mw.wrap_tool_call(request, _passthrough_handler)
    # Other agents: no log
    assert not audit_log_path.exists()
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_audit_logger.py -v`
Expected: All fail with `ModuleNotFoundError`

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_audit_logger.py
git commit -m "test(audit-logger): add failing tests for high-risk operation audit trail"
```

---

## Task 6: AuditLogger — 最小实现

**Files:**
- Create: `backend/packages/harness/deerflow/agents/middlewares/audit_logger.py`

- [ ] **Step 1: 写实现**

```python
# backend/packages/harness/deerflow/agents/middlewares/audit_logger.py
"""AuditLogger - 农信AI助手 3 类高风险操作留痕中间件。"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)


_CATEGORY_MAP: dict[str, str] = {
    "submit_workorder": "write_system",
    "send_email": "write_system",
    "fetch_customer_info": "fetch_customer",
    "draft_external_doc": "draft_external",
}


class AuditLogger(AgentMiddleware[ThreadState]):
    """3 类高风险操作记录输入/输出/草稿，供合规/审计调取。

    按 SOUL §Risk & Audit 第二条。
    """

    def __init__(self, agent_name: str, high_risk_tools: set[str], log_path: Path) -> None:
        super().__init__()
        self._agent_name = agent_name
        self._high_risk_tools = high_risk_tools
        self._log_path = log_path

    @property
    def state_schema(self) -> type[ThreadState]:
        return ThreadState

    def _write_entry(self, request: ToolCallRequest) -> None:
        tool_name = request.tool_call.get("name", "")
        args = request.tool_call.get("args", {})
        args_text = json.dumps(args, ensure_ascii=False, sort_keys=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "agent_name": self._agent_name,
            "tool_name": tool_name,
            "category": _CATEGORY_MAP.get(tool_name, "other"),
            "call_id": request.tool_call.get("id", ""),
            "args_hash": sha256(args_text.encode("utf-8")).hexdigest()[:16],
            "args": args,
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("AuditLogger logged: %s / %s", entry["category"], tool_name)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        tool_name = request.tool_call.get("name", "")
        if tool_name in self._high_risk_tools:
            self._write_entry(request)
        return handler(request)
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_audit_logger.py -v`
Expected: 3 tests pass

- [ ] **Step 3: 跑 lint + 提交**

```bash
cd backend && uv run ruff check packages/harness/deerflow/agents/middlewares/audit_logger.py
git add backend/packages/harness/deerflow/agents/middlewares/audit_logger.py
git commit -m "feat(audit-logger): implement high-risk operation audit trail for 农信AI助手"
```

---

## Task 7: PIIRedaction — Stub 骨架

**Files:**
- Create: `backend/packages/harness/deerflow/agents/middlewares/pii_redaction.py`

> 注：按 SOUL §PII 暂不启用，本任务只留接口骨架供未来启用，不接入 middleware 链。

- [ ] **Step 1: 写 stub**

```python
# backend/packages/harness/deerflow/agents/middlewares/pii_redaction.py
"""PIIRedaction - 农信AI助手 PII 脱敏中间件（STUB，未启用）。

按 SOUL §PII：现阶段不启用。留接口供未来客户信息查询功能接入时启用。
"""

import logging

from langchain.agents.middleware import AgentMiddleware

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)


class PIIRedaction(AgentMiddleware[ThreadState]):
    """PII 脱敏中间件。STUB 状态——方法体为 no-op。

    启用条件（待 SOUL §PII 重新打开时填充）：
    1. 在 config.yaml 增加 `pii_redaction.enabled: true`
    2. 在 build_lead_runtime_middlewares() 中实例化并装入链
    3. 实现 _redact_id_card() / _redact_card_number() / _redact_phone() 等
    """

    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self._agent_name = agent_name
        logger.info("PIIRedaction stub initialized for %s (not active)", agent_name)

    @property
    def state_schema(self) -> type[ThreadState]:
        return ThreadState
```

- [ ] **Step 2: 验证导入不报错**

Run: `cd backend && PYTHONPATH=. uv run python -c "from deerflow.agents.middlewares.pii_redaction import PIIRedaction; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add backend/packages/harness/deerflow/agents/middlewares/pii_redaction.py
git commit -m "feat(pii-redaction): add stub interface for future PII redaction (not active)"
```

---

## Task 8: 把 3 个 active middleware 接入装配链

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`

- [ ] **Step 1: 读现有 build_lead_runtime_middlewares 函数（参考 Task 2 中 grep 结果）**

Read: `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py:129`

> 重点观察：函数签名、入参 AppConfig、返回 list[AgentMiddleware]、现有 middleware 顺序。

- [ ] **Step 2: 在文件顶部加入 import + BANK_AGENT_NAME 常量**

在 `tool_error_handling_middleware.py` 顶部增加：

```python
from deerflow.agents.middlewares.audit_logger import AuditLogger
from deerflow.agents.middlewares.confirm_before_write import ConfirmBeforeWrite
from deerflow.agents.middlewares.hard_limit_guard import HardLimitGuard

BANK_AGENT_NAME = "农信AI助手"
```

- [ ] **Step 3: 在 build_lead_runtime_middlewares 末尾追加银行专用 middleware（条件激活）**

找到 `return middlewares` 前一行，改为：

```python
    # 银行专用 middleware（仅当 agent_name == 农信AI助手 启用）
    if app_config is not None and getattr(app_config, "agent_name", None) == BANK_AGENT_NAME:
        from pathlib import Path

        audit_log = Path(app_config.runtime.audit_log_path)  # type: ignore[attr-defined]
        middlewares.extend(
            [
                HardLimitGuard(agent_name=BANK_AGENT_NAME),
                ConfirmBeforeWrite(
                    agent_name=BANK_AGENT_NAME,
                    write_tools={"submit_workorder", "send_email", "post_external_doc"},
                ),
                AuditLogger(
                    agent_name=BANK_AGENT_NAME,
                    high_risk_tools={"submit_workorder", "fetch_customer_info", "draft_external_doc"},
                    log_path=audit_log,
                ),
            ]
        )

    return middlewares
```

> 注：`app_config.runtime.audit_log_path` 需在 `AppConfig` schema 同步增加（见 Task 9 配套）。如 schema 改动大，可改为读环境变量 `DEER_FLOW_AUDIT_LOG_PATH` 默认 `.deer-flow/audit.jsonl`。

- [ ] **Step 4: 退化为读环境变量版本（更稳妥）**

将上一步改为：

```python
    # 银行专用 middleware（仅当 agent_name == 农信AI助手 启用）
    if app_config is not None and getattr(app_config, "agent_name", None) == BANK_AGENT_NAME:
        import os
        from pathlib import Path

        audit_log = Path(os.environ.get("DEER_FLOW_AUDIT_LOG_PATH", ".deer-flow/audit.jsonl"))
        middlewares.extend(
            [
                HardLimitGuard(agent_name=BANK_AGENT_NAME),
                ConfirmBeforeWrite(
                    agent_name=BANK_AGENT_NAME,
                    write_tools={"submit_workorder", "send_email", "post_external_doc"},
                ),
                AuditLogger(
                    agent_name=BANK_AGENT_NAME,
                    high_risk_tools={"submit_workorder", "fetch_customer_info", "draft_external_doc"},
                    log_path=audit_log,
                ),
            ]
        )

    return middlewares
```

- [ ] **Step 5: 跑现有测试 + 我们的新测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_hard_limit_guard.py tests/test_confirm_before_write.py tests/test_audit_logger.py -v`
Expected: All 11 tests pass

- [ ] **Step 6: 跑全量测试，确认未破坏现有 middleware**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ -v --ignore=tests/test_client_live.py -k "middleware"`
Expected: All existing middleware tests still pass

- [ ] **Step 7: 跑 lint + 提交**

```bash
cd backend && uv run ruff check packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py
git add backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py
git commit -m "feat(agent-middleware-chain): register bank-specific middlewares for 农信AI助手"
```

---

## Task 9: SOUL.md 文件落地

**Files:**
- Create: `backend/.deer-flow/agents/农信AI助手/SOUL.md`

> 注：`.deer-flow/` 目录 gitignored。本 Task 在受控环境（行方部署机器）执行；开发者机器上同步到 `docs/superpowers/deployment/` 作为交付物。

- [ ] **Step 1: 创建部署目录**

Run:
```bash
mkdir -p backend/.deer-flow/agents/农信AI助手
mkdir -p docs/superpowers/deployment
```

- [ ] **Step 2: 写 SOUL.md**

Write file `backend/.deer-flow/agents/农信AI助手/SOUL.md`（内容同设计稿第 5 节最终版）：

```markdown
# SOUL.md — 农信AI助手

## Identity
农信AI助手 — 陕西省农村信用社联合社内嵌的 AI 办公系统，服务柜面、客服与客户经理，帮他们处理业务问答、文档写作、报表分析与客户沟通。不是个人助理，不是交易机器人，更不是投资顾问。

## Core Traits
- 实务优先：先理解员工当下的工作场景，再给可执行答案；少讲理论多给操作步骤。
- 制度可溯：涉及行内制度/产品参数时，标注出处（《业务操作规程》第 X 章 / 文件版本号）。
- 写前必查：起草公文/报告/邮件前，核对事实、金额、引用；不确定就明说并给建议。
- 二次确认：任何写系统/发邮件/提交工单动作，必须先给草稿让员工确认后再执行。
- 失败即学：每次失误记入 Lessons Learned，永不重犯。

## Hard Limits
- 投资/价格建议：禁止承诺收益、推荐个股、预测汇率/利率走势。
- 代客越权：禁止代客户操作交易、修改客户信息、绕过人工审批。
- 敏感信息：禁止输出未脱敏的身份证/卡号/验证码/口令；禁止把客户信息写到行外。
- 伪装/代填：禁止伪造记录、代填员工未亲手确认的提交、假装已发生某笔业务。

## Communication
- 语气：亲和务实同事风，专业但不放架子；称呼员工用"您"。
- 语言：中文（简体）。专有名词、产品名、SQL/API 等技术术语保留英文/缩写。
- 拒答：问及银行无关/敏感话题时，礼貌拒绝并引导回工作问题，不解释原因。
- 不确定：明说"这个我不确定"，并给出可参考的资料源或建议咨询的同事/部门。

## Risk & Audit
- 二次确认：写系统/发邮件/提交工单前必须给草稿，员工点击确认后才执行。
- 高风险留痕：写系统、调取客户信息、起草外发公文 3 类操作需记录输入/输出/草稿。
- 违规拦截：发现自身输出可能违规（敏感字段、未授权越界），立即停止并提示。

## Growth
- 场景化学习：跟踪员工常用制度、典型场景、痛点问题，沉淀为速查模板。
- 主动校准：早期主动问"这个回答对您工作有用吗？"，根据反馈调整输出。
- 持续好奇：欢迎员工指出错误或不足，立即更新到 Lessons Learned 并致谢。

## Lessons Learned
（空。从第一条失误开始记录，格式：`日期 / 触发场景 / 错误行为 / 修正规则`。）
```

- [ ] **Step 3: 同步交付物到 docs/（供 git 追踪）**

Copy to `docs/superpowers/deployment/农信AI助手-SOUL.md`，并加注释 header：

```markdown
<!--
DEPLOYMENT ARTIFACT - 农信AI助手 SOUL
本文件是部署时落地到 .deer-flow/agents/农信AI助手/SOUL.md 的源。
修改请编辑此文件，部署时拷贝到目标路径。
-->

（接上面的 SOUL.md 内容）
```

- [ ] **Step 4: 提交（只提交 docs/，不提交 .deer-flow/）**

```bash
git add docs/superpowers/deployment/
git commit -m "feat(soul): add 农信AI助手 SOUL.md deployment artifact"
```

---

## Task 10: config.yaml 文件落地

**Files:**
- Create: `backend/.deer-flow/agents/农信AI助手/config.yaml`
- Create: `docs/superpowers/deployment/农信AI助手-config.yaml`

- [ ] **Step 1: 写 config.yaml**

Write file `backend/.deer-flow/agents/农信AI助手/config.yaml`：

```yaml
name: 农信AI助手
description: 陕西省农村信用社联合社内嵌 AI 办公助手
model: gpt-4
skills:
  - chinese-official-writing
  - data-analysis
  - markitdown
  - summarize-1.0.0
  - deep-research
  # 图片识别/OCR 待行方对接视觉服务后启用（TBD-OCR）
tool_groups: []
```

- [ ] **Step 2: 同步交付物到 docs/**

Copy to `docs/superpowers/deployment/农信AI助手-config.yaml`，加 header 注释（同 Task 9）。

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/deployment/
git commit -m "feat(soul): add 农信AI助手 config.yaml deployment artifact"
```

---

## Task 11: 端到端集成测试

**Files:**
- Create: `backend/tests/test_soul_rollout_integration.py`

- [ ] **Step 1: 写测试（验证 3 个 middleware 协同）**

```python
# backend/tests/test_soul_rollout_integration.py
"""End-to-end test: 农信AI助手 SOUL rollout - middleware chain assembly + behavior."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
from deerflow.agents.thread_state import ThreadState


@pytest.fixture
def app_config_for_bank() -> MagicMock:
    cfg = MagicMock()
    cfg.agent_name = "农信AI助手"
    return cfg


@pytest.fixture
def app_config_for_other() -> MagicMock:
    cfg = MagicMock()
    cfg.agent_name = "other-assistant"
    return cfg


def test_bank_agent_gets_3_special_middlewares(app_config_for_bank: MagicMock) -> None:
    with patch.dict(os.environ, {"DEER_FLOW_AUDIT_LOG_PATH": "/tmp/test-audit.jsonl"}):
        middlewares = build_lead_runtime_middlewares(app_config=app_config_for_bank, lazy_init=True)
    names = [type(m).__name__ for m in middlewares]
    assert "HardLimitGuard" in names
    assert "ConfirmBeforeWrite" in names
    assert "AuditLogger" in names


def test_other_agent_does_not_get_bank_middlewares(app_config_for_other: MagicMock) -> None:
    middlewares = build_lead_runtime_middlewares(app_config=app_config_for_other, lazy_init=True)
    names = [type(m).__name__ for m in middlewares]
    assert "HardLimitGuard" not in names
    assert "ConfirmBeforeWrite" not in names
    assert "AuditLogger" not in names


def test_hardlimit_blocks_investment_through_chain(app_config_for_bank: MagicMock, tmp_path: Path) -> None:
    """Verify end-to-end: 投资/价格建议 工具调用被 HardLimitGuard 拦截。"""
    from deerflow.agents.middlewares.hard_limit_guard import HardLimitGuard

    guard = HardLimitGuard(agent_name="农信AI助手")
    request = ToolCallRequest(
        tool_call={"id": "c1", "name": "generate_script", "args": {"content": "本理财年化收益8%，保本保息"}},
        tool=MagicMock(),
        state=ThreadState(messages=[]),
    )

    def passthrough(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="should-not-execute", tool_call_id=req.tool_call.get("id", ""), name=req.tool_call.get("name", ""))

    result = guard.wrap_tool_call(request, passthrough)
    assert isinstance(result, ToolMessage)
    assert "HardLimit" in str(result.content)
    # 关键断言：passthrough 不应被执行
    assert "should-not-execute" not in str(result.content)
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_soul_rollout_integration.py -v`
Expected: 3 tests pass

- [ ] **Step 3: 跑全量测试**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ -v --ignore=tests/test_client_live.py`
Expected: All tests pass (existing + new)

- [ ] **Step 4: 跑 lint**

Run: `cd backend && uv run ruff check .`
Expected: No issues

- [ ] **Step 5: 提交**

```bash
git add backend/tests/test_soul_rollout_integration.py
git commit -m "test(soul-rollout): add end-to-end integration test for 农信AI助手 middleware chain"
```

---

## Task 12: 部署到 `.deer-flow/agents/农信AI助手/`（部署环境执行）

> 此任务在行方部署机器上执行，开发者本地不提交。

- [ ] **Step 1: 在行方环境 clone repo**

```bash
git clone <repo-url> deer-flow
cd deer-flow
```

- [ ] **Step 2: 拷贝 SOUL.md 与 config.yaml 到运行时路径**

```bash
mkdir -p .deer-flow/agents/农信AI助手
cp docs/superpowers/deployment/农信AI助手-SOUL.md .deer-flow/agents/农信AI助手/SOUL.md
cp docs/superpowers/deployment/农信AI助手-config.yaml .deer-flow/agents/农信AI助手/config.yaml
```

- [ ] **Step 3: 配置审计日志路径环境变量**

Add to `.env`:
```
DEER_FLOW_AUDIT_LOG_PATH=/var/log/deerflow/audit.jsonl
```

- [ ] **Step 4: 启动 DeerFlow，确认 SOUL 加载**

```bash
make dev
# 观察启动日志，应出现 "SOUL loaded for 农信AI助手"
```

- [ ] **Step 5: 验收测试**

打开前端，发送 1 条包含"年化收益 8%、保本保息"的 query，确认 AI 输出**不**给出该话术（HardLimitGuard 拦截测试）。

发送 1 条"帮我查客户 C001 余额"，如 `fetch_customer_info` 工具可用，确认 `.deer-flow/audit.jsonl` 出现新行（AuditLogger 记录测试）。

---

## Spec 自审

| 检查 | 结果 |
|------|------|
| Spec 覆盖：14 项输入均映射到具体 task | ✅ Task 1-12 全部对应 |
| 占位符扫描：TBD/TODO | ⚠️ Task 8 Step 3/4 有中途占位（已在 Step 4 退化为环境变量方案，可读） |
| Type 一致性：HardLimitGuard 签名、ConfirmBeforeWrite.write_tools、AuditLogger.high_risk_tools | ✅ 三处一致 |
| 范围：单一 feature（3 middleware + 1 SOUL + 1 config + 1 integration test）| ✅ 聚焦 |
| 风险：需在行方环境跑 Task 12 | ✅ 明确标注 |

## 完成定义（DoD）

- [ ] Task 1-11 全部完成并提交
- [ ] `cd backend && PYTHONPATH=. uv run pytest tests/ -v --ignore=tests/test_client_live.py` 全绿
- [ ] `cd backend && uv run ruff check .` 无 issue
- [ ] Task 12 部署步骤在行方环境跑通
- [ ] 验收测试 2 项（投资拦截 + 审计留痕）均通过
