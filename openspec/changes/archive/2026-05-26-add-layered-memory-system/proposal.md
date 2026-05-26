## Why

DeerFlow 当前的「记忆」实现（`packages/harness/deerflow/agents/memory/`）只覆盖**单用户的全局上下文 + 事实库**这一层：所有 Thread 共享一份 `memory.json`，由 `MemoryMiddleware` 在用户消息 + 最终 AI 回复后入队，30s 防抖后由 LLM 抽取 `workContext / personalContext / topOfMind` 与扁平 `facts[]`。这套设计在「轻量个人助手」语境下能用，但对企业 AI 应用平台暴露出三个核心缺口：

1. **会话内状态丢失**：同一 Thread 内，长对话（>summarization 触发阈值）触发上下文压缩后，「用户在第 7 轮要求过用 PDF 而不是 Markdown」这类**会话局部约束**会被压成抽象 summary、无法精确召回；而把所有会话局部偏好都塞进全局 `facts[]` 又会污染跨 Thread 行为。
2. **业务语义缺失**：故障诊断 / 设备分析等业务场景产生的「这台 8K 高压离心泵历史 3 次轴承温度异常都是因为 X」「该用户偏好 6K 腐蚀监测的 RBI 阈值定义」**属于业务领域知识、不属于个人偏好**。当前事实库不区分领域，混进 `facts[]` 后既不能按设备/工艺/工单维度检索，也不能授权给同租户其他用户复用。
3. **检索能力为零**：现状是「全量注入 top-15 facts + 三段 context 到系统提示词」，在 facts 数量增长后必然遇到 token 上限被 `max_facts=100` / `max_injection_tokens=2000` 硬截断；没有 embedding 检索、没有时间衰减、没有按当前任务相关性筛选。

参考业界做法（Mem0 / LangMem / Anthropic Memory cookbook）后，本提案把「记忆」拆成**会话（Session）/ 用户（User）/ 领域（Domain）三层**：每层独立持久化、独立写入策略、独立检索通道，由统一的 `MemoryService` 在系统提示词组装阶段按相关性融合注入。

**前端现状已纳入考虑**：项目已存在记忆管理 UI——[frontend/src/components/workspace/settings/memory-settings-page.tsx](frontend/src/components/workspace/settings/memory-settings-page.tsx)（982 行，单层 facts + 三段 user / history summary 增删改导出导入），底层依赖 [frontend/src/core/memory/](frontend/src/core/memory/)（`api.ts` REST 客户端、`hooks.ts` TanStack Query 封装、`types.ts` `UserMemory`/`MemoryFact`），通过 [frontend/src/app/api/memory/[...path]/route.ts](frontend/src/app/api/memory/[...path]/route.ts) 代理到 Gateway。本提案将前端演进与后端分层一并设计，使 UI 自然扩展到三层视图，**保持现有 `UserMemory`/`MemoryFact` 类型与 `useMemory` 行为完全兼容**（旧入口仍渲染 User 层为 legacy 视图）。

> **范围说明**：本轮 OpenSpec change **仅交付设计提案、规格与任务清单（design.md / specs / tasks.md），不包含代码实现**。实现拆分到后续 change 中按 spec 落地。前端的演进同样以 spec + tasks 形式交付，实现并入下一阶段的 change。

## What Changes

- **引入分层记忆模型**：在 `deerflow.agents.memory` 模块下新增三层抽象：
  - **Session Memory**：作用域 = `(tenant_id, user_id, thread_id)`，与 LangGraph checkpointer 同生命周期，存储「本会话局部约束」（用户在本会话明确要求过的格式、精度、设备 ID 等），Thread 关闭即归档；现有 `SummarizationMiddleware` 的产物归入此层。
  - **User Memory**：作用域 = `(tenant_id, user_id)`，对应当前已实现的 `FileMemoryStorage / StoreMemoryStorage` 层，**保留向后兼容**，只重构数据结构（见下条）。
  - **Domain Memory**：作用域 = `(tenant_id, domain, entity_id?)`，新建。承载「设备 / 工艺 / 工单 / 报告模板 / 行业知识」等业务事实，可被同租户多用户共享；entity 可选（按设备 ID 收敛，也可以是租户级常识）。
- **统一 Memory 抽象 `MemoryService`**：定义 `read(scope, query, top_k) → MemoryRecord[]` / `write(scope, record) → id` / `forget(scope, id|filter)` / `compose_for_prompt(scope, budget_tokens) → str` 四个核心操作；所有上层（Middleware / Tool / Gateway 路由）只与 `MemoryService` 交互，不直接操作存储后端。
- **MemoryRecord 统一模型**：所有层共用一个 Pydantic 模型，字段包含 `id / scope / layer / kind`（preference|fact|episode|domain_assertion）/ `content / embedding? / source / confidence / created_at / valid_from? / valid_to? / decay_policy / tags[]`，区别只在 `scope` 与 `layer`。
- **写入路径升级**：
  - `MemoryMiddleware` 改造为按层路由：会话局部产物 → Session Memory；跨 Thread 个人事实 → User Memory；带业务实体 ID 的诊断/报告结论 → Domain Memory（候选写入需经过 LLM 二次判定 + 阈值 confidence ≥ 0.7）。
  - 新增 `record_domain_memory` 工具，供 SOUL（如 `pump-fault-diagnosis` / `static-equipment-corrosion-diagnosis` / `ai-report--*`）显式写入领域结论；不依赖隐式抽取。
- **检索路径升级**：
  - 三层各自维护检索索引：Session 用全文 + 时间倒序；User 用既有 facts 列表 + 时间衰减；Domain 用 embedding（复用现有 `knowledge_base/` 的 ChromaDB / 嵌入提供方）+ 元数据过滤（domain / entity_id / tenant_id）。
  - `compose_for_prompt(...)` 在 token 预算内按 **Session > User > Domain** 优先级融合注入到 `<memory>` 标签，预算耗尽即截断。
- **遗忘 / 时效**：
  - User / Domain 层支持 `decay_policy`（`never` | `linear:days=N` | `exponential:half_life_days=N`），检索时按衰减后分数排序。
  - 显式 `forget(scope, filter)` API + `DELETE /api/memory/...` 路由暴露给前端「记忆管理」页（已存在 facts 增删，扩展到三层）。
- **数据迁移**：现有 `memory.json` 中所有 `facts[]` 默认归类到 User 层 `kind=preference|fact`；`workContext / personalContext / topOfMind` 三段 summary 转换成 User 层 `kind=context_summary`；零数据丢失，零阻断。
- **API & 前端**：Gateway `routers/memory.py` 在保留现有路由的同时，扩展为三层视图：`GET /api/memory?layer=session|user|domain&scope_*=...`、`POST /api/memory/{layer}/records`、`DELETE /api/memory/{layer}/records/{id}`；现有路径作为 `layer=user` 的兼容别名。
- **前端 UI 演进（与后端 API 同步交付契约）**：
  - [frontend/src/core/memory/types.ts](frontend/src/core/memory/types.ts) 新增 `MemoryLayer`、`MemoryScope`、`MemoryRecord`、`LayeredMemoryFilter` 类型，**保留现有** `UserMemory`/`MemoryFact`/`MemoryFactInput`/`MemoryFactPatchInput`（作为 User 层 legacy 视图）。
  - [frontend/src/core/memory/api.ts](frontend/src/core/memory/api.ts) 新增 `listLayeredRecords(layer, scope, filter)` / `createLayeredRecord(layer, body)` / `updateLayeredRecord(layer, id, patch)` / `deleteLayeredRecord(layer, id)` / `forgetLayeredRecords(layer, filter)` / `getMemoryTelemetrySummary()`；现有 `loadMemory / clearMemory / *MemoryFact / exportMemory / importMemory` 不变。
  - [frontend/src/core/memory/hooks.ts](frontend/src/core/memory/hooks.ts) 新增 `useLayeredMemoryRecords(layer, scope)` / `useCreateLayeredRecord` / `useUpdateLayeredRecord` / `useDeleteLayeredRecord` / `useForgetLayeredMemory` / `useMemoryTelemetrySummary`；TanStack Query key 命名空间统一为 `["memory", layer, ...scope_keys]`，已有 `["memory"]` key 仍作为 User layer legacy 视图。
  - [frontend/src/components/workspace/settings/memory-settings-page.tsx](frontend/src/components/workspace/settings/memory-settings-page.tsx) 顶部新增三层 Tab（Session / User / Domain）：
    - **User Tab**（默认）：保持现有交互完全不变（三段 summary + facts 增删改 + 导入导出）。
    - **Session Tab**：仅展示当前 thread 的会话记忆（thread 选择器，默认聚焦当前激活 thread）；只读优先 + 「Promote to User」单条提升按钮。
    - **Domain Tab**：仅 `tenant_admin` 可写；`domain` / `entity_id` 过滤器；普通用户只读。
  - 错误码本地化：复用 [conversion-errors.ts](frontend/src/core/uploads/conversion-errors.ts) 模式，在 `core/memory/errors.ts` 中以 `MEMORY_NOT_FOUND` / `MEMORY_FORBIDDEN` / `MEMORY_VALIDATION` / `MEMORY_STORAGE` / `MEMORY_EMBEDDING_UNAVAILABLE` 五个稳定 code 为键产出 bilingual toast 文案。
- **可观测性**：复用 `report_templates/telemetry.py` 的内存计数器 + JSONL 落盘模式，记录每层的写入 / 读取 / 命中 / 未命中 / 截断事件，暴露 `GET /api/telemetry/memory/summary`。

**非破坏性约束**：
- 现有 `routers/memory.py` 路径、响应模型、`MemoryMiddleware` 行为在 `layer` 参数缺省时**完全等价于今天**。
- `memory.json` 文件路径、JSON Schema 在迁移后**保持读写兼容**（迁移脚本只新增字段，不删除既有字段）。
- `StoreMemoryStorage` namespace `("memory", tenant_id, user_id, agent_name)` 不变；新增的 Session / Domain namespace 用 `("memory_session", ...)` / `("memory_domain", ...)` 前缀，互不干扰。

## Capabilities

### New Capabilities

- `layered-memory-model`: 定义 Session / User / Domain 三层记忆的 scope 计算规则、生命周期、统一 `MemoryRecord` 数据模型、`decay_policy` / `valid_from/to` 时效语义；定义跨层写入路由（Middleware 自动写入 vs 工具显式写入）的判定条件与 confidence 阈值。
- `memory-service-interface`: 定义统一 `MemoryService` 契约（`read / write / forget / compose_for_prompt` 四个方法的入参 / 出参 / 错误类型 / 一致性保证），以及它对底层 `MemoryStorage` / `KnowledgeBaseRetriever` 的依赖关系；规定 Middleware / Tool / Gateway 三类调用方都只能经由该接口访问记忆。
- `memory-retrieval-and-injection`: 定义三层检索算法（Session 全文+时间倒序 / User 时间衰减 / Domain embedding+元数据过滤）、`compose_for_prompt` 的 token 预算分配策略（Session > User > Domain 优先级 + 截断规则）、`<memory>` 注入标签的格式与优先级，以及 telemetry 事件类型。
- `memory-management-api`: 定义 Gateway `/api/memory/...` 在保留现有路径的前提下扩展三层 CRUD 的 REST 契约（list / get / create / patch / delete / export / import 在每一层的语义）、错误码、权限模型（用户只能管理自己 scope 内记录；tenant_admin 可管理 Domain 层全租户记录）。
- `layered-memory-frontend`: 定义前端三层记忆管理 UI 的可观察行为（Tab 切换、Scope 过滤、权限驱动的只读/可写状态、错误码本地化、TanStack Query 缓存键约定）；明确既有 `useMemory()` / `MemorySettingsPage` 的 User Tab 在三层 UI 启用后**行为不变**的契约。

### Modified Capabilities

<!--
当前 openspec/specs/ 中没有覆盖记忆系统的 spec（最接近的是 user-auth、ins-base-org-tenant-resolution，都不直接管 memory）。本提案纯新增四个 capability，不修改既有 spec 的 requirement。
-->

## Impact

- **设计文档（本提案交付物，新增）**：
  - [openspec/changes/add-layered-memory-system/proposal.md](openspec/changes/add-layered-memory-system/proposal.md)（本文件）
  - [openspec/changes/add-layered-memory-system/design.md](openspec/changes/add-layered-memory-system/design.md)：分层架构图、数据流、scope 计算规则、检索与注入伪代码、迁移策略、与现有 `MemoryMiddleware` / `StoreMemoryStorage` / `knowledge_base/` 的协同点
  - [openspec/changes/add-layered-memory-system/specs/](openspec/changes/add-layered-memory-system/specs/)：4 个 capability spec.md（按 WHEN/THEN 场景定义可观察行为）
  - [openspec/changes/add-layered-memory-system/tasks.md](openspec/changes/add-layered-memory-system/tasks.md)：实现期任务拆解（**本轮不执行**，作为下一个 change 的输入）
- **代码（本提案不修改任何代码）**：列出预期影响范围供后续 change 参考：
  - 修改：[backend/packages/harness/deerflow/agents/memory/storage.py](backend/packages/harness/deerflow/agents/memory/storage.py)、[updater.py](backend/packages/harness/deerflow/agents/memory/updater.py)、[queue.py](backend/packages/harness/deerflow/agents/memory/queue.py)、[prompt.py](backend/packages/harness/deerflow/agents/memory/prompt.py)、`MemoryMiddleware`
  - 新增：`memory/service.py`（`MemoryService`）、`memory/records.py`（`MemoryRecord` 模型）、`memory/session_storage.py`、`memory/domain_storage.py`、`memory/retrieval.py`、`memory/composer.py`
  - 修改：[backend/app/gateway/routers/memory.py](backend/app/gateway/routers/memory.py) 扩展三层路由
  - 新增：`memory/migration.py` + `scripts/migrate_layered_memory.py`
- **数据 / 存储**：复用既有 `BaseStore`（LangGraph Store）+ ChromaDB + 文件后备；新增 namespace 前缀，无新数据库依赖。
- **前端**：本提案**与前端演进同步设计**——proposal 与 spec 中明确前端的 3 个文件修改点（[types.ts](frontend/src/core/memory/types.ts)、[api.ts](frontend/src/core/memory/api.ts)、[hooks.ts](frontend/src/core/memory/hooks.ts)）+ 1 个 UI 入口扩展（[memory-settings-page.tsx](frontend/src/components/workspace/settings/memory-settings-page.tsx) 顶部 Tab 切换）+ 1 个新增错误码模块（`core/memory/errors.ts`）。User Tab 行为完全冻结（向后兼容），新 Tab 在前端 feature flag 关闭时不可见。详见 `layered-memory-frontend` capability spec。
- **测试**：列在 tasks.md 但本轮不实现。
- **依赖**：零新增第三方依赖（embedding 复用现有 `knowledge_base/` 的 provider）。
- **运维**：迁移脚本 `scripts/migrate_layered_memory.py` 可幂等执行；未运行迁移时系统行为等价于今天的 User-only 模式（向后兼容）。
- **范围说明**：
  - **本提案覆盖**：分层数据模型、统一服务契约、检索 / 注入算法、API 契约、迁移策略、可观测性事件类型、**前端三层 UI 的可观察行为契约（types / hooks / Tab 切换 / 错误码本地化）**。
  - **不在本提案范围**：具体的 LLM prompt 调优（属于实现期）、前端视觉稿（仅约定行为，不约束像素级布局）、跨租户 Domain 共享治理（按"先单租户内共享"逐步演进，跨租户委托给后续 change）、记忆审计 / 合规出口（GDPR delete-on-request 在后续 change 单独提）。
