# DeerFlow 代码事实表（HUIClaw / Phase 0）

> **仓库快照**：本文件依据当前 Fork 内源码整理，供 HUIClaw 扩展与上游合并时对照。  
> **若上游变更**：以 `upstream/main` 中 `deerflow.agents.lead_agent.agent` 与 `thread_state` 为准，并更新本表。

---

## 1. 请求路径（本地开发）

| 环节 | 说明 |
|------|------|
| 入口 | 浏览器 / 客户端 → **Nginx** `localhost:2026`（`docker/nginx/nginx.local.conf`） |
| 网关 | **Gateway (FastAPI)** `127.0.0.1:8001`，统一 `/api/*` |
| LangGraph | **LangGraph CLI** `127.0.0.1:2024`，经 Nginx 映射为 `/api/langgraph/*` |
| 前端 | **Next.js** `127.0.0.1:3000` |
| 图定义 | `backend/langgraph.json` → `graphs.lead_agent` = `deerflow.agents:make_lead_agent` |
| Checkpoint | `checkpointer` → `async_provider.py:make_checkpointer`（异步持久化） |

---

## 2. `ThreadState`（图状态模式）

**定义文件**：`backend/packages/harness/deerflow/agents/thread_state.py`

**基类**：`langchain.agents.AgentState`（兼容 LangGraph `state_schema`）。

| 字段 | 类型/说明 |
|------|-----------|
| （AgentState 基类字段） | `messages` 等，见 LangChain |
| `sandbox` | `SandboxState \| None`，沙箱 id |
| `thread_data` | `ThreadDataState \| None`，工作区/上传/输出路径 |
| `title` | `str \| None` |
| `artifacts` | `list[str]`，带 **merge_artifacts** 归约 |
| `todos` | `list \| None` |
| `uploaded_files` | `list[dict] \| None` |
| `viewed_images` | 带 **merge_viewed_images** 归约 |
| **HUIClaw 扩展** | `huiclaw_persona`、`huiclaw_lifecycle_state`、`huiclaw_persona_version`（`NotRequired`，默认未设置即等价 `None`） |

---

## 3. Middleware 链顺序（Lead Agent）

**组装函数**：`deerflow.agents.lead_agent.agent._build_middlewares()`  
**运行时基链**：`build_lead_runtime_middlewares()` → `_build_runtime_middlewares(include_uploads=True, include_dangling_tool_call_patch=True)`

### 3.1 基链 `build_lead_runtime_middlewares`（按 `_build_runtime_middlewares` 顺序）

| # | 类 | 备注 |
|---|-----|------|
| 1 | `ThreadDataMiddleware` | 注释要求须在 Sandbox 之前 |
| 2 | `UploadsMiddleware` | 依赖 thread_id |
| 3 | `SandboxMiddleware` | |
| — | `DanglingToolCallMiddleware` | 若 `include_dangling_tool_call_patch` |
| — | `GuardrailMiddleware` | 若 guardrails 配置启用 |
| 末 | `ToolErrorHandlingMiddleware` | 基链末尾 |

### 3.2 `_build_middlewares` 中**追加**顺序（在基链之后）

| # | 组件 | 条件 |
|---|------|------|
| A | `SummarizationMiddleware` | `summarization.enabled` |
| B | `TodoMiddleware` | `configurable.is_plan_mode` |
| C | `TokenUsageMiddleware` | `app_config.token_usage.enabled` |
| D | `TitleMiddleware` | 始终 |
| E | `MemoryMiddleware` | 始终（在 Title 之后） |
| F | `ViewImageMiddleware` | 当前模型 `supports_vision` |
| G | `DeferredToolFilterMiddleware` | `tool_search.enabled` |
| H | `SubagentLimitMiddleware` | `subagent_enabled` |
| I | `LoopDetectionMiddleware` | 始终 |
| **末** | `ClarificationMiddleware` | **始终最后**（源码注释） |

**HUIClaw PersonaMiddleware 插入约束（v0.3）**：在 Summarization **之后**、Clarification **之前**；若与事实冲突，在本表注明取舍。

---

## 4. Tool 注册与加载

**入口**：`deerflow.tools.tools.get_available_tools(...)`

| 来源 | 行为 |
|------|------|
| **config.yaml** `tools:` | 列表项含 `name`、`group`、`use:`（**可导入路径** `module:attr`），经 `deerflow.reflection.resolve_variable` 实例化为 `BaseTool` |
| **tool_groups** | Agent 可通过 `groups` 过滤子集 |
| **内置** | `present_file_tool`、`ask_clarification_tool`；可选 `task_tool`（subagent）、`view_image_tool`（vision 模型） |
| **MCP** | `extensions_config`（如 `extensions_config.json`）+ `get_cached_mcp_tools()`；`tool_search` 开启时改为延迟注册 + `tool_search` 工具 |
| **ACP** | `acp_agents` 配置时注入 `invoke_acp_agent` |

---

## 5. Skill 与配置

| 项 | 说明 |
|----|------|
| **config.yaml** `skills:` | `path`（主机技能目录）、`container_path`（容器内挂载路径，默认 `/mnt/skills`） |
| **加载** | `deerflow.config.skills_config.SkillsConfig`、`deerflow.skills.loader`（详见 `get_skills_root_path()`） |
| **仓库** | 仓库根目录 `skills/public/`、`skills/custom/` 等；与 Agent 提示词/沙箱内路径联动 |

---

## 6. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-03-28 | 初版：基于当前 `huiclaw/dev` 与 `lead_agent/agent.py` 整理；Middleware 数量为「基链 + 条件追加」，非固定 9/11。 |
| 2026-03-28 | Phase 0：`backend/tests/test_huiclaw_phase0.py` 验证 `huiclaw_*` 经 **MemorySaver** 异步/同步路径读回；`config.example.yaml` 含 `huiclaw.enabled`。 |

---

## 7. 测试锚点（HUIClaw）

- **`backend/tests/test_huiclaw_phase0.py`**：`ThreadState` + LangGraph `MemorySaver` 的 checkpoint 往返；`AppConfig` 接受 `huiclaw:` 顶级键。  
- **依赖快照**：`deps-snapshot.txt`（升级前可 diff）。
