# deerflow-storage 设计说明

本文说明 `backend/packages/storage` 的当前职责、总体设计、数据库接入方式、模型定义方式、数据库访问接口，以及它在 `app` 层中的使用路径。

## 1. 包的定位

`deerflow-storage` 是 DeerFlow 的统一持久化基础包，目标是把“数据库接入”和“业务对象持久化”从 `app` 层拆出来，形成一个独立、可复用的存储层。

它当前主要承担两类能力：

1. 为 LangGraph 运行时提供 checkpointer。
2. 为 DeerFlow 应用数据提供 ORM 模型、仓储协议和数据库实现。

这个包本身不直接提供 HTTP 接口，不直接依赖 FastAPI 路由，也不承担业务编排。它更接近一个“存储内核”。

## 2. 总体分层

当前代码大致分成下面几层：

```text
config
  └─ 读取配置、解析环境变量、确定数据库参数

persistence
  └─ 创建 AsyncEngine / SessionFactory / LangGraph checkpointer

repositories/contracts
  └─ 定义领域对象和仓储协议（Pydantic + Protocol）

repositories/models
  └─ 定义 SQLAlchemy ORM 表模型

repositories/db
  └─ 基于 AsyncSession 的数据库实现

app.infra.storage
  └─ 把 storage 仓储适配成 app 层直接可用的接口

gateway / runtime
  └─ 通过依赖注入、facade、observer、event store 使用 infra
```

核心思想是：

1. `storage` 包只负责“如何存”和“存什么”。
2. `app.infra` 负责把底层仓储转换为应用层语义。
3. `gateway` / `runtime` 只依赖 `infra` 暴露出来的接口，不直接碰 ORM 和 SQL。

## 3. 数据库如何接入

### 3.1 配置入口

数据库配置由 [`store/config/storage_config.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/config/storage_config.py) 定义，外层应用配置由 [`store/config/app_config.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/config/app_config.py) 负责读取。

配置来源有几个特点：

1. 默认从 `backend/config.yaml` 或仓库根 `config.yaml` 读取。
2. 支持 `DEER_FLOW_CONFIG_PATH` 指定配置文件。
3. 支持在配置中使用 `$ENV_VAR` 形式引用环境变量。
4. 时区配置也会影响存储层时间字段的处理。

### 3.2 persistence 入口

存储层统一入口是 [`store/persistence/factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/factory.py) 里的 `create_persistence()`。

它会做三件事：

1. 根据 `StorageConfig` 生成 SQLAlchemy URL。
2. 根据 driver 选择 SQLite / MySQL / PostgreSQL 的构建函数。
3. 返回 `AppPersistence`，其中包含：
   - `checkpointer`
   - `engine`
   - `session_factory`
   - `setup`
   - `aclose`

也就是说，应用启动时拿到的不是单一数据库连接，而是一整套“运行期持久化能力包”。

### 3.3 各数据库驱动的接入方式

驱动实现位于：

1. [`store/persistence/drivers/sqlite.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/drivers/sqlite.py)
2. [`store/persistence/drivers/mysql.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/drivers/mysql.py)
3. [`store/persistence/drivers/postgres.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/drivers/postgres.py)

三者的共同模式一致：

1. 创建 `AsyncEngine`
2. 创建 `async_sessionmaker`
3. 创建 LangGraph 对应的异步 checkpointer
4. 在 `setup()` 中先执行 checkpointer 初始化，再执行 `MappedBase.metadata.create_all`
5. 在 `aclose()` 中按顺序关闭 engine 和 checkpointer

这说明当前包的初始化策略是：

1. checkpointer 表和业务表一起由运行时启动时初始化。
2. 业务表当前依赖 `SQLAlchemy create_all()` 自动建表。
3. 当前包内没有独立的 migration 编排入口作为主路径。

### 3.4 SQLite 的当前行为

SQLite 使用 [`StorageConfig.sqlite_storage_path`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/config/storage_config.py) 生成数据库文件路径，默认落到 `.deer-flow/data/deerflow.db`。

对于 SQLite，当前模型主键会退化为 `Integer PRIMARY KEY`，这是因为 SQLite 的自增主键对 `BIGINT` 支持不如 `INTEGER PRIMARY KEY` 直接。

## 4. 持久化模型如何定义

### 4.1 基础模型约定

基础定义位于 [`store/persistence/base_model.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/base_model.py)。

这里统一了几件事：

1. `MappedBase` 作为所有 ORM 模型的声明基类。
2. `DataClassBase` 让模型天然支持 dataclass 风格。
3. `Base` 额外带上 `created_time` / `updated_time`。
4. `id_key` 统一主键定义。
5. `UniversalText` 统一长文本类型，兼容 MySQL 和其他方言。
6. `TimeZone` 统一时区感知的时间字段转换。

因此，包内新模型通常遵循这样的模式：

1. 如果需要 `created_time` / `updated_time`，继承 `Base`。
2. 如果只要 dataclass 风格、不要 `updated_time`，继承 `DataClassBase`。
3. 主键统一使用 `id: Mapped[id_key]`。

### 4.2 当前已定义的业务模型

模型位于 [`store/repositories/models`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/models)：

1. `Run`
   - 表：`runs`
   - 用于保存运行元数据、状态、token 统计、消息摘要、错误信息等。
2. `ThreadMeta`
   - 表：`thread_meta`
   - 用于保存线程级元数据、状态、标题、所属用户等。
3. `RunEvent`
   - 表：`run_events`
   - 用于保存 run 产生的事件流和消息流。
   - 通过 `(thread_id, seq)` 唯一约束维护线程内事件顺序。
4. `Feedback`
   - 表：`feedback`
   - 用于保存对 run 的反馈记录。

### 4.3 模型字段设计特点

当前模型有几个统一约定：

1. 业务主标识使用字符串字段，如 `run_id`、`thread_id`、`feedback_id`，数据库自增 `id` 仅作为内部主键。
2. 结构化扩展信息一般放在 `metadata` JSON 字段中，ORM 内部属性名通常映射为 `meta`。
3. 长文本内容统一用 `UniversalText`。
4. 时间字段统一走 `TimeZone`，避免不同时区下行为不一致。

`RunEvent.content` 还有一个额外约定：

1. 落库时如果 `content` 是 `dict`，会先序列化成 JSON 字符串。
2. 同时在 `metadata` 中写入 `content_is_dict=True`。
3. 读出时再按标记反序列化。

这让 `run_events` 同时兼容“纯文本消息”和“结构化事件内容”。

## 5. 数据库访问接口如何定义

### 5.1 contracts：仓储协议层

协议定义在 [`store/repositories/contracts`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/contracts)。

这一层做了两件事：

1. 用 Pydantic 模型定义输入对象和输出对象，例如 `RunCreate`、`Run`、`ThreadMetaCreate`、`ThreadMeta`。
2. 用 `Protocol` 定义仓储接口，例如 `RunRepositoryProtocol`、`ThreadMetaRepositoryProtocol`。

这意味着上层依赖的是“协议”和“数据契约”，而不是某个具体 SQLAlchemy 实现。

### 5.2 db：数据库实现层

实现位于 [`store/repositories/db`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/db)。

每个仓储实现都遵循同样的模式：

1. 构造函数接收 `AsyncSession`
2. 用 `select / update / delete` 执行数据库操作
3. 把 ORM 模型转换成 contracts 层的 Pydantic 对象返回

例如：

1. `DbRunRepository` 负责 `runs` 表的增删改查和完结统计更新。
2. `DbThreadMetaRepository` 负责线程元数据的查询、更新和搜索。
3. `DbRunEventRepository` 负责事件批量追加、消息分页、按线程或按 run 删除。
4. `DbFeedbackRepository` 负责反馈创建、查询、聚合前置数据读取。

### 5.3 factory：仓储构造入口

[`store/repositories/factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/factory.py) 提供了统一工厂函数：

1. `build_run_repository(session)`
2. `build_thread_meta_repository(session)`
3. `build_feedback_repository(session)`
4. `build_run_event_repository(session)`

这样上层只需要拿到 `AsyncSession`，就可以构造对应仓储，而不需要直接依赖具体类名。

## 6. 对外接口是什么

如果只看 `storage` 包本身，它对外暴露的是两类接口。

### 6.1 持久化运行时入口

由 [`store/persistence/__init__.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/__init__.py) 暴露：

1. `create_persistence()`
2. `AppPersistence`
3. ORM 基础模型相关基类与类型

这是应用初始化数据库和 checkpointer 的入口。

### 6.2 仓储接口与工厂

由 [`store/repositories/__init__.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/__init__.py) 暴露：

1. contracts 层的输入输出模型
2. 各仓储 `Protocol`
3. 各仓储 builder 工厂函数

这是应用按“仓储协议”接入业务持久化的入口。

换句话说，`storage` 包不会直接给 `app` 层一个 HTTP SDK，而是给它：

1. 初始化能力
2. session factory
3. repository protocol + repository builder

## 7. app 层如何调用：通过 infra 接入

`app` 层没有直接操作 `store.repositories.db.*`，而是通过 `app.infra.storage` 做一层适配。

相关代码在：

1. [`backend/app/infra/storage/runs.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/runs.py)
2. [`backend/app/infra/storage/thread_meta.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/thread_meta.py)
3. [`backend/app/infra/storage/run_events.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/run_events.py)

### 7.1 为什么要有 infra 这一层

因为 `app` 层需要的不是“裸仓储接口”，而是“符合应用语义的持久化服务”：

1. 自动开关 session
2. 自动 commit / rollback
3. 补充 actor / user 可见性控制
4. 把底层 Pydantic 模型转换成 app 需要的字典结构
5. 对齐运行时 facade、observer、router 的接口习惯

### 7.2 Run 的接入方式

`RunStoreAdapter` 用 `session_factory` 包装了 `build_run_repository(session)`，向上暴露：

1. `get`
2. `list_by_thread`
3. `create`
4. `update_status`
5. `set_error`
6. `update_run_completion`
7. `delete`

这里的关键点是：

1. 每次调用都会创建独立的 `AsyncSession`。
2. 读操作和写操作分开管理事务。
3. 会结合 `actor_context` 做 `user_id` 维度的可见性过滤。
4. 创建 run 时会先把 metadata / kwargs 做序列化，确保可安全落库。

### 7.3 Thread 的接入方式

线程元数据分成两层：

1. `ThreadMetaStoreAdapter`
   - 是 repository 级别的 session 包装器。
2. `ThreadMetaStorage`
   - 是面向 app 的更高层接口。

`ThreadMetaStorage` 额外提供了应用语义方法：

1. `ensure_thread`
2. `ensure_thread_running`
3. `sync_thread_title`
4. `sync_thread_assistant_id`
5. `sync_thread_status`
6. `sync_thread_metadata`
7. `search_threads`

也就是说，`app` 层通常依赖 `ThreadMetaStorage`，而不是直接依赖底层仓储协议。

### 7.4 RunEvent 的接入方式

`AppRunEventStore` 是运行时事件存储适配器。它不是简单 CRUD 包装，而是面向运行时协议设计的：

1. `put_batch`
2. `list_messages`
3. `list_events`
4. `list_messages_by_run`
5. `count_messages`
6. `delete_by_thread`
7. `delete_by_run`

它额外做了线程可见性校验：如果 actor 有 `user_id`，则会先查询线程归属，再决定是否允许读写该线程事件。

## 8. app 启动时怎么装配 storage

应用启动装配发生在 [`backend/app/gateway/registrar.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/registrar.py)。

`init_persistence()` 的流程是：

1. 调用 `create_persistence()`
2. 执行 `app_persistence.setup()`
3. 用 `session_factory` 构造：
   - `RunStoreAdapter`
   - `ThreadMetaStoreAdapter`
   - `FeedbackStoreAdapter`
   - `AppRunEventStore`
4. 再进一步构造 `ThreadMetaStorage`
5. 把这些对象注入到 `app.state`

因此对 `app` 而言，`storage` 并不是按“全局单例 repository”接入的，而是：

1. 底层共享一个 `session_factory`
2. 上层通过适配器按调用粒度创建 session
3. 最终挂在 `FastAPI app.state` 中给路由和服务使用

## 9. gateway / service 如何使用这些能力

### 9.1 依赖注入

[`backend/app/gateway/dependencies/repositories.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/dependencies/repositories.py) 从 `request.app.state` 取出：

1. `run_store`
2. `thread_meta_repo`
3. `thread_meta_storage`
4. `feedback_repo`

然后作为 FastAPI 依赖注入给路由层。

### 9.2 在线程路由中的调用

在线程路由 [`backend/app/gateway/routers/langgraph/threads.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/routers/langgraph/threads.py) 中：

1. 创建线程时调用 `ThreadMetaStorage.ensure_thread()`
2. 查询线程时调用 `ThreadMetaStorage.search_threads()`
3. 删除线程时调用 `ThreadMetaStorage.delete_thread()`

因此线程 API 并不直接碰 ORM 表，而是通过 infra 层完成。

### 9.3 在 runs facade 中的调用

[`backend/app/gateway/services/runs/facade_factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/facade_factory.py) 会把 storage 相关对象注入到 `RunsFacade`：

1. `run_read_repo`
2. `run_write_repo`
3. `run_delete_repo`
4. `thread_meta_storage`
5. `run_event_store`

然后再由：

1. `AppRunCreateStore`
2. `AppRunQueryStore`
3. `AppRunDeleteStore`
4. `StorageRunObserver`

这些 app 层组件去消费。

### 9.4 Run 生命周期如何回写数据库

`StorageRunObserver` 是一条很关键的链路。

它监听运行时生命周期事件，并把结果回写到持久层：

1. `RUN_STARTED` -> 更新 run 状态为 `running`
2. `RUN_COMPLETED` -> 更新 run 完结统计；必要时同步 thread title
3. `RUN_FAILED` -> 更新 run 错误状态和错误信息
4. `RUN_CANCELLED` -> 更新 run 为 `interrupted`
5. `THREAD_STATUS_UPDATED` -> 同步 thread status

这说明 `storage` 包不负责主动监听运行时事件，但 `app.infra.storage` 已经把它接到了运行时 observer 体系中。

## 10. 如何与外部通信

这里的“外部通信”可以分成两类。

### 10.1 与数据库通信

`storage` 包通过 SQLAlchemy async engine 与 SQLite / MySQL / PostgreSQL 通信。

通信入口是：

1. `create_async_engine`
2. `AsyncSession`
3. repository 中的 `select / update / delete`

LangGraph checkpointer 也通过各自的异步 saver 与数据库通信，但这部分被统一收敛在 `persistence/drivers` 中。

### 10.2 与应用外部接口通信

`storage` 包本身不直接暴露外部 API；对外通信由 `app` 层完成。

当前典型路径是：

1. HTTP 请求进入 FastAPI 路由
2. 路由从依赖注入中拿到 `infra` 适配器
3. `infra` 调用 `storage` 仓储
4. 数据结果再由路由转换为 API 响应

另外一条链路是运行时事件：

1. runtime 产生 run lifecycle event 或 run event
2. observer / event store 调用 `infra`
3. `infra` 调用 `storage`
4. 数据写入数据库

所以更准确地说，`storage` 的“对外通信方式”不是自己发请求，而是作为应用内部的数据库边界，被 HTTP 层和 runtime 层共同消费。

## 11. 当前包的设计理念

从现有代码看，这个包的设计理念比较明确：

1. 统一 checkpointer 和应用数据存储入口。
2. 以 repository contract 隔离上层业务与底层 ORM。
3. 用 `infra` 适配层隔离 app 语义与 storage 语义。
4. 优先采用异步 SQLAlchemy，适配现代 async 应用栈。
5. 保持数据库方言兼容性，把差异尽量收敛在基础类型和 driver 构造层。
6. 把 actor / user 可见性控制放在 app infra，而不是硬编码进底层 ORM 模型。

这意味着它不是一个“全功能业务数据层”，而是一个“可装配的底层持久化能力包”。

## 12. 作用范围与边界

当前 `storage` 包负责的范围：

1. 数据库连接参数和初始化
2. LangGraph checkpointer 接入
3. ORM 基础模型约定
4. DeerFlow 核心持久化模型
5. 仓储协议与数据库实现

当前不负责的范围：

1. FastAPI 路由协议
2. 认证鉴权
3. 业务工作流编排
4. actor 上下文绑定
5. SSE / stream bridge 的网络层通信
6. 更高层的 facade 业务语义

这些职责分别落在 `app.gateway`、`app.plugins.auth`、`deerflow.runtime` 和 `app.infra` 中。

## 13. 一条完整调用链示例

以“创建 run 并在运行结束后更新状态”为例，链路如下：

```text
HTTP POST /api/threads/{thread_id}/runs
  -> gateway router
  -> RunsFacade
  -> AppRunCreateStore
  -> RunStoreAdapter
  -> build_run_repository(session)
  -> DbRunRepository
  -> runs 表

运行完成
  -> runtime 产生 lifecycle event
  -> StorageRunObserver
  -> RunStoreAdapter / ThreadMetaStorage
  -> DbRunRepository / DbThreadMetaRepository
  -> runs / thread_meta 表
```

以“查询 run 的消息”为例：

```text
HTTP GET /api/threads/{thread_id}/runs/{run_id}/messages
  -> gateway router
  -> 从 app.state 获取 run_event_store
  -> AppRunEventStore
  -> build_run_event_repository(session)
  -> DbRunEventRepository
  -> run_events 表
```

## 14. 总结

`backend/packages/storage` 当前在整个工程中的角色，可以概括为一句话：

它是 DeerFlow 的数据库和持久化能力底座，统一封装了数据库接入、ORM 模型、仓储协议、数据库实现以及 LangGraph checkpointer 接入；而 `app` 层通过 `infra` 适配器把这些底层能力转化成线程、运行、事件、反馈等上层语义，再通过 HTTP 路由和运行时事件系统对外提供服务。
