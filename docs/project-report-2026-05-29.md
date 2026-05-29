# EHM AI 工作台 (DeerFlow) 项目汇报

> 汇报日期：2026/05/29
> 汇报对象：CTO、产品部经理
> 编制角色：产品经理 × 项目经理 × 架构师 联合视角

---

## 一、产品概述

EHM AI 工作台（内部代号 DeerFlow）是一款面向工业设备管理领域的 **AI 超级智能体平台**。系统以 LangGraph 为智能体编排引擎，结合 Next.js 前端与 FastAPI 后端，为设备运维工程师、工厂管理者提供 **对话式智能分析** 能力。

**核心价值主张**：让设备运维人员通过自然语言对话，完成从数据查询、趋势分析、故障诊断到报告生成的全链路工作，降低工业数据分析门槛。

### 产品定位

| 维度 | 定位 |
|------|------|
| **目标用户** | 设备运维工程师、工厂管理者、可靠性工程师 |
| **核心场景** | 设备日报/周报/月报生成、故障诊断、趋势分析、闭环工单、知识库问答 |
| **差异化** | 工业领域深度集成（InS 数据源四系列、机组/泵/往复机诊断模型）、DSL 驱动的自定义报告平台、多级智能体协作 |
| **部署形态** | 私有化部署（Docker Compose），支持单机与 K8s |
| **接入方式** | Web UI (port 2026)、飞书/钉钉/Slack/Telegram/Discord/微信/企微 7 路 IM |

---

## 二、功能全景图

### 2.1 核心功能模块一览

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              EHM AI 工作台 功能全景                                │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬────────────────┤
│ 智能对话  │ 报告平台  │ 设备诊断  │ 知识管理  │ 闭环管理  │ 安全治理  │  平台管理      │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼────────────────┤
│ 多轮对话  │ DSL 模板  │ 故障诊断  │ RAG 检索  │ 工单状态机│ 内容安全  │  多级智能体    │
│ 流式输出  │ 可视化编辑│ 趋势分析  │ 文档转换  │ SLA 管控  │ 工具护栏  │  租户管理      │
│ 文件上传  │ 模板市场  │ 状态监测  │ 异步索引  │ 事件审计  │ PII 脱敏  │  MCP 工具      │
│ 多层记忆  │ 蓝图创建  │ 异常判定  │ 知识提取  │ 验证关闭  │ 提示注入  │  技能系统      │
│ 子智能体  │ 报告运行  │ 往复/旋转 │ KB 绑定   │ 改进建议  │ 费用管控  │  认证授权      │
│ 语音输入  │ MD/PDF 导出│ 机泵诊断 │ 反馈聚合  │ 记忆集成  │ 速率限制  │  服务发现      │
│ IM 7 路  │ 遥测监控  │          │ Embedding │          │ 预算告警  │  RPC 客户端    │
│ 计划模式  │ GenUI 渲染│          │           │          │          │  管理后台      │
│ 动态UI   │          │          │           │          │          │               │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴────────────────┘
```

---

## 三、系统架构

### 3.1 整体架构图

```
                                ┌──────────────────────────┐
                                │   用户终端                 │
                                │  Web 浏览器 / IM 客户端    │
                                └────────────┬─────────────┘
                                             │
                                ┌────────────▼─────────────┐
                                │    Nginx (port 2026)      │
                                │    统一反向代理 + 路由     │
                                │  /api/langgraph → :8001   │
                                │  /api/*         → :8001   │
                                │  /*             → :3000   │
                                └───┬────────────────┬─────┘
                                    │                │
                      ┌─────────────▼──┐    ┌────────▼─────────────┐
                      │   Frontend     │    │   Gateway API         │
                      │   Next.js 16   │    │   FastAPI (port 8001) │
                      │   React 19     │    │                       │
                      │   TS 5.8       │    │  ┌─────────────────┐  │
                      │   Tailwind v4  │    │  │  Auth Pipeline  │  │
                      │   pnpm 10.26   │    │  │  JWT + CSRF     │  │
                      │                │    │  │  + API Key      │  │
                      │  ┌──────────┐  │    │  └────────┬────────┘  │
                      │  │ TanStack │  │    │           │           │
                      │  │ Query    │  │    │  ┌────────▼────────┐  │
                      │  └──────────┘  │    │  │  45 REST Routers│  │
                      │  ┌──────────┐  │    │  └────────┬────────┘  │
                      │  │ LangGraph│  │    │           │           │
                      │  │ SDK      │  │    │  ┌────────▼────────┐  │
                      │  └──────────┘  │    │  │  Agent Runtime  │  │
                      └────────────────┘    │  │  (LangGraph)    │  │
                                            │  └────────┬────────┘  │
                                            │           │           │
                                            │  ┌────────▼────────┐  │
                                            │  │  IM Channels    │  │
                                            │  │  7 平台桥接      │  │
                                            │  └────────┬────────┘  │
                                            └───────────┼───────────┘
                                                        │
               ┌──────────────┬─────────────┬───────────┼───────────┬──────────────┐
               │              │             │           │           │              │
        ┌──────▼──────┐ ┌─────▼─────┐ ┌────▼─────┐ ┌───▼────┐ ┌────▼─────┐ ┌─────▼──────┐
        │ PostgreSQL  │ │  Chroma   │ │  文件    │ │ LLM    │ │  MCP     │ │ Nacos      │
        │ 主数据库     │ │  向量库   │ │  系统    │ │  服务   │ │  服务器   │ │ 服务发现    │
        │ (SQLAlchemy │ │ (文档     │ │ .deer-   │ │ GPT/   │ │ stdio/   │ │ + RPC      │
        │  Async)     │ │  Embedding)│ │ flow/   │ │ DS/Qwen│ │ SSE/HTTP │ │            │
        └─────────────┘ └───────────┘ └──────────┘ └────────┘ └──────────┘ └────────────┘
```

### 3.2 后端 Harness / App 双层架构

后端采用严格的 **Harness / App 双层分离**，单向依赖：App → Harness，由 CI 边界测试 `test_harness_boundary.py` 强制执行。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          App 层 (app/)                                  │
│                                                                         │
│   app/gateway/                          app/channels/                   │
│   ├── app.py          FastAPI 主入口     ├── base.py        渠道抽象基类  │
│   ├── auth/           认证子系统         ├── manager.py     消息调度核心  │
│   │   ├── jwt.py      JWT 签发/验证      ├── message_bus.py 异步 Pub/Sub │
│   │   ├── csrf_middleware.py             ├── store.py       会话持久化   │
│   │   ├── middleware.py 认证中间件        ├── feishu.py      飞书适配     │
│   │   ├── providers.py 多认证提供者       ├── dingtalk.py    钉钉适配     │
│   │   ├── repositories/ 凭证存储         ├── slack.py       Slack 适配   │
│   │   └── ins_base_provider.py InS认证   ├── telegram.py    TG 适配      │
│   ├── routers/ (45 个路由模块)           ├── discord.py     Discord 适配  │
│   │   ├── agents.py, auth.py, ...       ├── wechat.py      微信适配      │
│   │   ├── report_templates.py           ├── wecom.py       企微适配      │
│   │   ├── knowledge_bases.py            └── commands.py    命令路由      │
│   │   ├── closure_tickets.py, ...                                        │
│   │   └── tenant_*.py (多租户管理)
│   ├── middleware/rate_limit.py 速率限制
│   ├── authz.py 授权矩阵
│   └── services.py 服务编排
│
│  ═══════════════════ 依赖边界（Harness 禁止 import App）═══════════════
│
├─────────────────────────────────────────────────────────────────────────┤
│                       Harness 层 (deerflow/)                            │
│                                                                         │
│   deerflow/agents/              deerflow/report_templates/              │
│   ├── lead_agent/               ├── schema.py          DSL v1 Pydantic  │
│   │   ├── agent.py  Lead Agent  ├── validator.py       交叉引用校验     │
│   │   └── prompt.py 系统提示     ├── repository.py      模板仓储         │
│   ├── middlewares/ (18层)       ├── service.py         业务编排         │
│   ├── memory/ (三层记忆)        ├── script_registry.py 脚本注册表      │
│   ├── thread_state.py           ├── blueprint_*.py     蓝图系统         │
│   └── prompts/                  ├── package_io.py      包导入导出       │
│                                 ├── telemetry.py       遥测系统         │
│   deerflow/tools/               └── runtime/                            │
│   ├── builtins/ (16 个工具)         ├── state.py         状态机         │
│   ├── skill_manage_tool.py          ├── step_renderer.py 表单渲染       │
│   └── tools.py (工具组装)           ├── step_submitter.py 表单提交       │
│                                     ├── data_runner.py   数据执行       │
│   deerflow/integrations/            ├── payload_builder.py 载荷组装     │
│   ├── adapters/                     ├── report_renderer.py 报告渲染     │
│   │   ├── base.py 适配器协议        └── exporter.py      导出器         │
│   │   ├── crm/                      │                                   │
│   │   ├── erp/                  deerflow/knowledge_base/                │
│   │   ├── ins/ (4 系列适配)     ├── dispatcher.py   异步索引调度        │
│   │   └── sms/                  ├── indexing.py     索引执行器          │
│   ├── services/                 ├── retrieval.py    检索编排            │
│   ├── tools/                    ├── service.py      KB 服务             │
│   ├── models/ (领域模型)        └── telemetry.py    KB 遥测             │
│   ├── registry.py 适配器注册                                            │
│   └── routing.py 路由分发       deerflow/rag/                           │
│                                 ├── backends/                           │
│   deerflow/closed_loop/         │   ├── chroma.py    Chroma 后端        │
│   ├── state_machine.py          │   └── pgvector.py  PgVector 后端      │
│   ├── service.py                ├── chunking.py     文档分块             │
│   ├── repository.py             ├── embeddings.py   Embedding 管理      │
│   ├── events.py                 ├── ingestion.py    文档摄入             │
│   ├── permissions.py            ├── retrieval.py    向量检索             │
│   └── jobs.py                   └── tools.py        RAG 工具            │
│                                                                         │
│   deerflow/sandbox/            deerflow/memory → 见 §4.4 记忆系统       │
│   ├── sandbox.py 抽象接口      deerflow/subagents/                     │
│   ├── local/     本地提供者     ├── executor.py  后台执行引擎            │
│   ├── tools.py   5 个沙箱工具   ├── registry.py  Agent 注册表           │
│   └── middleware.py 生命周期     └── builtins/    内置子智能体            │
│                                                                         │
│   deerflow/runtime/            deerflow/models/                         │
│   ├── runs/                    ├── factory.py    模型工厂               │
│   │   ├── manager.py 运行管理   └── vllm_provider.py  vLLM 适配         │
│   │   └── worker.py  运行工作器                                          │
│   ├── checkpointer/  检查点     deerflow/mcp/                           │
│   ├── stream_bridge/ 流式桥接   ├── (MultiServerMCPClient)              │
│   ├── events/store/  事件存储   └── 懒加载 + mtime 缓存失效             │
│   └── journal.py     日志       deerflow/skills/  44 个技能包加载        │
│                                 deerflow/config/  配置系统               │
│   deerflow/cost/               deerflow/feedback/ 反馈存储               │
│   ├── budget.py 预算管控        deerflow/guardrails/ 工具护栏            │
│   ├── calculator.py 费用计算    deerflow/content_safety/ 内容安全         │
│   ├── notifications.py 告警    deerflow/audio/ ASR 语音转文字            │
│   ├── pg_storage.py PG 存储    deerflow/events/ 事件总线+Webhook        │
│   └── storage.py JSON 存储     deerflow/cache/ Embedding+语义缓存       │
│                                 deerflow/uploads/ 文件上传管理            │
│                                 deerflow/tracing/ 链路追踪               │
│                                 deerflow/persistence/ 持久化层           │
│                                 deerflow/client.py 嵌入式客户端           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 四、核心子系统深度解析

### 4.1 智能体系统

#### 4.1.1 Lead Agent 入口

Lead Agent 是整个系统的核心智能体，由 `make_lead_agent(config)` 工厂函数创建，注册在 `langgraph.json` 中。

**创建流程**：
1. `create_chat_model()` — 根据 `config.yaml` 中的模型配置实例化 LLM（支持 thinking/vision）
2. `get_available_tools()` — 组装工具集（沙箱 + 内置 + MCP + 社区 + 子智能体）
3. `apply_prompt_template()` — 生成系统提示（注入技能、记忆、子智能体指令）
4. `_build_middlewares()` — 装配 18 层中间件链

**ThreadState Schema**（`thread_state.py`）：

```python
class ThreadState(AgentState):
    sandbox: SandboxState          # sandbox_id
    thread_data: ThreadDataState   # workspace/uploads/outputs 路径
    title: str                     # 自动生成的对话标题
    artifacts: list[str]           # 产物列表（merge_artifacts 去重）
    todos: list                    # 计划模式任务列表
    uploaded_files: list[dict]     # 上传文件元数据
    viewed_images: dict            # 已查看图片 base64（merge_viewed_images）
```

#### 4.1.2 中间件链详解（18 层）

Lead Agent 的每次请求处理经过严格的中间件链，每层有明确的 before_model / after_model 钩子：

| # | 中间件 | 核心职责 | 关键实现 |
|---|--------|---------|---------|
| 1 | **ThreadDataMiddleware** | 创建线程级隔离目录 | `{base_dir}/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}` |
| 2 | **UploadsMiddleware** | 追踪新上传文件并注入对话 | 自动扫描 uploads 目录增量 |
| 3 | **SandboxMiddleware** | 获取沙箱实例 | `SandboxProvider.acquire()` 生命周期管理 |
| 4 | **DanglingToolCallMiddleware** | 处理中断导致的悬挂工具调用 | 注入占位 ToolMessage |
| 5 | **LLMErrorHandlingMiddleware** | LLM 调用错误标准化 | `ErrorCategory` 枚举映射 |
| 6 | **GuardrailMiddleware** | 工具调用前置授权 | 可插拔 `GuardrailProvider`，支持 Allowlist / OAP |
| 7 | **SandboxAuditMiddleware** | 沙箱操作审计 | 记录所有 shell/file 操作到日志 |
| 8 | **ToolErrorHandlingMiddleware** | 工具异常转错误消息 | 防止 run 因单个工具失败而终止 |
| 9 | **SummarizationMiddleware** | 上下文压缩 | Token/消息/比例触发，保留最近 N 条 + 摘要 |
| 10 | **TodoListMiddleware** | 计划模式任务跟踪 | `write_todos` 工具，一次仅 1 个 in_progress |
| 11 | **TokenUsageMiddleware** | Token 用量统计 | 与 cost 模块联动，按模型计费 |
| 12 | **TitleMiddleware** | 自动标题生成 | 首次完整对话后触发，max 6 词 / 60 字符 |
| 13 | **MemoryMiddleware** | 记忆异步更新 | 过滤用户+最终AI消息，30s 去抖，后台线程处理 |
| 14 | **ViewImageMiddleware** | 视觉模型图片注入 | `view_image` 工具 → base64 → state |
| 15 | **DeferredToolFilterMiddleware** | 延迟工具 Schema 隐藏 | 搜索启用前隐藏 deferred 工具 |
| 16 | **SubagentLimitMiddleware** | 子智能体并发限制 | `MAX_CONCURRENT_SUBAGENTS = 3`，截断多余调用 |
| 17 | **LoopDetectionMiddleware** | 工具调用循环检测 | 检测重复模式，强制文本回复 |
| 18 | **ClarificationMiddleware** | 澄清请求拦截 | `Command(goto=END)` 中断，必须最后 |

#### 4.1.3 工具系统

**内置工具**（`tools/builtins/`，16 个）：

| 工具 | 文件 | 用途 |
|------|------|------|
| `bash` | sandbox/tools.py | 沙箱命令执行，虚拟路径翻译 |
| `ls` | sandbox/tools.py | 目录列表（树形，最大 2 级） |
| `read_file` | sandbox/tools.py | 文件读取（支持行范围） |
| `write_file` | sandbox/tools.py | 文件写入/追加，自动创建目录 |
| `str_replace` | sandbox/tools.py | 子串替换（单/全部），沙箱隔离锁 |
| `present_files` | present_file_tool.py | 向用户展示输出文件 |
| `ask_clarification` | clarification_tool.py | 请求用户澄清（被 ClarificationMiddleware 拦截） |
| `view_image` | view_image_tool.py | 读取图片为 base64（需 vision 支持） |
| `http_connector` | http_connector_tool.py | 调用预配置 HTTP 端点（重试/截断/缓存） |
| `setup_agent` | setup_agent_tool.py | 引导式创建自定义 Agent（Bootstrap 专用） |
| `update_agent` | update_agent_tool.py | Agent 自更新 SOUL/config（原子写入） |
| `task` | task_tool.py | 子智能体任务委派（description/prompt/type） |
| `invoke_acp_agent` | invoke_acp_agent_tool.py | 外部 ACP 智能体调用 |
| `render_ui` | render_ui_tool.py | GenUI 动态 UI 块推送 |
| `report_template_*` | report_template_tools.py (6) + runtime_tools.py (8) | 报告模板平台 14 个工具 |
| `closure_ticket_*` | closure_ticket_tools.py (4) | 闭环工单 CRUD |

**社区工具**（`community/`）：

| 工具 | 提供者 | 用途 |
|------|--------|------|
| `web_search` | DuckDuckGo / Tavily / Serper / Exa | 网络搜索（默认 5 条结果） |
| `web_fetch` | Jina AI / Firecrawl | 网页抓取 + 可读性提取（4KB 限制） |
| `image_search` | DuckDuckGo | 图片搜索 |
| `ddg_search` | DuckDuckGo | 综合搜索 |
| `infoquest` | InfoQuest | 信息检索 |

#### 4.1.4 子智能体系统

- **内置子智能体**：`general-purpose`（全工具集）和 `bash`（命令专家）
- **执行模型**：双线程池 — `_scheduler_pool`（3 workers）+ `_execution_pool`（3 workers）
- **并发控制**：`MAX_CONCURRENT_SUBAGENTS = 3`，15 分钟超时，5 秒轮询
- **生命周期事件**：`task_started` → `task_running` → `task_completed` / `task_failed` / `task_timed_out`

#### 4.1.5 多级智能体发现

```
┌──────────────────────────────────────────────────────────┐
│  优先级：用户级 > 租户级 > 内置级                          │
│                                                          │
│  ┌─────────┐   ┌──────────┐   ┌──────────┐             │
│  │ Builtin  │   │ Tenant   │   │ User     │             │
│  │ (只读)   │   │ (CRUD)   │   │ (Fork+   │             │
│  │          │   │          │   │  自定义)  │             │
│  │ 16 个    │   │ 租户管理  │   │ 用户私有  │             │
│  └──────────┘   └──────────┘   └──────────┘             │
│                                                          │
│  Agent 定义 = SOUL.md + config.yaml                      │
│  租户级 CRUD 需 superadmin / tenant_admin 角色            │
│  用户级 Fork 后独立修改，不影响原始定义                      │
└──────────────────────────────────────────────────────────┘
```

---

### 4.2 报告模板平台

#### 4.2.1 DSL Schema (v1)

DSL 采用 YAML 定义，Pydantic 模型验证，完整的报告生命周期：

```yaml
# DSL v1 顶层结构
form_steps:         # 表单步骤（多步骤表单，支持 before_step 数据预加载）
  - id: step_1
    fields:          # 字段列表
      - name: device_id
        type: select  # text|textarea|number|date|select|checkbox|multi-select
        options: [...]  # 静态选项
        options_source: # 或动态数据源（引用前序步骤输出）
          step: step_0
          path: $.devices
          label: $.name
          value: $.id
        validation:    # 校验规则
          pattern: ...
          min: 0
          max: 100
    before_step:       # 预加载数据步骤引用
      step: load_devices
    next: step_2       # 下一步骤（链式）

data_steps:          # 数据步骤（脚本执行）
  - id: fetch_data
    name: data-analyst/query_daily  # 技能命名空间/脚本名
    args:
      device_id: $.form.step_1.device_id

transforms:          # 数据转换步骤
  - id: enrich
    source: $.fetch_data
    operations: [...]

sections:            # 报告章节
  - id: overview
    title: 概览
    type: markdown   # markdown|card|card_group|echart|table|image
    source: $.transformed.overview

export:              # 导出配置
  markdown: true
  pdf: true
```

#### 4.2.2 运行时架构

运行时 **不是后台 Worker**，而是 14 个内置工具由 `ai-report--custom` Agent 在 SOUL 指引下顺序调用：

```
┌─────────────────────────────────────────────────────────────┐
│                  报告运行生命周期                              │
│                                                              │
│  report_template_prepare_run                                │
│       │                                                     │
│       ▼                                                     │
│  ┌─ 表单循环 ──────────────────────────────────────────┐    │
│  │  report_template_render_step  → GenUI form 推送      │    │
│  │  report_template_submit_step  → 参数校验 + 存储      │    │
│  │  (循环直到所有 form_steps 完成)                       │    │
│  └──────────────────────────────────────────────────────┘    │
│       │                                                     │
│       ▼                                                     │
│  report_template_run_data_steps  → 沙箱子进程执行脚本        │
│       │                                                     │
│       ▼                                                     │
│  report_template_assemble_payload → 组装 report_payload.json │
│       │                                                     │
│       ▼                                                     │
│  report_template_render_report  → GenUI 章节渲染推送         │
│       │                                                     │
│       ▼                                                     │
│  report_template_export         → Markdown + PDF 导出        │
│                                                              │
│  横切关注点：                                                 │
│  report_template_list / get / validate / save_draft /        │
│  publish / fork / resume_run                                 │
│  report_template_record_fallback (回退记录)                   │
└─────────────────────────────────────────────────────────────┘
```

**状态机**：`status.json` 文件跟踪每个步骤的状态转换，每个工具在执行前验证 `report_run_id` + `expected_step`，状态不匹配返回 `STATE_MISMATCH` 错误。

#### 4.2.3 内置模板清单

| 模板 | 用途 | 章节类型 |
|------|------|---------|
| `daily-equipment` | 设备日报 | card_group + echart + table |
| `weekly-equipment` | 设备周报 | markdown + echart + table |
| `monthly-equipment` | 设备月报 | markdown + card_group + echart |
| `trend-equipment` | 趋势分析 | echart + markdown + table |
| `diagnosis-fault` | 故障诊断 | card + echart + findings |
| `failure-analysis` | 失效分析 | markdown + evidence + confidence |
| `closure-summary` | 闭环总结 | table + markdown + timeline |
| `inspection` | 巡检报告 | markdown + image + card |

#### 4.2.4 存储与并发安全

- **模板存储**：`{DEER_FLOW_HOME}/report-templates/{users|tenants}/{owner_id}/{template_id}/`
  - `template.json`（元数据 + etag）
  - `versions/v{N}.json`（不可变快照，含解析后的 `dsl` 和原始 `dsl_yaml`）
  - `runs/{report_run_id}.json`（轻量索引）
- **并发安全**：临时文件 + 原子重命名、`expected_etag` 乐观锁（409 冲突）、fcntl/Windows 回退跨进程锁
- **ID 校验**：`template_id` 匹配 `^tpl_[A-Z0-9]{20,32}$`，`report_run_id` 匹配 `^rr_[A-Z0-9]{20,32}$`
- **路径安全**：所有路径经过 `Path.resolve()` + `relative_to()` 包含性检查

---

### 4.3 外部系统集成框架

#### 4.3.1 适配器架构

采用 **Protocol-based 适配器模式**，支持 CRM/ERP/InS/SMS 四类外部系统：

```
┌────────────────────────────────────────────────────────────────┐
│                    集成框架 (integrations/)                      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  tools/          Agent 可调用的集成工具                     │   │
│  │  ├── asset_tools.py       设备资产查询                     │   │
│  │  ├── monitoring_tools.py 监测数据查询                     │   │
│  │  ├── assessment_tools.py  评估查询                        │   │
│  │  ├── crm_tools.py         CRM 客户查询                    │   │
│  │  ├── erp_tools.py         ERP 工单查询                    │   │
│  │  ├── tool_builder.py      工具自动生成                     │   │
│  │  └── registry.py          工具注册表                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                   │
│  ┌──────────────────────────▼───────────────────────────────┐   │
│  │  services/       业务服务层                                │   │
│  │  ├── asset_service.py     设备资产管理                     │   │
│  │  ├── monitoring_service.py 监测数据聚合                    │   │
│  │  ├── assessment_service.py 评估管理                       │   │
│  │  ├── crm_service.py       CRM 对接                       │   │
│  │  └── erp_service.py       ERP 对接                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                   │
│  ┌──────────────────────────▼───────────────────────────────┐   │
│  │  adapters/       适配器实现（Protocol 接口）               │   │
│  │  ├── base.py              IntegrationAdapter Protocol      │   │
│  │  │                        call() / health_check()         │   │
│  │  ├── crm/adapter.py       CRM 适配器                      │   │
│  │  ├── erp/adapter.py       ERP 适配器                      │   │
│  │  ├── ins/adapter.py       InS 设备监测适配器              │   │
│  │  │   ├── client_bridge.py  InS 客户端桥接                 │   │
│  │  │   ├── kpi_aggregator.py KPI 聚合器                    │   │
│  │  │   └── kpi_map.py        KPI 字段映射                   │   │
│  │  └── sms/adapter.py       SMS 通知适配器                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                   │
│  ┌──────────────────────────▼───────────────────────────────┐   │
│  │  models/         规范化领域模型                             │   │
│  │  ├── asset.py       设备资产                              │   │
│  │  ├── monitoring.py  监测数据                              │   │
│  │  ├── assessment.py  评估报告                              │   │
│  │  ├── crm.py         CRM 客户/工单                         │   │
│  │  ├── erp.py         ERP 物料/工单                         │   │
│  │  ├── overview.py    综合概览                              │   │
│  │  ├── queries.py     查询参数模型                           │   │
│  │  └── provenance.py  数据溯源                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  registry.py       适配器注册与发现                              │
│  routing.py        基于系统类型的请求路由                         │
│  entity_link.py    实体关联                                     │
│  connector_ref.py  HTTP 连接器引用                               │
└────────────────────────────────────────────────────────────────┘
```

#### 4.3.2 InS 数据系列适配

InS（设备监测系统）支持四大数据系列，每系列有不同的 payload 结构和设备类型：

| 系列 | 设备类型 | Payload 结构 | 典型应用 |
|------|---------|-------------|---------|
| **2k** | 传统振动 | 嵌套 name-based | 基础振动监测 |
| **6k** | 腐蚀监测 | 嵌套 key-based | 管道腐蚀分析 |
| **8k** | 旋转机械（默认） | 扁平 payload | 泵/风机/电机 |
| **9k** | 高端旋转/往复 | 扁平 payload | 压缩机/往复泵 |

---

### 4.4 多层记忆系统

```
┌────────────────────────────────────────────────────────────────┐
│                     记忆系统三层架构                             │
│                                                                 │
│  ┌─ Layer 1: 工作记忆（Session）─────────────────────────────┐  │
│  │                                                            │  │
│  │  范围：单个 Thread 内                                       │  │
│  │  存储：LangGraph Checkpointer（ThreadState 内存快照）       │  │
│  │  机制：SummarizationMiddleware 上下文压缩                   │  │
│  │  触发：Token 超 15564 / 消息数 / 比例触发                   │  │
│  │  保留：最近 10 条消息 + 5 个最近技能文件读取（5000 tokens/个）│  │
│  │                                                            │  │
│  │  session_storage.py / session_queue.py                     │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Layer 2: 用户记忆（Persistent）──────────────────────────┐  │
│  │                                                            │  │
│  │  范围：跨 Thread 的长期用户画像                              │  │
│  │  存储：{base_dir}/users/{user_id}/memory.json              │  │
│  │  结构：                                                     │  │
│  │    ├── workContext      工作上下文（1-3 句摘要）             │  │
│  │    ├── personalContext  个人偏好                            │  │
│  │    ├── topOfMind        当前关注                            │  │
│  │    ├── history          近期/早期/长期历史                   │  │
│  │    └── facts[]          离散事实（id/内容/类别/置信度/来源）  │  │
│  │  类别：preference / knowledge / context / behavior / goal   │  │
│  │  流程：                                                     │  │
│  │    MemoryMiddleware → 30s 去抖队列 → LLM 事实提取           │  │
│  │    → 原子写入（temp + rename）→ 缓存失效                     │  │
│  │  注入：下次对话时注入 top 15 facts + context 到 <memory>     │  │
│  │                                                            │  │
│  │  updater.py / queue.py / storage.py / retrieval.py         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Layer 3: 领域记忆（Domain）─────────────────────────────┐  │
│  │                                                            │  │
│  │  范围：特定 Agent 的领域知识                                 │  │
│  │  存储：{base_dir}/users/{user_id}/agents/{name}/memory.json│  │
│  │  用途：Agent 级别的领域专属知识积累                          │  │
│  │                                                            │  │
│  │  domain_storage.py / domain_queue.py / domain_retrieval.py │  │
│  │  domain_prompt.py                                          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Layer 4: 知识库记忆（RAG）──────────────────────────────┐  │
│  │                                                            │  │
│  │  范围：租户级知识库                                         │  │
│  │  存储：Chroma 向量数据库（或 PgVector）                     │  │
│  │  隔离：每个 KB 绑定 Embedding 模型+维度，防止跨 KB 污染     │  │
│  │  检索：retrieval_top_k=5，score_threshold=0.0              │  │
│  │  注入：max 3 chunks / 2000 tokens 注入到系统提示            │  │
│  │                                                            │  │
│  │  rag/backends/chroma.py / pgvector.py                      │  │
│  │  rag/chunking.py / embeddings.py / retrieval.py            │  │
│  └────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

---

### 4.5 闭环工单系统

#### 4.5.1 状态机

```
                        ┌──────────────────────────────────┐
                        │          闭环工单状态机             │
                        │                                  │
    pending ─────────▶ assigned ─────────▶ in_progress     │
         │                │                     │          │
         │ (reject)       │ (reject)            │ (submit_ │
         │                │                     │ verification)
         ▼                ▼                     ▼          │
    rejected ──┐    rejected ──┐    pending_verification    │
    (after     │    (after     │         │                  │
     reopen)   │     reopen)   │    ┌────┴────┐            │
               │               │    │         │            │
               │               │    │(verify_ │(reject_    │
               │               │    │ close)  │verification│
               │               │    ▼         )│           │
               │               │  closed      │           │
               │               │              ▼           │
               │               │         in_progress      │
               │               │         (返工)            │
               └───────────────┘                           │
                                                           │
    超时标记：任何状态 → mark_overdue（不改变当前状态）       │
└──────────────────────────────────────────────────────────┘
```

**SLA 配置**（默认，可租户级覆盖）：

| 优先级 | SLA 时限 |
|--------|---------|
| urgent | 4 小时 |
| important | 72 小时 |
| normal | 7 天 |
| observe | 30 天 |

**审计**：每次状态转换生成不可变 `ClosureTicketEventRow`，记录时间戳、操作者、载荷。禁止直接 PATCH `status` 列，必须通过 `transition()` 函数。

---

### 4.6 内容安全系统

```
┌──────────────────────────────────────────────────────────────┐
│                   内容安全双护栏架构                           │
│                                                               │
│  ┌─ Input Guard ─────────────────────────────────────────┐   │
│  │  触发时机：用户消息进入 Agent 前                         │   │
│  │  检测项：                                              │   │
│  │    ├── 有害内容分类：hate / sexual / violence /         │   │
│  │    │                      self-harm / illegal           │   │
│  │    └── 提示注入检测 (prompt_injection_detection)        │   │
│  │  动作：block_on_harmful=true → 拦截并返回安全提示       │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─ Output Guard ────────────────────────────────────────┐   │
│  │  触发时机：AI 响应返回用户前                            │   │
│  │  检测项：                                              │   │
│  │    ├── PII 检测（邮箱/中国身份证号/信用卡/手机号）       │   │
│  │    └── 有害内容检测                                     │   │
│  │  动作：pii_action=mask → 脱敏处理                      │   │
│  │  提供者：RegexPIIProvider（内置正则，可插拔扩展）         │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─ Tool Guardrail ──────────────────────────────────────┐   │
│  │  触发时机：工具调用执行前                                │   │
│  │  提供者：                                              │   │
│  │    ├── AllowlistProvider（零依赖白名单）                 │   │
│  │    ├── OAP Policy Provider（apart-agent-guardrails）   │   │
│  │    └── 自定义 Provider                                  │   │
│  │  动作：deny → 返回错误 ToolMessage，run 继续            │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

### 4.7 GenUI 动态 UI 系统

GenUI 是平台的核心交互范式 — Agent 通过 `render_ui` 工具将结构化 UI 块推送到前端实时渲染。

#### 4.7.1 组件清单（25 个）

| 组件 | 文件 | 用途 |
|------|------|------|
| **GenUIRenderer** | GenUIRenderer.tsx | 顶层渲染器，根据 block type 分发 |
| **GenUIBlockList** | GenUIBlockList.tsx | 块列表容器 |
| **FormBlock** | FormBlock.tsx | 表单（报告模板 step 渲染） |
| **CardBlock** | CardBlock.tsx | 信息卡片 |
| **ChartBlock** | ChartBlock.tsx | 基础图表 |
| **EChartBlock** | EChartBlock.tsx | ECharts 交互图表 |
| **TableBlock** | TableBlock.tsx | 数据表格 |
| **MetricBlock** | MetricBlock.tsx | 指标数值展示 |
| **GaugeBlock** | GaugeBlock.tsx | 仪表盘 |
| **StatusBlock** | StatusBlock.tsx | 状态指示器 |
| **AlarmBlock** | AlarmBlock.tsx | 告警信息 |
| **TimelineBlock** | TimelineBlock.tsx | 时间线 |
| **ImageBlock** | ImageBlock.tsx | 图片展示 |
| **CodeBlock** | CodeBlock.tsx | 代码块 |
| **MarkdownBlock** | MarkdownBlock.tsx | Markdown 渲染 |
| **LayoutBlock** | LayoutBlock.tsx | 布局容器 |
| **ConfirmBlock** | ConfirmBlock.tsx | 确认对话框 |
| **DeviceSelectorBlock** | DeviceSelectorBlock.tsx | 设备选择器（单选） |
| **DeviceSelectorMultiBlock** | DeviceSelectorMultiBlock.tsx | 设备选择器（多选） |
| **SubDeviceSelectorBlock** | SubDeviceSelectorBlock.tsx | 子设备选择器 |
| **IndustrialDashboardBlock** | IndustrialDashboardBlock.tsx | 工业仪表盘 |
| **OrgTreePanel** | OrgTreePanel.tsx | 组织架构树 |
| **BlockErrorBoundary** | BlockErrorBoundary.tsx | 块级错误边界 |

#### 4.7.2 核心引擎（`core/genui/`）

| 模块 | 职责 |
|------|------|
| `store.ts` | 动态 UI 块存储，SSE 流恢复 |
| `registry.ts` | 组件类型注册表 |
| `interaction.ts` | 交互事件处理（表单提交、按钮点击等） |
| `history.ts` | 历史恢复机制 |
| `sse-recovery.ts` | SSE 断线重连后的块状态恢复 |
| `sanitizer.ts` | UI 块输入净化 |
| `validator.ts` | UI 块 Schema 校验 |
| `visibility.ts` | 条件显示逻辑 |
| `telemetry.ts` | 渲染性能遥测 |
| `chart-screenshots.ts` | 图表截图导出 |

---

### 4.8 认证与授权系统

```
┌──────────────────────────────────────────────────────────────┐
│                   认证授权架构                                │
│                                                               │
│  ┌─ 认证层 ───────────────────────────────────────────────┐  │
│  │                                                         │  │
│  │  多认证方式：                                            │  │
│  │  ├── JWT (jwt.py)          — 主认证，HS256，1440 分钟    │  │
│  │  ├── API Key (api_key_handler.py) — 程序化访问           │  │
│  │  ├── CSRF (csrf_middleware.py)    — 跨站请求防护         │  │
│  │  ├── Local Provider (local_provider.py) — 本地账户       │  │
│  │  └── InS Base Provider (ins_base_provider.py) — InS 认证 │  │
│  │                                                         │  │
│  │  RSA 公钥加密 (rsa_utils.py)                              │  │
│  │  凭证文件存储 (credential_file.py)                        │  │
│  │  内部认证透传 (internal_auth.py)                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 授权层 ───────────────────────────────────────────────┐  │
│  │                                                         │  │
│  │  角色体系（authz.py）：                                   │  │
│  │  ├── superadmin    — 全平台管理                          │  │
│  │  ├── tenant_admin  — 租户级管理                          │  │
│  │  └── user          — 普通用户                            │  │
│  │                                                         │  │
│  │  权限矩阵：                                              │  │
│  │  ├── insights:read / insights:write                     │  │
│  │  ├── closure:verify                                    │  │
│  │  ├── agents:manage / mcp-servers:manage                │  │
│  │  └── (可扩展的 action-based 权限模型)                     │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─ 速率限制 ─────────────────────────────────────────────┐  │
│  │  backend: memory | redis                                │  │
│  │  ├── global:  1000 req/min                             │  │
│  │  ├── tenant:  100 req/min                              │  │
│  │  ├── user:    60 req/min                               │  │
│  │  ├── llm:     50 calls/min                            │  │
│  │  └── tokens:  100,000 tokens/min                      │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

### 4.9 费用管控系统

| 模块 | 文件 | 职责 |
|------|------|------|
| **费用计算** | calculator.py | 按模型 token 用量计算费用 |
| **预算管理** | budget.py | 日/月预算限额，告警阈值 |
| **告警通知** | notifications.py | 超预算告警（80% 阈值） |
| **PG 存储** | pg_storage.py | PostgreSQL 持久化费用数据 |
| **JSON 存储** | storage.py | JSON 文件存储（轻量模式） |

**当前定价配置**：

| 模型 | 输入（/1K tokens） | 输出（/1K tokens） |
|------|-------------------|-------------------|
| gpt-5.4 (InS-5.4) | $0.003 | $0.015 |
| gpt-5.2 (InS-5.2) | $0.003 | $0.015 |

**预算策略**：默认日限 $50、月限 $1000、告警阈值 80%、超限动作 `block`。

---

### 4.10 语音输入系统 (ASR)

| 配置项 | 值 |
|--------|-----|
| **默认语言** | zh-CN |
| **支持语言** | zh-CN, en-US |
| **提供方** | OpenAI Transcription Provider (qwen3-asr-flash) |
| **支持格式** | mp3, wav, webm, ogg, m4a, aac, flac |
| **最大文件** | 25 MB |
| **功能** | 麦克风实时录音 + 文件转录 |

---

### 4.11 IM 渠道桥接系统

| 渠道 | 文件 | 特殊能力 |
|------|------|---------|
| **飞书** | feishu.py | 流式卡片更新，同一卡片原地 patch |
| **钉钉** | dingtalk.py | AI Card 流式更新（PUT /v1.0/card/streaming） |
| **Slack** | slack.py | runs.wait() 阻塞式回复 |
| **Telegram** | telegram.py | runs.wait() 阻塞式回复 |
| **Discord** | discord.py | Discord 消息桥接 |
| **微信** | wechat.py | 微信消息桥接 |
| **企业微信** | wecom.py | 企业微信桥接 |

**消息流**：外部平台 → Channel → MessageBus.publish_inbound() → ChannelManager._dispatch_loop() → 创建/查找 Thread → LangGraph runs.stream()/wait() → OutboundMessage → 平台回复

---

### 4.12 事件与 Webhook 系统

| 模块 | 职责 |
|------|------|
| `events/bus.py` | 异步事件总线（Pub/Sub） |
| `events/models.py` | 事件模型定义 |
| `events/webhook.py` | Webhook 推送（外部系统通知） |

---

### 4.13 缓存系统

| 缓存层 | 模块 | 用途 |
|--------|------|------|
| **Embedding 缓存** | embedding_cache.py | 缓存文档 Embedding 结果，减少重复计算 |
| **语义缓存** | semantic_cache.py | 语义相似度匹配的响应缓存 |
| **Redis 客户端** | redis_client.py | Redis 连接管理 |
| **MCP 工具缓存** | mcp/ | mtime 驱动的缓存失效 |
| **HTTP 连接器缓存** | http_connector_cache.py | 按 cache_ttl_seconds 缓存 HTTP 响应 |

---

## 五、Gateway API 路由矩阵（45 个路由模块）

### 5.1 路由分类

| 类别 | 路由模块 | 数量 |
|------|---------|------|
| **认证** | auth.py, auth_router.py, ins_base_auth.py | 3 |
| **对话** | threads.py, thread_runs.py, runs.py, suggestions.py | 4 |
| **智能体** | agents.py, tenant_agents.py, capabilities.py | 3 |
| **报告** | report_templates.py, report_runs.py, report_template_telemetry.py | 3 |
| **知识库** | knowledge_bases.py, knowledge_base_schemas.py, rag.py | 3 |
| **闭环** | closure_tickets.py | 1 |
| **工具/MCP** | mcp.py, skills.py, uploads.py, artifacts.py | 4 |
| **租户** | tenant_mcp_servers.py, tenant_connectors.py, tenant_status.py, tenant_industrial_migration.py | 4 |
| **管理** | admin.py, models.py, system.py, memory.py | 4 |
| **数据** | feedback.py, cost.py, insights.py, integrations.py | 4 |
| **UI/UX** | genui.py, genui_telemetry.py, greetings.py, audio.py, organize.py | 5 |
| **市场** | marketplace.py, blueprints.py | 2 |
| **渠道** | channels.py | 1 |
| **工业** | industrial_skills_telemetry.py, machine.py | 2 |
| **兼容** | assistants_compat.py | 1 |

---

## 六、前端模块深度解析

### 6.1 App Router 路由树

```
/                                    Landing 着陆页
/login                               登录
/admin/
  ├── skills                         技能管理
  ├── tenants                        租户管理
  ├── usage                          用量统计
  └── logs                           日志查看
/workspace/
  ├── chats/[thread_id]              对话页面（核心）
  ├── agents/
  │   ├── [agent_name]/chats/[id]    智能体对话
  │   └── new/                       创建自定义智能体
  ├── report-templates/
  │   ├── (list)                     模板列表（筛选/搜索/创建）
  │   ├── [template_id]/             模板详情（元数据/版本/YAML/操作）
  │   ├── editor/[id]/               可视化编辑器（调色板/画布/属性面板）
  │   └── new/                       蓝图目录
  ├── report-runs/
  │   ├── (list)                     运行历史
  │   └── [run_id]/                  运行详情（参数/章节/导出）
  ├── template-marketplace/
  │   ├── (list)                     市场列表（搜索/筛选/排序）
  │   ├── [id]/                      市场详情（描述/评论/安装）
  │   └── industrial/                工业模板专区
  ├── knowledge-bases/               知识库管理
  ├── closed-loop/                   闭环工单
  ├── capabilities/[type]/[name]     能力浏览
  ├── debug/a2ui                     A2UI 调试
  └── settings                       设置
```

### 6.2 Core 业务层（42 个子模块）

| 模块 | 文件数 | 核心功能 |
|------|--------|---------|
| `threads/` | 6 | 对话流式/状态管理/hooks/导出/历史 |
| `genui/` | 11 | 动态 UI 块存储/注册/交互/恢复/校验/遥测 |
| `report-templates/` | — | TanStack Query hooks（模板 CRUD/验证/发布/Fork/运行） |
| `marketplace/` | — | 市场列表/详情/评论/安装 hooks |
| `blueprints/` | — | 蓝图目录/模板创建 hooks |
| `knowledge-base/` | 4 | KB API/hooks/类型 |
| `closed-loop/` | 5 | 工单 client/hooks/events/types |
| `memory/` | 6 | 记忆 API/hooks/events/utils |
| `cost/` | 3 | 费用 API/预算状态 hook |
| `feedback/` | 2 | 反馈 API/类型 |
| `auth/` | — | 认证状态管理 |
| `admin/` | — | 管理后台功能 |
| `i18n/` | — | 国际化（zh-CN / en-US） |
| `api/` | — | LangGraph SDK 客户端单例 |
| `artifacts/` | — | 产物加载与缓存 |
| `audio/` | — | 语音输入处理 |
| `models/` | — | TypeScript 类型模型 |
| `settings/` | — | 用户偏好（localStorage） |
| `skills/` | — | 技能管理 |
| `mcp/` | — | MCP 集成 |
| `messages/` | — | 消息处理与转换 |
| `todos/` | — | 计划模式任务 |
| `uploads/` | — | 文件上传 + 转换错误处理 |
| `streamdown/` | — | 流式 Markdown 渲染 |
| `notification/` | — | 通知系统 |
| `tenant/` | — | 租户管理 |
| `rag/` | — | RAG 检索 |
| `rehype/` | — | Rehype Markdown 插件 |
| `industrial-migration/` | — | 工业租户迁移 |
| `industrial-skills/` | — | 工业技能管理 |

---

## 七、配置系统详解

### 7.1 config.yaml 顶层结构（17 个配置域）

| 配置域 | 说明 | 关键参数 |
|--------|------|---------|
| `config_version` | 配置版本号（当前 11） | 版本不匹配时警告，`make config-upgrade` 自动合并 |
| `database` | 数据库后端 | backend: sqlite/postgres, postgres_url |
| `auth` | 认证配置 | enabled, jwt_secret, jwt_algorithm, rsa_public_key, api_key_enabled |
| `models[]` | LLM 模型列表 | name, use (class path), supports_thinking/vision, when_thinking_enabled |
| `tool_groups[]` | 工具组 | web, file:read, file:write, bash |
| `tools[]` | 工具配置 | name, group, use (variable path) |
| `uploads` | 上传配置 | pdf_converter, max_files (10), max_file_size (50MB) |
| `sandbox` | 沙箱配置 | use (Provider class), image, environment, bash_output_max_chars |
| `skills` | 技能路径 | container_path |
| `title` | 自动标题 | enabled, max_words (6), max_chars (60) |
| `summarization` | 上下文摘要 | trigger (tokens/messages), keep (messages), preserve_recent_skill |
| `memory` | 持久记忆 | enabled, debounce_seconds (30), max_facts (100), injection_enabled |
| `session_memory` | 会话记忆 | enabled, debounce_seconds, max_facts, injection |
| `cost` | 费用管控 | storage_backend, model_pricing[], budget (daily/monthly/threshold) |
| `content_safety` | 内容安全 | input_guard (hate/sexual/...), output_guard (pii), provider |
| `rag` | 知识库检索 | embedding_model, vector_store_backend, chunk_size, retrieval_top_k |
| `http_connectors` | HTTP 连接器 | 按 tenant_id 分组，每个含 url/method/auth/timeout/retries/cache |
| `rate_limit` | 速率限制 | global/tenant/user/llm/tokens per minute |
| `nacos` | 服务发现 | server_addr, namespace, service.name/port |
| `rpc` | RPC 客户端 | services[] (name, base_url / discovery), default_timeout |
| `audio_input` | 语音输入 | provider, supported_locales, accepted_mime_types, max_file_size |
| `run_events` | 运行事件 | backend (db), max_trace_content, track_token_usage |

### 7.2 extensions_config.json

```json
{
  "mcpServers": {
    "server_name": {
      "enabled": true,
      "type": "stdio|sse|http",
      "command": "...",
      "args": [...],
      "env": {...},
      "url": "...",
      "headers": {...},
      "oauth": { ... }
    }
  },
  "skills": {
    "skill_name": {
      "enabled": true|false
    }
  }
}
```

---

## 八、项目规模指标

| 类别 | 指标 | 数值 |
|------|------|------|
| **代码规模** | 后端 Python 源文件 | 427 个 |
| | 前端 TypeScript 源文件 | 419 个 |
| | **合计源文件** | **846 个** |
| **测试覆盖** | 后端测试文件 | 374 个 |
| | 前端测试文件 | 57 个 |
| | **合计测试文件** | **431 个** |
| **智能体** | 内置 Agent（SOUL.md + config.yaml） | 16 个 |
| | 内置报告 DSL 模板 | 8 套 |
| | 内置子智能体类型 | 2 个（general-purpose, bash） |
| **工具** | 内置工具 | 16 个 |
| | 社区工具 | 5 个（Tavily/Jina/Firecrawl/DDG/Image） |
| | 报告平台工具 | 14 个 |
| | 集成框架工具 | 5 类（asset/monitoring/assessment/crm/erp） |
| **技能** | 公共技能 | 21 个 |
| | 自定义技能 | 23 个 |
| | **合计技能** | **44 个** |
| **API** | Gateway 路由模块 | 45 个 |
| | IM 渠道 | 7 个（飞书/钉钉/Slack/Telegram/Discord/微信/企微） |
| **前端** | GenUI 组件 | 25 个 |
| | Core 业务子模块 | 42 个 |
| | App Router 路由 | 18 个 |
| **后端** | 中间件层数 | 18 层 |
| | 持久化模块 | 12 个子包（agent/feedback/http_connector/knowledge_base/marketplace/mcp_server/run/tenant/thread_meta/user/migrations） |
| | 数据库迁移版本 | 5 个 |
| | 集成适配器 | 4 个（CRM/ERP/InS/SMS） |
| **配置** | config.yaml 顶层域 | 17 个 |
| | config_version | 11 |
| **基础设施** | 国际化语言 | 2 种（zh-CN / en-US） |
| | Docker 服务 | 4 个（nginx/frontend/gateway/provisioner） |

---

## 九、技术栈总览

| 层次 | 技术 | 版本/说明 |
|------|------|----------|
| **前端框架** | Next.js | 16 (App Router) |
| **前端 UI** | React | 19 |
| **前端样式** | Tailwind CSS | v4 |
| **前端组件** | Shadcn UI + MagicUI + Vercel AI SDK | 自动生成 |
| **前端语言** | TypeScript | 5.8 |
| **前端包管理** | pnpm | 10.26 |
| **前端状态** | TanStack Query | Server State |
| **前端拖拽** | @dnd-kit/core + sortable | 模板编辑器 |
| **前端 YAML** | js-yaml | DSL 双向同步 |
| **后端框架** | FastAPI | Python 3.12+ |
| **智能体引擎** | LangGraph | 嵌入式 Runtime |
| **LLM 集成** | langchain_openai / vLLM / DeepSeek / Google GenAI | 多 Provider |
| **MCP** | langchain-mcp-adapters | 多服务器 |
| **数据库** | PostgreSQL | SQLAlchemy Async 2.0+ |
| **向量数据库** | Chroma (主) / PgVector (备) | KB Embedding |
| **ORM** | SQLAlchemy | Async + 2.0 风格 |
| **迁移** | Alembic | 5 版本 |
| **认证** | JWT + CSRF + API Key + RSA | 多认证方式 |
| **反向代理** | Nginx | 路径路由 + 重写 |
| **容器化** | Docker Compose | 4 服务 |
| **服务发现** | Nacos | 可选 |
| **RPC** | HTTP 直连 / Nacos 发现 | ins-bus-rpc / ins-base-rpc |
| **语音** | qwen3-asr-flash (OpenAI Compatible) | ASR |
| **测试（后端）** | pytest | 374 测试文件 |
| **测试（前端）** | Vitest + Playwright | 57 测试文件 |
| **代码质量** | ruff (Python) + ESLint (TS) | 自动格式化 |

---

## 十、近期迭代重点（2026/04 - 2026/05）

| 时间 | 里程碑 | 关键交付 |
|------|--------|---------|
| 4 月初 | **SQLite → PostgreSQL 迁移** | 全量数据迁移，SQLAlchemy Async，Alembic 5 版本迁移 |
| 4 月中 | **费用管控系统** | Token 计费、日/月预算、80% 告警、block 策略（前后端） |
| 4 月中 | **认证体系增强** | CSRF 中间件、JWT refresh、角色权限矩阵、API Key |
| 4 月下 | **外部集成框架** | Protocol 适配器（CRM/ERP/InS/SMS）、领域模型、工具自动注册 |
| 4 月下 | **闭环工单系统** | 7 状态状态机、SLA 管控、事件审计、verify-close 权限 |
| 5 月初 | **报告模板平台** | DSL v1 Schema、14 工具运行时、可视化编辑器、蓝图目录 |
| 5 月中 | **模板市场** | 发布/安装/评论、.template 包 IO、版本追踪、来源标记 |
| 5 月中 | **智能体增强** | 三层记忆（Session/Domain/Persistent）、Lead Agent 重构 |
| 5 月中 | **内容安全** | Input/Output 双护栏、PII 脱敏、提示注入检测 |
| 5 月下 | **语音输入** | ASR (qwen3-asr-flash)、麦克风录音、文件转录、中英双语 |
| 5 月下 | **IM 扩展** | Discord/微信/企微 渠道接入 |
| 5 月下 | **个性化 UX** | 智能问候 API、共情错误处理、头像/状态、全量 i18n |
| 5 月底 | **服务发现** | Nacos 集成、RPC 客户端（ins-bus-rpc/ins-base-rpc） |
| 5 月底 | **遥测体系** | 报告遥测（6 类事件）、GenUI 遥测、KB 遥测、工业技能遥测 |

---

## 十一、当前挑战与后续规划

### 11.1 当前挑战

| 挑战 | 影响 | 缓解措施 | 优先级 |
|------|------|---------|--------|
| **PDF 导出依赖 weasyprint** | 部分部署环境 PDF 不可用 | 已记录 `pdf_skipped_reason`，UI 优雅降级 | 中 |
| **Local 沙箱安全** | 共享文件系统，隔离不足 | 生产环境使用 AioSandboxProvider (Docker) | 高 |
| **前端测试覆盖** | 57 vs 后端 374 测试文件 | 需加强前端单元测试和 E2E | 中 |
| **知识库大文档** | 大文档索引延迟 | 异步索引池已实现，可调节 Worker 数 | 低 |
| **LLM 延迟** | 复杂分析任务响应慢 | 流式输出 + 子智能体并行 + 摘要压缩 | 中 |

### 11.2 后续规划建议

| 阶段 | 方向 | 具体内容 |
|------|------|---------|
| **Q3 2026** | 模板生态 | 开放更多蓝图模板、DSL 条件章节/循环数据源、模板版本对比 |
| **Q3 2026** | 安全加固 | SSO 集成、审计日志完善、数据脱敏增强、合规审计 |
| **Q4 2026** | 多模态深化 | 振动波形图/频谱图视觉分析、设备照片智能识别 |
| **Q4 2026** | 编排可视化 | 基于节点编辑器的多智能体工作流编排 |
| **Q1 2027** | 可观测性 | Prometheus/Grafana 全链路监控、告警规则引擎 |
| **Q1 2027** | 移动体验 | 响应式 UI 优化、PWA 支持、IM 渠道功能对齐 |
| **持续** | 质量工程 | 前端测试覆盖提升至 200+、E2E 关键路径全覆盖 |

---

## 十二、总结

EHM AI 工作台已构建为一个 **功能完整、架构清晰、可扩展** 的工业 AI 智能体平台。

### 核心价值

| 维度 | 成果 |
|------|------|
| **产品完整性** | 覆盖对话 → 报告 → 诊断 → 闭环 → 知识 全链路，16 个内置 Agent、8 套报告模板、44 个工业技能 |
| **架构先进性** | Harness/App 分层、18 层中间件链、DSL 报告引擎、Protocol 适配器框架、三层记忆系统 |
| **工程质量** | 846 源文件 + 431 测试文件、CI 边界强制、原子写入+乐观锁并发安全、结构化错误码 |
| **业务差异化** | InS 四系列数据深度集成、旋转/往复/机泵专项诊断、7 路 IM 桥接、Nacos+RPC 企业级基础设施 |
| **平台可扩展** | 三级智能体发现、MCP 多服务器热更新、DSL 模板市场生态、可插拔安全护栏 |

### 关键数字

- **846** 个源文件（427 Python + 419 TypeScript）
- **431** 个测试文件（374 后端 + 57 前端）
- **45** 个 Gateway 路由模块
- **25** 个 GenUI 动态组件
- **18** 层智能体中间件
- **16** 个内置智能体
- **44** 个技能包
- **7** 路 IM 渠道
- **4** 类外部系统适配器
- **3** 层记忆系统
- **17** 个配置域

平台已具备向更多工厂/租户规模化推广的条件。建议下一步聚焦于 **模板生态建设**、**企业级安全加固** 与 **前端质量工程**。
