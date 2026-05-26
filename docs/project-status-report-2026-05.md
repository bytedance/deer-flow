# DeerFlow / EHM AI 工作台 — 项目阶段性汇报

> 汇报对象：公司管理层  
> 汇报人：CTO / 产品部  
> 日期：2026 年 5 月 26 日

---

## 一、项目定位

DeerFlow（产品名：**EHM AI 工作台**）是公司自主研发的**工业设备智能运维 AI 平台**。项目以 LangGraph 多智能体框架为核心引擎，面向设备管理、故障诊断、运行监测等工业场景，为企业提供一个集"对话式分析 + 自动化报告 + 知识沉淀"于一体的 AI 工作台。

**核心价值主张：**

- 让一线工程师用自然语言即可完成复杂的设备数据分析与故障诊断
- 将分散在不同系统中的设备运行数据，通过 AI Agent 自动整合成可决策的洞察
- 形成"数据 → 分析 → 报告 → 知识"的闭环，持续积累企业设备管理知识资产

---

## 二、技术架构概览

### 2.1 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| **前端** | Next.js 16 / React 19 / TypeScript 5.8 / Tailwind CSS 4 | 现代化 Web 应用，支持 SSR、流式渲染、GenUI 动态表单 |
| **后端网关** | FastAPI + SSE 流式传输 | REST API + 嵌入式 LangGraph 运行时 |
| **AI 引擎** | LangGraph + LangChain | 多 Agent 编排、工具调用、状态管理 |
| **数据存储** | SQLite（单节点）/ PostgreSQL（生产）| 统一存储：Checkpoint、运行记录、向量检索（pgvector） |
| **向量检索** | ChromaDB / pgvector | RAG 知识库，支持文档语义检索 |
| **沙箱执行** | Local / Docker / K8s Provisioner | 代码执行隔离环境，三档安全级别 |
| **反向代理** | Nginx（端口 2026）| 统一入口，路由分发 |

### 2.2 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     Nginx (:2026)                       │
│                  统一入口 / 路由分发                      │
└────────┬──────────────────────┬──────────────────────────┘
         │ /api/*               │ /
         ▼                      ▼
┌─────────────────┐    ┌─────────────────┐
│  Gateway API    │    │   Frontend      │
│  FastAPI :8001  │    │  Next.js :3000  │
│  ┌───────────┐  │    │                 │
│  │ LangGraph │  │    │  React 19       │
│  │ Runtime   │  │    │  TanStack Query │
│  │ (Agent)   │  │    │  Zustand        │
│  └───────────┘  │    │  ECharts        │
└────────┬────────┘    └─────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│ SQLite │ │ Postgres│
│ 单机   │ │ + pgvec │
└────────┘ └────────┘
```

### 2.3 核心架构设计

项目采用 **Harness / App 分层架构**，严格单向依赖：

- **Harness 层**（`deerflow-harness` 包）：可独立发布的 AI Agent 框架，包含 Agent 编排、工具系统、沙箱、模型管理、MCP 集成、技能系统等核心能力
- **App 层**（`app/`）：应用层代码，包含 FastAPI 网关、IM 渠道集成、业务逻辑

这一设计保证了核心 Agent 框架可独立演进和复用，同时应用层可灵活扩展。

---

## 三、项目规模指标

| 指标 | 数值 | 备注 |
|------|------|------|
| **项目启动时间** | 2025 年 4 月 | 至今约 13 个月 |
| **累计提交数** | 2,277 commits | 高频迭代 |
| **贡献者** | 254 人 | 含开源社区 |
| **后端代码（Harness）** | 346 个 Python 文件 / 55,636 行 | Agent 框架核心 |
| **后端代码（App）** | 86 个 Python 文件 / 20,217 行 | 网关与业务层 |
| **前端代码** | 359 个 TS/TSX 文件 / 45,135 行 | Web 工作台 |
| **测试代码** | 329 个测试文件 / 93,082 行 | 测试代码量 > 业务代码量 |
| **测试文件数** | 329 个 | 覆盖核心模块 |

> 测试代码行数（93K）超过业务代码行数（75K），体现了项目对质量保障的重视。

---

## 四、核心功能模块

### 4.1 多智能体系统（Multi-Agent System）

项目构建了一个**三层级 Agent 体系**，支持 Builtin → Tenant → User 三级发现与覆盖：

**内置工业 Agent 矩阵（17 个）：**

| 类别 | Agent | 功能描述 |
|------|-------|----------|
| **报告生成** | `ai-report--daily` / `weekly` / `monthly` | 设备日报 / 周报 / 月报自动生成 |
| **趋势分析** | `ai-report--trend` | 设备运行趋势分析，含组件富化与导出 |
| **故障诊断** | `ai-report--diagnosis` / `fault-diagnosis` | 通用故障诊断报告 |
| **专项诊断** | `fault-diagnosis--pump` / `rotating` / `reciprocating` | 机泵 / 旋转机械 / 往复机械专项诊断 |
| **失效分析** | `ai-report--failure-analysis` | 失效根因分析报告 |
| **监测分析** | `monitoring-analysis` | 多级监测分析（Pro / Ultra 档位） |
| **异常判断** | `anomaly-judgment` | 设备异常智能判断 |
| **闭环管理** | `ai-report--closure` / `defect-closure` | 缺陷闭环追踪与工单管理 |
| **巡检** | `ai-report--inspection` | 巡检报告生成 |
| **报告平台** | `ai-report--custom` / `report-templates` | DSL 驱动的自定义报告模板平台 |

**通用能力 Agent：**

| Agent | 功能 |
|-------|------|
| `lead_agent` | 主协调 Agent（EHM AI 工作台入口） |
| `general-purpose` | 通用任务子 Agent |
| `bash` | 命令执行专家子 Agent |

### 4.2 报告模板平台（Report Template Platform）

这是项目近期的重要产品创新 — 一个 **DSL 驱动的自定义报告生成平台**：

- **DSL 定义**：用户通过 YAML 描述报告结构（表单步骤、数据步骤、转换、章节、导出格式）
- **GenUI 渲染**：运行时通过 GenUI 动态表单收集用户输入
- **LLM 驱动运行时**：14 个内置工具由 AI Agent 按序调用，状态机严格校验步骤流转
- **脚本注册表**：技能（Skill）可贡献数据处理脚本，通过命名空间隔离
- **版本管理**：模板支持草稿、发布、版本快照、Fork、归档全生命周期
- **8 个内置模板**：daily-equipment、weekly-equipment、monthly-equipment、trend-equipment、diagnosis-fault、failure-analysis、closure-summary、inspection
- **多格式导出**：Markdown（必选）+ PDF（可选）

### 4.3 RAG 知识库系统

- **向量检索**：支持 ChromaDB 和 pgvector 双后端
- **KB 绑定 Embedding**：每个知识库绑定其向量化模型，防止维度混用
- **异步索引**：`IndexingDispatcher` 基于 asyncio.Queue 的工作池，支持崩溃恢复
- **多租户隔离**：租户级 Collection 隔离，防止数据串扰
- **文档转换**：支持 PDF / DOCX / PPTX / XLSX 自动转 Markdown，含标准化错误码

### 4.4 持久化记忆系统（Memory）

- **用户级隔离**：每个用户独立记忆文件
- **多维度存储**：工作上下文、个人偏好、近期关注、历史背景、离散事实
- **LLM 驱动更新**：自动从对话中提取事实和上下文更新
- **去重与置信度**：事实去重 + 置信度阈值过滤（默认 ≥ 0.7）
- **Prompt 注入**：下次对话自动注入 Top 15 相关事实

### 4.5 工具与技能系统

**工具系统**：
- 文件操作（读/写/搜索/替换）
- Bash 命令执行（沙箱隔离）
- Web 搜索（DuckDuckGo / Serper / Tavily / Exa / Firecrawl）
- 网页抓取（Jina AI / InfoQuest / Firecrawl）
- 图像搜索与理解
- HTTP 连接器（预配置 API 调用）
- MCP（Model Context Protocol）工具扩展
- 子 Agent 任务委派

**技能系统**（21 个公共技能）：
- 数据分析、深度研究、学术论文评审
- 图表可视化、PPT 生成、图像生成、视频生成
- 代码文档、前端设计、Web 设计指南
- 播客生成、Newsletter 生成、咨询分析
- 技能创建器、Vercel 部署等

### 4.6 IM 多渠道集成

支持 7 个即时通讯平台无缝对接：

| 平台 | 特性 |
|------|------|
| 飞书（Feishu）| 增量流式更新，卡片原地修补 |
| Slack | Socket Mode，用户白名单 |
| Telegram | Bot API，消息持久化 |
| 钉钉（DingTalk）| AI Card 流式更新 |
| 企业微信（WeCom）| 企业应用集成 |
| 微信（WeChat）| QR 码登录，文件收发 |
| Discord | 社区集成 |

### 4.7 安全与运维能力

| 能力 | 实现 |
|------|------|
| **认证** | JWT（用户名/密码）+ API Key 双模式 |
| **多租户** | Tenant / User 双层隔离 |
| **限流** | 全局限流 + 租户限流 + 用户限流 + LLM 调用限流 + Token 限流 |
| **护栏（Guardrails）** | 可插拔工具调用授权（内置白名单 / OAP 标准 / 自定义） |
| **内容安全** | 输入/输出审核（PII 检测、有害内容过滤、Prompt 注入检测） |
| **熔断器** | LLM 调用失败熔断，防止重试风暴 |
| **成本管理** | Token 计量 + 成本核算 + 预算限额（日/月） |
| **审计** | 沙箱操作审计日志 |

---

## 五、模型生态支持

项目支持**广泛的 LLM 模型接入**，已验证的模型提供商包括：

| 提供商 | 代表模型 | 特性 |
|--------|----------|------|
| **OpenAI** | GPT-4 / GPT-5 | Vision, Responses API |
| **Anthropic** | Claude 3.5 Sonnet | Thinking, Vision |
| **Google** | Gemini 2.5 Pro | Thinking, Vision |
| **DeepSeek** | DeepSeek V3 / Reasoner | Thinking |
| **字节跳动** | 豆包 Seed 1.8 | Thinking, Vision |
| **月之暗面** | Kimi K2.5 | Thinking, Vision |
| **MiniMax** | M2.5 / M2.7 | 204K 上下文 |
| **阿里** | Qwen3 32B / Coder 480B | Thinking, MindIE |
| **本地部署** | Ollama / vLLM | 完全离线，数据不出域 |
| **OpenRouter** | 多模型路由 | 统一接入 |

> 所有模型均支持运行时动态切换，支持 Thinking（深度推理）和 Vision（图像理解）模式的开关控制。

---

## 六、近期重要迭代（最近 30 次提交摘要）

| 方向 | 代表提交 | 说明 |
|------|----------|------|
| **诊断报告** | `feat: add diagnosis report export pipeline` | 新增诊断报告导出流水线 |
| **监测分析** | `feat: add tiered monitoring analysis with pro/ultra` | 分级监测分析（Pro/Ultra） |
| **趋势报告** | `feat: enhance trend report pipeline` | 趋势报告组件富化与导出 |
| **机泵诊断** | `feat: 增加机泵诊断 Agent` | 机泵专项诊断 Agent |
| **往复机诊断** | `feat: 增加往复机诊断 Agent` | 往复机械专项诊断 Agent |
| **用户身份** | `fix: propagate user identity to usage records` | 用户身份传播到用量与审计 |
| **设备事件** | `feat: add machine drop events to AI reports` | AI 报告集成设备停机事件 |
| **KPI 优化** | `feat: KPI auto-substitution per equipment type` | 按设备类型自动替换 KPI |
| **知识库** | `fix: 修复知识库创建认证失败` | 知识库认证链路修复 |
| **报告历史** | `feat: 报告对话归属到报告历史菜单` | 报告历史 UX 优化 |

---

## 七、产品竞争力分析

### 7.1 与同类产品的差异化

| 维度 | DeerFlow / EHM AI 工作台 | 通用 AI 对话产品 |
|------|--------------------------|------------------|
| **领域深度** | 17 个工业设备专项 Agent，覆盖日/周/月报、趋势、诊断、失效分析全场景 | 通用对话，无领域专项能力 |
| **报告能力** | DSL 驱动的自定义报告平台，支持版本管理、模板 Fork、多格式导出 | 仅文本输出 |
| **数据接入** | HTTP 连接器 + MCP 协议 + RAG 知识库 + 设备数据 API（INS 2k/6k/8k/9k） | 用户手动粘贴 |
| **执行能力** | 沙箱代码执行（Local / Docker / K8s），可运行数据分析脚本 | 无代码执行 |
| **多渠道** | 7 个 IM 平台原生集成 | 仅 Web |
| **部署灵活性** | 本地单机 / Docker / K8s / 混合部署，支持完全离线运行 | 仅 SaaS |
| **安全合规** | 多租户隔离 + 限流 + 护栏 + 内容安全 + 成本管理 | 基础安全 |

### 7.2 技术壁垒

1. **LangGraph 多 Agent 编排**：18 层中间件链，覆盖线程隔离、上传处理、沙箱管理、护栏授权、错误处理、上下文摘要、记忆更新、循环检测等全链路
2. **DSL 报告平台**：业界少见的"AI Agent + DSL + GenUI"三位一体报告生成架构
3. **工业数据适配器**：INS 四端点系列（2k/6k/8k/9k）数据接入，覆盖旋转机械、往复机械、腐蚀监测等场景
4. **三层 Agent 体系**：Builtin → Tenant → User 的优先级覆盖机制，支持企业级多租户定制

---

## 八、质量保障

### 8.1 测试覆盖

- **329 个测试文件**，涵盖单元测试、集成测试、端到端测试
- **测试代码 93,082 行**，超过业务代码总量
- **CI 流水线**：每次 PR 自动运行后端单元测试 + 前端类型检查
- **关键回归测试**：Docker 沙箱模式检测、Kubeconfig 处理、Harness/App 边界检查

### 8.2 安全实践

- 沙箱隔离：代码执行在独立沙箱中运行，路径虚拟化防止目录穿越
- 上传安全：文件类型校验、大小限制、自动转换、错误码标准化
- XSS 防护：活跃内容类型（HTML/SVG）强制下载
- 工具授权：Guardrail 中间件对每个工具调用进行前置授权
- 密钥管理：所有 API Key 通过环境变量注入，禁止硬编码

---

## 九、部署方案

| 方案 | 适用场景 | 说明 |
|------|----------|------|
| **本地单机** | 开发 / 演示 / 个人使用 | `make dev` 一键启动 |
| **Docker Dev** | 团队开发 / 测试环境 | docker-compose，含 Provisioner |
| **Docker Prod** | 生产环境 | 多节点部署，PostgreSQL + pgvector |
| **K8s** | 大规模生产 | Provisioner 管理沙箱 Pod |

支持 **Nacos 服务发现**，可与现有 Java 微服务体系（ins-bus-rpc / ins-base-rpc）无缝集成。

---

## 十、下一步规划建议

| 优先级 | 方向 | 预期收益 |
|--------|------|----------|
| P0 | 完善工业报告模板库，扩充更多设备类型的内置模板 | 降低用户使用门槛，提升报告覆盖率 |
| P0 | PostgreSQL 生产环境迁移与性能调优 | 支撑多节点生产部署 |
| P1 | RAG 知识库与报告联动，实现"数据自动注入" | 减少人工操作，提升报告准确性 |
| P1 | 成本管理精细化，按租户/用户/Agent 维度核算 | 支撑商业化定价 |
| P2 | 多语言国际化（i18n）完善 | 拓展海外市场 |
| P2 | 移动端适配优化 | 提升一线工程师移动办公体验 |
| P3 | 技能市场化，支持技能分享与安装 | 构建开发者生态 |

---

## 附录：术语表

| 术语 | 说明 |
|------|------|
| **Agent** | AI 智能体，能自主使用工具完成任务的 AI 程序 |
| **LangGraph** | LangChain 的多 Agent 编排框架 |
| **MCP** | Model Context Protocol，模型上下文协议，工具扩展标准 |
| **RAG** | Retrieval-Augmented Generation，检索增强生成 |
| **GenUI** | 动态 UI 渲染引擎，根据 Agent 指令实时生成表单和展示组件 |
| **DSL** | Domain Specific Language，领域特定语言（本报告指报告模板定义语言） |
| **Sandbox** | 代码执行沙箱，隔离运行用户脚本的安全环境 |
| **INS** | 工业设备数据服务接口（2k/6k/8k/9k 四系列端点） |
| **SSE** | Server-Sent Events，服务器推送事件流 |
| **pgvector** | PostgreSQL 向量扩展，用于 RAG 语义检索 |

---

*本文档基于项目截至 2026-05-26 的代码仓库自动生成。*
