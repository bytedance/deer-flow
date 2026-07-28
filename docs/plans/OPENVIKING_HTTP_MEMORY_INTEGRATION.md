# OpenViking HTTP Memory Backend 接入实现方案

> 状态：设计稿
> 范围：通过 HTTP 将 OpenViking 接入为 DeerFlow 的可选 `MemoryManager` 后端
> 默认行为：DeerMem 继续作为默认后端，OpenViking 需要显式启用
> 非目标：本文不包含代码实现、DeerMem 存量数据迁移、OpenViking 服务端开发

## 1. 背景

DeerFlow 已提供可插拔的 `MemoryManager` 接口。内置的 DeerMem 负责从对话中提取事实、持久化事实并向后续对话注入记忆；`noop` 则提供最小空实现。后端发现器会扫描：

```text
backend/packages/harness/deerflow/agents/memory/backends/<backend_name>/
```

只要子包导出 `MANAGER_CLASS`，便可通过以下配置选择：

```yaml
memory:
  manager_class: <backend_name>
  backend_config: {}
```

OpenViking 本身提供 Session、Memory Extraction、语义检索、多租户和后台任务能力。它的 Session 生命周期为：

```text
创建 Session
  -> 添加 user/assistant 消息
  -> commit
  -> 同步归档消息
  -> 后台生成摘要并提取长期记忆
  -> 后续 search/find 检索记忆
```

因此，本方案不在 DeerFlow 内重复实现 OpenViking 已具备的抽取、去重、合并和向量索引逻辑，而是在 DeerFlow 的 `MemoryManager` 边界增加一个 HTTP 适配器。

## 2. 目标

首版实现以下闭环：

1. DeerFlow 能通过配置选择 `openviking` 记忆后端。
2. 每轮对话完成后，DeerFlow 将本轮有效消息提交到对应的 OpenViking Session。
3. OpenViking 完成归档及异步长期记忆提取。
4. 新一轮对话开始时，DeerFlow 按当前用户、Agent 和线程范围检索相关记忆。
5. 检索结果被格式化为有长度上限的纯文本，通过现有 prompt 注入路径提供给 Agent。
6. OpenViking 短暂不可用时，DeerFlow 主对话链路可以按配置降级，并留下可观测错误。
7. 不同 DeerFlow 用户之间保持强隔离；不同 Agent 的专属记忆不会互相污染。

## 3. 非目标

以下内容不进入首版：

- 不替换 DeerFlow 的 thread、checkpoint、run event 等持久化系统。
- 不把 OpenViking 嵌入 DeerFlow Gateway 进程。
- 不修改 OpenViking 服务端。
- 不迁移现有 DeerMem Markdown/JSON 数据。
- 不接管 DeerFlow 的资源库、上传文件或 Skill 存储。
- 不保证现有 Memory 页面上的 fact 新增、编辑、删除按钮可用于 OpenViking。
- 不将 OpenViking 原生多类型记忆强行压平成 DeerMem 的事实模型。
- 不在首版启用 `memory.mode: tool`。
- 不在 DeerFlow 内再次调用 LLM 进行事实抽取、去重或合并。

## 4. 总体架构

```text
┌──────────────────────── DeerFlow Gateway ────────────────────────┐
│                                                                  │
│  MemoryMiddleware / summarization hook / prompt injection        │
│                              │                                   │
│                              ▼                                   │
│                    MemoryManager contract                        │
│                              │                                   │
│                              ▼                                   │
│               OpenVikingMemoryManager adapter                    │
│                  │                         │                     │
│                  ▼                         ▼                     │
│          scope/message mapping       result formatting           │
│                  │                         ▲                     │
│                  └──────── OpenVikingHttpClient ────────────────┐│
└─────────────────────────────────────────────────────────────────┼┘
                                                                  │ HTTP
                                                                  ▼
┌──────────────────────── OpenViking Server ───────────────────────┐
│  Sessions │ Memory Extraction │ Search │ Tasks │ Tenant Storage │
└──────────────────────────────────────────────────────────────────┘
```

OpenViking 作为独立服务运行。DeerFlow 只依赖其 HTTP API，不依赖 OpenViking 的 Python 嵌入式运行时。

选择 HTTP 模式的原因：

- 避免把 OpenViking 的模型、向量库、Rust/C++ 扩展和后台任务依赖带入 Gateway。
- OpenViking 可独立升级、扩容、监控和持久化。
- 一个 OpenViking 服务可以服务多个 DeerFlow Gateway 实例。
- HTTP 边界更容易进行超时、熔断、认证和契约测试。
- 降低 DeerFlow 与 OpenViking Python SDK 版本的耦合。

## 5. 代码布局

新增：

```text
backend/packages/harness/deerflow/agents/memory/backends/openviking/
├── __init__.py
├── config.py
├── client.py
├── models.py
└── openviking_manager.py
```

建议职责如下。

### 5.1 `__init__.py`

仅负责注册后端：

```python
from .openviking_manager import OpenVikingMemoryManager

MANAGER_CLASS = OpenVikingMemoryManager
```

目录名、注册名和配置值统一使用 `openviking`。

### 5.2 `config.py`

定义并验证 OpenViking 私有配置，禁止读取 DeerFlow 全局配置单例。所有值均从 `backend_config` 或明确的环境变量引用取得。

职责包括：

- 校验 `base_url`；
- 校验认证模式；
- 解析 API key 环境变量名；
- 校验 timeout、重试次数、检索数量和注入长度；
- 为日志生成脱敏后的配置摘要；
- 拒绝未知字段，避免拼写错误静默失效。

### 5.3 `models.py`

定义适配器内部数据模型，隔离 OpenViking HTTP 响应格式变化，例如：

```text
OpenVikingMessage
OpenVikingSearchHit
OpenVikingCommitResult
OpenVikingTaskStatus
OpenVikingErrorBody
```

这些模型不暴露到 DeerFlow 公共 API，也不导入 OpenViking SDK 类型。

### 5.4 `client.py`

实现一个薄 HTTP Client，只封装接入所需的稳定 API：

- `GET /health`
- 创建或获取 Session
- 批量添加 Session 消息
- commit Session
- 查询后台 Task
- `search`/`find` 检索

HTTP URL、请求头、响应 envelope、timeout、重试和错误转换全部集中在此文件。`OpenVikingMemoryManager` 不直接拼接 URL。

### 5.5 `openviking_manager.py`

实现 `MemoryManager`：

- `from_config`
- `add`
- `add_nowait`
- `get_context`
- `search`
- `shutdown_flush`
- 可选 `warm`

首版不实现的管理方法继承基类的 `NotImplementedError`。

## 6. DeerFlow 与 OpenViking 的概念映射

### 6.1 租户与用户

推荐映射：

| DeerFlow | OpenViking | 说明 |
|---|---|---|
| 一个 DeerFlow 部署或业务工作区 | `account` | 外层租户边界 |
| `user_id` | `user` | 用户记忆和 Session 的隔离边界 |
| `agent_name` | Agent scope/tag/安全 URI 段 | 同一用户下的 Agent 专属范围 |
| `thread_id` | Session 稳定键的一部分 | 对话来源，不单独作为全局 Session ID |

OpenViking 的 `user` 是强数据边界。每个请求必须显式带上当前 DeerFlow 用户身份，不能依赖 OpenViking 的 `default/default` 开发身份。

首版推荐使用 OpenViking `trusted` 认证模式，由 DeerFlow Gateway 向内部 OpenViking 服务传递：

```text
X-OpenViking-Account: <configured account>
X-OpenViking-User: <current DeerFlow user_id>
X-API-Key: <trusted upstream key, if configured>
```

部署必须满足以下安全条件：

- OpenViking 仅暴露在可信内网；
- 外部客户端不能绕过 DeerFlow 直接伪造 account/user header；
- DeerFlow 不接受客户端传入的 OpenViking account/user 值；
- user 值只来自 DeerFlow 已认证的 runtime user context；
- API key 只从服务端环境变量或 secrets provider 读取。

如后续选择 OpenViking `api_key` 模式，需要增加用户注册、用户 key 保存、轮换和吊销机制，不作为首版默认方案。

### 6.2 Agent 范围

DeerFlow 当前记忆作用域是：

```text
(user_id, agent_name)
```

其中 `agent_name=None` 表示默认/共享桶。OpenViking 的用户记忆默认属于整个用户，因此必须额外表达 Agent 范围。

首版采用以下逻辑命名：

```text
default Agent: __default__
custom Agent:  canonicalize(agent_name)
```

`canonicalize` 必须与 DeerFlow Agent 命名规则一致：

- 转为小写；
- 只允许安全字符；
- 拒绝路径分隔符、`.`、`..` 和控制字符；
- 显式 Agent 不允许占用 `__default__`。

首版采用独立 OpenViking trusted-user 映射作为硬隔离边界：

```text
openviking_user = "df_" + sha256(account + user_id + agent_scope)[:40]
```

这样不依赖 OpenViking 的实验性 Agent tag/URI 过滤语义，不同 DeerFlow
Agent 不可能通过一次普通用户级检索读到彼此的记忆。代价是同一 DeerFlow
用户的 profile/preferences 不会自动跨 Agent 共享；这是首版为强隔离选择的
明确权衡。后续只有在 OpenViking 提供稳定、服务端强制的 Agent 过滤后，才
考虑改为同一 OpenViking user 下的子范围，并且需要数据迁移方案。

### 6.3 Thread 与 Session

Session ID 必须稳定、不可碰撞且不暴露原始标识。建议：

```text
session_id = "df_" + base32(
    sha256(
        integration_namespace
        + "\0" + account
        + "\0" + user_id
        + "\0" + canonical_agent_scope
        + "\0" + thread_id
    )
)
```

要求：

- 同一用户、Agent、线程始终映射到同一 Session；
- 任意一个作用域字段不同，Session ID 必须不同；
- 不直接把邮箱、用户名或 thread ID 放进 OpenViking Session ID；
- 算法一旦发布不得随意修改；
- `integration_namespace` 使用固定版本值，例如 `deerflow-openviking-v1`。

## 7. 写入流程

### 7.1 正常写入

现有 `MemoryMiddleware` 在 Agent 一轮完成后调用：

```python
manager.add(
    thread_id,
    messages,
    agent_name=...,
    user_id=...,
    trace_id=...,
)
```

OpenViking 后端处理流程：

```text
接收 DeerFlow messages
  -> 验证 user_id/thread_id
  -> 计算 Agent scope 与 Session ID
  -> 过滤框架内部消息
  -> 转换 user/assistant 文本消息
  -> 根据同步水位去除已提交到 Session 的消息
  -> 批量写入 OpenViking Session
  -> 原子记录 submitted 水位
  -> commit Session
  -> 推进 committed 水位并记录 commit task_id
  -> 返回，不等待后台提取完成
```

首版应使用 OpenViking 的批量消息接口；若锁定版本不支持批量接口，Client 可内部降级为逐条提交，但 Manager 接口保持批量语义。

### 7.2 消息过滤

首版只同步：

- 用户的真实输入；
- Agent 最终可见的 assistant 回复。

首版不上传：

- system prompt；
- middleware 内部提醒；
- `hide_from_ui` 且不含真实用户澄清内容的消息；
- tool call 的原始参数与完整输出；
- 二进制或 base64 payload；
- 仅用于流式拼接的中间 assistant chunk；
- subagent 内部推理和不可见消息。

消息过滤应由适配器自己的纯函数完成并单独测试。后端可以消费 DeerFlow 工厂传入的 `should_keep_hidden_message` hook，但不能直接导入 DeerFlow 的消息过滤内部模块。

### 7.3 幂等与同步水位

`add`、总结前的 `add_nowait`、请求重试和 Gateway 关闭 flush 可能看到重叠消息。仅依赖 OpenViking 去重不足以保证不会重复归档。

适配器需要保存每个 Session 的同步水位：

```json
{
  "schema_version": 2,
  "session_id": "df_...",
  "submitted_message_ids": ["..."],
  "committed_message_ids": ["..."],
  "last_commit_task_id": "...",
  "last_archive_uri": "viking://..."
}
```

水位文件使用工厂提供的 `backend_config.storage_path`，建议位置：

```text
<storage_path>/openviking/sessions/<session_id>.json
```

要求：

- 原子写入；
- 不保存消息正文；
- 记录一个有界的近期 message ID 窗口，而不是无限增长；
- 批量添加成功后立即推进 `submitted_message_ids`，避免 commit 结果未知时
  在下一轮重复添加消息；
- commit 结果未知时不自动重试该 commit；后续相同历史直接跳过，出现新消息时
  只添加新消息，并由新的 commit 一并归档仍留在 Session 中的旧消息；
- commit 成功后将 `committed_message_ids` 推进到 submitted 水位并保存
  task/archive 元数据；
- 网络超时后需要区分“请求未到达”和“服务端可能已处理”；
- 若 OpenViking API 支持客户端 message ID，应始终发送 DeerFlow 的稳定 message ID。

这里的 submitted 水位只解决“批量添加已明确成功、随后 commit 失败”的确定性
重复路径。如果批量添加在服务端成功、但客户端在收到响应或保存水位前中断，
没有服务端幂等键仍无法做到 exactly-once；多 Gateway 部署同样需要共享水位或
OpenViking 原生幂等支持。

如果 DeerFlow 消息缺少稳定 ID，应基于角色、规范化内容和在本轮中的稳定位置生成适配器 ID，但该方案只作为兼容路径。

### 7.4 `add` 与 `add_nowait`

OpenViking 自己在 commit 后异步提取，不需要复制 DeerMem 的 debounce queue。

- `add`：完成消息上传和 commit 接受确认后返回。
- `add_nowait`：语义为“不要因 DeerFlow 总结丢失消息”，仍应立即完成上传和 commit 接受确认；它不是 fire-and-forget。

两者均不默认等待 OpenViking 后台 task 完成。

### 7.5 后台提取

OpenViking commit 通常先返回 `task_id`，摘要与长期记忆提取随后在后台执行。因此系统是最终一致的：

```text
commit accepted != memory immediately searchable
```

首版策略：

- 正常轮次不轮询 task；
- 保存最近一次 task ID 用于日志与诊断；
- task 失败不回滚 DeerFlow 主回复；
- `shutdown_flush` 只保证待上传消息已获得 commit 接受确认，不保证所有 OpenViking 提取任务完成；
- 集成测试可轮询 task 以验证完整闭环。

## 8. 检索与注入流程

### 8.1 `get_context`

`get_context` 没有显式 query 参数，而且当前 prompt 调用点也不传
`thread_id`。为保持主框架和共享接口不变，首版使用可配置的受控通用查询：

```text
user profile preferences important entities events ongoing goals constraints and prior decisions
```

该值由 `retrieval.injection_query` 配置。请求固定限制到当前 hashed trusted
user 的 `viking://user/memories`，并设置 `context_type=memory`。显式
`MemoryManager.search(query)` 仍使用调用者提供的语义查询。后续如果需要
基于当前用户输入进行更精准的自动召回，应单独为共享接口设计可选 query
参数并更新所有 backend，不能通过线程局部变量隐式传递。

### 8.2 `search`

映射到 OpenViking 检索接口：

```text
query           -> query
top_k           -> node_limit
user_id         -> OpenViking user identity
agent_name      -> Agent scope filter
context_type    -> memory
score_threshold -> backend_config.retrieval.score_threshold
```

返回值转换为 DeerFlow `memory_search` 可消费的字典：

```json
{
  "id": "stable-result-id-or-uri",
  "content": "retrieved memory text",
  "category": "openviking memory type",
  "confidence": 0.82,
  "source": "viking://...",
  "score": 0.82
}
```

字段规则：

- `id` 优先使用 OpenViking 稳定 URI；
- `content` 使用可读正文或 L1/L2 摘要，不返回内部原始 envelope；
- `category` 使用 OpenViking memory type；
- `confidence` 若 OpenViking 未提供事实置信度，可使用归一化检索 score，但必须在代码中明确这是兼容映射；
- `source` 只返回非敏感 URI；
- 不向模型返回 account、API key、内部文件系统路径或服务端堆栈。

首版 `category` 过滤应映射到 OpenViking memory type。若无法服务端过滤，可以在适配器中先过滤再截取 `top_k`，不能先截断再过滤。

### 8.3 注入文本

`get_context` 返回纯文本，由 DeerFlow 现有调用点包裹进 `<memory>`。适配器自身不得再添加 `<memory>` 标签。

建议格式：

```markdown
## Relevant long-term memory

- [preferences] User prefers concise technical explanations.
- [entities] Project Alpha uses Python 3.12.
- [experiences] Previous deployment succeeded after enabling trusted auth.
```

要求：

- 按相关度排序；
- 去除重复 URI 和重复内容；
- 限制单条长度；
- 限制总字符数或估算 token 数；
- 结果为空时返回空字符串；
- OpenViking 读取失败且配置为 fail-open 时返回空字符串；
- 不把 HTTP 错误文本注入 prompt。

## 9. `MemoryManager` 方法支持矩阵

| 方法 | 首版 | 实现策略 |
|---|---:|---|
| `from_config` | 支持 | 解析配置并创建 Client |
| `add` | 支持 | 批量添加消息并 commit |
| `add_nowait` | 支持 | 立即添加并 commit |
| `get_context` | 支持 | 检索并格式化注入文本 |
| `search` | 支持 | OpenViking memory search |
| `shutdown_flush` | 支持 | 有界等待本地待提交操作 |
| `warm` | 支持 | `/health`，不改变数据 |
| `get_memory` | 暂不支持 | 继承 `NotImplementedError` |
| `clear_memory` | 暂不支持 | 继承 `NotImplementedError` |
| `import_memory` | 暂不支持 | 继承 `NotImplementedError` |
| `reload_memory` | 暂不支持 | 继承默认行为 |
| `create_fact` | 暂不支持 | OpenViking 不是 DeerMem fact 模型 |
| `update_fact` | 暂不支持 | 同上 |
| `delete_fact` | 暂不支持 | 同上 |

由于 `supports_search=True`，技术上可通过 `MemoryManager` 的 tool-mode invariant，但首版配置校验应明确拒绝 `mode: tool`。原因是 DeerFlow tool 模式不仅需要 `search`，还暴露 `memory_add/update/delete`，而首版不实现 fact CRUD。

## 10. HTTP Client 设计

### 10.1 Client 接口

建议内部接口：

```python
class OpenVikingHttpClient:
    def health(self) -> bool: ...

    def ensure_session(
        self,
        *,
        identity: OpenVikingIdentity,
        session_id: str,
    ) -> None: ...

    def add_messages(
        self,
        *,
        identity: OpenVikingIdentity,
        session_id: str,
        messages: list[OpenVikingMessage],
    ) -> None: ...

    def commit_session(
        self,
        *,
        identity: OpenVikingIdentity,
        session_id: str,
    ) -> OpenVikingCommitResult: ...

    def search(
        self,
        *,
        identity: OpenVikingIdentity,
        query: str,
        session_id: str | None,
        agent_scope: str,
        top_k: int,
        category: str | None,
    ) -> list[OpenVikingSearchHit]: ...

    def get_task(
        self,
        *,
        identity: OpenVikingIdentity,
        task_id: str,
    ) -> OpenVikingTaskStatus: ...
```

### 10.2 HTTP 库

优先复用 DeerFlow 已声明的 HTTP 客户端库。若使用 `httpx`：

- 同步 `MemoryManager` 路径使用有连接池的 `httpx.Client`；
- Client 生命周期跟随 `OpenVikingMemoryManager` 单例；
- 禁止每次请求创建新 Client；
- 连接池上限配置化；
- 关闭时显式释放 Client。

不能直接使用 OpenViking 嵌入式 Python Client。若官方 HTTP SDK 只带来轻量依赖且能够稳定锁版本，可以在后续替换，但适配器内部 Client 接口不变。

### 10.3 Timeout

必须分别设置：

- connect timeout；
- read timeout；
- write timeout；
- pool timeout；
- shutdown 总预算。

任何请求不得无限等待。推荐初始值：

```yaml
connect_timeout_seconds: 2
read_timeout_seconds: 10
write_timeout_seconds: 10
pool_timeout_seconds: 2
shutdown_flush_timeout_seconds: 20
```

### 10.4 重试

只自动重试满足幂等条件的操作：

| 操作 | 自动重试 |
|---|---|
| health | 可以 |
| search/find | 可以 |
| get task | 可以 |
| ensure/get session | 可以 |
| add messages | 仅在稳定 message ID 被服务端幂等处理时 |
| commit | 仅在服务端提供幂等键或可确认当前 archive 状态时 |

重试采用有上限的指数退避和 jitter。HTTP 400/401/403/404 等确定性错误不重试；429、502、503、504 和连接建立失败可按策略重试。

### 10.5 错误类型

Client 将底层异常转换为适配器私有错误：

```text
OpenVikingConnectionError
OpenVikingTimeoutError
OpenVikingAuthenticationError
OpenVikingProtocolError
OpenVikingRateLimitError
OpenVikingUnavailableError
OpenVikingScopeError
```

错误对象可包含：

- 操作名；
- HTTP status；
- 可公开的错误码；
- request ID；
- 是否可重试。

错误对象不得包含：

- API key；
-完整认证 header；
- 用户消息正文；
- OpenViking 内部堆栈；
- 未脱敏的响应 body。

## 11. 失败与降级策略

### 11.1 启动

配置语法错误、认证模式矛盾或 URL 非法时启动失败，不能静默切换回 DeerMem。错误的持久化后端若被静默替换，会把记忆写入错误存储。

OpenViking 健康检查失败有两种可配置策略：

- `startup_policy: fail_fast`：生产推荐，Gateway 启动失败；
- `startup_policy: warn`：本地开发可用，Gateway 启动但记忆暂时降级。

### 11.2 读取

默认：

```yaml
failure_policy:
  read: fail_open
```

search/get_context 超时或服务不可用时：

- 记录结构化 warning/error；
- 返回空结果或空字符串；
- 不阻塞主 Agent 回复；
- 认证失败和 scope 错误使用更高等级日志，不视为普通临时故障。

### 11.3 写入

首版不实现无限持久化重试队列。默认：

```yaml
failure_policy:
  write: log_and_drop
```

含义：

- 写入失败不使已经生成的主回复失败；
- 记录 thread/session、操作类型和错误码；
- 不记录消息正文；
- 暴露指标以便告警；
- 明确承认本轮记忆可能未被 OpenViking 捕获。

后续如要求“至少一次”交付，应增加独立、持久化的 outbox，而不是简单扩大内存重试：

```text
DeerFlow commit outbox
  -> durable enqueue
  -> background delivery
  -> OpenViking idempotency
  -> acknowledge/delete
```

该能力不属于首版。

## 12. 配置草案

`config.example.yaml` 增加注释示例，默认仍为 `deermem`：

```yaml
memory:
  enabled: true
  mode: middleware
  injection_enabled: true
  manager_class: deermem

  # To use OpenViking over HTTP:
  # manager_class: openviking
  # backend_config:
  #   base_url: http://openviking:1933
  #   auth_mode: trusted
  #   account: deerflow
  #   api_key_env: OPENVIKING_API_KEY
  #
  #   connect_timeout_seconds: 2
  #   read_timeout_seconds: 10
  #   write_timeout_seconds: 10
  #   pool_timeout_seconds: 2
  #
  #   startup_policy: fail_fast
  #   failure_policy:
  #     read: fail_open
  #     write: log_and_drop
  #
  #   retrieval:
  #     top_k: 8
  #     score_threshold: 0.25
  #     max_injection_chars: 12000
  #
  #   session:
  #     wait_for_extraction: false
```

配置要求：

- `api_key_env` 保存环境变量名，不保存密钥值；
- `auth_mode=trusted` 时必须配置 `account`；
- 非 localhost 的 OpenViking URL 默认要求 HTTPS，或显式允许内部明文 HTTP；
- `top_k`、timeout 和注入长度设置合理上下限；
- `mode != middleware` 时首版拒绝启动；
- `/memory/config` 返回配置时只显示 `api_key_env`，不解析或回显密钥。

## 13. 并发与生命周期

`MemoryManager` 是进程级单例，可能从 Agent 请求线程、总结路径和 Gateway 关闭路径并发访问。

实现必须保证：

- HTTP Client 可跨线程安全使用，或使用明确的线程本地 Client；
- Session 水位更新有进程内锁；
- 多 Gateway 进程共享同一 `storage_path` 时使用跨进程锁或不依赖本地水位作为唯一真相；
- 同一 Session 的 add + commit 串行化；
- 不同 Session 可以并行；
- `shutdown_flush(timeout)` 遵守硬超时；
- Gateway 关闭后拒绝接受新的写入；
- Client close 与在途请求之间不存在竞态。

如果部署允许多个 Gateway 副本同时处理同一 thread，本地水位文件不足以提供全局一致性。此时必须依赖 OpenViking 稳定 message ID/幂等键，或把水位迁移到 DeerFlow 的共享数据库。首版发布前必须明确支持的部署拓扑。

## 14. 可观测性

至少记录以下结构化事件：

```text
openviking.health
openviking.session.ensure
openviking.messages.add
openviking.session.commit
openviking.search
openviking.task.status
openviking.degraded
```

推荐字段：

- operation；
- duration_ms；
- success；
- status_code；
- error_type；
- retry_count；
- result_count；
- account 的非敏感别名；
- user/session 的不可逆 hash；
- DeerFlow trace ID；
- OpenViking request ID/task ID。

禁止记录：

- API key；
-完整用户消息；
-完整记忆正文；
-认证 header；
-未经处理的 HTTP response body。

推荐指标：

```text
openviking_requests_total{operation,status}
openviking_request_duration_seconds{operation}
openviking_commit_total{status}
openviking_search_results{operation}
openviking_degraded_total{reason}
openviking_pending_writes
```

`MemoryCallbacks.on_memory_llm_call` 不适用于远程 OpenViking 内部的 LLM 调用，因为 DeerFlow 看不到该 LLM 边界。DeerFlow 应记录 HTTP 调用 span，并由 OpenViking 自己提供服务端模型调用可观测性。

## 15. 测试方案

### 15.1 单元测试

新增建议：

```text
backend/tests/test_openviking_memory_config.py
backend/tests/test_openviking_memory_client.py
backend/tests/test_openviking_memory_manager.py
backend/tests/test_openviking_memory_scope.py
```

配置测试：

- 合法配置；
- 未知字段；
- URL 和 timeout 边界；
- 环境变量密钥解析；
- 配置序列化不泄漏密钥；
- tool mode 被首版拒绝。

Client 测试：

- 正确 endpoint、method、header 和 body；
- trusted identity header；
- response envelope 解析；
- timeout；
- 401/403/429/5xx 映射；
- 只对允许操作重试；
- 日志脱敏。

Manager 测试：

- backend 注册发现；
- `from_config`；
- DeerFlow 消息过滤与转换；
- Session ID 稳定性和隔离性；
- add -> batch messages -> commit；
- 重复 message ID 不重复发送；
- search 结果转换；
- context 排序、去重和长度上限；
- read fail-open；
- write failure 不抛到主链路；
- shutdown 硬超时。

范围测试：

- 不同 user 的请求 header 和 Session 不同；
- 同一 user 不同 Agent 的 scope 不同；
- `agent_name=None` 稳定映射为默认范围；
- 非法 Agent 名称不能进入 URI/header；
- category 在 top-k 之前过滤；
- 检索请求始终限制为 `context_type=memory`。

### 15.2 契约测试

CI 默认使用 mock HTTP server，不要求安装或启动真实 OpenViking。契约测试应固定本项目所支持 OpenViking 版本的：

- endpoint；
-请求字段；
-响应 envelope；
-错误格式；
-认证 header；
-commit/task 状态枚举；
-search hit 字段。

OpenViking 升级时先更新契约 fixture，再修改 Client。

### 15.3 真实集成测试

提供可选测试标记，例如：

```text
pytest -m openviking_integration
```

真实测试至少验证：

```text
创建测试身份
  -> 写入一轮明确偏好
  -> commit
  -> 轮询 task 完成
  -> 新 Session 搜索该偏好
  -> 结果只在当前 user/Agent 范围可见
```

测试数据必须使用独立 account/user 前缀，并在测试后清理。

### 15.4 阻塞 IO 测试

本接入会引入网络 IO，必须纳入仓库 blocking-IO 检查：

- 确认所有同步 HTTP 调用都运行在允许的 worker/thread 路径；
- 不允许在 ASGI event loop 上直接执行同步 `httpx.Client` 请求；
- 为关键调用路径增加 `tests/blocking_io/` 回归锚点；
- 若现有调用点不能保证 offload，应优先改为调用 `aadd`、`aget_context`、`asearch` 的 async 实现，而不是在 backend 内创建隐藏 event loop。

## 16. 文档与部署

实现完成时需要同步更新：

- 根 `README.md`：列出 OpenViking 可选记忆后端；
- `backend/AGENTS.md`：记录架构、配置与测试边界；
- `config.example.yaml`：完整注释示例；
- 前端 application configuration 文档；
- harness memory 文档；
- memory backends README；
- OpenViking 服务部署与认证说明。

首版不要求修改 Docker Compose。部署文档先要求操作者提供：

- 可访问的 OpenViking Server URL；
- 已配置的 embedding/VLM；
- trusted auth 或用户 key；
-持久化存储；
-健康检查；
-支持版本。

后续可增加可选 Compose profile，而不把 OpenViking 变成 DeerFlow 的强制服务。

## 17. 实施阶段

### 阶段 0：版本与范围验证

- 锁定一个 OpenViking 支持版本；
- 验证 Session batch messages、commit、task、search API；
- 固定 hashed trusted-user Agent scope 映射；
- 固定 `retrieval.injection_query` 自动召回策略；
- 确认 OpenViking HTTP 错误 envelope；
- 产出固定的契约 fixture。

退出条件：身份隔离、Agent 隔离和 query 数据流没有未决设计。

### 阶段 1：HTTP Client

- 配置模型；
-内部数据模型；
- HTTP Client；
-认证、timeout、重试、错误映射；
- Client 单元测试。

退出条件：Client 可以在 mock server 上完成 health、消息提交、commit、task 和 search。

### 阶段 2：MemoryManager 适配

- backend 注册；
-作用域映射；
-消息转换；
-同步水位；
- `add`、`add_nowait`；
- `get_context`、`search`；
- `warm`、`shutdown_flush`；
- Manager 和隔离测试。

退出条件：mock 环境跑通 DeerFlow 写入与检索注入闭环。

### 阶段 3：真实联调

-连接真实 OpenViking；
-完成 commit 后轮询提取；
-跨 Session 召回；
-用户和 Agent 隔离；
-故障、超时和重启测试；
- blocking-IO 验证。

退出条件：验收用例全部通过，且 OpenViking 故障不会拖垮主对话链路。

### 阶段 4：文档与发布

-补充配置与部署文档；
-锁定兼容版本；
-记录已知限制；
-保留 DeerMem 默认值；
-增加发布说明和回滚方法。

## 18. 验收标准

功能：

- `manager_class: openviking` 可被后端扫描器发现并实例化；
- middleware 模式下每轮有效消息只提交一次；
- commit 获得接受确认并记录 task ID；
-后续对话能召回已完成提取的长期记忆；
-注入文本有明确长度上限；
-搜索结果可被 DeerFlow `memory_search` 兼容消费；
- OpenViking 内部完成抽取，DeerFlow 不执行第二套抽取。

隔离：

-不同 DeerFlow user 无法互相读写 Session 或记忆；
-同一 user 的不同 Agent 专属记忆按既定策略隔离；
-默认 Agent 与显式 Agent 不冲突；
-非法 scope 输入在发送 HTTP 请求前被拒绝。

可靠性：

-所有 HTTP 请求有硬 timeout；
-读取故障按配置 fail-open；
-写入故障不会导致已生成的主回复失败；
-不存在 API key 日志泄漏；
- shutdown 遵守总预算；
-同步网络 IO 不阻塞 ASGI event loop。

兼容：

- DeerMem 继续为默认 backend；
-未配置 OpenViking 的部署不引入额外运行时依赖或启动开销；
- OpenViking backend 目录除 `MemoryManager` 契约外不导入 DeerFlow 内部模块；
-现有 DeerMem/noop 测试全部通过。

## 19. 回滚

回滚只修改配置并重启 DeerFlow：

```yaml
memory:
  manager_class: deermem
```

注意：

-回滚不会自动把 OpenViking 记忆迁回 DeerMem；
- OpenViking 中已有数据保持不变；
-切回 DeerMem 后只会使用 DeerMem 自己的历史数据；
-禁止在 OpenViking 加载失败时运行时静默回退到 DeerMem，因为这会把新写入路由到不同存储并制造分叉。

## 20. 待确认事项

进入实现前必须关闭以下问题：

1. 首个支持的 OpenViking 版本及升级策略是什么？
2. DeerFlow 的目标部署是否允许多个 Gateway 副本并发处理同一 thread？
3. 写入失败的首版策略是否长期接受 `log_and_drop`，还是后续必须实现 durable outbox？
4. 是否需要在后续版本对 `/memory` 管理页面隐藏不支持的 CRUD 操作？

这些问题涉及数据隔离、幂等性或用户可见行为，不应由实现代码中的隐式默认值代替。

## 21. OpenViking 参考

- API Overview: <https://docs.openviking.ai/en/api/01-overview>
- Sessions API: <https://docs.openviking.ai/en/api/05-sessions>
- Retrieval API: <https://docs.openviking.ai/en/api/06-retrieval>
- Session Management: <https://docs.openviking.ai/en/concepts/08-session>
- Multi-Tenant: <https://docs.openviking.ai/en/concepts/11-multi-tenant>
- Authentication: <https://docs.openviking.ai/en/guides/04-authentication>
- OpenViking repository: <https://github.com/volcengine/OpenViking>
