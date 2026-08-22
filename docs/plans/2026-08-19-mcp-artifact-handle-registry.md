# Spec: MCP 工具产物持久化句柄注册表（Artifact Handle Registry）

**关联 Issue**: [#4676](https://github.com/bytedance/deer-flow/issues/4676) — [feat] 为 MCP 协议工具产物提供通用句柄以支持可持久化引用
**范围**: 后端 harness + 中间件 + state schema + 前端渲染
**依赖**: 无（独立实现，可与 #4652 MCP Tasks 扩展协议并存）
**状态**: 草案（待评审）

---

## 1. 问题描述

MCP 工具在 `ToolMessage.content` 中返回文件路径、task_id、资源 URI 等结构化引用。当 `SummarizationMiddleware` 压缩上下文时，这些引用被 LLM 摘要为自然语言（存储在 `summary_text`），原始结构化引用丢失，导致后续工具无法确定性地消费上游产物。

**具体场景**：
```
轮次1: 用户 → "分析这个数据集"
轮次2: Agent 调用 mcp_server_analyze(dataset.csv) → 返回 {file_path: "/mnt/user-data/outputs/report.html", summary: "..."}
轮次3-N: 多轮对话，触发上下文压缩
  → ToolMessage 被 RemoveMessage 删除，摘要写"生成了 report.html"
轮次N+1: 用户 → "把那个报告发给 QA 工具"
  → Agent 幻觉路径，或重新问用户
```

### 现有机制的断点（代码级）

1. **`ToolMessage.artifact` 只存 `structuredContent`** — `backend/packages/harness/deerflow/mcp/tools.py:429-432` 中，仅 MCP 的 `structuredContent` 字段被保存为 artifact；普通文本返回的文件路径、`ResourceLink` 的 URL、`ImageContent` 的 base64 数据都不进入 artifact，只存在于 `content` 列表中。
2. **上下文压缩不保留 tool_call_id 链** — `backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py:603-613` 中，压缩后 `messages` 被 `RemoveMessage(id=REMOVE_ALL_MESSAGES)` 清空重建，旧的 `ToolMessage`（含 `tool_call_id`）被删除，结构化映射丢失。
3. **`DurableContextMiddleware` 只捕获 `task` 委托** — `backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py:225-235` 中，`extract_delegations()` 只匹配 `tool_name == "task"` 的调用；普通 MCP 工具的产物不在捕获范围内。

## 2. 目标

1. **捕获** — 从 MCP 工具结果（及任何产生产物的工具）中提取产物引用，存入持久化注册表，存续于压缩之后。
2. **注入** — 将产物元数据注入模型上下文，使 LLM 能通过短句柄引用产物。
3. **解析** — 在工具调用时，将参数中的短句柄解析为真实引用，再传给下游 MCP 工具。
4. **展示** — 在前端工具调用步骤 UI 中展示产物引用。
5. **共存** — 叠加在现有机制之上（`ToolOutputBudgetMiddleware`、`DurableContextMiddleware`、`ThreadState.artifacts`），不破坏它们。

## 3. 非目标

- 后台轮询 / 任务生命周期管理（由 #4652 MCP Tasks 覆盖）。
- 产物文件存储 / 提供（现有 artifact API 处理）。
- 跨线程产物共享（所有权限定为 thread 级）。
- 前端产物编辑（现有 artifact panel 处理）。

---

## 4. 数据模型

### 4.1 `ArtifactEntry`（新增 TypedDict，放 `thread_state.py`）

```python
class ArtifactEntry(TypedDict):
    """从工具结果中捕获的产物引用。"""
    handle: str                    # 短稳定引用，如 "art_3a7f2b"（8位hex）
    tool_name: str                 # 产出该产物的工具名
    tool_call_id: str              # 对应的 AIMessage.tool_calls[].id
    call_index: int                # 批次内 0-based 序号
    artifact_type: str             # "file" | "image" | "resource" | "task_id" | "data"
    display_name: str              # 人类可读：文件名、描述、或截断内容预览
    real_ref: str                  # 真实引用：文件路径、URL、task_id 等
    mime_type: NotRequired[str]    # MIME 类型（如已知）
    created_at: str                # ISO 8601 时间戳
    consumed_by: NotRequired[list[str]]  # 消费过该句柄的 tool_call_id 列表
```

### 4.2 `ThreadState` 新增字段

```python
class ThreadState(AgentState):
    # ... 现有字段 ...
    tool_artifacts: Annotated[list[ArtifactEntry], merge_tool_artifacts]
```

### 4.3 Reducer：`merge_tool_artifacts`

```python
_ARTIFACT_MAX_ENTRIES = 100

def merge_tool_artifacts(
    existing: list[ArtifactEntry] | None,
    new: list[ArtifactEntry] | None,
) -> list[ArtifactEntry]:
    """追加新产物；按 handle 去重；保留最近 N 条。"""
    if not new:
        return existing or []
    by_handle: dict[str, ArtifactEntry] = {}
    order: list[str] = []
    for entry in [*(existing or []), *new]:
        h = entry["handle"]
        if h not in by_handle:
            order.append(h)
        by_handle[h] = entry  # 最新的覆盖旧的
    merged = [by_handle[h] for h in order]
    if len(merged) > _ARTIFACT_MAX_ENTRIES:
        merged = merged[-_ARTIFACT_MAX_ENTRIES:]
    return merged
```

### 4.4 注册到 `THREAD_STATE_REDUCER_FIELDS`

```python
THREAD_STATE_REDUCER_FIELDS = frozenset({
    "messages", "sandbox", "artifacts", "todos", "goal",
    "viewed_images", "promoted", "delegations", "skill_context",
    "tool_artifacts",  # ← 新增
})
```

---

## 5. 句柄生成

格式：`art_` + 8位 hex，由 `(thread_id, tool_call_id, call_index)` 确定性派生：

```python
# 新模块: backend/packages/harness/deerflow/tools/artifact_registry.py

import hashlib

_HANDLE_PREFIX = "art_"
_HANDLE_LENGTH = 8

def generate_handle(thread_id: str, tool_call_id: str, call_index: int) -> str:
    """确定性短句柄。相同输入 → 相同句柄。"""
    seed = f"{thread_id}:{tool_call_id}:{call_index}"
    digest = hashlib.sha256(seed.encode()).hexdigest()[:_HANDLE_LENGTH]
    return f"{_HANDLE_PREFIX}{digest}"
```

**碰撞安全性**：`tool_call_id` 在一个 AIMessage 内唯一，`call_index` 区分同一批次的多个调用。不同线程不会共享 state，因此无碰撞风险。

---

## 6. 从工具结果中提取产物

### 6.1 提取逻辑（`artifact_registry.py`）

```python
def extract_artifacts_from_result(
    result: ToolMessage,
    *,
    thread_id: str,
    call_index: int = 0,
) -> list[ArtifactEntry]:
    """从 ToolMessage 的 content 和 artifact 字段中提取产物引用。"""
    entries = []
    now = _utc_now_iso()
    tool_name = result.name or "unknown"
    tool_call_id = result.tool_call_id or ""

    # 路径1：ToolMessage.artifact（MCP structuredContent）
    if result.artifact and isinstance(result.artifact, dict):
        sc = result.artifact.get("structured_content")
        if sc is not None:
            entries.append(_make_entry(
                handle=generate_handle(thread_id, tool_call_id, call_index),
                tool_name=tool_name, tool_call_id=tool_call_id,
                call_index=call_index, artifact_type="data",
                display_name=f"{tool_name} 的结构化结果",
                real_ref=json.dumps(sc)[:500], created_at=now,
            ))
            return entries

    # 路径2：Content blocks（file、image、resource）
    content = result.content
    if isinstance(content, str):
        return entries
    if not isinstance(content, list):
        return entries

    for i, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type == "file":
            source = block.get("source", {})
            url = source.get("url") or ""
            if url:
                entries.append(_make_entry(
                    handle=generate_handle(thread_id, tool_call_id, call_index + i),
                    tool_name=tool_name, tool_call_id=tool_call_id,
                    call_index=call_index + i, artifact_type="file",
                    display_name=url.split("/")[-1] or url,
                    real_ref=url, mime_type=source.get("mime_type"),
                    created_at=now,
                ))

        elif block_type == "image":
            source = block.get("source", {})
            url = source.get("url")
            if url:
                entries.append(_make_entry(
                    handle=generate_handle(thread_id, tool_call_id, call_index + i),
                    tool_name=tool_name, tool_call_id=tool_call_id,
                    call_index=call_index + i, artifact_type="image",
                    display_name=f"{tool_name} 的图片",
                    real_ref=url, mime_type=source.get("mime_type"),
                    created_at=now,
                ))

        elif block_type == "text":
            # 保守策略：检测文本中的文件路径和 URL
            text = block.get("text", "")
            for ref in _detect_refs_in_text(text):
                entries.append(_make_entry(
                    handle=generate_handle(thread_id, tool_call_id, call_index + i),
                    tool_name=tool_name, tool_call_id=tool_call_id,
                    call_index=call_index + i,
                    artifact_type=ref["type"],
                    display_name=ref["display"],
                    real_ref=ref["ref"],
                    created_at=now,
                ))

    return entries


def _detect_refs_in_text(text: str) -> list[dict]:
    """从文本中检测文件路径和 URL。"""
    refs = []
    # 匹配 /mnt/user-data/... 路径（sandbox 虚拟路径）
    for match in re.finditer(r'/mnt/user-data/\S+', text):
        path = match.group(0).rstrip('.,;:)')
        refs.append({
            "type": "file",
            "ref": path,
            "display": path.split("/")[-1],
        })
    # 匹配指向文件的 https URL
    for match in re.finditer(r'https?://\S+\.(?:png|jpg|jpeg|html|pdf|csv|json|txt|log)', text):
        url = match.group(0).rstrip('.,;:)')
        refs.append({
            "type": "file",
            "ref": url,
            "display": url.split("/")[-1],
        })
    return refs
```

### 6.2 为什么不在 `_convert_call_tool_result()` 中直接做？

转换函数是纯函数（MCP 结果 → LangChain 内容块）。产物提取是**横切关注点**，适用于所有工具（不仅是 MCP）。独立为注册表模块的好处：

- 内置工具返回文件路径也能被捕获。
- 中间件可通过配置开关，不触碰 MCP 代码。
- 提取逻辑可独立测试。

---

## 7. 中间件：`ArtifactCaptureMiddleware`

### 7.1 在中间件链中的位置

```
ToolErrorHandlingMiddleware      （包装异常，盖章 deerflow_tool_meta）
    ↓
ArtifactCaptureMiddleware        ← 新增（从结果中捕获产物）
    ↓
ToolOutputBudgetMiddleware       （截断/外部化超大输出）
    ↓
ToolResultSanitizationMiddleware （中和注入标签）
```

**位置理由**：必须在 `ToolErrorHandlingMiddleware` 之后（结果已成型），在 `ToolOutputBudgetMiddleware` 之前（捕获完整内容，不被截断）。产物注册表只存轻量元数据（句柄 + 真实引用），不存内容本体，截断不影响它。

### 7.2 实现方式：`before_model` hook

**关键决策**：不在 `wrap_tool_call` 中用 `Command(update=...)` 包装结果（会替换 ToolMessage）。改用 `before_model` hook，与 `DurableContextMiddleware._capture_delegations()` 完全一致的模式：

```python
# 新模块: backend/packages/harness/deerflow/agents/middlewares/artifact_capture_middleware.py

class ArtifactCaptureMiddleware(AgentMiddleware[AgentState]):
    """从工具结果中捕获产物引用到 ThreadState.tool_artifacts。

    运行在 before_model hook（不是 wrap_tool_call），
    扫描尚未捕获的最新 ToolMessage，提取产物，返回 state update。
    """

    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        existing = state.get("tool_artifacts") or []
        existing_call_ids = {e["tool_call_id"] for e in existing}

        thread_id = runtime.context.get("thread_id", "")
        if not thread_id:
            return None

        new_entries = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            if message.tool_call_id in existing_call_ids:
                continue
            if message.status == "error":
                continue

            entries = extract_artifacts_from_result(
                message,
                thread_id=thread_id,
                call_index=0,
            )
            new_entries.extend(entries)

        if new_entries:
            return {"tool_artifacts": new_entries}
        return None

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)
```

---

## 8. 模型上下文注入

### 8.1 注入点：`DurableContextMiddleware`

扩展现有的 `DurableContextMiddleware`，将 `tool_artifacts` 投影到每个模型请求的隐藏 `HumanMessage` 数据块中：

```python
# 在 durable_context_middleware.py 中，扩展 _build_durable_context_block()

def _build_artifact_section(self, state: AgentState) -> str | None:
    artifacts = state.get("tool_artifacts") or []
    if not artifacts:
        return None

    lines = ["## 可用产物引用"]
    lines.append("以下是工具产出的持久化句柄。在工具参数中使用它们来引用产物。")
    lines.append("")

    for entry in artifacts:
        consumed = entry.get("consumed_by", [])
        status = "[已消费]" if consumed else "[可用]"
        mime = f" ({entry['mime_type']})" if entry.get("mime_type") else ""
        lines.append(f"- `{entry['handle']}` → {entry['artifact_type']}: {entry['display_name']}{mime} {status}")
        lines.append(f"  来源: {entry['tool_name']} (call {entry['tool_call_id'][:12]})")

    return "\n".join(lines)
```

### 8.2 LLM 看到的内容（注入后）

```
## 可用产物引用
以下是工具产出的持久化句柄。在工具参数中使用它们来引用产物。

- `art_3a7f2b1c` → file: report.html (text/html) [可用]
  来源: mcp_server_analyze (call call_a1b2c3d4e5f6)
- `art_8e4d9f2a` → image: chart.png (image/png) [可用]
  来源: mcp_chart_gen (call call_f6e5d4c3b2a1)
```

### 8.3 上下文压缩后的行为

| 数据 | 压缩后保留？ | 机制 |
|---|---|---|
| `messages`（ToolMessages） | 否 — 被 `RemoveMessage(REMOVE_ALL_MESSAGES)` 删除 | 摘要文本 |
| `ThreadState.tool_artifacts` | **是** — channel state，不是 messages | `merge_tool_artifacts` reducer |
| `ThreadState.delegations` | 是 — 同一模式 | `merge_delegations` reducer |
| `ThreadState.skill_context` | 是 — 同一模式 | `merge_skill_context` reducer |

---

## 9. 工具参数句柄解析

### 9.1 新中间件：`ArtifactResolutionMiddleware`

在工具执行**之前**，将参数中的句柄解析为真实引用：

```python
# 新模块: backend/packages/harness/deerflow/agents/middlewares/artifact_resolution_middleware.py

class ArtifactResolutionMiddleware(AgentMiddleware[AgentState]):
    """将工具参数中的产物句柄解析为真实引用。"""

    _HANDLE_PATTERN = re.compile(
        r'`(art_[0-9a-f]{8})`|(?<!\w)(art_[0-9a-f]{8})(?!\w)'
    )

    def wrap_tool_call(self, request, handler):
        args = request.tool_call.get("args", {})
        if not isinstance(args, dict):
            return handler(request)

        state = request.state
        artifacts = state.get("tool_artifacts") or []
        handle_map = {a["handle"]: a for a in artifacts}

        resolved_args = self._resolve_args(args, handle_map)
        if resolved_args != args:
            request = request._replace(
                tool_call={**request.tool_call, "args": resolved_args}
            )

        return handler(request)

    async def awrap_tool_call(self, request, handler):
        args = request.tool_call.get("args", {})
        if not isinstance(args, dict):
            return await handler(request)

        state = request.state
        artifacts = state.get("tool_artifacts") or []
        handle_map = {a["handle"]: a for a in artifacts}

        resolved_args = self._resolve_args(args, handle_map)
        if resolved_args != args:
            request = request._replace(
                tool_call={**request.tool_call, "args": resolved_args}
            )

        return await handler(request)

    def _resolve_args(self, args: dict, handle_map: dict) -> dict:
        """递归解析字符串值中的产物句柄。"""
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_string(value, handle_map)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, handle_map)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_string(v, handle_map) if isinstance(v, str)
                    else self._resolve_args(v, handle_map) if isinstance(v, dict)
                    else v
                    for v in value
                ]
            else:
                resolved[key] = value
        return resolved

    def _resolve_string(self, text: str, handle_map: dict) -> str:
        """将产物句柄替换为真实引用。"""
        def replace_handle(match):
            handle = match.group(1) or match.group(2)
            entry = handle_map.get(handle)
            if entry:
                return entry["real_ref"]
            return match.group(0)
        return self._HANDLE_PATTERN.sub(replace_handle, text)
```

### 9.2 消费追踪

在 `ArtifactCaptureMiddleware.before_model` 中，同时扫描 `AIMessage.tool_calls` 的参数，记录哪些句柄被消费了：

```python
def _track_consumption(self, state, runtime):
    messages = state.get("messages", [])
    existing = state.get("tool_artifacts") or []
    if not existing:
        return None

    handle_map = {a["handle"]: a for a in existing}
    consumed_updates = []

    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in (message.tool_calls or []):
            args = tool_call.get("args", {})
            if not isinstance(args, dict):
                continue
            found_handles = _find_handles_in_values(args)
            for handle in found_handles:
                if handle in handle_map:
                    entry = handle_map[handle]
                    if tool_call["id"] not in entry.get("consumed_by", []):
                        consumed_updates.append({
                            **entry,
                            "consumed_by": [*entry.get("consumed_by", []), tool_call["id"]],
                        })

    if consumed_updates:
        return {"tool_artifacts": consumed_updates}
    return None
```

---

## 10. 配置

```yaml
# config.yaml
tool_artifacts:
  enabled: true            # 默认开启
  max_entries: 100         # 每线程最大产物数
  detect_refs_in_text: true   # 保守文本扫描（检测路径/URL）
  inject_model_context: true  # 将句柄投影到 LLM 上下文
```

```python
# deerflow/config/tool_artifact_config.py

class ToolArtifactConfig(BaseModel):
    enabled: bool = Field(default=True)
    max_entries: int = Field(default=100, ge=10, le=1000)
    detect_refs_in_text: bool = Field(default=True)
    inject_model_context: bool = Field(default=True)
```

---

## 11. API 接口

### 11.1 无新增端点

产物注册表是 state channel-only。现有端点已暴露 `ThreadState`：

- `GET /api/threads/{id}` → 返回值中包含 `tool_artifacts`
- `GET /api/langgraph/threads/{id}/state` → 同上

### 11.2 流式传输

`tool_artifacts` 在 `values` stream 模式下自动包含（它是带 reducer 的 `ThreadState` 字段）。

---

## 12. 前端变更

### 12.1 类型扩展

```typescript
// frontend/src/core/threads/types.ts

export interface ArtifactEntry {
  handle: string;
  tool_name: string;
  tool_call_id: string;
  artifact_type: "file" | "image" | "resource" | "task_id" | "data";
  display_name: string;
  real_ref: string;
  mime_type?: string;
  created_at: string;
  consumed_by?: string[];
}

export interface AgentThreadState extends Record<string, unknown> {
  // ... 现有字段 ...
  tool_artifacts?: ArtifactEntry[];
}
```

### 12.2 工具调用步骤渲染

在 `message-group.tsx` 的 `convertToSteps()` 中，为产出产物的工具调用附加产物数据：

```typescript
// 构建 step 后，检查该工具调用是否产出了产物
const artifacts = state.tool_artifacts ?? [];
const producedArtifacts = artifacts.filter(
  a => a.tool_call_id === tool_call.id
);
if (producedArtifacts.length > 0) {
  step.artifacts = producedArtifacts;
}
```

### 12.3 产物徽章 UI

```tsx
// 在 ToolCall 组件中，工具名展示之后
{step.artifacts && step.artifacts.length > 0 && (
  <div className="artifact-badges">
    {step.artifacts.map(a => (
      <span key={a.handle} className="artifact-badge" title={a.real_ref}>
        {a.artifact_type === "file" ? <FileIcon /> : <DataIcon />}
        {a.display_name}
        <code>{a.handle}</code>
      </span>
    ))}
  </div>
)}
```

---

## 13. 文件清单

| 新增/修改 | 路径 | 用途 |
|---|---|---|
| **新增** | `backend/packages/harness/deerflow/tools/artifact_registry.py` | 句柄生成、提取、文本检测 |
| **新增** | `backend/packages/harness/deerflow/config/tool_artifact_config.py` | 配置 schema |
| **新增** | `backend/packages/harness/deerflow/agents/middlewares/artifact_capture_middleware.py` | 捕获 + 消费追踪 |
| **新增** | `backend/packages/harness/deerflow/agents/middlewares/artifact_resolution_middleware.py` | 工具参数句柄解析 |
| **修改** | `backend/packages/harness/deerflow/agents/thread_state.py` | 新增 `ArtifactEntry`、`tool_artifacts` 字段、reducer |
| **修改** | `backend/packages/harness/deerflow/agents/middlewares/durable_context_middleware.py` | 注入产物句柄到模型上下文 |
| **修改** | `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` | 追加中间件到链 |
| **修改** | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | 接入配置 + 中间件 |
| **修改** | `backend/packages/harness/deerflow/config/app_config.py` | 注册 `tool_artifacts` 配置 |
| **修改** | `frontend/src/core/threads/types.ts` | 新增 `ArtifactEntry` 类型 |
| **修改** | `frontend/src/components/workspace/messages/message-group.tsx` | 渲染产物徽章 |
| **新增** | `backend/tests/test_artifact_registry.py` | 单元测试 |
| **新增** | `backend/tests/test_artifact_capture_middleware.py` | 中间件测试 |
| **新增** | `backend/tests/test_artifact_resolution_middleware.py` | 解析测试 |

---

## 14. 测试计划

### 14.1 单元测试（`test_artifact_registry.py`）

| 用例 | 验证点 |
|---|---|
| `test_generate_handle_deterministic` | 相同输入 → 相同句柄 |
| `test_generate_handle_unique` | 不同输入 → 不同句柄 |
| `test_extract_from_file_block` | ResourceLink → ArtifactEntry type="file" |
| `test_extract_from_image_block` | ImageContent → ArtifactEntry type="image" |
| `test_extract_from_text_with_path` | 文本含 `/mnt/user-data/...` → ArtifactEntry |
| `test_extract_from_structured_content` | structuredContent → ArtifactEntry type="data" |
| `test_no_extraction_from_error_result` | 错误 ToolMessage → 空列表 |
| `test_no_extraction_from_plain_text` | 纯字符串 content → 空列表 |
| `test_merge_tool_artifacts_dedup` | 相同 handle → 最新覆盖 |
| `test_merge_tool_artifacts_cap` | 超过上限 → 保留最近 |
| `test_handle_pattern_detection` | 正则匹配 `art_3a7f2b1c` |

### 14.2 中间件测试（`test_artifact_capture_middleware.py`）

| 用例 | 验证点 |
|---|---|
| `test_capture_from_mcp_file_result` | MCP 文件 → state update 含产物 |
| `test_capture_from_mcp_image_result` | MCP 图片 → state update |
| `test_skip_error_result` | 错误 → 不捕获 |
| `test_dedup_existing` | 已捕获的 handle → 不重复捕获 |
| `test_track_consumption` | 工具参数含句柄 → consumed_by 更新 |

### 14.3 解析测试（`test_artifact_resolution_middleware.py`）

| 用例 | 验证点 |
|---|---|
| `test_resolve_single_handle` | `"use file art_3a7f2b1c"` → 真实路径 |
| `test_resolve_in_nested_args` | `{"path": "art_3a7f2b1c"}` → `{"path": "/mnt/user-data/..."}` |
| `test_resolve_in_list_args` | `["art_3a7f2b1c", "other"]` → `["真实路径", "other"]` |
| `test_no_resolve_unknown_handle` | 未知句柄 → 不变 |
| `test_no_resolve_non_string` | 非字符串值 → 不变 |

### 14.4 集成测试

| 用例 | 验证点 |
|---|---|
| `test_artifact_survives_summarization` | 创建产物 → 触发压缩 → `tool_artifacts` 仍存在 |
| `test_artifact_visible_in_model_context` | 隐藏 HumanMessage 含产物区段 |
| `test_full_cycle_mcp_to_resolution` | MCP 返回文件 → 捕获 → 模型看到句柄 → 模型用句柄调工具 → 解析 → 正确路径 |

---

## 15. 迁移与向后兼容

- `tool_artifacts` 字段使用 `Annotated[list[ArtifactEntry], merge_tool_artifacts]` — 现有线程默认空列表。
- 无需数据库迁移（checkpoint schema 通过 TypedDict 自描述）。
- 配置默认 `enabled: true` — 仅需 opt-out。
- 前端优雅处理缺失的 `tool_artifacts`（可选字段，`?? []`）。

## 16. 待确认问题

1. **句柄呈现形式**：LLM 看到的句柄用反引号包裹（`` `art_3a7f2b1c` ``）还是裸文本？反引号有助于正则检测，但部分模型会将其视为代码。
2. **多调用批次序号**：`call_index` 假设顺序执行。同一 AIMessage 中的并行工具调用，顺序取决于 LangGraph 的 dispatch 合约，需确认。
3. **句柄过期策略**：超过上限时自动淘汰，还是支持显式"关闭/释放"语义？MVP 仅做上限淘汰。

---

## 17. 实施拆解

**预估工作量**：后端 ~800 行 + 前端 ~100 行 + 测试 ~600 行。可拆为 3 个 PR：

1. **PR 1（基础设施）**：State schema + 注册表 + 捕获中间件 + 单元测试
2. **PR 2（解析与注入）**：解析中间件 + 模型上下文注入 + 中间件测试
3. **PR 3（前端）**：前端渲染 + 集成测试
