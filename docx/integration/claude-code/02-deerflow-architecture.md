# DeerFlow 关键架构速查

> 基于 codegraph 探索 + CLAUDE.md + 关键源文件阅读整理
> 用于回顾"SDK 集成应该接在哪一层的"前置参考

## 一、仓库结构

```
deer-flow/
├── config.example.yaml          # 主配置（acp_agents 段在 735-756）
├── config.yaml                  # 实际配置（gitignored）
├── extensions_config.json       # MCP 服务器 + 技能开关
├── backend/
│   ├── langgraph.json           # 图入口：deerflow.agents:make_lead_agent
│   ├── pyproject.toml           # Python 依赖
│   ├── packages/harness/deerflow/   # 公开包，import prefix: deerflow.*
│   │   ├── agents/
│   │   │   ├── lead_agent/      # make_lead_agent、_build_middlewares
│   │   │   ├── middlewares/     # 18 个中间件
│   │   │   ├── memory/          # 记忆存储、更新
│   │   │   └── thread_state.py
│   │   ├── subagents/           # SubagentExecutor + 配置
│   │   ├── tools/builtins/      # invoke_acp_agent_tool、tool_search、task_tool
│   │   ├── sandbox/             # 沙箱接口 + bash/ls/read/write/str_replace
│   │   ├── mcp/                 # MCP 多服务器集成
│   │   ├── models/              # 模型工厂 + vLLM
│   │   ├── skills/              # 技能发现 / 加载
│   │   ├── config/              # 配置系统 + ACP/Subagent/AppConfig
│   │   ├── community/           # 外部集成（aio_sandbox、dify、tavily、jina、...）
│   │   ├── runtime/             # RunManager、StreamBridge、Journal
│   │   ├── reflection/          # 动态模块/类加载
│   │   └── client.py            # 嵌入式 DeerFlowClient
│   ├── app/                     # 应用层，import prefix: app.*
│   │   ├── gateway/             # FastAPI Gateway（routers/, services.py）
│   │   └── channels/            # IM 集成：飞书 / Slack / Telegram / 微信 / 企业微信
│   └── tests/
├── frontend/                    # Next.js 16
└── skills/                      # Agent 技能（public/ 内置，custom/ 自定义）
```

## 二、运行时模式

| 模式 | 进程数 | Lead agent 跑在哪 |
|---|---|---|
| **Standard**（`make dev`） | 4 | LangGraph server（2024）—— `langgraph.json` 入口 `make_lead_agent` |
| **Gateway / dev-pro**（`make dev-pro`） | 3 | Gateway（8001）进程内 `RunManager.run_agent()` + `StreamBridge` |
| **Docker Dev** | 容器化 | 跟 Standard 一样 |
| **Docker Prod** | 容器化 | 跟 Standard 一样 |

**Nginx 路由**：

- `/api/langgraph/*` → LangGraph（2024）/ Gateway 嵌入 runtime（8001）
- `/api/*` → Gateway（8001）
- `/` → Frontend（3000）

## 三、关键调用链（Gateway 模式）

```
HTTP POST /api/threads/{thread_id}/runs/stream
  └─ app/gateway/routers/thread_runs.py:stream_run
       └─ app/gateway/services.py:start_run
            └─ RunManager.create → RunRecord
            └─ asyncio.create_task → runtime/runs/worker.py:run_agent
                 ├─ RunJournal (event_store)
                 ├─ bridge.publish('metadata', {run_id, thread_id})
                 ├─ resolve_agent_factory(config) → deerflow.agents.lead_agent.agent:make_lead_agent
                 ├─ agent = make_lead_agent(config)
                 └─ async for chunk in agent.astream(config=..., stream_modes=['values', 'updates', 'messages']):
                      bridge.publish(run_id, event, data)
                 └─ bridge.publish_end(run_id)
SSE
  └─ bridge.subscribe(run_id) → stream_bridge/memory.py
       └─ async for stream_event in bridge.subscribe(run_id): yield SSE formatted
```

## 四、Lead Agent 中间件链（18 个，严格顺序）

`agents/lead_agent/agent.py:_build_middlewares` 构造：

1. `ThreadDataMiddleware` —— 给每线程建独立目录
2. `UploadsMiddleware` —— 把上传文件注入 context
3. `SandboxMiddleware` —— 拿沙箱
4. `DanglingToolCallMiddleware` —— 补 placeholder ToolMessage
5. `LLMErrorHandlingMiddleware` —— 归一化 provider 错误
6. `GuardrailMiddleware` —— 工具调用前鉴权（可选）
7. `SandboxAuditMiddleware` —— 沙箱审计日志
8. `ToolErrorHandlingMiddleware` —— 工具异常转可恢复错误
9. `SummarizationMiddleware` —— token 触顶时压缩（可选）
10. `TodoListMiddleware` —— 计划模式多步跟踪（可选）
11. `TokenUsageMiddleware` —— token 指标（可选）
12. `TitleMiddleware` —— 自动生成会话标题
13. `MemoryMiddleware` —— 排队异步记忆更新
14. `ViewImageMiddleware` —— 视觉模型注图
15. `DeferredToolFilterMiddleware` —— 隐藏 defer 工具直到 search
16. `SubagentLimitMiddleware` —— 限最多 3 个并发子代理
17. `LoopDetectionMiddleware` —— 重复工具循环检测停
18. `ClarificationMiddleware` —— 拦截 clarification（**必须最后**）

> `SafetyFinishReasonMiddleware` 会在自定义中间件之后、Clarification 之前插入。

## 五、子代理子系统

| 文件 | 职责 |
|---|---|
| `subagents/executor.py` | `SubagentExecutor.execute()` —— 独立事件循环线程跑，跑完 join |
| `subagents/executor.py:_get_isolated_subagent_loop` | 每线程一个 event loop（避开 LangGraph 同步） |
| `config/subagents_config.py` | `SubagentConfig` / `load_subagents_config_from_dict` |
| `tools/builtins/task_tool.py:187` | `task_tool` —— lead agent 委派入口 |
| `agents/lead_agent/agent.py:make_lead_agent` | 把 `task_tool` 加到 lead agent 工具列表 |

子代理**复用同一模型工厂**（`deerflow.models.create_chat_model`），**限 3 并发、15 分钟超时**。

## 六、ACP 集成（已有）—— SDK 集成的对位参考

| 文件 | 职责 |
|---|---|
| `config/acp_config.py` | `ACPAgentConfig(command, args, env, description, model, auto_approve_permissions)` |
| `tools/builtins/invoke_acp_agent_tool.py:139` | `build_invoke_acp_agent_tool(agents)` 工厂 |
| `tools/builtins/invoke_acp_agent_tool.py:165` | `_invoke(agent, prompt, config)` —— 工具闭包 |
| `tools/builtins/invoke_acp_agent_tool.py:181-207` | `_CollectingClient(Client)` —— ACP 客户端，收集 `session_update` 文本 |
| `tools/builtins/invoke_acp_agent_tool.py:226-242` | `spawn_agent_process(client, cmd, *args, env, cwd)` 起 ACP 适配器子进程 |
| `tools/tools.py:44` | `get_available_tools()` —— 注入到 lead agent 工具列表 |

**调用模式**：lead agent 调 `invoke_acp_agent(agent="claude_code", prompt="...")` → 起 ACP 子进程 → 收完整文本 → 整段返回 ToolMessage。

**缺点**（SDK 路径可补足）：

- 不流式，前端看不到"Claude Code 在干活"
- 不支持 hooks（只能 `request_permission` 一次决策）
- 不支持自定义工具（要另外起 MCP 子进程）
- 不支持 sessions / resume
- 不支持 file checkpointing

## 七、社区集成模式（`community/`）

已有：

- `aio_sandbox/` —— 沙箱 provider
- `dify/` —— Dify HTTP API 包装
- `ddg_search/` `exa/` `firecrawl/` `infoquest/` `jina_ai/` `serper/` `tavily/` —— 搜索 providers

`dify/` 是个有用的**自包含集成**模板：

```
dify/
├── dify_client.py    # HTTP 客户端
├── router.py         # FastAPI 路由
└── workflows/
    ├── __init__.py
    ├── aml.py
    ├── document_review.py
    ├── general.py
    ├── image_recognition.py
    ├── knowledge.py
    ├── policy_qa.py
    └── writing.py
```

—— 跟 ACP 工具不同，`dify/` 是**完全独立**的 HTTP 端点，不通过 lead agent 委派。

## 八、配置边界

- `deerflow.*`（harness 包）—— 公开，可单独发布为 `deerflow-harness` PyPI 包；**禁止 import `app.*`**
- `app.*` —— 应用层；**不发布**
- 由 `backend/tests/test_harness_boundary.py` 在 CI 强制
- 集成 SDK 时，**新代码全部进 `deerflow.*`**（社区模式放 `community/claude_code_agent/`）

## 九、sandbox 与工具

- 沙箱通过 `deerflow.sandbox.sandbox_provider` 注册（`aio_sandbox` provider 是默认）
- 沙箱工具（`bash_tool`、`ls_tool`、`read_file_tool` 等）都是 `BaseTool`（LangChain）
- `sandbox/tools.py:1329+` —— `bash_tool`、`ls_tool`、`read_file_tool` 实现
- `tools/tools.py:44` —— `get_available_tools()` 收集所有 `BaseTool`
- **SDK 子代理可以直接复用这些 `BaseTool`** —— 把它们包成 `create_sdk_mcp_server` 的 `@tool` 即可

## 十、模型工厂

- `deerflow.models.create_chat_model(name, thinking_enabled, app_config)` —— 主入口
- `models/factory.py:50` —— 实现
- 支持 OpenAI、Anthropic、vLLM、Codex、MindIE 等
- 跟模型相关的 token 计量通过 `TokenUsageMiddleware` 透出
- **子代理用 `inherit` 模式**：子代理 `model: null` 时继承 lead agent 的模型；可单独覆盖走别的模型（如本地 Ollama）
- SDK 路径需要决定：`ClaudeSDKClient` 是不是用 DeerFlow 配的模型（建议：DeerFlow 配什么 Claude，SDK 就用同一个）

## 十一、关键文件位置速查

| 概念 | 文件 |
|---|---|
| Lead agent 工厂 | `backend/packages/harness/deerflow/agents/lead_agent/agent.py:378` |
| Lead agent 中间件构造 | `backend/packages/harness/deerflow/agents/lead_agent/agent.py:266` |
| `task_tool`（子代理入口） | `backend/packages/harness/deerflow/tools/builtins/task_tool.py:187` |
| `SubagentExecutor` | `backend/packages/harness/deerflow/subagents/executor.py` |
| `invoke_acp_agent` 工具 | `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py:139` |
| ACP 配置 | `backend/packages/harness/deerflow/config/acp_config.py` |
| `make_chat_model` | `backend/packages/harness/deerflow/models/factory.py:50` |
| `RunManager` | `backend/packages/harness/deerflow/runtime/runs/manager.py:106` |
| `run_agent` worker | `backend/packages/harness/deerflow/runtime/runs/worker.py:124` |
| `StreamBridge` 抽象 | `backend/packages/harness/deerflow/runtime/stream_bridge/base.py:37` |
| `MemoryStreamBridge` | `backend/packages/harness/deerflow/runtime/stream_bridge/memory.py:25` |
| `start_run` 网关入口 | `backend/app/gateway/services.py:265` |
| `/threads/{id}/runs/stream` | `backend/app/gateway/routers/thread_runs.py:148` |
| Harness 边界测试 | `backend/tests/test_harness_boundary.py` |
| ACP 集成测试 | `backend/tests/test_invoke_acp_agent_tool.py` |
| 配置 ACP 段 | `config.example.yaml:735-756` |
| ACP 测试用 doc | `docx/integration/claude-code/claude-agent-sdk-smoke-test-summary.md` |
