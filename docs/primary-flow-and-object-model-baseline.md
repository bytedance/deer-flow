# DeerFlow 第一主流程与对象模型基线

> ISSUE-01 输出文档 | 状态：已确认 (6/6 待决问题已拍板)
> 创建日期：2026-05-22 | 最后更新：2026-05-22

## 1. 当前状态审计

### 1.1 七个核心对象当前定义差异

基于代码库审计（`backend/packages/harness/deerflow/` 及 `frontend/src/`），七个核心对象在前端、后端和数据库中定义如下：

| 对象 | 后端 Model | 数据库表 | 当前状态值 | 前端消费 |
|------|-----------|---------|-----------|---------|
| **Thread** | `ThreadMetaRow` | `threads_meta` | `status`: String(20), default="idle" | `useThreads()` hooks |
| **Run** | `RunRow` | `runs` | `"pending"`, `"running"`, `"success"`, `"error"`, `"timeout"`, `"interrupted"` | SSE stream + `useThreadStream` |
| **Upload** | 无独立 ORM (文件系统) | 无表 | 无显式状态枚举（文件存在=已上传） | `uploadFiles()` API |
| **Artifact** | `ThreadState.artifacts` (in-memory dict) | 无表 | 无显式状态枚举 | `/api/threads/{id}/artifacts/` |
| **Knowledge Base** | `KnowledgeBaseRow` | `knowledge_bases` | KB: `"active"`; Document: `"pending"` | KB selector + retrieval |
| **Report Run** | `ReportRunRecord` | `runs/{id}.json` (文件) | `"pending"`, `"running"`, `"succeeded"`, `"failed"`, `"canceled"` | `useReportRuns()` hooks |
| **Closure Ticket** | `ClosureTicketRow` | `closure_tickets` | `"pending"` (初期); 事件: create/assign/start/submit_verification/verify_close/reject/reopen | `useClosureSummary()` |

### 1.2 关键差异发现

1. **状态命名不一致**：
   - Run 用 `"error"` 表示失败，Report Run 用 `"failed"`
   - Run 有 `"timeout"` 和 `"interrupted"`，Report Run 只有 `"failed"` 和 `"canceled"`
   - Thread 只有 `"idle"` 一个状态值，无法反映实际执行状态

2. **Upload 和 Artifact 无显式状态**：
   - Upload 在文件系统层面没有状态枚举，上传成功/失败通过 API 返回值表达
   - Artifact 没有独立持久化，附着在 ThreadState 上

3. **失败分类缺失**：
   - 所有对象均无统一的 `failure_category`（执行失败 vs 外部依赖 vs 上传失败）
   - 无 `failed_layer` 标识（runtime vs gateway vs external）

4. **权限模型不一致**：
   - Knowledge Base 有独立的 `visibility`（private/tenant/builtin）和 `kb_permissions` 表
   - Thread 仅通过 `tenant_id` + `user_id` 隔离
   - Report Template 复用 Knowledge Base 的 visibility + permissions 模块

---

## 2. 第一主流程图 (草案)

### 2.1 泳道图

```
┌──────────┬────────────┬────────────┬────────────┬────────────┐
│  阶段    │ 任务/对话   │ 工具/知识   │ 报告/产物   │ 闭环/治理   │
│  Stage   │ Task/Chat  │ Tool/KB    │ Report/Art │ Closure    │
├──────────┼────────────┼────────────┼────────────┼────────────┤
│ 用户      │ 创建Thread  │ 上传文档    │ 查看报告    │ 创建工单    │
│ User     │ 发送消息    │ 选择知识库  │ 下载产物    │ 确认闭环    │
│          │ 查看回复    │ 配置能力    │ 分享结果    │            │
├──────────┼────────────┼────────────┼────────────┼────────────┤
│ 产品面    │ 工作台首页  │ 知识库管理  │ 报告模板页  │ 闭环管理页  │
│ Product  │ 对话详情页  │ 能力配置页  │ 报告运行页  │ 工单详情页  │
│ Surface  │ 产物预览    │             │ 报告历史    │            │
├──────────┼────────────┼────────────┼────────────┼────────────┤
│ 运行时    │ LangGraph  │ 索引调度    │ Report Run │ 状态机      │
│ Runtime  │ RunManager │ 检索服务    │ DSL Runner │ SLA Timer   │
│          │ Stream     │ RAG Pipeline│ 产物生成   │ 事件审计    │
├──────────┼────────────┼────────────┼────────────┼────────────┤
│ 网关      │ Auth/租户  │ 权限校验    │ 模板读写    │ 工单 API    │
│ Gateway  │ Thread API │ KB API      │ Report API │ Ticket API  │
│          │ Run API    │ Doc API     │ Artifact   │ SLA API     │
├──────────┴────────────┴────────────┴────────────┴────────────┤
│  外部依赖故障分支 (External Dependency Unavailable)            │
│  ┌─ LLM/RPC/存储不可用 ─▶ 503 + 明确提示 ─▶ 等待恢复 ─▶ 重试 ─┐ │
│  └───────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 每个阶段的用户场景

**阶段一：任务/对话**
- 场景：用户在 DeerFlow 工作台创建新对话 → 输入问题 → Agent 开始执行 → 流式返回结果
- 关键对象：Thread, Run
- 关键页面：`/workspace/chats/[thread_id]`

**阶段二：工具/知识**
- 场景：用户上传设备数据文档到知识库 → 系统建立索引 → Agent 在后续对话中检索到该知识
- 关键对象：Upload, Knowledge Base
- 关键页面：`/workspace/knowledge-bases/[kb_id]`

**阶段三：报告/产物**
- 场景：用户在对话中触发报告生成 → Report Run 启动 → 执行 DSL → 生成 report.md + report.pdf → 用户下载
- 关键对象：Report Run, Artifact
- 关键页面：`/workspace/report-runs/[run_id]`

**阶段四：闭环/治理**
- 场景：用户从诊断结果创建闭环工单 → 分配处理人 → 处理完成 → 验证关闭 → 回溯到源报告
- 关键对象：Closure Ticket
- 关键页面：`/workspace/closed-loop`

---

## 3. 主对象模型卡片清单 (草案)

### 3.1 Thread (对话线程)

| 属性 | 值 |
|------|-----|
| **业务含义** | 一次用户与 Agent 的持续对话上下文，是工作台的基础交互单元 |
| **生命周期** | 创建 → active(有Run运行) → idle(无活跃Run) → archived(已归档) |
| **统一状态** | `idle`(空闲), `active`(运行中), `archived`(已归档) |
| **状态来源** | 由下属 Run 状态聚合推断，非手动设置 |
| **关联对象** | Run (1:N), Artifact (1:N), Upload (1:N) |
| **归属模块** | Agent Runtime (`deerflow.persistence.thread_meta`) |
| **表名** | `threads_meta` |
| **决策** | Q3: 从单一 `idle` 扩展为三态 |

### 3.2 Run (执行运行)

| 属性 | 值 |
|------|-----|
| **业务含义** | Thread 内一次 Agent 执行的生命周期，承载消息流、工具调用和产物生成 |
| **生命周期** | pending → running → success / failed / cancelled |
| **统一状态** | `pending`, `running`, `success`, `failed`（含 `timeout` 和 `interrupted` 作为 failed 子类）, `cancelled` |
| **失败子类** | `timeout`（执行超时）, `interrupted`（中断）, `external_dependency_unavailable`（外部依赖不可用） |
| **关联对象** | Thread (N:1), Artifact (1:N), Report Run (1:1 可选) |
| **归属模块** | Agent Runtime (`deerflow.persistence.run`) |
| **表名** | `runs` |
| **决策** | Q4: 统一为 `success`/`failed`，`error` 改为 `failed`；Q2: 增加 `external_dependency_unavailable` 子类 |

### 3.3 Upload (文件上传)

| 属性 | 值 |
|------|-----|
| **业务含义** | 用户上传到 Thread 或 Knowledge Base 的文件，经转换后供 Agent 消费 |
| **生命周期** | uploading → converting → ready → (deleted) |
| **统一状态** | `uploading`(上传中), `converting`(转换中), `ready`(就绪), `failed`(失败) |
| **关联对象** | Thread (N:1), Knowledge Base (N:1 可选) |
| **归属模块** | Gateway (`deerflow.uploads`) |
| **存储** | 文件系统 `{base}/users/{uid}/threads/{tid}/user-data/uploads/` |
| **决策** | Q5: 增加独立 ORM 模型，记录状态、转换进度和索引进度 |

### 3.4 Artifact (产物)

| 属性 | 值 |
|------|-----|
| **业务含义** | Agent 执行过程中生成的文件输出（代码、图表、文档等），用户可预览和下载 |
| **生命周期** | generating → ready → downloaded |
| **统一状态** | `generating`(生成中), `ready`(就绪), `failed`(生成失败) |
| **关联对象** | Thread (N:1), Run (N:1) |
| **归属模块** | Agent Runtime (`ThreadState.artifacts`) |
| **访问** | `GET /api/threads/{id}/artifacts/{path}` |
| **决策** | Q5: 增加独立 ORM 模型，持久化 artifact 元数据（不依附于 ThreadState 内存） |

### 3.5 Knowledge Base (知识库)

| 属性 | 值 |
|------|-----|
| **业务含义** | 用户管理的文档集合，经索引后被 Agent 在检索时消费 |
| **生命周期** | 创建 → 活跃 → 索引中 → (停用/删除) |
| **当前状态** | KB: `active`; Document: `pending`/`indexing`/`indexed`/`failed` |
| **关联对象** | Document (1:N), Retrieval (查询引用) |
| **归属模块** | Knowledge & Retrieval (`deerflow.persistence.knowledge_base`) |
| **表名** | `knowledge_bases`, `knowledge_base_documents` |

### 3.6 Report Run (报告运行)

| 属性 | 值 |
|------|-----|
| **业务含义** | 一次报告模板的 DSL 执行实例，生成 report_payload.json 和导出产物 |
| **生命周期** | pending → running → success / failed / cancelled |
| **统一状态** | `pending`, `running`, `success`, `failed`, `cancelled` |
| **关联对象** | Report Template (N:1), Run (1:1), Artifact (1:N) |
| **归属模块** | Report & Outcome (`deerflow.report_templates`) |
| **存储** | `{thread}/report-runs/{id}/` |
| **决策** | Q4: 与 Run 统一为 `success`/`failed` 命名 |

### 3.7 Closure Ticket (闭环工单)

| 属性 | 值 |
|------|-----|
| **业务含义** | 从诊断/报告/对话结果转化出的可追踪处理工单 |
| **生命周期** | pending → assigned → in_progress → submitted → verified_closed / rejected → (reopened) |
| **当前状态** | `pending`(初期); 流转通过 state machine event 推进 |
| **来源类型** | `diagnosis`(诊断结果), `report_run`(报告运行), `report_template`(报告模板), `manual`(手动), `chat`(对话) |
| **关联对象** | Run (N:1, via source_run_id), Device (N:1) |
| **归属模块** | Closed Loop & Governance (`deerflow.persistence.models.closure_ticket`) |
| **表名** | `closure_tickets` |
| **决策** | Q6: `report` 重命名为 `report_run`，新增 `report_template` 类型 |

### 3.8 对象关系图

```
Thread ──1:N──▶ Run ──1:1──▶ Report Run ──▶ Artifact
  │               │
  │               └──N:1──▶ Closure Ticket
  │
  ├──1:N──▶ Upload ──N:1──▶ Knowledge Base ──▶ Document
  │
  └──1:N──▶ Artifact
```

---

## 4. 工作台导航分类 (草案)

### 4.1 当前一级导航项

来自 `frontend/src/components/workspace/workspace-nav-chat-list.tsx`：

| # | 导航项 | 路由 | 当前类型 | 建议分类 |
|---|--------|------|---------|---------|
| 1 | 会话 (Chats) | `/workspace/chats` | 固定 | **主入口** |
| 2 | 智能体 (Agents) | `/workspace/agents/*` | 固定 (可折叠) | **主入口** |
| 3 | 知识库 (Knowledge Bases) | `/workspace/knowledge-bases` | 固定 | **主入口** |
| 4 | 闭环管理 (Closed Loop) | `/workspace/closed-loop` | 条件 (defect-closure) | **主入口** |
| 5 | 报告模板 (Report Templates) | `/workspace/report-templates` | 动态 (agent nav_items) | **主入口** |
| 6 | 报告历史 (Report History) | `/workspace/report-runs` | 动态 (agent nav_items) | **主入口** |
| 7 | A2UI Debug | `/workspace/debug/a2ui` | 固定 | **扩展域** |
| 8 | 设置 (Settings) | 弹窗 | 用户菜单 | **扩展域** |

### 4.2 分类标准

- **主入口 (Primary Entry Point)**：面向所有用户的核心业务流页面。满足以下至少两项：
  1. 属于主流程四阶段（任务/对话、工具/知识、报告/产物、闭环/治理）
  2. 在正常用户路径中高频访问
  3. 承载主要价值产出
- **扩展域 (Extension Domain)**：面向特定角色的辅助功能页面。特征：
  1. 仅开发者/管理员使用
  2. 不属于四阶段主流程
  3. 调试/诊断/实验性质

---

## 5. 已决问题清单

以下问题已在 2026-05-22 逐项确认：

| # | 问题 | 决策 | 拍板人 |
|---|------|------|--------|
| Q1 | 知识库和报告中心是否属于主入口？ | **两者都是主入口**，属于四阶段主流程核心页面 | 用户确认 |
| Q2 | 主流程是否显式处理"外部依赖不可用"路径？ | **是**，在主流程泳道图增加外部依赖故障分支，统一用 `EXTERNAL_DEPENDENCY_UNAVAILABLE` 分类 | 用户确认 |
| Q3 | Thread 状态细化为多状态？ | **三态** `idle` / `active` / `archived`，由 Run 状态聚合推断 | 用户确认 |
| Q4 | Run 的 `error` 和 ReportRun 的 `failed` 统一命名？ | **统一为 `success` / `failed`**，`timeout` 和 `interrupted` 作为 `failed` 子类 | 用户确认 |
| Q5 | Upload 和 Artifact 是否需要独立 ORM？ | **两个都加 ORM**，Upload 记录状态+索引进度，Artifact 持久化元数据 | 用户确认 |
| Q6 | Closure Ticket 的 source_type 是否增加 `report_template`？ | **增加 `report_template`，`report` 重命名为 `report_run`**，共五种来源类型 | 用户确认 |

---

## 6. 后续关联

此基线文档是以下 ISSUE 的前置依赖：

- **ISSUE-02** (`unify-execution-lifecycle-and-state-semantics`)：基于此处的对象模型，统一状态枚举
- **ISSUE-03** (`connect-chat-report-artifact-navigation`)：基于此处的对象关系，打通跳转链路
- **ISSUE-04** (`establish-upload-to-report-knowledge-chain`)：基于此处的知识对象模型，建立知识主链
- **ISSUE-05** (`solidify-ownership-and-module-status`)：基于此处的模块归属，固化 owner

---

*本文档将在 Workshop 1-3 和正式审批后更新为终版。*
