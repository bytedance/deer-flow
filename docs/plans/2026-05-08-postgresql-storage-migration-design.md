# PostgreSQL 存储迁移技术设计方案

> **For Codex/Claude:** 后续实施时建议按“配置收口 -> 结构化数据切换 -> 运行态持久化切换 -> 向量存储切换 -> 旧存储退役”的顺序推进，避免一次性大切换。

**Goal:** 将项目当前分散在 SQLite、JSON 文件、内存和 Chroma 的核心持久化能力统一迁移到 PostgreSQL，提升可靠性、多实例一致性、备份恢复能力和后续运维可控性。  
**Architecture:** 保留“仓储抽象 + LangGraph 运行时 + RAG 派生索引”架构，在不改变产品能力边界的前提下，把 PostgreSQL 升级为结构化状态和运行态状态的主存储。  
**Tech Stack:** PostgreSQL 15+、SQLAlchemy Async、Alembic、LangGraph Postgres Checkpointer/Store、pgvector。

---

## 1. 背景与问题定义

当前项目的“存储”并不是单一后端，而是多套能力并存：

- 结构化业务数据默认走 SQLite：
  - `database.backend: sqlite`
  - 包括 `users`、`tenants`、`threads_meta`、`runs`、`knowledge_bases`、`knowledge_base_documents` 等 ORM 表
- 线程状态持久化由 `database` 统一控制：
  - Checkpointer/Store 后端已跟随 `database.backend` 自动选择
  - 旧的独立 `checkpointer` 配置段已废弃（保留向后兼容）
- 运行事件 `run_events` 当前默认走内存：
  - 重启后丢失
- 成本统计 `token usage` 当前默认走 `token_usage.json`
- 用户记忆 `memory` 当前默认走 `memory.json`
- 用户反馈 `feedback` 已切换到 SQL 仓储（`FeedbackRepository`）
- RAG 向量索引当前默认走 Chroma
- 上传文件、产物、线程工作目录走本地文件系统

从代码现状看，项目已经具备不少 PostgreSQL 基础能力，但仍未形成“统一主存储”：

- 已支持 PostgreSQL 的能力：
  - `backend/packages/harness/deerflow/config/database_config.py`
  - `backend/packages/harness/deerflow/persistence/engine.py`
  - `backend/packages/harness/deerflow/runtime/checkpointer/provider.py`
  - `backend/packages/harness/deerflow/runtime/store/provider.py`
  - `backend/packages/harness/deerflow/runtime/events/store/db.py`
  - `backend/packages/harness/deerflow/agents/memory/storage.py` 中的 `StoreMemoryStorage`
  - `backend/packages/harness/deerflow/persistence/feedback/sql.py`
  - `backend/packages/harness/deerflow/rag/backends/pgvector.py`
- 仍然分裂或未切流的能力：
  - `token usage` 虽有 `PgUsageStorage` 原型，但未纳入统一 ORM/Alembic 体系
  - `run_events` 默认仍为内存
  - `memory` 默认仍为文件（`StoreMemoryStorage` 已实现但未设为默认）
  - `RAG` 默认仍为 Chroma
- 已完成切流的能力：
  - `feedback` 路由已使用 `FeedbackRepository`（SQL 仓储）
  - `checkpointer` 配置已收口到 `database` 段（旧 `checkpointer` 段已废弃）
  - `database.backend` 支持 `memory`、`sqlite`、`postgres` 三种模式

因此，本方案不是“新增 PostgreSQL 支持”，而是“把已有的局部 PostgreSQL 支持收口成统一存储架构”。

## 2. 设计目标

### 2.1 必须满足

1. PostgreSQL 成为核心结构化数据和运行态状态的权威存储。
2. 多实例部署时，线程状态、运行记录、用户数据保持一致，不依赖本地磁盘。
3. 迁移过程中可灰度、可回滚、可校验，不要求一次性停机重构。
4. 尽量复用现有仓储抽象、SQLAlchemy、LangGraph Postgres Provider。
5. 保持现有 API 和前端行为基本不变，优先做存储层替换而不是产品重构。
6. 将配置源头收敛，避免“同一业务在多个后端分别持久化”的分裂状态。
7. 同一套代码支持 SQLite 与 PostgreSQL 两种部署模式，允许通过配置在重启/重部署时切换后端。

### 2.2 非目标

1. 不把上传文件、生成产物、线程工作目录强行迁入 PostgreSQL。
2. 不在本期重做整套多租户隔离模型。
3. 不重构现有 RAG 产品能力边界，只替换底层元数据和向量存储实现。
4. 不要求一步完成所有历史文件型数据的强一致在线迁移，可接受脚本式离线导入。
5. 不支持服务运行中的无损热切换，不建设 SQLite 与 PostgreSQL 的长期双写双读架构。

## 3. 迁移范围

### 3.1 本期纳入 PostgreSQL 的存储

1. 业务结构化数据
   - `users`
   - `tenants`
   - `threads_meta`
   - `runs`
   - `knowledge_bases`
   - `knowledge_base_documents`
   - 其他已纳入 `Base.metadata` 的 ORM 表
2. 运行态状态
   - LangGraph checkpointer
   - LangGraph store
   - `run_events`
3. 用户行为与运营数据
   - `feedback`
   - `token_usage`
4. 记忆数据
   - 通过 `StoreMemoryStorage` 进入 LangGraph Store
5. RAG 向量索引
   - 由 Chroma 迁移到 `pgvector`

### 3.2 保持文件 / 对象存储的内容

1. 线程工作目录
   - `workspace`
   - `uploads`
   - `outputs`
2. 上传原文件与转换后的 Markdown
3. 生成产物和附件访问路径
4. 技能文件、扩展配置、静态文档等仓库资产

结论：本方案是“核心状态 PostgreSQL 化”，不是“所有字节都入库”。

## 4. 当前存储盘点

| 存储域 | 当前实现 | 当前默认后端 | 现状问题 | 目标状态 |
| --- | --- | --- | --- | --- |
| 业务表 | SQLAlchemy ORM | SQLite | 单机友好，但不利于多实例和统一备份 | PostgreSQL |
| Checkpointer | LangGraph Saver | 跟随 `database.backend` | ~~已收口到 `database` 段~~ ✅ 已完成 | PostgreSQL |
| LangGraph Store | memory/sqlite/postgres | 跟随 `database.backend` | 记忆与线程状态可能不一致 | PostgreSQL |
| Run Events | memory/db/jsonl | memory | 重启丢失、无法稳定审计 | PostgreSQL |
| Feedback | SQL 仓储（`FeedbackRepository`） | SQLite/PostgreSQL（跟随 `database`） | ~~已切换到 SQL~~ ✅ 已完成 | PostgreSQL |
| Token Usage | JSON 文件版已上线；PG 原型已存在 | `token_usage.json` | 统计、查询、保留策略差 | PostgreSQL |
| Memory | 文件版默认；`StoreMemoryStorage` 已实现（首选） | `memory.json`（文件）或 LangGraph Store | 默认仍为文件，Store 版已就绪待切换 | PostgreSQL Store |
| RAG 元数据 | ORM 表 | SQLite | 与主业务一起受 SQLite 限制 | PostgreSQL |
| RAG 向量索引 | Chroma / pgvector 原型 | Chroma | 另一个持久化系统，备份与运维分裂 | pgvector |
| 内容安全审计 | JSON 文件 | `content_safety_logs.json` | 审计检索能力有限 | 可选 Phase 2 迁移到 PostgreSQL |
| 上传/产物 | 文件系统 | 本地磁盘 | 适合文件，不宜强行进关系库 | 保持文件或对象存储 |

## 5. 目标架构

### 5.1 总体原则

1. PostgreSQL 是“核心状态主存储”。
2. 文件系统只承担 Blob/Workspace 角色，不承担业务主状态。
3. 向量索引视为“可重建的派生存储”，其权威源仍是知识库文档内容和元数据。
4. 保持“领域仓储抽象不变，底层后端切换”的演进方式。

### 5.2 目标拓扑

```text
Frontend / Gateway / Runtime
        |
        v
   PostgreSQL
   ├─ App ORM tables
   │  ├─ users / tenants
   │  ├─ threads_meta / runs / run_events
   │  ├─ feedback / token_usage
   │  └─ knowledge_bases / knowledge_base_documents
   ├─ LangGraph checkpointer tables
   ├─ LangGraph store tables
   └─ pgvector tables (RAG chunks)

File/Object Storage
   ├─ uploads
   ├─ outputs
   └─ artifacts
```

### 5.3 架构决策

1. 使用同一 PostgreSQL 集群承载业务表、运行态表和向量表。
2. Phase 1 默认使用同一个数据库，避免初期引入过多跨库运维复杂度。
3. 应用业务表继续由 Alembic 管理。
4. LangGraph checkpointer/store 表继续由 LangGraph Provider 管理，不纳入 Alembic。
5. `pgvector` 表建议在应用侧正式建模并纳入迁移，而不是继续使用运行时临时 DDL。

### 5.4 SQLite / PostgreSQL 切换语义

本方案支持“双模式部署”，但不支持“运行中热插拔”。

更准确地说：

1. 支持通过配置选择 `sqlite` 或 `postgres` 作为启动后端。
2. 支持在完成数据迁移、停写、重启或重部署后，从 SQLite 切换到 PostgreSQL。
3. 支持在故障回滚场景下，通过恢复旧数据快照和旧配置重新切回 SQLite。
4. 不支持服务运行过程中，把正在使用的主存储从 SQLite 无缝热切到 PostgreSQL。
5. 不支持长期双写 SQLite 与 PostgreSQL，也不支持自动双向同步。

切换能力矩阵如下：

| 场景 | 是否支持 | 说明 |
| --- | --- | --- |
| 本地开发使用 SQLite 启动 | 支持 | 默认保留单机低门槛模式 |
| 生产环境使用 PostgreSQL 启动 | 支持 | 推荐默认模式 |
| 修改配置后重启服务切换后端 | 支持 | 需先完成数据迁移和校验 |
| 灰度环境 SQLite，生产环境 PostgreSQL | 支持 | 属于部署拓扑差异，不是在线切换 |
| 服务运行中无重启热切换 | 不支持 | 当前 engine/provider 不是双活热切架构 |
| SQLite 与 PostgreSQL 长期双写 | 不支持 | 会显著抬高一致性和运维复杂度 |
| Chroma 与 pgvector 自动双向同步 | 不支持 | 向量迁移采用重建索引，而不是长期双写 |

### 5.5 环境建议矩阵

| 环境 | 推荐后端 | 是否允许 SQLite | 说明 |
| --- | --- | --- | --- |
| 本地开发 | SQLite | 允许 | 最低门槛，适合单人开发与快速调试 |
| 单元测试 / CI | SQLite 或 memory | 允许 | 以速度和隔离性优先 |
| 预发环境 | PostgreSQL | 可临时允许 | 若要验证迁移、并发和恢复能力，应尽量贴近生产 |
| 单机演示 / POC | SQLite | 允许 | 仅适合短期演示，不建议承载长期业务数据 |
| 单机正式环境 | PostgreSQL | 不建议 | 即使单机，也更利于备份、审计和后续扩容 |
| 多实例正式环境 | PostgreSQL | 不允许 | 线程状态、事件、记忆和向量索引都需要统一主存储 |

额外约束：

1. 只要进入多用户、多实例、需要恢复或需要审计的部署形态，就应默认 PostgreSQL。
2. 只要启用 `pgvector`、持久化 `run_events`、Store-backed memory 等能力，就不应再把 SQLite 视为长期正式方案。

## 6. 设计细节

### 6.1 配置收口设计

当前最大的结构问题不是“缺少 PostgreSQL 驱动”，而是配置源头分裂。建议以 `database` 为主入口收口。配置切换粒度定义为“重启/重部署级切换”，不是“运行中热切换”。

PostgreSQL 模式：

```yaml
database:
  backend: postgres
  postgres_url: postgresql://user:pass@host:5432/deerflow
  pool_size: 20
  echo_sql: false

# checkpointer 段已废弃，Checkpointer/Store 自动跟随 database.backend
# 保留仅为向后兼容，新部署无需配置
# checkpointer:
#   type: postgres
#   connection_string: ""

run_events:
  backend: db

cost:
  storage_backend: postgres

memory:
  storage_class: deerflow.agents.memory.storage.StoreMemoryStorage

rag:
  vector_store_backend: pgvector
  pgvector_connection_string: ""  # 可选，默认继承 database.postgres_url
```

SQLite 模式：

```yaml
database:
  backend: sqlite
  sqlite_dir: .deer-flow/data

# checkpointer 段已废弃，自动跟随 database.backend=sqlite
# checkpointer:
#   type: sqlite
#   connection_string: checkpoints.db

run_events:
  backend: db

cost:
  storage_backend: json

memory:
  storage_class: deerflow.agents.memory.storage.FileMemoryStorage

rag:
  vector_store_backend: chroma
```

Memory 模式（单元测试 / CI）：

```yaml
database:
  backend: memory
  # 无持久化，适合测试隔离
```

推荐规则：

1. `database.backend=postgres` 时，Checkpointer/Store 自动使用 PostgreSQL（无需额外配置）。
2. `database.backend=postgres` 时，若 `rag.pgvector_connection_string` 为空，则自动继承 `database.postgres_url`。
3. `database.backend=postgres` 时，启动期默认值改为：
   - `run_events.backend = db`
   - `cost.storage_backend = postgres`
   - `memory.storage_class = StoreMemoryStorage`
4. 旧 `checkpointer` 配置段保留向后兼容，但启动时打印 deprecation warning。
5. 启动自检必须拒绝以下”分裂组合”：
   - `database.backend=postgres` 但 `run_events.backend=memory`
   - `database.backend=postgres` 但 `cost.storage_backend=json`
   - `database.backend=postgres` 但 `memory` 仍强制文件版
   - `rag.enabled=true` 且期望统一备份，但 `vector_store_backend=chroma`

### 6.2 数据访问层设计

#### 6.2.1 继续复用共享 ORM 引擎

沿用现有 `persistence/engine.py`：

- 业务表继续使用共享 `AsyncEngine`
- Repository 模式不变
- Alembic 继续管理 `Base.metadata`

#### 6.2.2 Checkpointer / Store 继续使用 LangGraph 官方 Provider

不建议自行重写：

- `runtime/checkpointer/provider.py`
- `runtime/store/provider.py`

但需要把它们与主库配置收口，保证它们不再是一套独立“可随意切后端”的系统。

#### 6.2.3 Token Usage 改为正式仓储

当前 `PgUsageStorage` 通过原生 `psycopg` 运行时建表并带 JSON fallback，这更像过渡实现，不适合长期维护。建议：

1. 新增 `token_usage` ORM Model 与 Repository。
2. 纳入 Alembic。
3. 由 `cost` 中间件统一写 PostgreSQL。
4. JSON 文件导入逻辑保留为一次性迁移脚本，不保留在线 fallback。

#### 6.2.4 Feedback ✅ 已完成

Feedback 已完成 SQL 仓储切换：

- 网关路由已使用 `FeedbackRepository`（SQL）
- ORM Model `FeedbackRow` 已纳入 `Base.metadata`
- 不再存在 JSON 文件版后端

剩余工作：

1. ~~路由从 `FeedbackStorage` 切到 `FeedbackRepository`~~ ✅
2. 若存在历史 `feedback.json` 数据，仍需一次性导入脚本
3. 无需保留双写或在线 fallback

#### 6.2.5 Memory 统一到 Store

`StoreMemoryStorage` 已实现，可将 memory 写入 LangGraph Store（跟随 `database.backend` 自动选择 memory/sqlite/postgres）。当 Store factory 可用时，系统优先使用 Store-backed 存储，否则 fallback 到文件版。

建议：

1. PostgreSQL 模式下强制默认使用 `StoreMemoryStorage`
2. `memory.json` 仅作为历史数据来源，不再作为主存储
3. 新增导入脚本，把每个用户 / Agent 的历史 `memory.json` 写入对应 Store namespace

这比单独再设计一张 `memory` 表更符合当前项目结构。

### 6.3 RAG 存储设计

RAG 需要拆成两部分看：

1. 元数据
   - `knowledge_bases`
   - `knowledge_base_documents`
   - 已属于 ORM 体系，直接跟随主库迁移
2. 向量索引
   - 当前默认 Chroma
   - 目标迁移到 pgvector

#### 6.3.1 为什么不建议继续保留 Chroma

1. 又引入一套持久化系统，备份与恢复链路分裂。
2. 多实例部署时，Chroma 本地持久化带来额外状态同步问题。
3. 知识库元数据已经在关系库里，向量索引继续旁路存储会让排障和一致性校验复杂化。

#### 6.3.2 pgvector 方案要求

当前 `rag/backends/pgvector.py` 更接近原型实现，正式化时建议补齐：

1. 不再依赖运行时字符串拼 DDL。
2. 明确扩展依赖：
   - `CREATE EXTENSION IF NOT EXISTS vector`
   - `CREATE EXTENSION IF NOT EXISTS pgcrypto`
3. 明确表结构和索引策略：
   - `tenant_id`
   - `collection`
   - `document_id`
   - `chunk_id`
   - `content`
   - `metadata JSONB`
   - `embedding vector(<dimension>)`
   - `created_at`
4. 为检索建立 ANN 索引：
   - HNSW 或 IVFFlat
5. 由文档内容重建向量，而不是把 Chroma 当权威源

结论：向量存储迁移以“重建索引”为主，不以“原样拷贝 Chroma 内部文件”为主。

### 6.4 内容安全审计

`content_safety_logs.json` 是否本期迁移，建议作为 Phase 2 可选项：

1. 如果目标是“产品主状态统一”，它不是最先阻塞项。
2. 如果目标包含“合规审计、集中查询、长期保留”，则应迁移到 PostgreSQL。

建议新增 `content_safety_logs` 表的前提：

- 明确保留周期
- 明确是否要存原文
- 明确是否需要脱敏后落库

## 7. 数据模型与 Schema 变化

### 7.1 复用现有表

以下表优先复用现有 ORM 定义，不重做：

- `users`
- `tenants`
- `threads_meta`
- `runs`
- `run_events`
- `feedback`
- `knowledge_bases`
- `knowledge_base_documents`
- `index_jobs`

### 7.2 新增表

#### 7.2.1 `token_usage`

建议新增正式表：

```text
token_usage
- id BIGSERIAL PK
- tenant_id VARCHAR NOT NULL
- user_id VARCHAR NULL
- thread_id VARCHAR NULL
- run_id VARCHAR NULL
- model_name VARCHAR NOT NULL
- input_tokens INTEGER NOT NULL
- output_tokens INTEGER NOT NULL
- total_tokens INTEGER NOT NULL
- cost_usd NUMERIC(12, 8) NOT NULL
- created_at TIMESTAMPTZ NOT NULL
```

索引建议：

- `(tenant_id, created_at DESC)`
- `(thread_id, created_at DESC)`
- `(user_id, created_at DESC)`

#### 7.2.2 `rag_chunks` 或等价 pgvector 表

建议显式建模，而不是运行时自动创建：

```text
rag_chunks
- id UUID PK
- tenant_id VARCHAR NOT NULL
- collection VARCHAR NOT NULL
- document_id VARCHAR NULL
- chunk_id VARCHAR NOT NULL
- content TEXT NOT NULL
- metadata JSONB NOT NULL
- embedding VECTOR(<dimension>) NOT NULL
- created_at TIMESTAMPTZ NOT NULL
```

索引建议：

- `(tenant_id, collection)`
- 向量索引：HNSW / IVFFlat

#### 7.2.3 `content_safety_logs`（可选）

若纳入 Phase 2，再新增：

- `tenant_id`
- `thread_id`
- `direction`
- `role`
- `allowed`
- `flagged_categories`
- `reasons`
- `provider`
- `sanitized_text`
- `created_at`

## 8. 迁移策略

### 8.1 总体策略

采用“先统一配置和代码路径，再做数据回填，最后切流”的三段式迁移：

1. 代码支持 PostgreSQL 成为唯一主路径
2. 对历史 SQLite / JSON / Chroma 数据做一次性回填或重建
3. 切换生产配置并观察

### 8.2 迁移顺序

#### Phase 0：准备与基线

1. 确定 PostgreSQL 版本，建议 15+
2. 安装依赖 extras：
   - `postgres`
   - `pgvector`
3. 建立测试库、预发库、生产库
4. 准备备份和回滚策略
5. 完成配置收口设计

#### Phase 1：结构化业务表迁移

1. 将 `database.backend` 切为 `postgres`
2. 运行 Alembic 初始化 PostgreSQL 表结构
3. 编写 `sqlite -> postgres` 迁移脚本，迁移：
   - users
   - tenants
   - threads_meta
   - runs
   - knowledge_bases
   - knowledge_base_documents
   - feedback（若旧数据已在 SQLite/SQL 表中）
4. 做记录数和抽样校验

#### Phase 2：运行态状态迁移

1. `checkpointer.type` 切为 `postgres`
2. `run_events.backend` 切为 `db`
3. `memory` 切为 `StoreMemoryStorage`
4. 对历史状态做迁移：
   - `checkpointer sqlite -> postgres`
   - `memory.json -> Store namespace`
   - `feedback.json -> feedback`
   - `token_usage.json -> token_usage`

说明：

- `run_events.backend=memory` 的历史数据若已未持久化，则无法补迁，只能从切流时刻开始保证落库。
- `checkpointer` 的历史迁移优先通过 LangGraph 抽象层读写完成，避免直接依赖底层表结构；若验证后确认 SQLite 和 PostgreSQL schema 版本一致，再评估表级搬迁。

#### Phase 3：向量存储迁移

1. 将 `rag.vector_store_backend` 切为 `pgvector`
2. 初始化 pgvector 表与索引
3. 以知识库文档内容为源，触发全量 reindex
4. 对比迁移前后：
   - chunk 数量
   - 文档覆盖率
   - Top-K 检索抽样结果

不建议：

- 直接拷贝 Chroma 底层文件
- 把 Chroma 当作永久权威数据源

#### Phase 4：清理与退役

1. 停止写入：
   - `feedback.json`
   - `token_usage.json`
   - `memory.json`
   - Chroma persist dir
2. 保留只读快照一段时间
3. 更新文档和运维手册

### 8.3 标准切换流程

#### 8.3.1 SQLite -> PostgreSQL

推荐按以下顺序切换：

1. 宣布维护窗口，并在切换期间停止新写入。
2. 备份以下数据：
   - SQLite 数据库文件
   - `feedback.json`
   - `token_usage.json`
   - `memory.json`
   - Chroma persist 目录
3. 初始化 PostgreSQL：
   - 创建数据库
   - 安装 `vector` 扩展
   - 运行 Alembic
4. 执行离线迁移脚本：
   - `sqlite -> postgres`
   - `feedback.json -> feedback`
   - `token_usage.json -> token_usage`
   - `memory.json -> Store`
5. 触发知识库全量 reindex 到 `pgvector`。
6. 更新配置：
   - `database.backend = postgres`
   - `run_events.backend = db`
   - `memory.storage_class = StoreMemoryStorage`
   - `rag.vector_store_backend = pgvector`
   - （注：`checkpointer` 已自动跟随 `database.backend`，无需单独配置）
7. 重启或重部署服务。
8. 完成切换后执行验收：
   - 线程可读取
   - 新对话可写入
   - run events 可查询
   - memory 可注入
   - RAG 检索结果正常

#### 8.3.2 PostgreSQL -> SQLite 回滚

仅建议在迁移失败或严重故障时使用：

1. 立即停止新写入。
2. 恢复 SQLite、JSON 文件和 Chroma 的切换前快照。
3. 将配置恢复到 SQLite/文件版组合。
4. 重启服务。
5. 用抽样线程验证：
   - 历史消息
   - 反馈
   - 成本记录
   - RAG 检索
6. 保留 PostgreSQL 故障现场用于排查，不做在线反向同步。

## 9. 兼容性与回滚

### 9.1 兼容策略

1. 旧配置保留一个版本周期，但标记 deprecated。
2. 导入脚本支持重复执行时幂等：
   - 通过业务主键 / 唯一键去重
3. 迁移期间允许只读访问旧快照，但不允许长期双写。
4. SQLite 与 PostgreSQL 的兼容方式是“二选一主后端 + 重启切换”，不是“在线双活”。

### 9.2 回滚策略

1. 保留原 SQLite 文件、JSON 文件、Chroma 数据目录快照。
2. 切流前完成：
   - PostgreSQL schema 备份
   - SQLite 与 JSON 文件备份
3. 若切流失败：
   - 恢复旧配置
   - 回退到 SQLite / 文件后端
   - 保留 PostgreSQL 数据供故障分析

注意：RAG reindex 切换后若回滚到 Chroma，需要重新启用旧的 Chroma 目录，不建议在回滚阶段尝试双向同步。

## 10. 实施改造清单

### 10.1 配置层

需要重点改造：

- `backend/packages/harness/deerflow/config/app_config.py`
- `backend/packages/harness/deerflow/config/database_config.py`
- ~~`backend/packages/harness/deerflow/config/checkpointer_config.py`~~ ✅ 已废弃，收口到 database
- `backend/packages/harness/deerflow/config/cost_config.py`
- `backend/packages/harness/deerflow/config/rag_config.py`
- `backend/packages/harness/deerflow/config/memory_config.py`

目标：

- 统一默认值
- 增加启动期一致性校验（尚未实现）
- 增加 deprecation warning（尚未实现）

### 10.2 持久化层

需要重点改造：

- 新增 `token_usage` model/repository
- ~~将 `feedback` 路由切换到 `FeedbackRepository`~~ ✅ 已完成
- 视 Phase 2 决定是否新增 `content_safety_logs` model/repository
- 正式化 `pgvector` 表定义与索引策略

### 10.3 运行时层

需要重点改造：

- `runtime/checkpointer/provider.py`
- `runtime/store/provider.py`
- `runtime/events/store/__init__.py`
- `agents/memory/storage.py`
- `cost/*`
- `rag/vector_store.py`

目标：

- PostgreSQL 模式下默认选对后端
- 去除运行时 fallback 为文件/JSON 的生产默认路径

### 10.4 脚本与运维

建议新增迁移脚本：

1. `scripts/migrate_sqlite_to_postgres.py`
2. `scripts/migrate_feedback_json_to_postgres.py`
3. `scripts/migrate_token_usage_json_to_postgres.py`
4. `scripts/migrate_memory_to_store.py`
5. `scripts/reindex_rag_to_pgvector.py`

## 11. 测试与验收

### 11.1 测试维度

1. 单元测试
   - Repository CRUD
   - 导入脚本幂等性
   - 配置继承逻辑
2. 集成测试
   - PostgreSQL 启动建表
   - Checkpointer/Store 连通性
   - `run_events` 查询分页
   - `feedback`、`token_usage`、`memory` 持久化
3. 端到端测试
   - 新建线程 -> 对话 -> 重启服务 -> 恢复历史
   - 上传知识库 -> 检索 -> 重启服务 -> 再检索
   - 多用户隔离

### 11.2 验收标准

1. 服务重启后，线程历史、运行状态、知识库元数据可恢复。
2. `run_events` 不再默认丢失。
3. `feedback`、`token_usage`、`memory` 不再依赖本地 JSON 文件。
4. 启用 RAG 时，向量索引可在 PostgreSQL 中重建并稳定检索。
5. 同一套 PostgreSQL 备份即可覆盖核心业务状态。
6. 旧存储只保留为迁移快照，不再作为生产读写主路径。

## 12. 风险与缓解

| 风险 | 描述 | 缓解方式 |
| --- | --- | --- |
| 配置分裂 | 虽然上了 PostgreSQL，但仍有模块写文件 | 启动期一致性校验，生产模式拒绝分裂配置 |
| Checkpointer 迁移复杂 | LangGraph 表结构由库管理 | 优先走抽象层迁移，必要时维护窗口切换 |
| 向量迁移成本高 | Chroma -> pgvector 可能触发全量 re-embed | 以文档为源做批量重建，预估 token/embedding 成本 |
| 高体量表膨胀 | `run_events`、`token_usage` 增长快 | 增加归档/保留策略，必要时后续分区 |
| 本地开发门槛提高 | 开发机不一定有 PostgreSQL | 保留 dev-only SQLite 模式，但生产默认 PostgreSQL |

## 13. 推荐结论

推荐采用以下落地策略：

1. 明确把 PostgreSQL 定位为“核心状态唯一主存储”。
2. 不把 uploads/artifacts/workspace 强行迁入 PostgreSQL。
3. 支持 SQLite / PostgreSQL 双模式部署，但切换粒度定义为“重启/重部署级切换”，不是“运行中热插拔”。
4. 先完成配置收口和结构化数据切换，再迁移运行态状态。
5. RAG 向量迁移采用 `pgvector + 全量 reindex`，不直接复制 Chroma 文件。
6. 充分复用现有 PostgreSQL 基础能力，重点解决“未切流”和“多套配置并存”问题，而不是重写存储框架。

这条路径改动面可控、收益明确，也最符合当前项目已经具备的技术基础。

---

## 14. 实施进度跟踪

> 最后更新：2026-05-11

### 14.1 已完成

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| `database.backend` 支持 memory/sqlite/postgres | ✅ | `DatabaseConfig` 已实现三模式 |
| Checkpointer 配置收口到 `database` 段 | ✅ | 旧 `checkpointer` 段保留向后兼容 |
| Store Provider 跟随 `database.backend` | ✅ | memory/sqlite/postgres 三模式 |
| Feedback 切换到 SQL 仓储 | ✅ | `FeedbackRepository` 已在路由使用 |
| `StoreMemoryStorage` 实现 | ✅ | 可将 memory 写入 LangGraph Store |
| `run_events` DB 后端实现 | ✅ | `runtime/events/store/db.py` |
| `PgUsageStorage` 原型实现 | ✅ | 带 JSON fallback |
| pgvector 后端原型实现 | ✅ | `rag/backends/pgvector.py` |
| ORM 表定义完整 | ✅ | users, tenants, threads_meta, runs, run_events, feedback, knowledge_bases, knowledge_base_documents, index_jobs |

### 14.2 待实施

| 项目 | 优先级 | 对应章节 |
| --- | --- | --- |
| 启动期配置一致性校验（拒绝分裂组合） | P0 | §6.1 |
| `database.backend=postgres` 时子系统默认值自动继承 | P0 | §6.1 |
| `token_usage` 正式 ORM Model + Alembic | P1 | §6.2.3, §7.2.1 |
| pgvector 表正式建模 + Alembic | P1 | §6.3.2, §7.2.2 |
| `memory` 默认切换为 `StoreMemoryStorage`（postgres 模式） | P1 | §6.2.5 |
| `run_events` 默认切换为 `db`（postgres 模式） | P1 | §6.1 |
| 迁移脚本：`sqlite -> postgres` | P2 | §10.4 |
| 迁移脚本：`feedback.json -> feedback`（历史数据） | P2 | §10.4 |
| 迁移脚本：`token_usage.json -> token_usage` | P2 | §10.4 |
| 迁移脚本：`memory.json -> Store` | P2 | §10.4 |
| 迁移脚本：`reindex_rag_to_pgvector` | P2 | §10.4 |
| `content_safety_logs` 表（可选） | P3 | §6.4, §7.2.3 |
| Deprecation warning 输出 | P3 | §6.1 |
