# GuardrailRequest 运行时归因上下文补充 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `GuardrailRequest` 新增 `user_id`、`run_id`、`tool_call_id` 三个 optional 字段，并在 `_build_request()` 中从 `ToolCallRequest.runtime.context` 和 `tool_call` 读取填充。

**Architecture:** 纯数据类扩字段 + middleware 内读取运行时已有上下文，不涉及新依赖或外部调用。MCP metadata、config 不变。

**Tech Stack:** Python 3.12+, dataclasses, langgraph ToolCallRequest/ToolRuntime, pytest

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| Modify | `backend/packages/harness/deerflow/guardrails/provider.py:9-19` | `GuardrailRequest` 数据类新增 3 个 optional 字段 |
| Modify | `backend/packages/harness/deerflow/guardrails/middleware.py:34-40` | `_build_request()` 从 `request.runtime.context` 和 `request.tool_call` 读取 |
| Modify | `backend/tests/test_guardrail_middleware.py` | 新增 7 个测试用例覆盖新字段和缺失场景 |

---

### Task 1: GuardrailRequest 字段扩展

**Files:**
- Modify: `backend/packages/harness/deerflow/guardrails/provider.py:9-19`

- [ ] **Step 1: 在 GuardrailRequest 数据类末尾新增 3 个 optional 字段**

```python
@dataclass
class GuardrailRequest:
    """Context passed to the provider for each tool call."""

    tool_name: str
    tool_input: dict[str, Any]
    agent_id: str | None = None
    thread_id: str | None = None
    is_subagent: bool = False
    timestamp: str = ""

    # Runtime attribution context — provider cannot reliably infer these
    user_id: str | None = None
    run_id: str | None = None
    tool_call_id: str | None = None
```

**改动要点：**
- 全部为 `str | None = None`
- 不修改现有字段
- 不修改 `GuardrailDecision` 或 `GuardrailReason`

- [ ] **Step 2: 运行现有测试确保未破坏已有行为**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_guardrail_middleware.py -v
```

Expected: 20+ tests passing (TestAllowlistProvider + TestGuardrailMiddleware + TestGuardrailsConfig)

- [ ] **Step 3: Commit**

```bash
git add backend/packages/harness/deerflow/guardrails/provider.py
git commit -m "feat(guardrails): add user_id/run_id/tool_call_id fields to GuardrailRequest"
```

---

### Task 2: _build_request 填充运行时上下文

**Files:**
- Modify: `backend/packages/harness/deerflow/guardrails/middleware.py:34-40`

- [ ] **Step 1: 重写 `_build_request` 方法**

替换现有的 `_build_request`（从 middleware.py 第 34 行开始）：

```python
def _build_request(self, request: ToolCallRequest) -> GuardrailRequest:
    # Read runtime context (thread_id, run_id, user_id)
    runtime = getattr(request, "runtime", None)
    ctx = getattr(runtime, "context", None) if runtime is not None else None
    ctx = ctx if isinstance(ctx, dict) else {}

    return GuardrailRequest(
        tool_name=str(request.tool_call.get("name", "")),
        tool_input=request.tool_call.get("args", {}),
        agent_id=self.passport,
        thread_id=ctx.get("thread_id"),
        timestamp=datetime.now(UTC).isoformat(),
        # Runtime attribution
        user_id=ctx.get("user_id"),
        run_id=ctx.get("run_id"),
        tool_call_id=request.tool_call.get("id"),
    )
```

**改动要点：**
- 不再手动构造空 dict 传给 `tool_input`、不再手动拼接 `thread_id`（之前未传）
- 新增 3 行：`runtime`/`ctx` 提取 + `user_id`/`run_id`/`tool_call_id` 字段
- `getattr` 安全防护：`request.runtime` 可能为 `None`（测试 mock 场景）
- `isinstance(ctx, dict)` 防护：`runtime.context` 可能是 `None` 或其他类型
- 保留原有 import：`ToolCallRequest`、`GuardrailRequest` 等已在顶楼导入，无需新增

确认 middleware.py 顶楼 import 不变（已包含所需模块）：

```python
from deerflow.guardrails.provider import GuardrailDecision, GuardrailProvider, GuardrailReason, GuardrailRequest
```

- [ ] **Step 2: 运行现有测试确保未破坏已有行为**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_guardrail_middleware.py -v
```

Expected: 所有原有测试继续通过。注意现有 `_make_tool_call_request` 返回的 MagicMock 不设 `runtime`，因此新的 `runtime` 提取路径应返回 `None` 并安全兜底——新字段均为 `None`，不影响现有断言。

- [ ] **Step 3: Commit**

```bash
git add backend/packages/harness/deerflow/guardrails/middleware.py
git commit -m "feat(guardrails): populate user_id/run_id/tool_call_id from runtime context"
```

---

### Task 3: 新增测试覆盖

**Files:**
- Modify: `backend/tests/test_guardrail_middleware.py`

需要在现有测试文件末尾（`TestGuardrailsConfig` 类之前或之后）新增 `TestGuardrailRequestAttribution` 测试类。

关键考虑：现有 `_make_tool_call_request` helper 创建的 MagicMock 没有 `runtime` 属性。为了测试新字段，需要一种方式创建带 `runtime.context` 的 mock。有两种方式：

1. 扩展 `_make_tool_call_request` 接受 `runtime_context` 参数
2. 在测试类中直接构造带 `runtime` 的 MagicMock

采用方式 2（更清晰，不修改已有 helper，避免波及现有测试）。

- [ ] **Step 1: 新增测试类 `TestGuardrailRequestAttribution`**

```python
class TestGuardrailRequestAttribution:
    """Tests for GuardrailRequest runtime attribution fields."""

    def _make_runtime_mock(self, context: dict | None = None):
        """Create a MagicMock with a ToolRuntime-like interface."""
        runtime = MagicMock()
        runtime.context = context
        return runtime

    def _make_request(
        self,
        runtime: Any = None,
        tool_call: dict | None = None,
        tool: Any = None,
    ) -> MagicMock:
        """Create a ToolCallRequest-like MagicMock."""
        req = MagicMock()
        req.runtime = runtime
        req.tool_call = tool_call or {"name": "bash", "args": {}, "id": "call_test"}
        req.tool = tool
        req.state = {}
        return req

    def test_user_id_from_runtime_context(self):
        runtime = self._make_runtime_mock(context={"user_id": "user_abc", "run_id": "run_xyz", "thread_id": "thread_123"})
        req = self._make_request(runtime=runtime)

        captured = {}

        class CaptureProvider:
            name = "capture"
            def evaluate(self, request):
                captured["user_id"] = request.user_id
                return GuardrailDecision(allow=True)
            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        assert captured["user_id"] == "user_abc"

    def test_run_id_from_runtime_context(self):
        runtime = self._make_runtime_mock(context={"user_id": "user_abc", "run_id": "run_xyz", "thread_id": "thread_123"})
        req = self._make_request(runtime=runtime)

        captured = {}

        class CaptureProvider:
            name = "capture"
            def evaluate(self, request):
                captured["run_id"] = request.run_id
                return GuardrailDecision(allow=True)
            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        assert captured["run_id"] == "run_xyz"

    def test_tool_call_id_from_tool_call(self):
        req = self._make_request(tool_call={"name": "web_search", "args": {"query": "test"}, "id": "call_42"})

        captured = {}

        class CaptureProvider:
            name = "capture"
            def evaluate(self, request):
                captured["tool_call_id"] = request.tool_call_id
                return GuardrailDecision(allow=True)
            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        assert captured["tool_call_id"] == "call_42"

    def test_thread_id_from_runtime_context(self):
        runtime = self._make_runtime_mock(context={"thread_id": "thread_789"})
        req = self._make_request(runtime=runtime)

        captured = {}

        class CaptureProvider:
            name = "capture"
            def evaluate(self, request):
                captured["thread_id"] = request.thread_id
                return GuardrailDecision(allow=True)
            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        assert captured["thread_id"] == "thread_789"

    def test_missing_runtime_context_fields_are_none(self):
        """No runtime set → all attribution fields default to None."""
        req = self._make_request(runtime=None)

        captured = {}

        class CaptureProvider:
            name = "capture"
            def evaluate(self, request):
                captured.update(user_id=request.user_id, run_id=request.run_id, tool_call_id=request.tool_call_id, thread_id=request.thread_id)
                return GuardrailDecision(allow=True)
            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        assert captured["user_id"] is None
        assert captured["run_id"] is None
        assert captured["thread_id"] is None
        # tool_call_id still has the value from tool_call dict
        assert captured["tool_call_id"] == "call_test"

    def test_missing_tool_call_id(self):
        """tool_call missing 'id' key → tool_call_id is None."""
        req = self._make_request(tool_call={"name": "bash", "args": {}})

        captured = {}

        class CaptureProvider:
            name = "capture"
            def evaluate(self, request):
                captured["tool_call_id"] = request.tool_call_id
                return GuardrailDecision(allow=True)
            async def aevaluate(self, request):
                return self.evaluate(request)

        mw = GuardrailMiddleware(CaptureProvider())
        mw.wrap_tool_call(req, MagicMock())
        assert captured["tool_call_id"] is None

    def test_existing_providers_backward_compat(self):
        """AllowlistProvider does not read new fields → still works."""
        provider = AllowlistProvider()
        req = GuardrailRequest(tool_name="bash", tool_input={})
        decision = provider.evaluate(req)
        assert decision.allow is True

        req2 = GuardrailRequest(tool_name="bash", tool_input={}, user_id="u1", run_id="r1", tool_call_id="c1")
        decision2 = provider.evaluate(req2)
        assert decision2.allow is True  # AllowlistProvider ignores new fields
```

- [ ] **Step 2: 运行新测试确保通过**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_guardrail_middleware.py::TestGuardrailRequestAttribution -v
```

Expected: 7 tests PASS

- [ ] **Step 3: 运行完整 guardrail 测试确保向后兼容**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_guardrail_middleware.py -v
```

Expected: 全部原有测试 + 新增测试通过。`_make_tool_call_request` 创建的 mock 没有 `runtime` 属性，`getattr(request, "runtime", None)` 返回 `None` → 新字段为 `None`，原有断言不变。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_guardrail_middleware.py
git commit -m "test(guardrails): add attribution field tests for GuardrailRequest"
```

---

## 自检清单

1. **Spec coverage:** ✓ `user_id`, `run_id`, `tool_call_id`, `thread_id` 四个字段均被覆盖（补填 thread_id 在 Task 2 中实现，测试在 Task 3 中）。全部 7 个测试用例与 spec 中的表格一一对应。
2. **无占位符:** ✓ 所有步骤包含完整代码和命令。
3. **类型一致性:** ✓ `user_id: str | None = None` 在 provider.py 定义、middleware.py 填充（`ctx.get("user_id")` 返回 `str | None`）、测试断言中保持一致。

## 执行交接

Plan 保存至 `docs/superpowers/plans/2026-06-19-guardrail-request-attribution.md`。两个执行选项：

**1. Subagent-Driven（推荐）** — 每个任务派发独立子 agent，任务间 review，快速迭代

**2. 当前会话内执行** — 使用 executing-plans，分 batch 带 checkpoint

选择哪个？