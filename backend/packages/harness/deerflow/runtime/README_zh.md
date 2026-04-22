# deerflow.runtime 设计说明

本文基于当前代码实现，说明 `backend/packages/harness/deerflow/runtime` 的总体设计、约束边界、`stream_bridge` 与 `runs` 的协作方式、与外部基础设施和 `app` 层的交互方式，以及 `actor_context` 如何通过动态注入实现用户隔离。

## 1. 总体定位

`deerflow.runtime` 是 DeerFlow 的运行时内核层。它位于 agent / tool / middleware 之下、app / gateway / infra 之上，主要负责定义“运行时语义”和“基础边界契约”，而不直接拥有 Web 接口、数据库模型或具体基础设施实现。

当前 `runtime` 的公开表面由 [`__init__.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/__init__.py) 统一导出，主要包括四类能力：

1. `runs`
   - run 领域类型、执行 façade、生命周期观察者、store 协议
2. `stream_bridge`
   - 流式事件桥接契约与公共类型
3. `actor_context`
   - 请求/任务级的 actor 上下文与用户隔离桥
4. `serialization`
   - 运行时对外事件与 LangChain / LangGraph 数据的序列化能力

从结构上看，可以把当前 `runtime` 理解成：

```text
runtime
  ├─ runs
  │   ├─ facade / types / observer / store
  │   ├─ internal/*
  │   └─ callbacks/*
  ├─ stream_bridge
  │   ├─ contract
  │   └─ exceptions
  ├─ actor_context
  └─ serialization / converters
```

## 2. 总体设计与约束范式

### 2.1 设计目标

`runtime` 当前最核心的设计目标是把“运行时控制面”和“基础设施实现”解耦。

它自己只关心：

1. run 是什么、状态如何变化
2. 执行时会产出哪些生命周期事件和流式事件
3. 哪些能力必须由外部注入，例如 checkpointer、event store、stream bridge、durable store
4. 当前 actor 是谁，以及下游如何据此做隔离

它刻意不关心：

1. 事件是落到内存、Redis 还是别的消息介质
2. run / thread / feedback 是怎么持久化的
3. HTTP / SSE / FastAPI 细节
4. 认证插件如何识别 request user

### 2.2 约束边界

当前 `runtime` 的边界约束比较明确：

1. `runs` 负责运行编排，不直接写 ORM 或 SQL。
2. `stream_bridge` 只定义流语义，不提供 app 级基础设施装配。
3. `actor_context` 只定义运行时上下文，不依赖 auth plugin。
4. durable 数据只能通过协议边界接入：
   - `RunCreateStore`
   - `RunQueryStore`
   - `RunDeleteStore`
   - `RunEventStore`
5. 生命周期副作用只能通过 `RunObserver` 接入。
6. 用户隔离不是散落在每个模块里做，而是通过 actor context 自上而下传递。

这套范式可以概括成一句话：

`runtime` 定义语义和边界，`app.infra` 提供实现和装配。

## 3. runs 子系统的设计

### 3.1 作用

`runtime/runs` 是运行编排域。它负责：

1. 定义 run 的领域对象与状态机
2. 组织 create / stream / wait / join / cancel / delete 等操作
3. 维护进程内运行控制面
4. 在执行期间发出流式事件与生命周期事件
5. 通过 callbacks 收集 trace、token、title、message 等运行数据

### 3.2 核心对象

见 [`runs/types.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/types.py)。

关键对象有：

1. `RunSpec`
   - 由 app 输入层构建，是执行器输入
2. `RunRecord`
   - 运行中的记录对象，由 `RunRegistry` 管理
3. `RunStatus`
   - `pending` / `starting` / `running` / `success` / `error` / `interrupted` / `timeout`
4. `RunScope`
   - 区分 stateful / stateless 与临时 thread

### 3.3 当前约束

当前 `runs` 明确限制了一些能力范围：

1. `multitask_strategy` 当前主路径只支持 `reject` 和 `interrupt`
2. `enqueue`、`after_seconds`、批量执行等尚未进入当前主路径
3. `RunRegistry` 是进程内状态，不是 durable source of truth
4. 外部查询可以走 durable store，但控制面仍然以内存 registry 为中心

### 3.4 façade 与内部组件

`RunsFacade` 在 [`runs/facade.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/facade.py) 中暴露统一入口：

1. `create_background`
2. `create_and_stream`
3. `create_and_wait`
4. `join_stream`
5. `join_wait`
6. `cancel`
7. `get_run`
8. `list_runs`
9. `delete_run`

它底层组合了：

1. `RunRegistry`
2. `ExecutionPlanner`
3. `RunSupervisor`
4. `RunStreamService`
5. `RunWaitService`
6. `RunCreateStore` / `RunQueryStore` / `RunDeleteStore`
7. `RunObserver`

也就是说，`RunsFacade` 是 public entry point，而真正的执行和状态推进拆散在内部组件中。

## 4. stream_bridge 的设计和实现思路

### 4.1 为什么单独抽象

`StreamBridge` 在 [`stream_bridge/contract.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/stream_bridge/contract.py) 中定义。

把它单独抽象出来的原因是：run 执行期间需要一个“可订阅、可回放、可终止、可恢复”的事件通道，而这件事不能直接绑定到 HTTP SSE、in-memory queue 或 Redis 细节。

所以：

1. harness 负责定义流语义
2. app 层负责选择和实现流后端

### 4.2 契约内容

`StreamBridge` 当前提供这些关键方法：

1. `publish(run_id, event, data)`
2. `publish_end(run_id)`
3. `publish_terminal(run_id, kind, data)`
4. `subscribe(run_id, last_event_id, heartbeat_interval)`
5. `cleanup(run_id, delay=0)`
6. `cancel(run_id)`
7. `mark_awaiting_input(run_id)`
8. `start()`
9. `close()`

公共类型包括：

1. `StreamEvent`
2. `StreamStatus`
3. `ResumeResult`
4. `HEARTBEAT_SENTINEL`
5. `END_SENTINEL`
6. `CANCELLED_SENTINEL`

### 4.3 语义边界

当前契约显式区分了两类终止语义：

1. `end` / `cancel` / `error`
   - 是 run 级别的真实业务终止事件
2. `close()`
   - 是 bridge 自身关闭
   - 不应被当作 run 被取消

### 4.4 当前实现方式

当前实际使用的实现是 app 层的 [`MemoryStreamBridge`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/stream_bridge/adapters/memory.py)。

它的设计是“每个 run 一条内存事件日志”：

1. `_RunStream` 保存事件列表、offset 映射、状态、subscriber 计数和 awaiting-input 标记
2. `publish()` 生成递增事件 ID 并追加到 per-run log
3. `subscribe()` 支持 replay、heartbeat、resume、terminal 退出
4. `cleanup_loop()` 处理：
   - 过老 stream
   - 长时间无 publish 的 active stream
   - orphan terminal stream
   - TTL 过期 stream
5. `mark_awaiting_input()` 为 HITL 场景延长超时

Redis 版本当前仍在 [`RedisStreamBridge`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/stream_bridge/adapters/redis.py) 中作为占位。

### 4.5 调用链路

stream bridge 在运行链路中的作用可以概括为：

```text
RunsFacade
  -> RunStreamService
  -> StreamBridge
  -> app route converts events to SSE
```

更具体地说：

1. `_RunExecution._start()` 会发布 `metadata`
2. `_RunExecution._stream()` 会把 agent 的 `astream()` 输出统一转成 bridge 事件
3. `_RunExecution._finish_success()` / `_finish_failed()` / `_finish_aborted()` 会发布 terminal 事件
4. `RunWaitService` 通过 `subscribe()` 等待 `values` / `error` / terminal
5. app 路由层再把这些事件转换为对外 SSE

### 4.6 后续扩展

后续可以沿几个方向扩展：

1. Redis 真正落地，支持跨进程 / 多实例流桥接
2. 更完整的 Last-Event-ID gap recovery
3. 更细粒度的 HITL 状态管理
4. 跨节点运行协调和 dead-letter 策略

## 5. 如何与外部通信，store 如何读写数据

### 5.1 两条主要外部边界

`runtime` 自身不直接发 HTTP 请求，也不直接写 ORM，但通过两条主边界与外界交互：

1. `StreamBridge`
   - 对外输出流式运行事件
2. `store` / `observer`
   - 对外输出 durable 数据与生命周期副作用

### 5.2 store 边界协议

在 [`runs/store`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/store) 中定义了四个协议：

1. `RunCreateStore`
2. `RunQueryStore`
3. `RunDeleteStore`
4. `RunEventStore`

这些协议不是 harness 内部的数据层，而是 harness 对 app 层的依赖声明。

### 5.3 app 层如何提供 store 实现

当前 app 层提供了这些实现：

1. [`AppRunCreateStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/store/create_store.py)
2. [`AppRunQueryStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/store/query_store.py)
3. [`AppRunDeleteStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/store/delete_store.py)
4. [`AppRunEventStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/run_events.py)
5. [`JsonlRunEventStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/run_events/jsonl_store.py)

这里的统一模式是：

1. harness 只看协议
2. app 层自己决定 session、commit、访问控制和后端选型
3. durable 数据最终通过 `store.repositories.*` 落数据库，或者通过 JSONL 落盘

### 5.4 runs 生命周期数据是怎么写出去的

单次执行器 [`_RunExecution`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/internal/execution/executor.py) 不直接写数据库。

它把数据写出去的方式有三条：

1. bridge 事件
   - 流式发布给订阅者
2. callback -> `RunEventStore`
   - 执行 trace / message / tool / custom event 以批次方式落地
3. lifecycle event -> `RunObserver`
   - 把 run 开始、完成、失败、取消、thread status 更新发给 app 层观察者

### 5.5 `RunEventStore` 的后端

`RunEventStore` 当前由 app 层工厂 [`app/infra/run_events/factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/run_events/factory.py) 统一构造：

1. `run_events.backend == "db"`
   - 走 `AppRunEventStore`
2. `run_events.backend == "jsonl"`
   - 走 `JsonlRunEventStore`

因此，`runtime` 不关心事件最终是数据库还是文件，它只要求支持 `put_batch()` 和相关读取方法。

## 6. runs 生命周期数据、callback 和查询回写

### 6.1 单次 run 的主流程

`_RunExecution.run()` 的主流程是：

1. `_start()`
2. `_prepare()`
3. `_stream()`
4. `_finish_after_stream()`
5. `finally`
   - `_emit_final_thread_status()`
   - `callbacks.flush()`
   - `bridge.cleanup(run_id)`

### 6.2 start 阶段记录什么

`_start()` 会：

1. 把 run 状态置为 `running`
2. 发出 `RUN_STARTED`
3. 抽取首条 human message，并发出 `HUMAN_MESSAGE`
4. 捕获 pre-run checkpoint id
5. 发布 `metadata` 流事件

### 6.3 callbacks 收集什么

当前 callbacks 位于 [`runs/callbacks`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/callbacks)。

主要有三类：

1. `RunEventCallback`
   - 记录 run_start / run_end / llm_request / llm_response / tool_start / tool_end / tool_result / custom_event 等
   - 按批 flush 到 `RunEventStore`
2. `RunTokenCallback`
   - 聚合 token 使用、LLM 调用次数、lead/subagent/middleware token、message_count、首条 human message、最后一条 AI message
3. `RunTitleCallback`
   - 从 title middleware 响应或 custom event 中提取 thread title

### 6.4 completion_data 如何形成

`RunTokenCallback.completion_data()` 会得到 `RunCompletionData`，包括：

1. `total_input_tokens`
2. `total_output_tokens`
3. `total_tokens`
4. `llm_call_count`
5. `lead_agent_tokens`
6. `subagent_tokens`
7. `middleware_tokens`
8. `message_count`
9. `last_ai_message`
10. `first_human_message`

执行器在完成 / 失败 / 取消时都会把这份数据带入 lifecycle payload。

### 6.5 app 层如何回写

执行器通过 [`RunEventEmitter`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/internal/execution/events.py) 发出 `RunLifecycleEvent`。

app 层 [`StorageRunObserver`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/runs.py) 再根据事件类型回写 durable 状态：

1. `RUN_STARTED`
   - 更新 run 状态为 `running`
2. `RUN_COMPLETED`
   - 写 completion_data
   - 同步 title 到 thread metadata
3. `RUN_FAILED`
   - 写 error 和 completion_data
4. `RUN_CANCELLED`
   - 写 `interrupted` 状态与 completion_data
5. `THREAD_STATUS_UPDATED`
   - 同步 thread status

### 6.6 查询路径

`RunsFacade.get_run()` / `list_runs()` 有两条路径：

1. 注入了 `RunQueryStore` 时，优先查 durable store
2. 否则回退到 `RunRegistry`

这意味着：

1. 内存 registry 负责控制面
2. durable store 负责对外查询面

## 7. actor_context 如何动态注入并实现用户隔离

### 7.1 设计目标

`actor_context` 在 [`actor_context.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/actor_context.py) 中定义。

它的目标是让 runtime 和下游基础模块可以依赖“当前 actor 是谁”这个运行时事实，但不直接依赖 auth plugin、FastAPI request 或具体用户模型。

### 7.2 当前实现方式

当前实现是一个基于 `ContextVar` 的请求/任务级上下文：

1. `ActorContext`
   - 当前只有 `user_id`
2. `_current_actor`
   - `ContextVar[ActorContext | None]`
3. `bind_actor_context(actor)`
   - 绑定当前 actor
4. `reset_actor_context(token)`
   - 恢复之前上下文
5. `get_actor_context()`
   - 获取当前 actor
6. `get_effective_user_id()`
   - 取当前 user_id，如果没有则返回 `DEFAULT_USER_ID`
7. `resolve_user_id(value=AUTO | explicit | None)`
   - 在 repository / storage 边界统一解析 user_id

### 7.3 app 如何动态注入

动态注入链路当前在 auth plugin 侧完成。

HTTP 请求路径：

1. [`app.plugins.auth.security.middleware`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/security/middleware.py)
   - 从认证后的 request user 构造 `ActorContext(user_id=...)`
   - 在请求处理期间绑定 / 重置 runtime actor context
2. [`app.plugins.auth.security.actor_context`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/security/actor_context.py)
   - 提供 `bind_request_actor_context(request)` 和 `bind_user_actor_context(user_id)`
   - 在路由或非 HTTP 入口中显式绑定 runtime actor

非 HTTP / 外部通道路径：

1. [`app/channels/manager.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/channels/manager.py)
2. [`app/channels/feishu.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/channels/feishu.py)

这些入口在把外部消息转入 runtime 前，也会用 `bind_user_actor_context(user_id)` 包住执行过程。这样做的意义是：

1. runtime 不区分请求来自 HTTP、飞书还是别的 channel
2. 只要入口能解析出 user_id，就能把同一套隔离语义注入进去
3. 同一份 runtime/store/path/memory 代码不需要知道上层协议来源

因此 runtime 自己不知道 request 是什么，也不知道 auth plugin 的 user model 长什么样；它只知道当前 `ContextVar` 中是否绑定了 `ActorContext`。

### 7.4 注入后的传播语义

这里的“动态注入”本质上不是把 `user_id` 一层层作为函数参数硬传下去，而是在 app 边界把 actor 绑定进 `ContextVar`，让当前请求/任务上下文中的 runtime 代码按需读取。

当前语义可以理解为：

1. 入口边界先 `bind_actor_context(...)`
2. 在该上下文内创建的异步调用链共享同一个 actor 视图
3. 请求结束或任务退出后用 `reset_actor_context(token)` 恢复

这有两个直接效果：

1. 运行链路中的大部分接口不需要把 `user_id` 塞进每一层函数签名
2. 真正需要 durable 隔离或路径隔离的边界，仍然可以通过 `resolve_user_id()` / `get_effective_user_id()` 显式取值

### 7.5 用户隔离如何生效

用户隔离当前是通过“动态注入 + 下游统一读取”实现的。

几条关键链路如下：

1. path / uploads / sandbox / memory
   - 通过 `get_effective_user_id()` 把 user_id 带入路径解析和目录隔离
2. app storage adapter
   - 通过 `resolve_user_id(AUTO)` 在 `RunStoreAdapter`、`ThreadMetaStorage` 等处做查询和写入隔离
3. run event store
   - `AppRunEventStore` 会读取 `get_actor_context()`，判断当前 actor 是否可见指定 thread

也就是说，用户隔离并不是靠单一中间件“一次性做完”，而是：

1. app 边界把 actor 动态绑定进 runtime context
2. runtime 及其下游模块在需要时读取该 context
3. 每个边界按自己的职责决定如何使用 user_id

### 7.6 这种方式的优点

当前设计有几个明显优点：

1. runtime 不依赖具体 auth 实现
2. HTTP 和非 HTTP 入口都能复用同一套隔离机制
3. user_id 可以自然传递到路径、memory、store、事件可见性等不同边界
4. 需要强约束时可通过 `AUTO` + `resolve_user_id()` 强制要求 actor context 存在

### 7.7 后续如何扩展

`ActorContext` 文件里已经预留了扩展点注释，后续完全可以在不破坏当前模式的前提下继续扩展：

1. `tenant_id`
   - 用于多租户隔离
2. `subject_id`
   - 用于更稳定的主体标识
3. `scopes`
   - 用于更细粒度授权
4. `auth_source`
   - 用于记录来源渠道

扩展方式建议保持现有模式不变：

1. 继续由 app/auth 边界负责绑定 richer `ActorContext`
2. runtime 只依赖抽象上下文字段，不依赖 request/user 对象
3. 下游基础模块按需读取必要字段
4. 在 store / path / sandbox / stream / memory 等边界逐步引入 tenant-aware 或 scope-aware 行为

更具体地说，后续如果要做多租户和更强隔离，推荐按边界渐进式扩展：

1. store 边界
   - 在 `RunStoreAdapter`、`ThreadMetaStorage`、feedback/event store 中引入 `tenant_id` 过滤
2. 路径与沙箱边界
   - 把目录分片从 `user_id` 扩展成 `tenant_id/user_id`
3. 事件可见性边界
   - 在 run event 查询和 thread 查询时叠加 `scopes` 或 `subject_id`
4. 外部通道边界
   - 为不同来源填充 `auth_source`，区分 API / channel / internal job

这样 runtime 仍然只依赖“当前 actor 上下文”这个抽象，不会重新耦合回 FastAPI request 或某个认证实现。

## 8. 与 app 层的交互

### 8.1 app 如何装配 runtime

当前 app 层会在 [`app/gateway/services/runs/facade_factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/facade_factory.py) 装配 `RunsFacade`。

它会组装：

1. `RunRegistry`
2. `ExecutionPlanner`
3. `RunSupervisor`
4. `RunStreamService`
5. `RunWaitService`
6. `RunsRuntime`
   - `bridge`
   - `checkpointer`
   - `store`
   - `event_store`
   - `agent_factory_resolver`
7. `StorageRunObserver`
8. `AppRunCreateStore`
9. `AppRunQueryStore`
10. `AppRunDeleteStore`

### 8.2 app.state 如何提供基础设施

在 [`app/gateway/registrar.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/registrar.py)：

1. `init_persistence()` 创建：
   - `persistence`
   - `checkpointer`
   - `run_store`
   - `thread_meta_storage`
   - `run_event_store`
2. `init_runtime()` 创建：
   - `stream_bridge`

然后这些对象挂在 `app.state`，供依赖注入和 façade 构造使用。

### 8.3 `stream_bridge` 的 app 边界

当前具体 stream bridge 的装配已经完全属于 app 层：

1. harness 只导出 `StreamBridge` 契约
2. 具体实现由 [`app.infra.stream_bridge.build_stream_bridge`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/stream_bridge/factory.py) 构造

这条边界非常清晰：

1. harness 定义运行语义和接口
2. app 选择和构造基础设施实现

## 9. 设计总结

可以把当前 `deerflow.runtime` 总结为一句话：

它是一个“以 run orchestration 为核心、以 stream bridge 为流式边界、以 actor context 为动态隔离桥、以 store / observer 为 durable 与副作用边界”的运行时内核层。

更具体地说：

1. `runs` 负责编排和生命周期推进
2. `stream_bridge` 负责流语义
3. `actor_context` 负责运行时用户上下文和隔离桥
4. `serialization` / `converters` 负责对外事件与消息格式转换
5. app 层通过 infra 负责真正的持久化、流式基础设施和 auth 注入

这套结构的优势是：

1. 运行语义与基础设施实现解耦
2. 请求身份与 runtime 逻辑解耦
3. HTTP、CLI、channel worker 等多种入口都可以复用同一套 runtime 边界
4. 后续可平滑扩展到多租户、跨进程 stream bridge、更多 durable backend

当前的主要限制也同样清楚：

1. `RunRegistry` 仍然是进程内控制面
2. Redis bridge 仍未落地
3. 一些多任务策略和批量能力仍未进入主路径
4. `actor_context` 目前只携带 `user_id`，还没有 tenant / scopes / auth_source 等 richer context

因此，当前最准确的理解方式不是“最终态平台”，而是“已经具备清晰语义和扩展边界的 runtime kernel”。
