# Storage Package 设计文档

## 背景

DeerFlow 当前有多类持久化职责分散在 app、gateway、runtime 和旧 persistence 模块中。这会带来几个问题：

- routers 和 runtime services 容易依赖具体 persistence 实现，而不是稳定契约。
- user/auth、run metadata、thread metadata、feedback、run events、checkpointer setup 的初始化路径不统一。
- memory、SQLite、PostgreSQL 相关路径中存在部分重复逻辑。
- app 层代码和 storage 层代码耦合，导致增量迁移困难。
- 增加或验证新的 SQL backend 时，需要改动 app/runtime，而不是只改 storage package。

引入 storage package 的目标，是把应用数据持久化抽象成 package 级能力，并提供明确契约、清晰边界和 SQL backend 兼容性。

## 目标

- 新增独立的 `packages/storage`，负责 durable application data。
- 通过统一 persistence 构造流程支持 SQLite、PostgreSQL、MySQL。
- 保持 LangGraph checkpointer 与同一个数据库 backend 兼容。
- 将 repository contracts 作为 package 对外唯一数据访问边界。
- app 层通过 `app.infra.storage` 适配 storage，而不是直接依赖 storage DB 实现类。
- 支持 app/gateway 后续小步迁移，避免一次性大重构。

## 非目标

- 第一阶段不删除旧 persistence。
- 不让 routers 直接依赖 storage package models。
- 不让 app routers 管理 SQLAlchemy sessions。
- cron persistence 不属于 storage package 基础迁移范围。
- memory backend 不属于 durable storage package。若 app runtime 仍需要 memory 兼容，应放在 `packages/storage` 之外。

## Storage 设计理念

### Package 自己负责 Durable Storage

`packages/storage` 负责应用数据的 durable persistence，包括：

- storage 持久化配置
- SQLAlchemy models
- repository contracts 和 DTOs
- SQL repository 实现
- persistence factory functions
- 面向现有 config 的兼容初始化入口

该 package 不应该 import `app.gateway`、routers、auth providers 或 runtime 中的 gateway 对象。

### SQL Backend 兼容

该 package 支持三种 SQL backend：

- SQLite：本地或单节点部署
- PostgreSQL：生产多节点部署
- MySQL：使用 MySQL 作为标准数据库的部署

backend 差异在 storage package 内部处理：

- SQLAlchemy async engine URL 构造
- LangGraph checkpointer 连接串兼容
- SQLite/PostgreSQL/MySQL 的 JSON metadata filter
- 不同 SQL 方言在 locking、aggregation、JSON 类型语义上的差异

### 统一 Persistence Bundle

Storage 初始化返回 `AppPersistence` bundle：

```python
@dataclass(slots=True)
class AppPersistence:
    checkpointer: Checkpointer
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    setup: Callable[[], Awaitable[None]]
    aclose: Callable[[], Awaitable[None]]
```

app runtime 只需要初始化一次 persistence，调用 `setup()`，然后注入：

- `checkpointer`
- `session_factory`
- repository adapters

这样 checkpointer 和应用数据可以对齐到同一个 backend，同时 routers 不需要理解数据库配置。

## Package 结构

```text
backend/packages/storage/
  store/
    config/
      storage_config.py
      app_config.py
    persistence/
      factory.py
      types.py
      base_model.py
      json_compat.py
      drivers/
        sqlite.py
        postgres.py
        mysql.py
    repositories/
      contracts/
        user.py
        run.py
        thread_meta.py
        feedback.py
        run_event.py
      models/
        user.py
        run.py
        thread_meta.py
        feedback.py
        run_event.py
      db/
        user.py
        run.py
        thread_meta.py
        feedback.py
        run_event.py
      factory.py
```

## Persistence 构造

storage 的主要入口：

```python
from store.persistence import create_persistence_from_storage_config

persistence = await create_persistence_from_storage_config(storage_config)
await persistence.setup()
```

为了兼容现有 app database config，也提供：

```python
from store.persistence import create_persistence_from_database_config

persistence = await create_persistence_from_database_config(config.database)
await persistence.setup()
```

预期 app startup 流程：

```python
persistence = await create_persistence_from_database_config(config.database)
await persistence.setup()

app.state.persistence = persistence
app.state.checkpointer = persistence.checkpointer
app.state.session_factory = persistence.session_factory
```

预期 app shutdown 流程：

```python
await app.state.persistence.aclose()
```

## Repository 契约设计

Repository contracts 是 storage package 对外公开的数据访问边界。它们位于 `store.repositories.contracts`，并通过 `store.repositories` re-export。

主要契约包括：

- `UserRepositoryProtocol`
- `RunRepositoryProtocol`
- `ThreadMetaRepositoryProtocol`
- `FeedbackRepositoryProtocol`
- `RunEventRepositoryProtocol`

每组契约包含：

- 输入 DTO，例如 `UserCreate`、`RunCreate`、`ThreadMetaCreate`
- 输出 DTO，例如 `User`、`Run`、`ThreadMeta`
- repository protocol methods
- 必要的领域异常，例如 `InvalidMetadataFilterError`

Repository 通过 session 构造：

```python
from store.repositories import build_run_repository

async with persistence.session_factory() as session:
    repo = build_run_repository(session)
    run = await repo.get_run(run_id)
```

这样可以让 transaction ownership 保持明确。storage package 不通过全局 singleton 隐式隐藏 commit 或 session 生命周期。

## App/Infra 调用契约

app 层不应该直接调用 `store.repositories.db.*`。预期的 app 边界是 `app.infra.storage`。

`app.infra.storage` 负责：

- 从 FastAPI runtime 初始化中接收 `session_factory`
- 为 app-facing repository methods 管理 session 生命周期
- 在必要时将 storage DTOs 转成 app/gateway DTOs
- 迁移期间保留现有 app-facing 名称
- 依赖 storage repository protocols，而不是具体 DB classes

预期 adapter 模式：

```python
class StorageRunRepository(RunRepositoryProtocol):
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def get_run(self, run_id: str):
        async with self._session_factory() as session:
            repo = build_run_repository(session)
            return await repo.get_run(run_id)
```

为了兼容 gateway，app state 可以暂时保持现有名字，只替换内部实现：

```python
app.state.run_store = StorageRunStore(run_repository)
app.state.feedback_repo = StorageFeedbackStore(feedback_repository)
app.state.thread_store = StorageThreadMetaStore(thread_meta_repository)
app.state.run_event_store = StorageRunEventStore(run_event_repository)
app.state.checkpointer = persistence.checkpointer
app.state.session_factory = persistence.session_factory
```

app-facing objects 可以在迁移期间保留旧方法名，但内部数据访问必须经过 storage contracts。

## 边界规则

### 允许调用的范围

storage package 调用方可以使用：

```python
from store.persistence import create_persistence_from_database_config
from store.persistence import create_persistence_from_storage_config
from store.repositories import build_run_repository
from store.repositories import build_user_repository
from store.repositories import build_thread_meta_repository
from store.repositories import build_feedback_repository
from store.repositories import build_run_event_repository
from store.repositories import RunRepositoryProtocol
from store.repositories import UserRepositoryProtocol
```

app 层应该使用：

```python
from app.infra.storage import StorageRunRepository
from app.infra.storage import StorageUserDataRepository
from app.infra.storage import StorageThreadMetaRepository
from app.infra.storage import StorageFeedbackRepository
from app.infra.storage import StorageRunEventRepository
```

### 禁止调用的范围

app/gateway/router/auth 代码不应该 import：

```python
from store.repositories.db import DbRunRepository
from store.repositories.models import Run
from store.persistence.base_model import MappedBase
```

routers 禁止：

- 创建 SQLAlchemy engines
- 直接创建 SQLAlchemy sessions
- 直接调用 storage DB repository classes
- 直接 commit/rollback storage transactions，除非这是 infra adapter 明确管理的范围
- 依赖 storage SQLAlchemy model classes

storage package 禁止 import：

```python
import app.gateway
import app.infra
import deerflow.runtime
```

依赖方向必须是：

```text
app/gateway -> app.infra.storage -> packages/storage contracts/factories -> packages/storage db implementations
```

禁止反向依赖。

## Checkpointer 兼容

storage persistence bundle 会同时初始化 LangGraph checkpointer 和应用数据持久化。

backend 说明：

- SQLite 使用 `langgraph-checkpoint-sqlite`。
- PostgreSQL 使用 `langgraph-checkpoint-postgres`，需要字符串形式的 `postgresql://...` 连接串。
- MySQL 使用 `langgraph-checkpoint-mysql`，需要字符串形式的 MySQL 连接串。

SQLAlchemy 可以使用 `postgresql+asyncpg://...` 或 `mysql+aiomysql://...` 这类 async driver URL，但 LangGraph checkpointer 构造函数需要普通字符串连接串。这个转换应该封装在 storage driver implementation 内部。

## JSON Metadata Filtering

Thread metadata search 通过 `store.persistence.json_compat` 支持跨方言 JSON filtering。

支持的 filter value 类型：

- `None`
- `bool`
- `int`
- `float`
- `str`

拒绝：

- unsafe keys
- nested JSON path expressions
- dict/list values
- 超出 signed 64-bit 范围的整数

这样可以避免 SQL/JSON path injection，避免 compiled-cache 类型漂移，并保留类型语义，例如 `True != 1`，显式 JSON `null` 不等于 missing key。

## 分步实现方案

### 第 1 步：新增 Storage Package 基础

- 新增 `backend/packages/storage`。
- 增加 storage config models。
- 增加 `AppPersistence`。
- 增加 SQLite/PostgreSQL/MySQL persistence drivers。
- 增加 repository contracts、models、DB implementations 和 factory helpers。
- 接入 package dependency。
- 排除 cron persistence。

### 第 2 步：补齐 Storage Backend 兼容性

- 验证 SQLite setup 和 repository 行为。
- 使用本地 E2E 验证 PostgreSQL 和 MySQL。
- 修复 checkpointer 连接串兼容。
- 修复 PostgreSQL locking 和 aggregation 差异。
- 增加跨方言 JSON metadata filtering。

### 第 3 步：新增 App Infra Adapters

- 新增 `backend/app/infra/storage`。
- 实现 app-facing repositories，由它们管理 session 生命周期。
- 保持 storage contracts 作为唯一数据访问边界。
- 为现有 app/gateway method shape 增加兼容 adapters。
- 避免 `packages/storage` import app/gateway。

### 第 4 步：切换 FastAPI Runtime 注入

- 在 FastAPI startup/lifespan 中初始化 storage persistence。
- 将 `persistence`、`checkpointer`、`session_factory` 注入 `app.state`。
- 暂时保留现有对外 state 名称：
  - `run_store`
  - `feedback_repo`
  - `thread_store`
  - `run_event_store`
  - `checkpointer`
  - `session_factory`
- 先切 user/auth provider 构造，再逐步迁移 run/thread/feedback/run_event。

### 第 5 步：Router 和 Auth 兼容

- 确保 routers 消费 app-facing adapters，而不是 storage DB classes。
- 确保 auth providers 依赖 user repository contracts。
- 保持 router response shapes 不变。
- 增加 auth/admin/router regression tests。

### 第 6 步：清理旧 Persistence

- app/gateway 迁移完成后，再比较旧 persistence usage。
- 所有 call sites 迁移完成后，再删除未使用的旧 repository implementations。
- 只在必要时保留短期 compatibility shims。
- 从 storage-owned durable persistence 中移除 memory backend 路径。

## 测试策略

单测应覆盖：

- config parsing
- persistence setup
- table creation
- repository CRUD/query behavior
- typed JSON metadata filtering
- dialect SQL compilation
- cron exclusion

E2E 应覆盖：

- SQLite persistence setup
- PostgreSQL temporary database setup
- MySQL temporary database setup
- 所有支持 SQL backend 下的 repository contract 行为
- JSON/Unicode round trip
- rollback behavior
- persistence close/cleanup

如果 CI 暂时没有 PostgreSQL/MySQL services，E2E 可以先作为 local-only 验证保留。
