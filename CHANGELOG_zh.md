# 更新日志

本文件记录 DeerFlow 的所有重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本规范](https://semver.org/lang/zh-CN/)。

[English](./CHANGELOG.md) | 中文

## [未发布]

本节累积面向 **2.1.0** 里程碑（[里程碑 2](https://github.com/bytedance/deer-flow/milestone/2)）的工作。
该里程碑随本次发布收尾，共合并 **765 个 pull request**。

### ⚠ 不兼容变更（Breaking Changes）

- **网关：** 现在会无条件签发请求 trace id，且每个 Gateway HTTP 响应都会携带
  `X-Trace-Id` header。此前二者均受 `logging.enhance.enabled` 控制；该配置现在
  **仅控制日志输出**——即日志记录是否包含 `trace_id` 字段及其格式。此 header
  无法关闭；使用默认 `enabled: false` 的安装在升级后也会开始收到它。定时任务、
  MCP 任务通知 run、IM 渠道消息以及内嵌 `DeerFlowClient` 都会为每个工作单元绑定
  一个 id，因此此前没有 trace id 的 run 记录、checkpoint 元数据和 Langfuse trace
  现在也会包含它。run 请求的 `metadata` 或 `config.context` 中提供的
  `deerflow_trace_id` 现在会被忽略并覆盖，以确保响应 header、日志和持久化 run
  保持一致；如需跨服务固定关联 id，请发送 `X-Trace-Id` 请求 header。`logging`
  仍需重启后生效。未新增或移除任何配置键。([#5119])
- **技能：** 沙箱现在将 `/mnt/skills` 保留给“仅启用项”的托管投影视图。
  `DEER_FLOW_HOST_SKILLS_PATH` 与 `SKILLS_HOST_PATH` 不再使用；Docker/AIO 和
  hostPath 部署会从 `DEER_FLOW_HOST_BASE_DIR` 推导投影路径。指向 `/mnt/skills`
  或其子路径的 E2B operator 挂载会被跳过并告警，避免遮蔽托管投影；请将额外内容
  挂载到其他容器路径。用户投影会从磁盘重读全局启用状态，使切换在下一次获取沙箱时
  跨 Gateway worker 生效。既有 E2B 沙箱在重建前仍保留创建时快照；PVC 模式暂不提供
  已禁用技能的文件系统隔离。([#4178])
- **沙箱：** E2B 现在将 `sandbox.replicas` 作为进程级容量上限来强制执行。默认的
  `wait` 策略会等待 `acquire_timeout`，随后令当前智能体回合失败。DeerFlow 不会自
  动重试该回合。可使用 `burst` 配合 `burst_limit` 允许有限地超出额度多开 VM。`reject`
  策略可在返回容量错误前先回收一个预热 VM。([#4391])
- **技能：** 包含 `SKILL.md` 的目录现在是一个运行时包边界。该包内嵌套的 `SKILL.md`
  文件被视为支撑数据，不再注册为独立技能；若自定义目录结构较为特殊，需将可独立加
  载的技能移到不带自身 `SKILL.md` 的命名空间目录下。([#4098])
- **记忆：** 记忆系统现已可插拔（`memory.manager_class` 选择后端；默认 `deermem`
  自包含）。DeerMem 私有配置从 `memory:` 顶层移入 `memory.backend_config`，`/memory/config`
  响应（以及 `client.get_memory_config()`）的结构也发生了变化。([#4122])
- **记忆：** `/memory/config` 与 `client.get_memory_config()` 不再返回扁平的 DeerMem
  字段（`storage_path`、`max_facts`、`debounce_seconds`、`token_counting`、`guaranteed_*`
  、`staleness_*` 等）。改为返回 `{enabled, mode, injection_enabled, manager_class,
  backend_config}`，其中 `backend_config` 是一个由当前后端自行解释的不透明 dict
  。记忆*数据*响应（`/memory`、`/memory/status` 的 data）未变。读取旧扁平字段的
  外部 API / SDK 客户端需改为读取 `backend_config`。([#4122])
- **记忆：** 自定义 `memory.storage_class` 发生迁移：旧的默认路径 `deerflow.agents.memory.storage.FileMemoryStorage`
  已不存在（现为 `deerflow.agents.memory.backends.deermem.deermem.core.storage.FileMemoryStorage`
  ）。自定义 `MemoryStorage` 子类的 `__init__` 必须接受 `config`（此前为无参）。
  损坏或过期的 `storage_class` 会记录错误并回退到 `FileMemoryStorage`（不会崩溃
  ）——请更新路径与签名以恢复使用。([#4122])
- **记忆：** `storage_path` 的语义由“文件路径”改为“根目录”。抽象化之前，绝对 `storage_path`
  是共享的记忆文件（不按用户隔离），相对值则是 data base_dir 下的全局文件。现在
  `storage_path`（无论绝对或相对）都是根目录；按用户的记忆存放在 `{storage_path}/users/{uid}/memory.json`
  。若升级后仍保留旧的默认 `storage_path: memory.json`（一个相对文件名），会导致
  按用户的记忆孤立，或在保存时触发 `NotADirectoryError`。因此旧版迁移会**带告警
  丢弃以 `.json` 结尾的文件式 `storage_path` 值**，且当 `storage_path` 解析到一
  个已存在的文件时工厂会**抛出异常**。如需自定义根目录，请将 `memory.backend_config.storage_path`
  设置为一个目录。([#4122])
- **记忆：** 当 `memory.mode: tool` 搭配一个未实现 `search()` 的后端时，现在会在
  Gateway 启动时由 `MemoryManager` 的不变量校验快速失败并抛出 `ValueError`，而不
  是启动成功后在每次 `memory_search` 调用时静默返回空结果。两个内置后端都实现了
  `search()`（DeerMem 会检索，`noop` 返回 `[]`），因此仅影响未覆盖 `search()` 就
  接入的自定义后端。这是有意为之——静默返回空比启动期报错更糟。修复方式：切换到 `mode:
  middleware`，或覆盖 `search()`（并设置 `supports_search=True`）。([#4324])

- **配置：** `database.checkpoint_delta_snapshot_frequency` 已迁移为
  `database.checkpoint_delta.snapshot_frequency`，默认值从 `1000` 改为 `10`。
  旧顶层字段仍会在告警后映射到新字段，显式的新字段优先。依赖旧默认值的 delta
  模式部署现在会将快照频率提高 100 倍；如需保留原节奏，请显式设置为 `1000`。([#4516])
- **Docker：** 两份 compose 文件发布的入口端口现在默认只绑定回环地址
  (`127.0.0.1`)。依赖旧 `0.0.0.0` 绑定的部署必须设置 `BIND_HOST` 才能向其他网卡
  暴露服务。([#4618])

### 新增

#### 调度器
- **scheduler：** 定时任务在 `once` 和 `cron` 之外新增 `interval`
  （`schedule_spec.every_seconds`）。节奏为 UTC 的 `now + N`，
  不补跑错过的节拍。N 不小于 `scheduler.min_once_delay_seconds`
  （默认 60 秒），不大于 30 天。([#5291])

- **scheduled-tasks：** 保存任务前即可查看即将到来的 cron 触发时刻。
  `POST /api/scheduled-tasks/preview-cron` 接受五段式 cron 表达式、时区、1–10
  的 `count`（默认 5）与一个可选的带时区（aware）参考时间，返回规范化后的
  cron、生效的 UTC 参考时间，以及 UTC 与本地时间下的触发时刻。
  它在工作线程中运行调度器自己的计算器，因此 DST 处理与保存后的任务实际
  行为一致；它不预留任何资源，也不触碰任何 task、thread 或 run 存储；输入
  非法与日期范围失败都会返回 422。([#5381])

- **scheduled-tasks：** 可以在服务端按触发状态过滤 run 历史。过去要找一个罕见
  的失败，只能把每一页历史都下载下来在客户端过滤，因为埋在大量较新成功记录
  后面的失败可能出现在任何一页；`GET /api/scheduled-tasks/{task_id}/runs`
  现在接受 `?status=`，取值有 `queued`、`launching`、`running`、`success`、
  `failed`、`skipped` 与 `interrupted`，并在分页之前应用该谓词，因此
  `?status=failed&limit=50&offset=0` 返回的就是第一页真正的失败记录。未知
  取值（包括父任务自身的 `completed`）返回 422，空结果返回 `[]`，
  未过滤时的数组响应保持不变。([#5384])

- **scheduled-tasks：** 定时任务详情面板可以向后翻页浏览执行记录。此前它只显示
  最新 50 条，尽管端点早已支持 limit 与 offset，更早的记录在 UI 上无法访问。
  “较新记录”、“更早记录”与“最新记录”导航现在会在历史中翻页，
  并带有本地化的页面、加载、错误与重试状态；每次请求都会多取一行来判断
  是否存在更早的页面，而不是凭空编造一个总数；最后一页不满时会禁用“更早
  记录”，切换任务会重置到最新页并取消过期的请求，使迟到的结果不会替换新
  任务的历史；且只有最新页会轮询。([#5363])

#### 认证
- **认证：** 新增用于程序化 API 访问的个人访问令牌（PAT）：
  `POST/GET/DELETE /api/v1/auth/pats` 用于管理令牌（仅展示一次，以 SHA-256
  摘要存储）；默认拒绝的路由策略只允许会话/run 生命周期路由，并进一步受令牌的
  `threads`/`runs` scope 限制；任何具有取消能力的请求维度（`?action=`、
  `multitask_strategy`）还额外要求 `runs:cancel`。([#5041])
- **认证：** 登录限流参数可配置：`auth.local.max_login_attempts`（默认 5，最小 2）
  与 `auth.local.lockout_seconds`（默认 300），实时解析，配置重载后下次登录即生效
  ，无需重启 Gateway——这对多名用户共享同一出口 IP 的企业代理 / NAT 部署是解锁
  通道。默认值不变。([#5110])

- **settings：**账户偏好可以跨浏览器清理或设备更换保留。通知开关、默认模型、对
  话模式与推理力度以独立的 `(user_id, key)` 行存储，位于需会话认证的
   `GET`/`PATCH /api/v1/auth/preferences` 之后，并在首帧渲染前从服务端拉取，同
  时配备标签页本地的发件箱与有上限的退避重试，因此失败的写入不会被静默丢弃；
  `null` 会重置某个字段。只有这四个白名单字段会被传输——设备通知权限、显示设置
  与线程级模型覆盖都保留在本地，自动的输入框回退也不会作为显式账户偏好上传。现
  有的无作用域本地设置不会被迁移，因为它们没有已知归属，因此用户升级后需要重新
  选择这四项。([#5397])

#### 智能体与运行时
- **scheduler：**定时任务可以把 `assistant_id` 固定为 `lead_agent`（默认）或创
  建者已有的自定义智能体。未知或格式错误的名称返回 422。工作区的创建/编辑表单
  提供同样的选择。([#5286], [#5288])

- **gateway：**`GET /api/threads/{thread_id}/runs/page` 以
   `(created_at, run_id)` 键集游标翻页遍历线程 run 历史（
  `{data, has_more, next_before_created_at, next_before_run_id}`）。
  `GET /api/threads/{thread_id}/runs` 仍返回仅含最新 100 条 run 的裸数组，以便
   LangGraph SDK 客户端继续工作。([#5282], [#5283])

- **中间件：** 新增 `TokenBudgetMiddleware`，强制单个 run 的 token 预算，在主智
  能体与子智能体之间累加共享。([#3412])
- **中间件：** 结构化的工具结果元数据与工具进度状态机，让运行时对多步工具流拥有
  一等可见性。([#3601])
- **上下文：** 每个 run 记录生效的记忆身份，并在摘要过程中持久化持久上下文（系统
  消息、记忆与工具状态），以结构化运行时元数据的形式发出，压缩（compaction）不再
  丢失这些信息。([#3556]、[#3887]、[#3906])
- **运行时：** 目标延续（goal continuation）允许 run 跨多个智能体回合朝目标继续
  执行，并跟踪、限制 `continuation_count`。([#3858])
- **子智能体：** 系统维护的委派账本（delegation ledger）防止对在途任务重复委派，
  并设总委派上限以约束单个 run 的扇出。([#3877]、[#4115])
- **子智能体：** 在会话中持久化并展示子智能体的步骤历史。([#3845])
- **工具：** 结构化摘要取代预览中原始的超大工具输出。([#3377])
- **文件：** 文件工具引入确定性的“写前读”版本门控，避免覆盖并发编辑。([#3912])
- **网关：** 感知缓存的成本核算将 token 成本归因到缓存 / 未缓存路径；Redis stream
  桥接启用分布式事件流；并向用户暴露手动上下文压缩。([#3920]、[#3191]、[#3969])
- **网关：** 可通过 `stream_bridge.heartbeat_interval_seconds` 配置 stream bridge
  的心跳间隔（默认 15 秒），使位于激进 proxy 空闲超时之后的部署可以统一调节 SSE、
  `/wait` 和内部订阅者。([#5017])
- **运行时：** 双模式 checkpoint 存储（基于 LangGraph `DeltaChannel`）将长调研 /
  编码 run 的会话存储从 O(N²) 降至近线性。([#4292])
- **智能体：** 配置声明的主智能体中间件，让部署方无需修改运行时链即可加入自定义
  `AgentMiddleware` 类。([#3964])
- **智能体：** 按智能体的模型与生成设置（`temperature`、`max_tokens`、`thinking_enabled`
  、`reasoning_effort`）可覆盖共享的模型 profile。([#4347])
- **运行时：** 记录终态的 artifact 投递回执，使预期要 `present_files` 的 run 在
  投递失败时不再误报成功。([#4365])
- **上传：** 通过 `list_uploaded_files` 工具懒加载历史文件，而非注入完整清单。([#4174])

- **运行时：** Delta 模式 checkpoint 历史缓存（内存/Redis）支持 O(1) 增量合成，
  通过 `database.checkpoint_cache` 配置。([#4638])
- **调度器：** `scheduler.recursion_limit` 可设置定时运行的 LangGraph super-step
  上限（默认 1000，与 Web UI 一致，并受 `max_recursion_limit` 限制）。([#4848])
- **运行时：** 每次工具调用都会携带由运行时签发且可防篡改的工具回执；有界回执账本
  会注入模型上下文，使智能体能在报告中引用执行证据。默认通过新的 `verification`
  配置节启用。([#4659])
- **子智能体：** 子智能体委派现在可验证，并按 RFC #4651 分层实现：每份子智能体
  报告都必须引用工具回执（例如 `[r3 write_file]`），并为每个交付物附上可验证
  handle；主智能体会将这些引用与子智能体的实际执行记录交叉核对，`task` 委派的
  `acceptance_criteria` 也会在父侧确定性检查（文件是否存在/非空、记录的测试命令
  退出状态），无法判定的项目会报告为 UNVERIFIED，而不是静默通过。([#5076]、
  [#5090]、[#5109])
- **澄清：** 人工输入卡片支持结构化表单字段，智能体可精确请求所需信息。([#4406])
- **子智能体：** 内置子智能体会接收当前日期上下文锚点，使相对日期任务与主智能体
  直接处理时表现一致。([#4797])
- **子智能体：** 设置页新增部署级子智能体目录；自定义智能体可配置显式 worker
  allowlist，并在 prompt 与执行阶段同时强制执行。([#4887])
- **子智能体：** 并发由统一的进程级容量控制器管理；可选 `batch_task` 工具可把大量
  独立项目作为基于 SQL 的持久、可恢复批次执行，支持租约、有限重试、暂停、恢复与
  取消，并在聊天中展示进度。([#4998])
- **智能体：** 注入 lead / 子智能体 prompt 的当前日期上下文遵循可选的
  `DEER_FLOW_DATE_TIMEZONE` 环境变量（IANA 名称，如 `Asia/Shanghai`），非 UTC
  部署的用户在午夜前后不再被告知错误的“今天”；未设置时保持服务器本地时区行为。
  ([#5154])
- **子智能体：** 被委派的子智能体可以发现此前回合上传的文件：父 run 经校验的
  `uploaded_files` 边界会注入子智能体的图状态，使 `list_uploaded_files` 可参与
  正常的工具策略过滤（持久 `batch_task` worker 保持禁用）。([#5170])

- **agents：**读取先于写入的拦截现在会把被阻止的 `write_file` / `str_replace`
  调用中无用的负载（`content`、`old_str`、`new_str`）从发往模型的请求中剔除。
  被阻止的调用从未执行，必须在重新读取后重新发出，因此原始参数只会占用上下文；
  已存储的历史、回执与 run 日志都会保留它们。被阻止的结果会与调用出现位置配对
  （工具调用 id 可能跨回合重复），而历史被重写的请求会丢弃 OpenAI 的 `resp_`
  响应 id，使 `use_previous_response_id` 链无法恢复原始的服务端历史。由
   `read_before_write.elide_blocked_payloads`（默认开启）与
   `read_before_write.elide_min_chars`（默认 2000）控制。([#5329])

- **agents：**`ToolOutputBudgetMiddleware` 现在还会在对话稍后又读取或修改了同
  一路径时，把成功的 `write_file` 调用的 `content` 从发往模型的请求中剔除。写
  入成功后磁盘上的文件才是事实来源，而读取先于写入的拦截会强制在下一次修改前
   `read_file`，因此历史副本是冗余的，长篇的报告撰写 run 会把每个章节携带两遍。
  最新的 `tool_output.keep_recent_writes` 次成功写入（默认 1）始终可见，
  `str_replace` 的负载从不改动，已存储的历史、回执与 run 日志都会保留原始参数。
  由 `tool_output.elide_superseded_writes`（默认开启）与
   `tool_output.superseded_write_min_chars`（默认 2000）控制。([#5374])

- **agents：**自定义智能体的 `config.yaml` 接受 `memory_enabled: false`，以把
  该智能体作为无状态的执行 worker 运行；省略时默认为 `true`。该退出选项只把该
  智能体从记忆生命周期中移除——召回记忆注入、被动捕获、
  `memory_search` / `memory_add` / `memory_update` / `memory_delete` 工具以及
  工具模式的记忆指引全部被抑制，自动摘要与手动 `/compact` 也会跳过持久记忆刷写。
  关闭一个已有智能体只清除 checkpoint 状态中被冻结的、由服务端标记的记忆提醒：
  日期提醒、真实的用户消息与未标记的相似内容都会保留，其他每个智能体的全局记忆
  设置都不受影响。([#5167])

- **runtime：**`ToolProgressMiddleware` 的干预现在可在持久的 run 事件流中审计。
  每次生效的 `warn`、`block`、`recover` 或更晚调用的 `reset` 阶段转换都会持久
  化一条新的 `middleware:tool_progress` 事件；此前这些重规划提示、工具状态提升
  与短路都消失在进程日志中，因此持久化的 run 无法显示模型是自行恢复的还是由运
  行时护栏干预的。只记录有界的决策元数据——状态与恢复词汇表来自规范的
   `tool_result_meta` schema，工具参数、结果内容、提示词以及由内容派生的哈希从
  不进入事件。子智能体与其他 recorder 归属键在 Gateway 与嵌入式 worker 边界处
  都由服务端持有，因此调用方无法伪造持久归属。事件只在 ToolProgress 启用时出现，
  而它默认仍处于关闭状态。([#5214])

- **subagents：**持久化的 `batch_task` 条目现在接受与普通 `task` 委派相同的可
  选 `acceptance_criteria`，因此批处理 worker 无法再声称某个缺失的交付物存在却
  仍作为成功条目落地、且没有任何记录在案的检查。判据在持久化前会被规范化（20
  条可用条目、中性化后 500 个字符；空值变为 `null`），并在租约恢复后保留；已完
  成的执行会复用现有的确定性检查器，对照归属方作用域内的线程文件与已记录的测试
  命令证据。条目查询与 JSONL 导出新增可空的 `acceptance_criteria` 和单独校验的
   `acceptance_verdict`（`holds`、`does not hold` 或 `UNVERIFIED`）：一个已完
  成、带有报告、缺少 CSV 且含不受支持的质量声明的条目会保持 `succeeded`，并带
  上这三个叶子，也不会被自动重试。没有判据的条目与遗留行不报告任何结论。
  ([#5289])

- **subagents：**`task(context_mode="snapshot")` 让委派可以携带派发时刻所保留
  的父对话副本，而不只是委派的提示词。快照模式在委派校验之后、子项设置之前捕获
  对话内容与 `summary_text`，因此被拒绝的委派不会序列化任何内容，之后父对话的
  编辑也不会传到子项。它被渲染为任务之前一条独立的历史 `HumanMessage`，保留纯
  文本、文本块、带匹配结果的历史工具调用描述以及可序列化的媒体输入；不可序列化
  的媒体会变成一条显式的省略声明，而父级系统消息、隐藏的框架状态（包括注入的记
  忆与 todo 状态）、推理块、执行元数据与待处理的工具调用都被排除。子项保留自己
  的角色、模型、工具与技能限制，父级工具帧从不进入它的执行历史，因此父级操作无
  法填充子项的回执、执行步骤或 bash 证据。`context_mode="isolated"` 仍是默认值，
  `batch_task` 条目仍要求自包含的提示词。([#5367])

- **context：**可选的任务笔记与压缩历史召回，由 `task_continuity.enabled`（默
  认 `false`；配置 schema 新增该小节并带禁用默认值）控制。启用后，`task_note`、
  `history_search` 与 `history_read` 会在现有授权与技能策略下对标准主智能体和
   `DeerFlowClient` 暴露，并同时支持同步与异步工具执行。`task_note` 在共享状态
  通道中保存关于约束、决策、失败尝试与下一步的简短检查点笔记，每次写入都强制执
  行笔记本容量限制与报告形态，并在持久化上下文的人类消息中渲染为已转义的历史数
  据。自动与手动压缩还会把有界的消息和工具文本——包括真正的隐藏澄清卡片答案——保
  留到沙箱挂载之外的 user/thread 本地 SQLite FTS5 归档中，随后由
   `history_search` 与 `history_read` 查询；格式错误的 checkpoint 元数据会报告
  为不可用，而不会中断模型调用或压缩，存储故障也不会影响普通压缩。这是单一任务
  内的字面召回：它不会恢复 run、跨主机复制归档，也不会创建跨线程记忆，且不引入
  任何 embedding 依赖。([#5382])

- **gateway：**Gateway 的 run 不再硬编码 100 的递归上限。那些常规任务需要更长
  智能体循环的部署此前必须让每个 API 调用方都提供请求级覆盖，而未这样做的调用
  方会在本来合法的工作上撞到 `GraphRecursionError`。现在一个可热重载的顶层
   `recursion_limit` 会在请求未指定时提供默认值（100，以保持向后兼容），显式的
  请求值仍然优先，无效的请求值回退到配置的默认值，而 `max_recursion_limit` 会
  同时限制已配置与客户端提供的值。([#5390])

- **gateway：**Gateway run 可以被要求读取一段指定的更早对话。可选的
   `read_conversation` 加上 `conversation_references` run 字段（最多三个线程
   id 或同源的聊天 URL）会授予主智能体对上一段对话的面向模型读取权限，同时继续
  当前任务；普通消息文本从不授予访问权，该授权绑定到该次 run 的引用、该 run 的
   `runs:read` 权限以及每个来源的归属。读取复用现有的转录分页与可见性规则，返
  回有界的用户与助手文本，并带上来源 id、续接游标以及截断或不可用声明，同时排
  除隐藏上下文、推理块与原始工具结果。读取器从不持久化到配置中，并在 run 结束
  时释放，因此恢复与重放需要再次提供引用；bootstrap、子智能体与普通嵌入式路径
  都不会获得它。文本上限为每条消息 4000 字符、每页 20000 字符。([#5399])

- **gateway：**对话引用现在可以由 SDK 客户端发送，并被它们检测。
  LangGraph JS SDK 的 `RunsClient.stream` 会丢弃未知的顶层字段，因此浏览器客户
  端此前根本无法发送 `conversation_references` 字段，也没有办法判断读取器是否
  启用——在关闭时无从隐藏入口。运行创建、流式与等待请求现在都接受
   `context.conversation_references`，限制相同（最多三个，每个 1–2048 字符），
  错误位置也相同，在校验前被提升为规范字段并从 `context` 中移除，因此它不会到
  达 run 上下文或被 checkpoint 的 configurable；同时发送两种写法会返回 422，而
  留在 `body.config` 中的副本仍不授予任何权限。`GET /api/features` 报告
   `conversation_references: {enabled, max_references}`，其中 `enabled` 遵循已
  配置的工具列表，因此 `config.yaml` 的改动无需重启即可生效。([#5463])

- **tools：**`list_uploaded_files` 接受可选的 `query`（大小写不敏感的文件名子
  串）与 `extensions`（`"pdf"` 或 `".PDF"`，两者都表示 `.pdf`），且两个过滤器
  都运行在 20 文件截断**之前**——而懒加载历史早已应用了该截断。此前上限作用于未
  过滤的按 mtime 排序的列表，因此在一个满是较新截图的线程里说“分析我之前上传的
  那些 PDF”会把 PDF 推进 `omitted_summary`，让智能体没有路径可交给 `read_file`；
  现在 `total_count`、`truncated` 与 `omitted_summary` 描述的是过滤后的集合。
  省略两个参数会保持当前行为，两个过滤器以 AND 组合，空值或无效值视为不过滤，
  过滤后无匹配会返回 `No uploaded files matched the given filters.`。([#5341])

- **agents：** 自定义智能体此前在 Gallery、聊天头部与欢迎页显示仅含 ASCII 的
  存储标识符，因此所有者无法用中文或其他非 ASCII 文字为智能体命名。每个
  智能体现在可以在其配置文档中，以及 create/update/read/list 各 API 中，携带
  一个可选的 `display_name`——去除首尾空白、至多 100 个字符；
  更新时省略该字段会保留原值，`null` 或空值则将其清除。该标签从智能体
  Gallery 的设置按钮进入编辑，按 Unicode 码位计数，并受一个可见的字符预算
  约束；若包含控制字符、不可见的格式字符，或仅由记号（marks）、分隔符
  （separators）与格式字符（format characters）构成，则会被拒绝；普通多语言
  文字与 ZWJ 表情仍被允许。路径、URL、运行时的 `agent_name`、归属与 React
  组件身份仍使用稳定标识符，因此无需迁移任何数据；存储中无效的取值在读取时
  会被忽略，而不会破坏 list/detail/bootstrap。([#5324])

#### 记忆
- **记忆：** 记忆合并（consolidation）合成碎片化的事实，并通过 LLM 为每条事实分
  配的 `expected_valid_days` / `staleFactsToExtend` 进行过期审查，剪除静默过期的
  事实。([#3996]、[#3860]、[#4143])
- **记忆：** 保证注入纠正事实（并优雅降级），使用户的纠正始终能触达模型。([#3592])
- **记忆：** 精简可插拔的 `MemoryManager` 接口以方便后端接入——新后端不再需要实现
  未被调用的抽象方法，DeerMem 专有的 hook 注入也移出共享工厂。([#4326])
- **记忆：** 增量式按智能体作用域的 Markdown 事实存储，按智能体隔离事实，且更新
  单条事实时无需重写或重建整个集合的索引。([#4279])
- **记忆：** 记忆消息处理新增会话水位（watermark）、无意义回合过滤与持久化队列，
  使抽取不再每回合都重新喂入完整会话。([#4447])

- **记忆：** 内置 FTS5/BM25 检索适配器，无需外部服务即可对已存记忆全文搜索。([#4360])
- **记忆：** 新增可插拔后端：通过 HTTP 接入 OpenViking 与 mem0，以及作为用户模型
  记忆 provider 的 Honcho。([#4509]、[#4528]、[#4730])
- **记忆：** 混合事实淘汰策略综合多种信号，决定容量满时应丢弃哪些事实。([#4789])

- **memory：** 可选的写入侧防护，避免把已有事实的改写再次存入记忆，因此重复的
  抽取不再以重复内容占用记忆容量与 prompt token。写入侧开关是
  `memory.backend_config.fact_dedup_enabled`（默认 `false`），另有
  `memory.backend_config.fact_dedup_similarity_threshold`（默认 `0.7`，取值
  范围 `0.5`–`1.0`）。在当前 user/agent 作用域内，
  新的同类事实会与既有事实以有界 token-Jaccard 相似度比较——对拉丁词与中文
  二元组（bigram）做词法启发式，而非语义等价判定。合并会保留既有事实的 id、
  content 与创建时间，把 `confidence` 提升到两者中较高的值，
  时刷新 `source`；`facts_merged_dedup` 计数器记录发生了多少次合并。
  成对的更正替换会绕过近似去重，移除提议会把自己的目标排除在匹配之外，
  且不会伪造任何确认信号——强化仍然需要真实的人类消息。([#5254])

#### 技能
- **skills：** 内置的图像生成技能现在可以使用兼容 OpenAI 的 Images API
  进行生成与参考图编辑，端点、模型、尺寸与输出格式均可配置。([#5389])

- **技能：** 原生 SkillScan（阶段一）在加载时静态分析技能包；`describe_skill` 支
  持延迟发现，模型按需获取技能 schema，而非一开始就加载全部技能。([#3033]、[#3775])
- **技能：** 按用户的自定义技能隔离，并配合沙箱挂载。([#3889])

- **技能：** 选中一个技能后技能列表会重新打开，便于连续附加多个技能。([#4639])
- **技能：** 可直接从“技能”设置页安装本地 `.skill` archive，并复用现有的按用户
  installer 和安全扫描。([#5039])
- **技能：** 播客生成的火山引擎音色可按说话人性别覆盖配置，默认值经过修剪、对空值
  安全。([#5156])

- **skills：** 可以从设置页导出自定义技能，包括已禁用的那些，因此备份、在多
  个安装之间搬迁或发给协作者的，都是实际安装的版本，而非原始上传的版本。
  双语预览会列出包大小、分页的文件路径、声明的依赖要求与可操作的阻塞项，
  两个新增的仅管理员 manifest 与 download 端点会将该预览
  绑定到一个修订摘要——期间被改动的包会返回 `409`，而不是给出
  过期的 ZIP。支持文件、空目录与规范化后的可执行权限能在往返中保留，
  而链接、特殊文件、不可移植的路径、嵌套的技能根与可执行二进制会被拒绝。
  导出复制的是原始保存的文件，不是脱敏步骤：它既不扫描密钥，也不
  运行技能脚本，因此凭据与账号设置仍需单独配置。([#5332])

- **skills：** 延迟技能发现现在会对候选排序，而不是把模型的整段自由文本查询
  当作一个正则表达式去匹配。设置 `skills.deferred_discovery: true` 后，
  智能体只能看到技能名称，并调用 `describe_skill` 来选择要加载的内容；
  但多词意图此前必须连续匹配：`chart visualization` 找不到
  `chart-visualization`，`analyze Python` 也找不到被描述为
  “Analyze data with Python, pandas, jupyter” 的技能，因此智能体无法加载
  匹配的工作流及其生效的工具策略。
  现在查找会规范化 Unicode、大小写与名称分隔符，并按字面意图词的覆盖率
  给候选打分，覆盖率相同时名称匹配优先于仅描述匹配，并以目录顺序
  打破平局，使结果保持可复现；模型生成的查询限制为 256 个字符与 16 个
  不同的词。`select:` 精确选择与 `+required` 名称过滤保持不变，且不涉及
  任何嵌入、模型调用或遥测。([#5369])

#### 模型与集成
- **社区工具：** 新增网络检索 / 抓取引擎——GroundRoute、Crawl4AI（`web_fetch`）与
  fastCRW provider——并新增 Browserless `web_capture` 截图工具和 Brave `image_search`
  。([#3675]、[#3821]、[#3585]、[#3881]、[#3866])
- **MCP：** MCP 工具调用支持按 server 的 `tool_call_timeout`，并提供路由提示引导
  模型选用正确的 server。([#3843]、[#4004])
- **MCP：** 新增官方 OpenViking `/mcp` 示例，通过 DeerFlow 通用 MCP 客户端暴露其
  原生工具集。([#4745])
- **社区工具：** 将“智能体化浏览器控制”作为会话的一等能力——基于 Playwright 的浏
  览器会话由智能体操作，用户可在工作区中观察或接管。([#4187])
- **社区工具：** Lark / 飞书 CLI 集成打包了运行时安装、官方 `lark-*` 技能包与交
  互式授权流程，使该集成不再依赖手动环境配置。([#3971])

- **集成：** 可在“设置 > 集成”中按用户切换 Lark/飞书应用凭据；新 App ID/Secret
  会在写入前校验，成功切换后撤销旧 OAuth token。([#4703])
- **ACP：** 支持 MiniMax Code (`mcode acp`) 作为原生外部编码智能体；ACP thought
  chunk 不再拼接进工具结果。([#4846])
- **模型：** 新增 Z.AI GLM-5.3-Flash profile，保持 thinking 始终开启并停止通用
  reasoning-effort 转发，因为该模型会拒绝关闭 thinking，且只接受自身定义的 effort
  值。([#5074])
- **社区工具：** 新增 Serply（支持 news 与 scholar 垂直搜索）和腾讯云 WSA 网络
  搜索 provider，并为 DDGS、Brave、Tavily 与 SearXNG 提供统一的原生时间范围过滤
  （日/周/月/年）。([#5023]、[#5057]、[#5099])
- **社区工具：** 新增 Sofya `web_search` 与 `web_fetch` provider——搜索结果直接
  携带每个页面的内容，并按结果设上限，使默认搜索保持内联。([#5239])
- **知识库：** 新增可选的只读 RAGFlow 检索，通过已配置的 RAGFlow dataset 暴露
  `knowledge_search(query)` 智能体工具，并提供 dataset ID allowlist，以及错误路径
  中的凭据和 dataset ID 脱敏。([#4955])
- **知识库：** 新增可选的只读 LightRAG 检索，作为同一 `knowledge` 组的另一个
  `knowledge_search(query)` provider——运营方通过配置哪个条目来选择 RAGFlow 或
  LightRAG。它调用 LightRAG 的结构化 `/query/data` endpoint（不做 LLM 生成），将
  排序后的 chunk 格式化为带引用编号的文本，可选的 `X-API-Key` 在所有模型可见路径
  中脱敏，服务端错误消息会映射为可操作的工具错误。([#5209])

- **models：** 新增按用户区分的收藏层，让常用模型触手可及，且不会改变当前选中
  或默认的模型。紧凑的两行模型列表现在在主聊天与 Side Chat（侧边对话）中都是
  锚定式下拉，每行带一个行内星标；收藏会排进第一组，但不会选中任何模型，
  也不会关闭选择器，并按已登录用户持久化，支持跨标签页同步，以及恢复暂时
  不可用的条目。原有的搜索框被移除，这是有意的简化，且没有单独的管理模式。
  ([#5441])

- **models：**有界并发并不限制请求速率：多个并发 run 仍可能耗尽某个 provider
  的每分钟请求配额，而分发前没有任何机制来对需求限速，因此 429 才是出错的第一
  信号。新增可选的 `models[].request_admission` 配置块，通过进程本地的队列放行
  模型调用，接受 `requests_per_minute`（必填）、可选的 `group`（默认为模型配置
  名）、`max_wait_seconds`（默认 `300`）与 `max_queue_size`（默认 `256`）；在
   60 RPM 下放行至少间隔一秒，而空闲期不会积累突发额度。同一个有界 FIFO 由同步
  调用方、独立的 asyncio 事件循环以及显式组内的每个模型实例共享，它们的策略必
  须一致——冲突的设置会在构造时失败并需要重启。取消与超时会丢弃一个等待者而不消
  耗一次放行，队列已满则会在分发前失败。该限制器通过 LangChain 的
   `BaseChatModel` 钩子挂载，因此智能体模型、invoke 与 stream 路径以及工厂创建
  的辅助模型都在覆盖范围内；工厂会把策略从 provider 参数中剥离，并把暴露给
   SDK 的 `max_retries` 设为零，使重试无法悄悄绕过钩子——现有的智能体中间件重试
  会重新进入放行队列，而非中间件调用方则会失去 SDK 重试。预算按进程计算，因此
  运维方必须把账户配额在 worker、副本与其他客户端之间划分；限制器统计的是请求
  而非 token，未配置的模型行为与之前完全一致。([#5432])

#### MCP
- **MCP：** 新增持久任务运行时：长时工具任务通过持久 driver 跨 Gateway 重启继续，
  进度与完成通知显示在聊天 UI 中。([#4665]、[#4690]、[#4833])
- **MCP：** 共享 MCP server 可注入按用户区分的凭据；未映射用户默认拒绝，存储的
  凭据在 Gateway API 响应中脱敏。([#4868])
- **MCP：** 新增按 server 的 `tool_name_prefix`，让已自行命名空间化工具的 server
  保留原始工具名；默认行为不变。([#4624])
- **MCP：** “设置 > 工具”现在可以通过定向 Gateway endpoint 新增、编辑和删除 MCP
  server；复制粘贴 JSON 的工作流会保留高级字段和已脱敏的 secret placeholder。
  ([#5022])
- **MCP：** 共享 HTTP/SSE server 可通过 `headers_from_context` 将请求作用域的
  secret 映射为 header：调用方在 `config.context.secrets` 中提供每次请求的值，
  配置只存储键名，缺失值默认拒绝。([#5010])
- **mcp：**`extensions_config.example.json` 中新增一个可选的
   `parallel-search` server 条目（`https://search.parallel.ai/mcp`，HTTP，默认
  无认证），默认禁用；启用后会暴露 `parallel-search_web_search` 与
   `parallel-search_web_fetch`，并文档化可选的 Bearer 认证。([#5028], [#5501])

- **MCP：** `extensions_config.example.json` 新增可选的 `parallel-search` server
  条目（`https://search.parallel.ai/mcp`，HTTP，默认无鉴权），默认禁用；启用后会
  暴露 `parallel-search_web_search` 与 `parallel-search_web_fetch`，并文档化可选
  的 Bearer 认证。([#5028])

#### 渠道
- **渠道：** 把 IM 的 `channel_user_id` 以 `DEERFLOW_CHANNEL_USER_ID` 暴露给沙箱
  命令。([#3926])
- **渠道：** 对同一会话的密集消息进行排队，并在批次间保留话题卡片预览。([#3988])

- **渠道：** 入站 webhook 去重迁移到 Postgres，使多个 Gateway Pod 可同时服务同一
  IM 渠道而不重复处理事件。([#4210])
- **渠道：** 钉钉入站消息支持文件与图片附件。([#4423])
- **渠道：** 新增 Buzz (Nostr) 渠道连接器及配套前端体验。([#4649]、[#4727])
- **渠道：** IM 命令 `/agent list` 与 `/agent use <name>` 允许会话切换到 owner 的
  自定义智能体：选择会持久化到会话元数据（重启后恢复）并优先于过期的渠道默认值，
  IM 创建的会话在 Web UI 打开时路由到同一智能体；同时 `/agent` 在斜杠技能解析器
  、前端与 TUI 中保留，避免任何技能遮蔽该命令。([#5168])

#### 认证与防护
- **认证：** 通用 OIDC / SSO 认证，并支持 Keycloak。([#3506])
- **护栏：** 已认证的运行时上下文在 `GuardrailRequest` 中暴露，安全干预以 run 事
  件的形式持久化。([#3665]、[#3837])
- **认证：** “保持登录”选项，配合统一的会话 cookie 策略（HTTPS 下使用持久化 `Secure`
  cookie，公网 HTTP 下使用会话 cookie）。([#4255])
- **认证：** 部署方可关闭本地自注册，将新账号限制为仅通过 SSO / OIDC 开通。([#4311])
- **鉴权：** 内置 RBAC 鉴权 provider 与统一工厂，并在装配期（模型可见前移除工具
  ）与运行期（拒绝被禁用的调用）双重强制执行工具鉴权。([#4260]、[#4370])

- **鉴权：** Gateway 路由权限改由已配置的 `AuthorizationProvider` 推导，不再使用
  固定表。([#4439])
- **鉴权：** 模型权限会在 Gateway 路由和智能体运行时双重执行，获取沙箱时还会校验
  `sandbox:execute`。([#4540]、[#4911])
- **鉴权：** `GET /auth/me` 现在返回调用方的生效路由权限（RFC #4063 阶段 4），直接
  读取认证中间件在每个已认证请求上标记的 `AuthContext`——不产生额外的 provider
  评估——使前端能隐藏调用方角色无法执行的操作。([#5228])

- **authz：**被拒绝 `threads:delete` 或 `runs:cancel` 的角色此前仍会看到线程行
  的删除菜单项、侧边删除按钮与一个可用的输入框停止按钮，于是 UI 提供了一个
   Gateway 的 `@require_permission` 守卫只会拒绝的操作。前端现在消费
   `GET /auth/me` 报告的生效权限并隐藏删除入口，并在流式输出时禁用停止按钮，同
  时用 `aria-label`/`title` 标明权限边界。强制逻辑没有变化——Gateway 守卫仍是唯
  一决策点——而缺失、为 `null` 或尚未加载的权限列表会被当作宽松处理，因此新旧后
  端混布的部署绝不会隐藏调用方仍可执行的操作。([#5294])

#### 沙箱与 provisioner
- **沙箱：** 新增 E2B 与 BoxLite（micro-VM）沙箱 provider；BoxLite 自带预热池。([#3883]
  、[#3940]、[#3951])
- **provisioner：** ClusterIP Service 与按技能作用域的 PVC 挂载，并支持配置沙箱
  容器端口。([#4016]、[#3928])

- **沙箱：** 新增云沙箱 provider：Tenki 与 OpenSandbox。([#4382]、[#4877])
- **沙箱：** K8s provisioner 模式新增可选的 lark-cli 凭据 broker sidecar，将 Lark
  应用密钥与 OAuth token 移出沙箱文件系统；沙箱只看到转发命令的 shim。默认关闭。
  ([#4501])
- **沙箱：** E2B mount 上传的 wall-clock deadline 可通过
  `mount_upload_deadline_seconds` 配置（默认 120 秒）。([#4876])
- **沙箱：** E2B 沙箱创建后会携带结构化的 `MountUploadResult`（`truncated`、
  `reason`、上传统计），并在同进程内的 warm-pool 回收后保留——挂载上传因资源限制
  被截断的情况可以在代码中观察，而非只出现在 Gateway 日志。([#4884])
- **沙箱：** 本地 Docker AIO 沙箱新增可选的受控出网：`sandbox.network.mode` 支持
  `isolated`（每个沙箱独立内部 bridge，无出站路由）与 `allowlist`（同样的 bridge
  加上自行解析目标的域名 allowlist HTTP(S) 策略 sidecar，拒绝 IP 字面量与 ECH）；
  被拒绝的公网域名可通过人工输入卡片批准（临时授权或本沙箱内永久允许），非交互
  run 默认失败，受限模式下沙箱 API 也不再直接发布。要求 Docker Engine 28+；
  `open` 仍是默认值。([#5152])

#### 扩展与插件
- **扩展：** 新增 out-of-tree Python 扩展系统，可贡献中间件、任务生命周期与系统模型
  observer、Gateway 服务和 HTTP 路由，并用 `deerflow extensions` 管理。([#4636]、
  [#4684]、[#4780])
- **扩展：** 扩展可观察消息来源、中间件策略、智能体装配指纹、上下文压缩、护栏决策
  和工具的 MCP 来源。`deerflow-extension-api` 升至 0.2.0，0.1 扩展会在启动时被拒绝。
  ([#4863])

- **extensions：**`extensions.middlewares` 条目除了现有的
   `module.path:ClassName` 字符串外，还可以写成 `{class, kwargs}`，`kwargs` 会
  传给构造函数。需要设置阈值、请求头名称或任何其他参数的运维方管理中间件，不再
  必须为了设定一个值而硬编码一个子类。字符串条目仍以无参数构造，空的类路径会在
  配置校验时被拒绝，而不是留到智能体创建时才失败，像 `apply_to` 这样的未知字段
  也会被拒绝。([#5312])

- **extensions：**`deerflow extensions upgrade SOURCE`（也以
   `make extension-upgrade SOURCE=...` 暴露）会替换一个受管理的本地快照，或为
  已在 `extensions` 组中的依赖重新固定版本，并沿用现有的 `plugins:` 记录，使其
  私有的 `config` 与 `required` 得以保留。迁移到更新的固定版本此前意味着先
   `remove` 再 `install`，而 `remove` 会删除整条记录——包括密钥——而已经快照过的
  本地目录若不手工编辑受管理的副本根本无法重新安装。普通的 `install` 没有变化，
  仍会拒绝已存在的本地快照；升级未安装的来源会以安装提示的方式失败关闭；失败的
  升级会恢复先前的快照，即使并发的 `pyproject.toml` / `uv.lock` 编辑阻止了依赖
  文件回滚。([#5347])

- **extensions：** 新增可选的 `RunEvidenceReader` 契约，让 Gateway 扩展可以
  直接得知自上次查看以来发生了什么变化，而不必再反复对齐整个 thread：由宿主
  持有的单调递增 cursor 持久地发现 changed-run，另有按 run 限定范围的事件分
  页，以及具备权威性的状态读取。cursor 不透明、带版本、绑定作用域、可安全重
  放，对使用数据库支撑的存储而言还是持久的；分页按 `(change_seq, run_id)` 排
  序，而不是从 thread 作用域的事件序号或时间戳推断全局顺序；进度快照与租约心
  跳不会推进这个时钟；删除操作不产生 tombstone，因此消费方需要轮询状态，并把
  缺失的 run 视为不存在。既有扩展不受影响，因为
  `ExtensionRuntimeDeps.run_evidence_reader` 默认为 `None`；无法提供某一页的
  存储会显式失败，而不会返回一个具有误导性的空页。生产环境的 reader 以 app
  为作用域，并为受信任的运营方扩展提供全局跨用户可见性；它会脱敏事件元数据，
  但保持内容不变。([#5405])

#### 持久化
- **持久化：** 可通过 `postgres_schema` 选择自定义 PostgreSQL schema；ORM、LangGraph
  checkpointer 与 store 表均创建在其中，启动时自动创建。([#3442])

#### 前端
- **前端：** 支持对助手回合进行分支，以及针对引用追问的侧边对话。([#3950]、[#3934])
- **前端：** 支持重新生成最新回答。([#3637])
- **前端：** 引用来源证据面板、智能体 run 的工作区变更评审，以及可视化的 `ask_clarification`
  卡片。([#3907]、[#3945]、[#3956])
- **前端：** 语音输入、方向键回溯 prompt 历史、输入框内容润色，以及“（思考了 N
  秒）”思考时长标签。([#4036]、[#3718]、[#3986]、[#3627])
- **前端：** 用 `agents_api` 特性开关控制智能体 UI 的可见性，并在后端与 UI 中持
  久化 AI 回合时长。([#3769]、[#3663])
- **前端：** 将斜杠技能（slash-skill）激活渲染为内联标签（chip）。([#3981])
- **前端：** 本地化的 AI 辅助声明。([#4374])
- **前端：** 支持置顶最近会话。([#4442])
- **前端：** 在输入框中校验 `/goal` 目标长度。([#4337])

- **前端：** 实时显示上下文窗口使用量。([#3183])
- **前端：** 可原地编辑并重新运行最近一次用户回合。([#4377])
- **前端：** 澄清卡片待处理时仍可输入并发送回复。([#4530])
- **建议：** 可通过 `suggestions.max_suggestions` 配置后续建议数量（默认 3）。([#4533])
- **Artifact：** 可在 artifact 面板中内联编辑文本 artifact。([#4596])
- **Artifact：** Markdown artifact 可在新窗口 reader 中以渲染形式打开（并提供
  “查看源文件”和“下载”fallback）；一次 run 中展示的所有文件也可根据该 run 的
  投递回执打包下载为 zip。([#5056]、[#5117])
- **前端：** 自定义智能体聊天支持 Browser Live。([#4719])
- **前端：** 新增长会话大纲：超过 5 个用户回合后，紧凑侧边菜单会列出会话中的问题，
  支持跳转并跟踪当前章节。([#5025])
- **前端：** 定时任务可复制为可编辑草稿，保留配置但不带 run 历史。([#5064])
- **会话：** 分支会话自动使用 `Title (2)`、`Title (3)` 等编号区分标题，最近会话
  列表以树形连接线展示父子关系。([#4983])
- **前端：** 支持归档与恢复会话：侧边栏 Archive 操作配 Undo toast、搜索栏上方的
  “最近会话 / 已归档”标签页，以及按会话的恢复控件；SQL 与 Memory 存储在分页前
  应用归档过滤，同时保留消息、文件、链接、置顶状态与当前 URL。([#5236])
- **项目：** 项目工作区组织会话（Projects MVP 阶段一）：侧边栏 Projects 区块支持
  平铺 / 分组列表模式，项目详情页带分页的会话列表，项目内新建聊天会预创建线程并
  归属该项目，run 永远不会落到所选项目之外；分支继承项目归属、支持在项目间移动
  ，并提供项目的创建 / 重命名 / 归档 / 恢复 / 删除。([#5265])
- **Artifact：** 已完成的 CSV/TSV artifact 以有界表格预览（最多 200 行 × 50 列，
  每页 50 行，吸顶表头，可选首行表头），解析在后台线程进行、复用现有 1 MiB range
  加载器——字面字符串、前导零与多行带引号单元格都得以保留，长单元格可在可复制的
  对话框中打开，源码视图一键切换。([#5284])

- **title：** 仅含附件的首回合现在会得到真正的标题，而不是千篇一律的
  `New Conversation`，因此以文件开头的对话既可区分也可检索。当首个回合只携带
  一个通过校验的附件时，清理后的文件名会成为本地标题；携带多个附件时则生成类
  似 `2 files uploaded` 的计数；用户自己撰写的文本仍然优先作为标题来源，而在
  没有可用合法文件名时仍回退为 `New Conversation`。本地标题在配置的标题模型
  路径之前返回，因此仅含附件的回合不再需要为一次 LLM 调用付费。文件名只从上
  传中间件填充的 `uploaded_files` 状态中读取，客户端元数据不受信任，并且会做
  清洗：剥离控制字符与多余空白，保留普通 Unicode 字符和百分号，长名称在保留
  扩展名的前提下截断。这取代了此前 `<current_uploads>` 标题修复特意保留的
  `New Conversation` 回退行为。([#5304])

- **projects：** 项目 MVP 第二阶段让项目真正发挥作用，而不只是给文件夹起个名
  字。项目说明此前会被存储、可以编辑，却没有任何东西读取；现在它会在每个成员
  线程的 run 中作为有界的 user 角色 `<project>` 块送达模型，且只出现在该 run
  的请求里，永远不会进入系统提示词或持久化历史；重命名会在下一次 run 生效；
  超长文本会在写入时被拒绝，而不是被截断。每个项目的文档架新增 `Documents`
  标签页（上传、带来源信息的列表、预览、下载、移入回收站、按内容哈希去重），
  智能体可按需通过 `list_project_documents` / `read_project_document` 读取
  ——这些工具只在项目 run 中注册，且仅支持文本。此外还支持双向提升：
  `Save to project` 把任意线程文件连同来源信息复制到文档架，
  `Attach to thread` 则通过常规上传管道把文档架中的文档重新摄入一次对话。只
  读的对话文件视图会聚合各成员线程的上传文件与产物，项目删除也终于有了回收站
  这一层级。([#5443])

- **frontend：** 调试模式下可以查看通用调用与 MCP 调用的工具详情。这些步骤此
  前只显示一个标签，尽管浏览器早已收到它们的输入与结果，很难看清工具之间究竟
  传了什么。`Token Usage → Debug` 现在会带出一个折叠的 `Tool details` 面板
  ——对没有 token 统计数据的调用同样如此——展示工具名称、call ID、输入，以
  及原始结果或明确的错误，并配有复制操作与中英文标签。内容只在展开时才格式化，
  文本长度、嵌套层级与已访问的值都有上限，因此大体积载荷不会让面板卡住。
  ([#5309])

- **frontend：** 对话现在可以从输入框中引用。附件按钮旁边新增了
  `Reference a conversation` 按钮，仅当 `/api/features` 报告该能力时才渲染，
  并会打开一个选择器，其列表与侧边栏使用的最近会话列表相同——从不会提供当前
  对话，并以报告的 `max_references`（目前为 3）为上限，超过上限的行会被禁用，
  而已选中的行仍可点击以移除。被附加的对话在输入框中显示为可移除的 chip，在
  对话记录中则是指回来源的只读 chip。引用是按消息生效的：不随草稿保存，发送
  或切换线程时清除，重新生成或编辑某个回合时会不带引用运行，除非重新附加。
  ([#5465])

- **frontend：** 能力管理从设置中迁出，成为工作区侧边栏里独立的
  `Capability Center`。此前 MCP server、已连接应用授权与技能都挤在账号和外观
  偏好旁边，既难以找到，也让设置对话框难以扫读；现在它们集中在同一个页面上，
  其中 `Plugins` 合并了 MCP 管理与 Lark/飞书应用的安装与授权，`Skills` 提供
  `Built-in`、`Community`、`My skills` 与 `All skills` 四种视图，支持可搜索
  的卡片、启用开关、文件导入、创建以及自定义技能导出。设置保留其余七个分区，
  API 契约与权限均未改变，旧的 `?settings=tools|integrations|skills` 入口被
  移除。([#5468])

#### 可观测性与工具
- **可观测性：** trace-id 关联与增强日志，以及通过 Monocle 实现的智能体可观测性
  。([#3902]、[#4024])
- **工具：** 类 Hermes 的终端工作台（`deerflow` CLI，基于 `DeerFlowClient`），以
  及脱敏的社区支持包（support-bundle）生成器。([#3760]、[#3886])
- **安装向导：** 安装向导现在会询问 OpenAI 兼容的 gateway 模型是否支持 thinking
  ，并新增火山引擎 Coding Plan 快速安装路径。([#3428]、[#4141])
- **TUI：** `clear` 命令。([#4306])

- **TUI：** 支持透明终端背景。([#4631])
- **网关：** 新增 `GET /health/ready` 就绪探针，执行有界的数据库 `SELECT 1`，
  数据库不可达时返回 503（memory 后端返回 200 `not_configured`）；`/health` 仍为
  纯存活探针，生产 compose 的健康检查也改用就绪探针。([#5166])
- **可观测性：** 延迟工具晋升（routing-hint 自动晋升与显式 `tool_search`）会以
  隐私最小化的 `middleware:tool_promotion` run 事件持久化（工具名、来源、数量、
  智能体归因；不含查询、schema 或结果），且仅在技能策略过滤之后观测，被拒绝的
  schema 不会被报告为生效晋升。([#5183])

- **client：** 上下文压缩把结果存放在 `messages` 之外的
  `ThreadState.summary_text` 中，但嵌入式客户端的 `values` 事件只选择了
  `title`、`messages` 与 `artifacts`——因此 Gateway 之外的消费方（例如基准
  测试运行器）无法通过公开事件流观察到该摘要。现在每个嵌入式 `values` 事件都
  会携带 `summary_text`，缺失时为 `None`，并把更新、重复与清除作为状态快照转
  发。消息序列化、AI-delta 去重、工具产物与用量记账均未改变，也没有暴露任何
  checkpoint 内部实现。初始快照本身就可能包含恢复出来的摘要，因此仅凭取值变
  化并不能断定发生了一次压缩事件。([#5249])

### 变更

- **前端性能：** 保持公共根页面和本地化文档静态化；懒加载关闭的工作区面板及编辑器/
  高亮依赖；增量推导流式消息状态；限制流式 Markdown 工作量；虚拟化超长消息与聊天
  列表；暂停屏幕外装饰效果，并对代表性路由设置 JS/CSS 预算。
- **浏览器：** 协商二进制 Browser Live JPEG 帧，兼容旧 JSON/base64 协议；每次刷新
  只呈现最新帧，并撤销已替换的 object URL。
- **Artifact：** 普通文本 artifact 支持 HTTP byte-range 流式读取；Web UI 初始预览
  限制为 1 MiB，用户显式请求后才加载完整文件。
- **沙箱：** Helm chart 现在默认将每个沙箱的 Service 设为 `ClusterIP` 而非 `NodePort`
  ，因此代码执行沙箱只能通过集群内 Service DNS（`http://sandbox-<id>-svc.<ns>.svc.cluster.local`
  ）访问，不再绑定到每个节点（包括 GKE / EKS / AKS 上外部可达的）网卡。升级时现
  有 chart 安装会从 NodePort 切到 ClusterIP。如需保留原有可达性（外部探测命中 30xxx
  端口，或 gateway 不在 K8s 的 Docker-Compose / 混合部署路径），请设置 `provisioner.sandboxServiceType:
  NodePort`（必要时配合 `provisioner.nodeHost`）。provisioner 本身不变（自 #4016
  起已按模式感知）。([#4190])
- **技能：** 处于激活态的限制型技能若要委派给子智能体，必须在 `allowed-tools` 中
  显式声明 `task`。只读发现基础设施（`tool_search` 与 `describe_skill`）仍可用，
  但无法为被禁用的业务工具授予 schema 可见性或执行权限。([#4098])
- **记忆：** 抽象化之前位于顶层的 `memory.*` DeerMem 字段（`storage_path`、`max_facts`
  、`debounce_seconds`、`model_name`、`token_counting`、`staleness_*`、`consolidation_*`
  等）在加载时会**带告警自动迁移到 `backend_config`**，因此升级不会静默地把自定
  义配置回退为默认值（`model_name` -> `backend_config.model.model`）。将它们移到
  `config.yaml` 的 `memory.backend_config` 下即可消除告警。([#4122])
- **记忆：** 新增 `memory.mode`（`middleware` | `tool`）；`tool` 模式会注册供模
  型直接调用的记忆工具（`memory_search`/`add`/`update`/`delete`），取代被动的逐
  回合摘要。`manager_class` 解析改为快速失败（未知后端时抛出 `ValueError`，而非
  静默回退）。([#4023])
- **中间件：** 声明式分层中间件构建器；`ThreadData` 现在先于 `Uploads` 运行。([#3809])
- **沙箱：** 宿主机到虚拟机的输出脱敏正则现在统一归属，消除重复的模式编译。([#4108])
- **文档：** `AGENTS.md` 成为智能体指引的权威来源，`CLAUDE.md` 通过 `@AGENTS.md`
  导入；模块指南同步刷新。([#3770])

- **记忆：** OpenViking 后端改用官方适配器；旧 trusted-mode 的 `auth_mode`/`account`
  字段会被拒绝，改用绑定凭据的 USER API key。([#4707])
- **网关：** 在 run-event journal 出现之前创建的会话，会在首次新 run 前把 checkpoint
  历史回填为 seed event，使旧会话升级后仍可见且顺序正确。([#4590])
- **智能体：** 子智能体委派改按净收益路由；除非并行延迟、专长能力或上下文隔离明确
  有益，否则主智能体默认直接执行。([#4384])

### 修复

- **上传：** 删除已上传的文档时，不再连带删除其旁边转换生成的 Markdown。转换以文档主干名
  命名配套文件，名称被占用时回退为 `_N` 后缀，因此文档旁的 `.md` 可能属于主干名相同的另一个
  文档，或属于用户自己：上传 `a.docx` 与 `a.pdf` 会生成 `a.md` 与 `a_1.md`，删除 `a.pdf`
  却会销毁 `a.docx` 的配套文件。现在配套文件会保留、继续出现在列表中，可单独删除。([#5673])
- **nginx：** 把 600 秒读取超时扩展到其余两个会等待 Gateway 的 location，它们在线程路由的修复
  之后仍沿用 nginx 默认的 60 秒。`/api/` 兜底 location 之后：无状态的 `POST /api/runs/wait`
  阻塞在同一套运行完成等待上，并在客户端断开时取消该运行，因此等待超过 60 秒的 API 调用方会
  同时收到 504 **并且**运行被取消；输入框的 `POST /api/input-polish` 则等待一次性模型调用。
  `/api/skills` 之后：安装 `.skill` 压缩包会对其中每个文件各做一次 LLM 安全扫描，自定义技能的
  编辑与回滚各再做一次，它们都没有自己的超时；此前只有同级的 `/api/skills/install/upload`
  拿到了更长的超时，因此同样的安装经由 `POST /api/skills/install` 会在 60 秒失败。
  Docker、本地开发与 Helm 配置均已应用。([#5524])
- **nginx：** 需要等待模型调用的线程路由不再在 60 秒时失败。浏览器直接调用 `/api/threads/*`，
  而该 location 没有设置 `proxy_read_timeout`，因此沿用 nginx 默认的 60 秒，而 `/api/langgraph/`
  允许 600 秒。较慢的 `/compact` 会返回 504，但 Gateway 仍会继续执行并保存压缩结果，于是 UI
  对已经生效的操作显示错误，诱使用户重试并再次压缩。`/suggestions` 也受同一限制，`/runs/wait`
  则会在 nginx 断开连接时取消其运行。Docker、本地开发与 Helm 配置现在都为该 location 允许 600 秒。([#5505])
- **中间件：** 循环检测不再中断正在分段读取文件的智能体。此前 `read_file` 调用按 200 行分桶作为
  键，因此任何短于一个桶的读取都会与相邻读取塌缩到同一个键：连续五次 40 行读取会哈希成相同值并
  触发硬停止，运行被迫给出最终答复并带上 `stop_reason=loop_capped`——而这恰恰是 `read_file` 自身
  的截断提示要求模型去做的分段读取。现在键使用精确的行区间，省略 `end_line` 时保持"读到末行"的
  开放语义，因此不带范围的读取与显式 `start_line=1` 仍共用同一个键。重复同一区间依然会在原有阈值
  被拦下，边界抖动的读取循环仍由按工具类型计数的频率层覆盖。
- **子智能体：** `max_turns` 现在真正表示运维人员理解的"轮次"。此前它被直接当作 LangGraph 的
  `recursion_limit` 传入，而后者统计的是 super-step——每个图节点一步，且 `create_agent` 会为每个
  中间件生命周期钩子编译出一个节点，因此在子智能体的中间件链上一轮要花掉 7~8 步：内置
  `general-purpose` 的 `max_turns=150` 实际只买到约 18 轮带工具调用的轮次，随后以 `turn_capped`
  结束；每往链上加一个中间件，有效预算还会再缩水一次。现在执行器会按实际组装出的中间件链的
  每轮节点数来换算配置的轮次，调高 `max_turns` 就能得到它所声明的轮次。没有配置项变化；既有的
  `max_turns` 取值现在会获得完整预算，因此原先被截断的子智能体运行可能变长，其上界仍由
  `subagents.timeout_seconds` 与 `subagents.token_budget` 约束。
- **middleware：** 循环检测不再中断正在分段读取文件的智能体。`read_file` 调用
  此前按 200 行的分桶建键，因此短于一个分桶的读取都会塌缩到相邻分桶上：连续
  五次 40 行的读取哈希完全相同，会触发硬停止，使 run 以强制最终答复和
  `stop_reason=loop_capped` 结束——而这正是 `read_file` 自身的截断提示
  要求模型去做的分段读取。现在的键使用精确的行区间，省略的 `end_line` 保持
  "读到末行"的开放语义，不带范围的读取与显式 `start_line=1` 仍共用同一个键。
  重复同一区间仍会在原有阈值被拦下，边界抖动的读取循环仍由按工具类型计数的
  频率层覆盖。
  ([#5486])

- **subagents：** 让 `max_turns` 名副其实——表示运维人员所理解的轮次。它此前被
  直接当作 LangGraph 的 `recursion_limit` 传入，而后者统计的是 super-step，
  每个图节点算一步；而 `create_agent`
  又会为每个中间件生命周期钩子编译出一个节点，因此在
  子智能体的中间件链上一轮要花掉 7~8 步：内置 `general-purpose` 的
  `max_turns=150` 实际只买到约 18 轮带工具调用的轮次，随后以
  `turn_capped` 结束；每往链上加一个中间件，有效预算还会再缩水一次。现在
  执行器会按实际装配出的中间件链的每轮节点数来换算配置的轮次，调高
  `max_turns` 就能得到它所声明的轮次。没有配置项变化；既有的 `max_turns`
  取值现在会获得完整预算，因此原先被截断的子智能体 run 可能变长，其上界
  仍由 `subagents.timeout_seconds` 与 `subagents.token_budget` 约束。
  ([#5485])

- **调度器：** 在 SQLite 上同样强制执行全局 `max_concurrent_runs`，此前该上限只在 Postgres 上成立。
  认领排队中的 occurrence 时，会先统计正在执行的行，再把其中一行提升为 `launching`，Postgres 用
  advisory lock 将这两步串行化。而 SQLite 的 deferred 事务直到那条提升用的 UPDATE 才占用 writer，
  因此在不同行上并发认领的调用方——手动触发与轮询重叠，或第二个 Gateway 进程共用同一个数据库
  文件——会读到同一个过期计数并全部通过预算检查，导致实际运行数超过配置的上限。([#5469])
- **sandbox：** AIO 的 `glob` 不再把"恰好填满"的结果报告为截断。其
  `include_dirs` 分支在收集到 `max_results` 个匹配时就立即返回，
  因此一个只有这么多匹配、后面再无匹配的目录列表也会被标记为被截断，
  工具据此告诉模型结果不完整。该分支本就持有整份目录列表，
  现在改为多看一个匹配再判断，与同级的 `include_dirs=False` 分支
  一致，后者一直是按完整列表判断的。这里涉及的只是**过滤后匹配数**上限；
  `parse_remote_search_output` 管的是**原始输出行数**上限，是另一条限制、
  有自己的"多放一行"记账方式，其他 provider 的过滤后匹配数上限未作改动。
  ([#5449])

- **沙箱：** AIO 的 `glob` 不再把"恰好填满"的结果报告为截断。其 `include_dirs` 分支在收集到
  `max_results` 个匹配时就立即返回，因此一个只有这么多匹配、后面再无匹配的目录列表也会被标记为
  被截断，工具据此告诉模型结果不完整。该分支本就持有整份目录列表，现在改为多看一个匹配再判断，
  与同一函数的 `include_dirs=False` 分支一致（后者一直是按完整列表判断的）。这里涉及的只是
  **过滤后匹配数**上限；`parse_remote_search_output` 管的是**原始输出行数**上限，是另一条限制、
  有自己的"多放一行"记账方式，其他 provider 的过滤后匹配数上限未作改动。
- **沙箱：** AIO 的 `grep` 与各远端 provider 的 `glob`/`grep` 不再把"恰好填满"的结果报告为截断。
  它们本就持有整份列表——原始输出在上限之上截取并自行报告截断——但在收集到 `max_results` 个
  过滤后的匹配时就立即返回，因此一个只有这么多匹配、后面再无匹配的目录也会被标记为被截断，
  工具据此告诉模型结果不完整。现在改为多看一个匹配再判断，与 AIO 的 `glob` 两个分支一致。
  这里涉及的只是**过滤后匹配数**上限；`parse_remote_search_output` 管的**原始输出行数**上限未作改动。
  ([#5534])
- **中间件：** 移除工具调用的守卫不再导致 Claude 或 OpenAI Responses 线程之后的每一轮都失败。
  token 预算与循环检测的硬停止、subagent 数量限制的截断以及安全终止抑制只清空了 `tool_calls`，
  却把 provider 自身的工具调用块留在消息 content 中。Anthropic 与 Responses API 会重新发送这些块，
  导致下一次请求带着没有结果的工具调用而被 provider 拒绝；写入 checkpoint 的硬停止消息还会让之后
  每条新消息都失败。现在所有守卫都通过同一个共享 helper 删除对应的 content 块，该 helper 也会保留
  clarification 所保留的 Responses 调用。([#5447])
- **沙箱：** 远程 `glob` 与 `grep` 的输出被截断时，不再报告"没有匹配"。BoxLite、Tenki、E2B 与
  OpenSandbox 会先限制搜索的原始输出行数，再在 Python 中过滤（`node_modules` 等忽略目录、匹配模式或 `glob`
  范围），但只有达到 `max_results` 时才报告 `truncated`。若被截取的行全部被过滤掉，截断位置之后仍有
  真实匹配的搜索会返回空结果且显示为完整。现在搜索会多输出一行以判断是否被截断，`glob` 和 `grep`
  工具对被截断的空结果会说明结果不完整，而不是显示 "No matches found"。([#5427])
- **沙箱：** 当输出用 `:` 连接主机路径（如 `$PATH`、`$PYTHONPATH`）时，主机路径不再暴露给模型。
  匹配的路径会一直延伸到列表末尾，导致同一根目录下之后的条目都未被遮蔽；多余的遮蔽轮次每次
  恰好补回一个条目，因此短列表掩盖了这一泄露。现在遮蔽时匹配的路径在 `:` 处结束。
  挂载目录内指向所有挂载之外的符号链接，在命令输出和 `glob` 结果中改为显示其挂载路径，而不是目标的主机路径。([#5418])
- **沙箱：** BoxLite `grep` 不再忽略 `glob` 的目录部分。此前只比较文件名，`src/*.js`
  会匹配整棵目录树中的所有 `.js` 文件。现在 glob 作用于相对搜索根目录的路径，与 `glob()`
  及其他 provider 的范围一致。([#5419])
- **模型：** 通过 `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` 传递 Claude Code OAuth
  token 时，第一个之后的 Claude 模型不再丢失凭据。每个 `ClaudeChatModel` 实例都会重新加载凭据，
  但文件描述符只能读取一次，导致标题、摘要、subagent 模型以及之后的每次运行都没有凭据，并以
  `TypeError: Could not resolve authentication method` 失败。现在 token 在每个进程中只读取一次并复用。([#5411])
- **模型：** 当 `supports_reasoning_effort: true` 的模型同时从 profile 获得
  `reasoning_effort`（顶层、`when_thinking_enabled` 或 `when_thinking_disabled`
  中，或由 `extra_body.thinking` 的关闭路径注入）时，lead agent 不再构建失败。lead
  agent 的常规构建总会转发请求的 effort（即使未设置），导致该参数两次传给 provider 构造函数，抛出
  `TypeError: got multiple values for keyword argument 'reasoning_effort'`。现在请求值
  按每个 agent 的 `model_settings` 方式叠加：替换 profile 顶层的值，未设置时保留该值，
  最终值仍由 thinking 模式相关设置决定。Codex 保留自己的级别校验。([#5403])
- **运行时：** 带 `Idempotency-Key` 的 run 重试在 SQL run 存储上不再返回 500。HTTP
  准入不会传入 `user_id`，SQL 存储会把请求用户写入该行，但进程内的 run 记录仍为
  `None`。同一 key 的重试若落到另一个 Gateway worker，或在已完成的 run 被清理后回到
  同一 worker，就会比较两边的拥有者，把自己的 run 误判为其他用户的并抛错。同一不一致
  还让 HTTP run 被按拥有者过滤的历史读取漏掉，并跳过了 MCP `background_tasks` 投影，
  因此这类 run 的 `values` 事件现在会包含 `background_tasks`。`RunManager` 现在按
  SQL 存储的方式用请求用户补全缺省的拥有者，各存储记录的拥有者保持一致。([#5401])
- **运行时：** 跨 worker 的幂等 run 复用不再让复用方 worker 永久阻塞该线程。此前复用会
  把从存储中读取的行注册为本地 run 记录，但只有拥有该 run 的 worker 才会结束并清理自己的
  记录，因此这份副本会一直停留在准入时的 `pending`/`running` 状态：该 worker 上此线程后续
  所有 `reject` 准入都返回 409，直到重启；读取该 run 时持续返回过期状态；若拥有方崩溃，
  孤儿回收也会跳过这个 run。发往该 worker 的取消请求还会走本地拥有方路径，把拥有方仍在
  运行的行标记为 `interrupted`。现在复用方 worker 返回不注册到本地的 store-only 句柄，
  取消请求也按非拥有方的约定处理。([#5393])
- **Skills：** 切换 skill 启用状态时不再把解析后的密钥写入 `extensions_config.json`。
  此前 Gateway 的 skill 开关与 `DeerFlowClient.update_skill` 通过
  `ExtensionsConfig.from_file()` 读取配置（该方法会把所有 `$VAR` 值替换为环境变量的
  实际值），再把模型整体写回，于是 `"$GITHUB_TOKEN"` 引用会被持久化为明文令牌，未设置
  的变量则被永久写成 `""`。`DeerFlowClient.update_mcp_config` 对 `mcpServers` 以外的
  所有键也存在同样问题。现在这些写入方直接修改磁盘上的原始 JSON，并按运行时的加载方式
  校验候选配置后再写入，占位符与手写结构保持不变；MCP 路由也复用同一个原始读取函数。
  已被旧版本改写过的文件仍保留明文值，请恢复 `$VAR` 引用并轮换已暴露的凭据。([#5357])
- **Gateway：** `disable_clarification` 与 `github_token` 现在与 `non_interactive`
  一样，仅对内部认证的调用方生效。此前这两个键无论调用方身份都会从 `body.context`
  透传，而且不会从被逐字复制进 run config 的自由格式 `body.config` 中清除，因此任何
  会话或 PAT 调用方都能设置它们。其中 `disable_clarification` 影响更大：
  `ClarificationMiddleware` 会把包括 `risk_confirmation` 在内的所有澄清请求替换为
  "无需确认，继续执行"，`SandboxMiddleware` 也把它与 `non_interactive` 视作同一个
  非交互信号。`github_token` 则会进入 `runtime.context`，被 bash 工具导出为
  `GH_TOKEN`/`GITHUB_TOKEN`；若经由 `body.config['configurable']` 夹带，还会被写入
  checkpoint 存储。定时任务、IM 渠道与 GitHub webhook 渠道走内部请求通道，不受影响。
  ([#5338])
- **Artifact：** `PUT /api/threads/{id}/artifacts/{path}` 现在严格限制在
  `/mnt/user-data/outputs` 之内。此前 outputs-only 校验只是对原始路径做字符串前缀
  检查，百分号编码的 `..`（`outputs/%2e%2e/uploads/x.txt`，nginx 原样转发、Starlette
  解码后）可以通过，而路径解析器只把结果限制在 `user-data/` 内，因此调用者能覆盖自己
  线程里的上传文件或 workspace 文件。现在会先折叠 `.`/`..` 段再做前缀检查，并把解析
  后的宿主机路径与解析后的 outputs 根目录再次比对，`outputs/` 内被植入的符号链接同样
  无法把写入重定向到别处。该规则现在收敛为一个共享 helper，IM 渠道的附件投递也走同
  一实现，两处不会再各自漂移。([#5321])
- **运行时：** 会话元数据现在仅在 run 通过启动屏障后才切换为 `running`，待取消的
  run 不再短暂呈现 `running` 状态；worker 启动期间客户端可能观察到先前的会话状态
  。([#4450])
- **运行时：** 通过原子化、感知租约的接管（takeover）claim 重新检查孤儿候选 run
  ，使扫描后的成功心跳仍保持 run 活跃，且仅有一个 reconciler 上报恢复。([#4424]
  、[#4434])
- **技能：** `allowed-tools` 只作用于斜杠激活或实际加载的主智能体技能，避免被动
  启用的技能与评测 fixture 从每个 run 中移除 MCP、网络、文件与委派工具。([#4095]
  、[#4098]、[#4192])
- **模型：** 在所有 `BaseChatOpenAI` 子类（`VllmChatModel`、`MindIEChatModel`、`PatchedChatMiMo`
  、`PatchedChatStepFun`、`PatchedChatMiniMax`）上生效 `api_base`，而不只是 `ChatOpenAI`
  / `PatchedChatOpenAI`。此前这五个子类会静默丢弃配置的 endpoint，随后以一个含义
  不明的 `unexpected keyword argument 'api_base'` 让每次请求都失败；它们也未被纳
  入未知配置 key 的告警。两者现在都基于 `issubclass(BaseChatOpenAI)` 判断。([#4146])
- **智能体：** 在 LLM 请求前合并 `SystemMessage`；保证工具运行后仍有可见响应；避
  免在流结束前发起默认的 LLM 标题调用；为省略号预留空间以使本地标题遵守 `max_chars`
  ；并将工具输出尾部前移，使回退截断遵守 `max_chars`。([#3711]、[#4033]、[#3885]
  、[#4052]、[#4017])
- **智能体：** 动态上下文的日期扫描跳过无日期的提醒；从不含 `config.yaml` 的智能
  体目录加载 `SOUL.md`；`update_agent` 的旧版智能体守卫要求存在 `config.yaml`；
  并拒绝空的 `SOUL.md` 更新。([#3685]、[#4136]、[#4166]、[#4219])
- **中间件：** 为循环检测的工具频次计数器加窗口，避免长 run 误触；阻止标题中间件
  流式输出 token；修复“同内容列表耗尽时位置回退误取无关 todo”的问题；在 `_apply`
  、`before_agent`、`_clear_run_state` 与 `_drain_pending_warnings` 之间持有 token
  预算锁；丢弃孤立的 `ToolMessage` 以免严格型 provider 返回 400；净化非法 tool-call
  参数；并在 dangling 修复中从空的 tool-call 名称与畸形 tool-call id 恢复。([#4072]
  、[#3566]、[#3709]、[#3714]、[#4080]、[#4193]、[#4008]、[#4246])
- **子智能体：** 继承 `LoopDetectionMiddleware` 与摘要中间件，使工具循环能被打断
  、步骤能被捕获；将回合预算上限以 `MAX_TURNS_REACHED` 暴露并附带部分结果；在累
  加式 `stop_reason` + `token_budget` 上统一护栏上限；压缩前注入持久上下文；保留
  父 checkpoint 命名空间；在 general-purpose 系统 prompt 中禁用 `task` 工具；flush
  失败时重新缓冲子智能体事件以避免丢失步骤；并修复子智能体 `run_id` 为 `None` 时
  丢失 `loop_capped` 停止原因的问题。([#3931]、[#4009]、[#3949]、[#3980]、[#4040]
  、[#4215]、[#4161]、[#4082]、[#4059])
- **记忆：** 加固对 null / 空值边界情况的处理——跳过仅含空白的事实；在更新、检索
  与剩余三处原始读取中规整 null 的 `confidence` / `source.confidence`；将显式 `null`
  的 `backend_config` 值视为缺省；修复事实无 id 或事实列表为空时的 `KeyError` /
  `UnboundLocalError`；停止防抖更新队列的忙等（busy-spin）；并在优雅关闭时刷写记
  忆队列以防丢失。([#3719]、[#4074]、[#4076]、[#4034]、[#4217]、[#3993]、[#3992]
  、[#4073]、[#4181])
- **运行：** 关闭 run 原子性中的多 worker 归属缺口；在租约续期于截止期前无法确认
  时令本地执行快速失败，并在 peer 接管后对迟到的完成写入加围栏；多 worker 下将 cancel
  降级为租约接管；让 `create_thread` 在插入竞态时仍幂等；从运行时上下文读取 `stop_reason`
  ；并将 run 时长持久化到 checkpoint 以供历史读取。([#4003]、[#4064]、[#4414]、[#3800]
  、[#4188]、[#4118]、[#4431])
- **运行时：** 序列化 SQLite event-store 写入，避免按会话的序列号冲突；在 journal
  中跳过隐藏的人类消息；并去掉 `_merge_stream_text` 中静默丢弃 delta 的行为。([#4077]
  、[#3698]、[#4085])
- **网关：** 按真实 `event_type` 关联会话消息反馈；把 artifact 服务、gateway 上
  传与 Discord 渠道中的阻塞文件 IO 移出事件循环；限制上传文件的上下文清单；并实
  时追踪畸形的 Redis 重连 id。([#3651]、[#3551]、[#3935]、[#3927]、[#3917]、[#4012])
- **上传：** 在写入前先占位转换后的 Markdown 配套文件名，使同词干（stem）的两个
  可转换上传（或一个可转换上传加一个同词干 `.md` 上传）不再在同一请求内静默互相
  覆盖。`uploads.auto_convert_documents` 开启时，配套 `.md` 会得到唯一名称（如 `a_1.md`
  ）；`POST /threads/{id}/uploads` 与 `DeerFlowClient.upload_files` 都会在 `markdown_file`
  中返回实际文件名。([#4288])
- **配置：** 将为 null 的对象型配置节规整为默认值；在 store 与 sync checkpointer
  中遵循统一数据库配置；并让旧版 DB 回填在已存在的表上补建缺失的 `Index` 对象。([#3573]
  、[#3904]、[#3994]、[#4090])
- **模型：** 将 `stream_chunk_timeout` 默认值应用到所有 `BaseChatOpenAI` 子类；
  并为 `ChatOpenAI` 把 `api_base` 规范化为 `base_url`，遇到未知配置 key 时给出告
  警。([#4102]、[#3790])
- **MCP：** 按 server 隔离工具发现失败；同步 session-pool 单例的生命周期；按配置
  内容 + 路径（而非仅更新的 mtime）失效工具缓存；在加载时校验 MCP 工具名，使延迟
  prompt 保持惰性；并按来源 server 路由工具，而非按名称前缀。([#3772]、[#3797]、
  [#4124]、[#4154]、[#3812])
- **技能：** 斜杠技能每个 run 仅激活一次，而非每次模型调用都激活；补齐技能安装安
  全扫描的覆盖缺口；在评审 CI 中识别被完全删除的技能包，并在 SkillScan 中把剩余
  的 `requests` / `httpx` 方法识别为网络出口；在无参 skills prompt 段落复用已解
  析的 app 配置；并支持不重启 Gateway 即可重新加载已挂载技能。([#4103]、[#3924]
  、[#4169]、[#4130]、[#4160]、[#4264])
- **沙箱：** 为反向路径翻译与输出脱敏正则加上段边界；在 `read_file` / `str_replace`
  中处理单边行范围与空文件；对齐 AIO bash 工作目录；在 Windows 的反向 resolve 包
  含性检查中使用 `os.sep`；在 bash 命令中规范化 Windows 反斜杠路径；阻止 `glob`
  / `grep` / `ls` 暴露被禁用技能的文件；并在沙箱审计中允许合法的 heredoc 命令。([#4035]
  、[#4053]、[#4078]、[#4079]、[#4051]、[#4058]、[#3869]、[#4096]、[#3786])
- **沙箱：** 同步沙箱 provider 单例的生命周期（含并发回归测试），并让 provisioner
  中的 k8s 调用不阻塞事件循环。([#3730]、[#3941])
- **沙箱：** 将沙箱 artifact 挂载与渠道用户对齐；修复非 root / NFS 主机上的本地
  开发（`make dev`）；停止时回收 macOS 上的 nginx 进程；并修复 Docker 中生产环境
  Postgres 的 UV-extras 检测。([#3729]、[#3590]、[#3828]、[#3897])
- **渠道：** 在解析渠道 provider 配置前先校验 provider；对 GitHub webhook 重投递
  去重，并丢弃冗余的 GitHub review-comment webhook 扇出；把斜杠技能白名单检查限
  定在 run 的 owner 作用域；将飞书文件消息批量到一个会话，并以 bot @mention 前缀
  分发飞书群命令；在 `/connect` 绑定码前接受前导 @mention，且不把裸 `connect` 当
  作绑定命令；阻止飞书创建会话话题并限流卡片更新；让 UI 运行时渠道配置优先于 `config.yaml`
  ；修复 `bot_login` / `mention_login` 仅含空白时 `require_mention` 的门控；防护
  企业微信中为 null 的引用字段；并将入站去重按聊天作用域的工作区建立 key，使 Telegram
  、飞书、微信与钉钉在默认（未绑定）配置下不再因重投递重复执行智能体，遇到瞬时失
  败时释放去重 key 以便重投递仍可恢复。([#4100]、[#4104]、[#4131]、[#4129]、[#3753]
  、[#4229]、[#4222]、[#4251]、[#3810]、[#3674]、[#4055]、[#4069]、[#4287])
- **前端：** 摘要过程中保留消息与持久上下文；流式期间保留 artifact 并稳定 artifact
  路径；解析相对 artifact 图片路径；在 header 下拉中保留已展示的 artifact；保持
  孤立的工具消息可见；工具步骤期间展示助手文本；客户端导航时重置新会话；防止并发
  提交导致流被取消；修复过期 run 的重连与取消处理；修复聊天公式渲染、单波浪线 markdown
  、双重 reasoning 渲染、UTF-16 markdown 二进制分类与 Streamdown 中的 `<memory>`
  标签；让最近会话行整体可点击；上传前校验附件上限并修复消息复制中上传文件元数据
  ；修复移动端工作区与可访问性阻塞、卡片工具消息 bug 以及侧边聊天工具栏 / 面板按
  钮行为；拦截未解析的建议模板占位符；刷新通知权限；仅对已完成回合显示分支操作；
  在自定义智能体聊天中启用重新生成；并为被中断的首回合 run 生成兜底标题。([#3826]
  、[#3791]、[#4094]、[#4038]、[#3854]、[#3880]、[#4114]、[#3673]、[#3878]、[#3908]
  、[#3557]、[#4245]、[#3870]、[#3966]、[#4209]、[#3733]、[#3900]、[#3944]、[#3740]
  、[#3976]、[#3959]、[#3961]、[#3764]、[#3768]、[#4147]、[#3967]、[#3874]、[#3644])
- **TUI：** `/quit` 退出前先中断活动 run。([#4235])
- **harness：** 当大纲标题数恰好等于 `MAX_OUTLINE_ENTRIES` 时不再误判为被截断。([#3856])
- **追踪：** 把 Langfuse trace 元数据附加到目标评估器。([#4202])
- **上下文：** 修复 context-compress 的 bug。([#4065])
- **ThreadData：** 修复 `runtime.context` 为 `None` 时的 `AttributeError`。([#3989])
- **goal：** 修复 stand-down 期间 `continuation_count` 被重复递增的问题。([#4199])
- **熔断器：** 修复半开探测不可重试后熔断器卡死的问题。([#3991])
- **GitHub：** `allow_authors` 登录名改为大小写不敏感匹配。([#4218])
- **社区工具：** `image_search` 现在返回全分辨率图片 URL。([#3990])
- **技能：** 把技能历史接口中的阻塞文件 IO 移出事件循环。([#3563])
- **技能：** SkillScan 不再把惰性求值的 PEP 695 类型别名误判为网络出口。([#4315])
- **skills：** 技能压缩包的解压现在也按成员数量设限，而非只按未压缩大小。
  `safe_extract_skill_archive()` 是每次 `.skill` 安装都会经过的常开路径；它限
  制了
  未压缩字节总量以防御按大小计的 zip 炸弹，却没有成员数量上限，
  因此一个装有数万条微小条目的压缩包可以被顺利解出。
  `scan_archive_preflight()` 早已把条目数限制在 4096，但只会在可选的
  `skill_scan.enabled` 开关开启时运行，默认路径因此没有上限。现在解压会无条件
  执行同样的 4096 成员上限，直接抛出 `ValueError`；在启用了 SkillScan
  的情况下，结构化的 `package-too-many-members` 命中仍会优先呈现。
  ([#4241])

- **追踪：** 从运行时上下文解析 Langfuse trace 的用户。([#3794])
- **护栏：** 将内部 owner 归因透传到护栏上下文。([#3839])
- **子智能体：** 子智能体上限与 `MIN_SUBAGENT_LIMIT` 保持一致地限幅。([#4081])
- **子智能体：** 加载按用户作用域的技能。([#4356])
- **MCP：** 按 server 的 OAuth 预热改为失败即软降级，并持久化轮换后的 refresh token
  。([#4084])
- **MCP：** 忽略畸形的类路径文本。([#4456])
- **认证：** 邮箱账号改为大小写不敏感解析。([#4101])
- **认证：** 从 setup-status 超时中恢复。([#4371])
- **调度器：** 修复一个调度竞态，该竞态可能为同一个定时任务启动两个 run。([#4105])
- **渠道：** 缓冲并在 busy run 期间排空被排队的 GitHub 评论。([#4133])
- **渠道：** 在转换为 mrkdwn 前先转义 Slack 保留字符。([#4197])
- **渠道：** 飞书卡片 / reaction SDK 调用上检查 `response.success()`。([#4234])
- **渠道：** 丢弃不携带会话身份的入站钉钉消息。([#4316])
- **渠道：** 支持接收入站 Telegram 附件。([#4392])
- **记忆：** 合并后的事实从其来源继承 `expected_valid_days`。([#4225])
- **配置：** `_memory_config` 与 AppConfig 自动重载保持同步。([#4208])
- **Postgres：** 用 `pool_recycle` 与 `command_timeout` 加固异步引擎，消除陈旧连
  接导致的 504。([#4230])
- **harness：** 为 `invoke_acp_agent` 增加超时，避免无限挂起。([#4238])
- **社区工具：** 在 `web_fetch`（Browserless）中暴露目标页的错误状态。([#4239])
- **沙箱：** 放宽 BoxLite / AIO 的租户哈希范围，并在回收时校验身份。([#4171])
- **沙箱：** `str_replace` 在任意文件上遇到空 `old_str` 时改为无操作。([#4256])
- **沙箱：** 序列化 E2B 的释放状态转换。([#4355])
- **沙箱：** 限制 E2B 输出同步的资源占用。([#4364])
- **沙箱：** 在 `after_agent` 中解包被 `Overwrite` 包裹的沙箱状态。([#4381])
- **沙箱：** 本地 AIO 流量绕过代理。([#4444])
- **模型：** 暴露因长度截断的模型响应，而非直接丢弃。([#4309])
- **流式：** 保持大文件生成过程的响应性。([#4354])
- **流式：** 把自定义事件暴露给 `astream_events`。([#4403])
- **流式：** 对回放历史中的缺口发出信号。([#4426])
- **摘要：** 使用 run 模型进行摘要，摘要 provider 失败时回退。([#4361])
- **运行时：** 模型调用后移除临时的图片上下文。([#4267])
- **运行时：** 阻止子图流式帧冒充根帧。([#4407])
- **运行时：** 拒绝不支持的 run 选项与流模式。([#4430])
- **运行时：** 序列化 checkpoint 写入与活动 run、线性化 delta 模式的 checkpoint
  恢复，并接受 SDK 默认的 `stream_resumable=false`，以避免恢复竞态。([#4437]、[#4460]
  、[#4468])
- **checkpoint：** 解包对空 channel 的 `Overwrite` 首次写入。([#4383])
- **nginx：** 允许超长聊天 prompt 通过 `/api/langgraph/`，不再直接返回 500。([#4277])
- **网关：** 当 header 已设置时，优先使用 `X-Trace-Id` 而非 `metadata.deerflow_trace_id`
  。([#4283])
- **网关：** 为分支补种 run-events，使继承的历史在分叉后仍然保留。([#4385])
- **网关：** 分支历史补种的 run id 按继承的回合作用域划分。([#4459])
- **前端：** 加固 artifact 与 markdown 渲染。([#4117])
- **前端：** 工作区变更评审中，把“符号链接替换文件”与“删除”区分开。([#4170])
- **前端：** 把工作区变更文本缓存生命周期中的阻塞文件 IO 移出事件循环。([#4268])
- **前端：** 对 artifact URL 的路径段进行编码。([#4278])
- **前端：** 厘清 run 时长的展示。([#4348])
- **前端：** 在分支会话中保留重新生成状态。([#4358])
- **前端：** reasoning-effort 未设置时默认展示为 Medium。([#4373])
- **前端：** 剥离并解析 `<current_uploads>` 上传上下文标签。([#4402])
- **前端：** 保持前导的孤立工具消息可见。([#4408])
- **前端：** 刷新后保持已完成子任务卡片的稳定。([#4432])
- **前端：** 通过 inline style 应用消息图片的 `maxWidth`。([#4446])
- **前端：** 恢复 artifact 与侧边面板的可调整大小。([#4469])
- **前端：** 允许非 localhost 主机访问 dev-server。([#4471])
- **内容安全：** 回填空的内容过滤响应，避免污染会话。([#4394])
- **工具：** 从 `list_uploaded_files` 的 schema 中排除注入的 runtime。([#4376])
- **Artifact：** 显式加载完整文件时限定在来源会话内，使其他会话中同路径 artifact
  仍保持 1 MiB 预览。([#4634])
- **沙箱：** `SandboxAuditMiddleware` 改为按命令替换所处位置判断风险：普通输出捕获
  不再误拦，而命令位置、解释器代码参数、`eval`/`source`、process substitution 与
  here-string 中执行下载内容仍会阻止；heredoc 正文继续按数据处理。([#4611]、[#4623])
- **MCP：** 设置页的启停只校验目标 server；允许禁用已不合规目标但拒绝重新启用，
  支持规范中的 `transport` 别名、展示后端校验详情，并以原子方式更新共享配置。([#4574]、[#4577])
- **MCP：** 用按 server 的 `session_init_timeout`（默认 60 秒，`null` 可关闭）限制工具
  发现与持久 stdio session 初始化，避免挂起 server 阻塞智能体装配或 Gateway 事件循环。([#4657])
- **运行时：** `.tool-results` 等超大工具输出外置目录不再计入工作区变更和产物检测，
  仅外置工具输出的 run 不会再被投递校验误判失败。([#4657])
- **前端：** 回合仍在流式输出时隐藏旧的后续建议。([#3396])
- **前端：** 修复流式渲染抖动：不重复播放逐字动画、稳定步骤文本和消息顺序，并保持
  reasoning 位于答案上方。([#4266]、[#4510]、[#4513]、[#4578])
- **前端：** 聊天路由中的 thread id 现在会编码，特殊字符不再破坏导航。([#4302])
- **前端：** 从 React children 正确渲染引用链接。([#4486])
- **前端：** 本地化会话导出失败消息。([#4493])
- **前端：** 拖拽折叠面板时同步侧边面板状态。([#4556])
- **前端：** 每个 run 只渲染一张工作区变更卡片。([#4559])
- **前端：** 活动 artifact 发生变化时刷新其内容。([#4584])
- **网关：** 拒绝 API 请求中的非正读取上限。([#4284])
- **网关：** 解析 thread id 时兼容为 null 的 `config.configurable`。([#4301])
- **网关：** 统一各 API 路由的 thread id 校验。([#4589])
- **网关：** 合并并发的会话元数据更新，避免相互静默覆盖。([#4489])
- **网关：** 向跨域客户端暴露 run 元数据响应 header，使分离部署的前端能及时获知新 run id。([#4535])
- **网关：** 从稳定 checkpoint 执行“编辑并重跑”，确保编辑后的 prompt 真正运行，
  并在重跑后保留手动标题。([#4534]、[#4539])
- **运行时：** 可从任意存活 Gateway worker 取消 run，停止按钮不再依赖请求路由。([#4500])
- **运行时：** interrupt 或 rollback admission 中途取消时关闭替代 run，避免留下不可见的活动 run。([#4472])
- **运行时：** 重新生成响应时保留当前标题，并支持最近一次尚未写入 checkpoint 的中断响应。([#4480]、[#4524])
- **智能体：** 将 404 等 `web_fetch` 错误页识别为错误证据，使重试和停滞保护能够响应。([#4314])
- **智能体：** 规范化澄清选项时兼容 XML-to-dict 形态。([#4527])
- **子智能体：** 委派执行使用隔离 callback 与惰性技能激活，修复跨事件循环错误及被动
  技能移除 `write_file` 等基础工具的问题。([#4497])
- **沙箱：** 初始化沙箱时兼容被 `Overwrite` 包裹的状态。([#4429])
- **沙箱：** 安全协调 E2B 沙箱：选择首个健康候选、按用户与会话采纳规范实例、延后
  处理 peer 的活动副本，并在宽限期后回收孤儿。([#4443])
- **沙箱：** 销毁 readiness 失败的沙箱前先取得所有权，避免 peer 采纳后误杀活动回合。([#4505])
- **沙箱：** `grep` 支持搜索单个文件。([#4512])
- **沙箱：** 使用 Redis 所有权时在部署范围内强制 E2B 容量上限。([#4575])
- **技能：** 斜杠调用可从托管 integrations 根目录激活集成技能。([#4570])
- **技能：** 更新技能时把阻塞文件 IO 移出事件循环，并序列化并发写入。([#3565])
- **MCP：** 忽略过大的类路径文本。([#4582])
- **记忆：** 在创建临界区拒绝重复事实，按条目边界截断 mem0 注入上下文，并阻止
  “仅检查”等任务级指令进入长期记忆。([#4599]、[#4600]、[#4604])
- **调度器：** 启动成功后的记账若失败，仍保留 run slot 与 run id，防止后续重复启动。([#4504])
- **配置：** 被删除的 extensions 配置文件按不存在处理，工具与技能配置解析仍可继续。([#4275])
- **配置：** 为异步 ORM engine 规范化 `postgres://` 短 scheme。([#4293])
- **控制台：** 模型定价混用货币时禁用成本汇总，避免输出无意义总额。([#4564])
- **Browserless：** 接受 `timeout` 配置键并加固类型转换。([#4519])
- **Docker：** 仅在浏览器请求升级时发送 `Connection: upgrade`，修复远程访问 Docker
  dev stack 时登录页循环刷新。([#4250])
- **运行时：** JSONL 批量事件按 run 分组写入，避免跨多个 run 的批次全落入首个文件。([#4938])
- **运行时：** 恢复独立 LangGraph Studio 兼容：图入口、文件式 app、系统助手发现与
  `langgraph dev` 工作流重新可用。([#4760]、[#4838])
- **网关：** 只在 `/messages/page` 中把 `turn_duration` 标到 run 的最后一条 AI 消息。([#4755])
- **网关：** 跨越 event 分页上限仍保持精确历史归因，旧 AI 消息不再归到后续 run。([#4953])
- **网关：** MCP task worker 停止时以 HTTP 503 拒绝取消请求。([#4963])
- **中间件：** 修复动态上下文目标、列表字符串净化、重复无效工具占位符，以及摘要误
  压缩当前用户请求等四个上下文问题。([#4667]、[#4668]、[#4693]、[#4882])
- **中间件：** 恢复向模型说明 `write_todos` 工具的系统 prompt 注入。([#4735])
- **智能体：** SQL agent-store 签名改为内容敏感，时间戳复用时注册表也不会继续提供旧路由。([#4709])
- **工具：** 使用运行时用户解析待展示文件，避免有效 artifact 被误判在 outputs 外。([#4677])
- **工具：** 强引用延迟子智能体清理任务，防止 GC 销毁待执行清理并泄漏记录与锁。([#4928])
- **子智能体：** 每个后台执行使用服务端 execution ID，复用 provider tool-call ID 的
  并发 run 不再覆盖、轮询或取消彼此状态。([#4758])
- **Harness：** 把 ACP workspace 创建与 MCP 配置加载移出事件循环。([#4965])
- **MCP：** 收到 task snapshot 时拒绝非有限 `poll_after_seconds`。([#4750])
- **MCP：** OAuth token 交换中以配置的 `grant_type` 为准，`extra_token_params` 不再能
  静默切换 flow。([#4860])
- **runtime：** 缓慢或卡死的 stdio MCP server 不再拖住整个 Gateway。智能体装配
  此前在事件循环上同步装配 MCP 工具，因此等待一次进行中的 MCP
  初始化会阻塞所有其他请求的 SSE 投递、run 取消与定时器，
  而不只是阻塞那个正在等待自己工具的调用方。
  现在每个异步入口点都会把工具装配派发到工作线程：`task_tool` 中的子智能
  体生成路径、用于持久批处理的 `SubagentBatchService._execute_item`、
  `run_agent` 的 agent 工厂（它覆盖了 lead-agent 装配中两处
  `get_available_tools` 调用点），以及 checkpoint state-accessor 的构建——
  其冷缓存读取现在在工作线程中承担 MCP 初始化的等待，而不再停住事件循环。这四
  处卸载共用同一个有界专用池（`utils/assembly_io.py` 中的
  `run_assembly()`，8 个 worker，可用 `DEER_FLOW_ASSEMBLY_WORKERS`
  覆盖），而非事件循环的默认执行器，因此一个为等待完整 MCP 超时而停住的
  worker 无法把其他所有 `to_thread`
  调用方排到自己身后；contextvars
  会跨这次跳转复制，扩展的 build-context 快照因此仍能传播，
  而当等待中的装配数超过 worker 数时会以限流的警告记录下来。由于装配
  现在可能被长时间挂起，持久批处理会在启动前立即重新检查其条目的持久状态，
  因此在装配期间被取消的批处理不会再发起模型调用。
  ([#5217], [#5224])

- **agents：** `LoopDetectionMiddleware` 不再把一个轮次的预算消耗在另一个轮次的
  合法工作上。它此前只用 `thread_id` 界定相同调用哈希与按工具频率窗口
  的作用域，因此一个跨轮次复用的已编译智能体——`DeerFlowClient`
  会保留图并为每个轮次分配新的 `run_id`——
  会把先前轮次的普通调用计入后一个轮次的限额，在默认的相同调用阈值下，
  第三个独立轮次就产生一次虚假的循环警告，第五个轮次则被剥掉一次合法的工具
  调用。状态现在按 `(thread_id, run_id)` 界定作用域，同一个 run 内多次进入图
  时证据仍会累积（包括隐藏的 goal 延续），并发兄弟 run 则各自拥有独立的警
  告队列。LRU 淘汰会丢弃整个 run 作用域，`reset(thread_id)` 仍会清除该线程
  拥有的每个作用域，阈值以及警告/硬停止行为均未改变。
  ([#5344])

- **agents：** 现在，一个 run 的 `token_budget.max_tokens` 上限在活跃
  `/goal` 的各次隐藏延续中同样成立。worker 会在同一个 `run_id` 下重新进入图，
  而中间件此前会在 `after_agent` 中清空该 run 的用量，
  再把所有既有消息标记为已见，因此每次延续都从零开始计数：
  在 `max_tokens: 10000` 下，一个在 12k 处触发硬停止的轮次
  之后跟着一次继续调用工具的延续，run 一边上报 `stop_reason: token_capped`，
  一边花掉了 20k 令牌，并在达到上限后又执行了两次工具调用。
  现在用量与警告状态能够在相同 `run_id` 的多次进入图中存活下来，
  循环检测早已如此；而之后的一次用户 run 仍会拿到全新的 `run_id`
  和全新的预算。达到上限后，延续仍会先做一次模型调用，
  然后其工具调用才会被剥离。
  ([#5410])

- **middleware：** 人工输入卡片的回复现在会被识别为用户的当前请求。
  卡片答案以隐藏的 `HumanMessage` 形式到达，其中携带有效的
  `human_input_response`，而轮次检测辅助函数使用的是
  `is_real_user_message`，它会无差别地拒绝每条隐藏消息，没有任何豁免——
  因此由卡片回复启动的 run 会把较早的可见请求当作"当前"请求，而答案本身
  却被视为框架注入。在摘要中，当前请求的挽救逻辑因此锁在了那条过期的消息
  上：压缩之后模型看到的是原封不动的原始请求，
  而用户的地区与年份约束只存在于摘要里。在 `McpRoutingMiddleware`
  中，只出现在卡片答案里的路由关键词匹配不到任何东西，
  于是被推迟的 MCP 工具永远不会被自动提升，模型只能手动调用
  `tool_search`——同样的答案若以可见消息发送就能完成提升，
  可见行为只取决于答案的传输方式。现在两处都改用
  `is_genuine_user_message`，它跳过隐藏消息，除非其携带有效的
  `human_input_response`；没有该字段的隐藏消息仍会被跳过。
  ([#5416], [#5426])

- **goal：** 一个已达到 token 上限的 run 所满足的目标，
  其后不再跟着一次毫无意义的延续。既然延续现在共享该 run 的 token 预算，
  硬停止后排入队列的延续只会做一次模型调用，随后其工具调用便被剥离，
  因此无法取得任何进展——然而 worker 仍然会把它排入队列，
  每次都付出一次评估器调用和一次模型调用的代价，
  直到延续上限或无进展上限终止该目标为止。`run_agent` 现在会把 run 的
  `stop_reason` 传入目标延续的准备流程，当它是 `token_capped` 时，目标会以
  `stand_down_reason: "token_capped"` 退场，而不是再排入一次延续。
  评估器仍会先运行，因此已达到上限的 run 确实满足了的目标仍会被清除，其他
  `stop_reason` 的行为与之前相同。
  ([#5424])

- **agents：** 被重试的模型调用不再会丢掉守护中间件早已为它排入的警告。
  `LoopDetectionMiddleware`、`TokenBudgetMiddleware` 和
  `ToolProgressMiddleware` 会在 `wrap_model_call` 中、调用 handler
  之前取空各自已排队的警告或提示；由于 `LLMErrorHandlingMiddleware`
  包裹着它们并通过再次调用自己的 handler 来重试，
  第二次尝试是在队列为空的情况下运行的，而那条警告早已被
  标记为已发送。一个在某次工具调用上循环、并在携带该警告的请求上因 503 失败一次
  的模型从未看到这条警告，径直跑到了强制停止。现在这三者都会在 handler
  抛出时把取出的警告重新放回队列头部，从而让重试拿到它们；
  成功调用的行为不变，每个 run 的上限仍然生效，
  而若 run 在没有再次模型调用的情况下结束，警告仍会在 `after_agent`
  处被丢弃。
  ([#5433])

- **agents：** token 预算对没有 `run_id` 的 run 重新生效——包括 LangGraph
  Server、`langgraph dev` 以及直接调用 `create_deerflow_agent` 的调用方。
  两处缺陷都源于那个 runtime 局部的回退键。子智能体的硬停止被存在 id
  字符串下，却用 `consume_stop_reason(None)` 读回，因为 `SubagentExecutor`
  会传播父级的 `run_id` 而父级没有，于是被 token 上限截断的子智能体向父级
  报告的是干净的 `Task Succeeded`，而不是上限截断失败。此外，LangGraph
  会给每个节点各自的 `Runtime` 包装器，因此 `id(runtime)` 在 `after_model`、
  下一次 `wrap_model_call` 与 `before_agent` 之间各不相同：
  排队的预算警告从未被投递，`after_model` 错过了 `before_agent`
  的基线而把线程里的每条 `AIMessage` 都计入，
  同一线程上的第二次调用还被计入了第一次调用的令牌。现在，context
  中没有非空字符串 `run_id` 的调用会改用 LangGraph 按 run 作用域的
  `Runtime.control` 对象作为键，也就是循环检测使用的同一个锚点；
  而停止原因会严格按给定的 context `run_id`
  存储，包括 `None`。
  ([#5436])

- **agents：** 取消 `read_file` 或 `write_file` 调用不再会让 read-before-write
  门的锁被搁置或提前释放。`asyncio.to_thread()` 的取消只会取消 asyncio
  的等待者，不会取消已在运行的 worker，因此一次取消可能让已排队的
  `threading.Lock.acquire()` 一直挂起，或者在跨线程探测仍在运行时就把门释放掉。
  现在派发出去的门操作会在取消传播之前先在 `asyncio.shield()` 之下排空，第一个
  `CancelledError` 会被保留并在重复取消时重新抛出（包括被排空的那个
  worker 任务自身被取消的情况），取消之后才成功的锁会恰好释放一次，
  而同路径的门会一直被持有到写入检查与读取标记工作完成。
  ([#5395])

- **agents：** `create_deerflow_agent` 的三项功能现在名副其实。工厂图此前是在
  没有
  `DurableContextMiddleware` 的情况下构建的，
  而正是它写入 `delegations` 账本——因此 `SubagentLimitMiddleware`
  始终把此前的委派数计为零，只有 per-response 上限生效——也正是唯一会把
  `summary_text` 放回模型请求的东西，
  因此第一次压缩之后模型只看到保留的尾部，摘要就此丢失。另外，
  `RuntimeFeatures(token_budget=True)` 构建的 `TokenBudgetConfig()`
  其 `enabled` 默认为 `false`，于是每个钩子都提前返回，既没有警告，
  也没有硬停止，更没有 `token_capped`。现在
  `_assemble_from_features` 总会按 lead-agent 链的同一位置添加
  `DurableContextMiddleware`，工厂的模型请求会在图含有摘要、委派或
  已加载技能文件时携带隐藏的 durable-context 块，而
  `token_budget=True` 会构建 `TokenBudgetConfig(enabled=True)`。
  ([#5488])

- **subagents：** 子智能体的验收检查在 Windows 上不再让越界命令算作证据。
  `_cd_target_in_scope()` 此前用宿主机平台的路径模块来规范化 bash `cd` 目标，
  因此
  在 Windows 上一个绝对 POSIX 路径或 `..` 逃逸
  可能被判为安全的相对目标，一次在受检范围之外运行的测试就能满足某项验收标准。
  现在 bash 目标与配置的根路径在任何宿主机上都按 POSIX 语义规范化，带盘符的
  Windows 路径会被识别并做大小写不敏感的比较，
  而盘符或目录不匹配时会失败关闭。
  ([#5162])

- **sandbox：** 一旦并发子智能体数量超过 AIO 镜像的 shell 会话上限，并发子智能
  体就会停止工作。每个并发子智能体都会获得自己的持久化 scoped shell，但 AIO
  镜像把 `MAX_SHELL_SESSIONS` 限制为 10，因此第十一个 shell 会在 DeerFlow
  仍持有其 scoped id 的情况下淘汰掉最旧的空闲会话——该子智能体的下一条命令随即以
  `404 Session not found` 失败，而在不提高容量的情况下重建会话只会淘汰另一个
  子智能体并丢失其 shell 状态。新的本地容器现在会把
  `subagent_runtime.max_running + 1`（多出的那个槽位给 lead shell 留出空间）
  作为 `MAX_SHELL_SESSIONS`，provisioner 模式会把同一个值转发给 sandbox Pod，
  而显式设置的、低于所需容量的 `sandbox.environment.MAX_SHELL_SESSIONS`
  现在会在 provider 启动时报错并列出两个数值。如果 scoped 会话仍然丢失
  （因超时或外部清理），DeerFlow 会重建它一次，且仅针对结构化的
  `404 Session not found` 响应。([#5178])

- **view-image：** `view_image` 不再为远程沙箱图片提供过期或缺失的图片。
  它此前把 `/mnt/user-data/...` 解析为 Gateway 宿主机路径，
  因此字节只有在同步之后才可用，而宿主机上较旧的副本可能顶替当前的图片。
  现在只要存在活跃的沙箱，字节就从当前的活跃沙箱读取，
  不会仅仅因为存在持久化的沙箱 ID 就去获取一个替代沙箱；轻量的
  来源信息——精确的 SHA-256 加上源沙箱 ID——会记录在 `viewed_images` 中，而不是
  把图片字节或 base64 写入 checkpoint。报告图片缺失的替代沙箱只有在与记录的大小
  和 SHA-256 都相符时才会回退到同步后的宿主机副本，因此大小相同的过期内容会被
  拒绝；缺失文件的判定对 provider 中立，依据显式的 `__cause__` 链，
  并有意忽略隐式的异常上下文。异步工具调用与模型注入现在会通过
  `run_sync_lifecycle_operation()` 执行阻塞式的沙箱读取，因此取消操作无法在读取
  排空之前拆除沙箱租约清理。
  ([#5306])

- **subagents：** 子智能体在自己的上下文被压缩之后仍保留自己的指令。执行器以
  `system_prompt=None` 构建 agent，并把拼装好的提示作为第一条消息放进
  state，因此其中承载着角色提示、`<report_contract>` 引用规则、验收标准
  说明、技能索引，以及被推迟的 MCP 工具和路由提示——而压缩是按索引裁剪的，
  索引 0 永远落在被摘要掉的部分里。第一次压缩之后的每一次模型调用都是在
  完全没有系统提示的情况下进行的，而摘要也替代不了它，因为它是以隐藏数据
  注入的，权限契约明确告诉模型不要遵从它。现在动态上下文保留会一并挽救
  `SystemMessage`，以及带标签的提醒和最新的用户消息，并保持它们的顺序，
  使提示仍排在最前、且不会被送进摘要器；当提示加上当前请求就是剩下的全部
  内容时，直接跳过压缩，而不是把提示摘要掉。lead agent 不受影响——它的提示
  是请求的 system message，而不是 state 里的一条消息。([#5454])

- **subagents：** 被反复取消的子智能体不再永久占用自己的执行槽位。
  `SubagentExecutionCapacity.slot()` 会在让出之前递增进程级运行计数，
  并在异步上下文管理器的 `finally` 中释放它；但第二次 `Task.cancel()`
  若在释放等待容量锁时到达，就会打断这次清理：任务以取消状态退出，
  而 `_running` 仍处于递增状态。在 `max_running=1` 下，之后每个原生子智能
  体都会排队直到超时或被拒绝，尽管当时并没有任何东西在运行，违反了文档记载
  的不变量——取消与超时会释放队列与槽位归属。现在最后一次释放在自己的任务
  中运行，不受调用方取消的影响，并在取消传播出去之前跨反复取消完成排空。
  ([#5477])

- **worker：** 被委派的子智能体出错不再导致父 run 失败。当子智能体的模型
  调用在重试后仍以错误结束时，执行器报告 `task_failed`，lead agent 仍然
  作答，但 worker 还在根级 `task_running` 自定义事件里看到了
  `deerflow_error_fallback` 标记——每一个都携带一条带 `additional_kwargs`
  的子智能体消息——并据此把父 run 标记为 `error`，错误文本取自子智能体。
  目标延续随之停止，而一次编辑并重跑把线程回滚，丢弃了编辑后的问题和新的
  回答。自定义帧不再参与父级的错误回退检测，而 lead 自身的错误回退仍通过
  `values`、`messages` 和 `updates` 帧送达；现在 lead 完成时父 run 以
  `success` 结束。([#5407])

- **sandbox：** 规范化掩码输出尾部的分隔符，使虚拟路径在 Windows 宿主机上也
  按 POSIX 风格拼写。两个输出掩码器都在输出的正斜杠规范化副本中搜索宿主机
  基路径，却从原始文本里切出匹配到的尾部，因此嵌套的反斜杠得以存活进拼接
  结果，`glob` 结果与被掩码的技能读取会以混合拼写返回，例如
  `/mnt/user-data/workspace/pkg\util.py`。深度为 1 的尾部恰好能干净拼接，
  这正是 Linux CI 从未发现它的原因；现在两处拼接点都会在把尾部接到虚拟
  前缀之前先规范化它。([#5247])

- **sandbox：** 反向解析 Windows 宿主机路径的正斜杠拼写。正向解析以 `/`
  拼写已解析的路径，因为反斜杠会破坏 `\U` 这类 bash 转义序列，但把输出中的
  宿主机路径映射回其 `/mnt/...` 形式的反向扫描器仍把匹配锚定在原生的反
  斜杠基路径上——因此每个在命令输出或智能体写入的文件中回来的正向解析路径
  都无法匹配，把原始宿主机路径、真实用户名和完整目录树泄露给了模型，而不是
  智能体本应引用的容器路径。现在扫描器的匹配与分隔符无关，与沙箱工具早已
  采用的同一份契约一致；在两种拼写重合的 POSIX 宿主机上不受影响。([#5373])

- **sandbox：** 远程 `list_dir` 不再把失败报告为空目录。在缺失路径上执行
  `find ... 2>/dev/null` 只产生空的 stdout，而客户端错误被当作 `[]` 吞掉，
  于是 `ls` 告诉智能体该目录是 `(empty)`——一个已死的沙箱、一个已关闭的
  客户端和一个不存在的路径看上去都像一棵可写的空树，让智能体覆盖已有文件
  或跳过恢复。AIO、E2B、BoxLite、OpenSandbox 和 Tenki 现在会在命令或客户端
  失败时抛出 `OSError`，在什么都没列出时抛出 `FileNotFoundError`，与本地
  沙箱对非目录路径的既有行为一致；真正空的目录仍报告 `(empty)`，而
  `find -H` 让带符号链接的根仍可列出。([#5264])

- **sandbox：** 拒绝不完整的远程 `list_dir` 遍历，而不是把它当作完整结果
  呈现。`find` 对缺失的起始路径、以及对打印了部分条目后无法读取的文件或
  子目录都退出 `1`，而解析器两种情况都接受 `1`——因此一次中途失败的遍历会
  把可见条目当作一次成功的完整列目返回，`ls` 交给智能体的是一棵静默不完整
  的树。仍无条目时的状态 `1` 依旧抛出 `FileNotFoundError`，而只要有任意
  条目的状态 `1` 现在抛出 `OSError`，指出遍历不完整并建议换用更窄的路径，
  与远程 `glob` 早已应用的同一份契约一致。每个共用远程 `list_dir` helper
  的 provider 都无需 provider 侧改动即可继承它。([#5422])

- **sandbox：** 远程 `grep` 与 `glob` 不再把失败报告为“没有匹配”。这些搜索
  丢弃了 stderr，并从 `head` 取管道状态，因此缺失的搜索根、缺失的
  `grep`/`find` 二进制或不可读的目录树会什么都不打印并以 0 退出——而工具会
  告诉智能体 “No matches found”，而本地沙箱在这种情形下报告的是
  `Error: Directory not found`。现在一个共享包装器会记录搜索命令自身的状态：
  根缺失时抛出 `FileNotFoundError`，任何其他失败——包括在已经打印了部分结果
  之后的 `grep` 2 或 `find` 1，因为调用方无法区分部分结果与完整结果——都抛出
  `OSError`，告诉智能体有些路径无法读取。真正的无匹配仍返回 `[]`。E2B、
  OpenSandbox、BoxLite 和 Tenki 在客户端已关闭时也会抛出，而不是返回空。
  ([#5380])

- **sandbox：** 以行为单位报告 `read_file` 的截断，并点明应从哪一行继续。
  该工具按 `sandbox.read_file_output_max_chars`（默认 50,000）做头部截断，
  其标记告诉模型用 `start_line`/`end_line` 继续，但切口是按字符偏移切下的，
  标记也只报告字符计数——因此切口几乎总是落在某一行中间，模型看到的最后
  一行是一个读起来像完整行的片段，且没有任何东西说明该从哪一行继续。
  在被要求对截断后的文件做下一次读取时，三个模型在 15 次尝试中有 0 次选对了
  `start_line`，偏差达几十行甚至上百行。现在切口落在预算允许的最后一个行
  边界上，标记以行为单位陈述位置并给出确切的续读位置，例如
  `[truncated: showing first 743 of 1828 lines (49746 of 155704 chars). Continue with start_line=744]`
  带范围的读取报告的是文件行号，而不是 provider 的切片相对行号。单个超长
  行仍然在字符上限处截断，因为丢掉它会浪费掉大部分预算，此时标记指向
  `bash`，而不是一次无法返回该内容的 `read_file` 调用。([#5474], [#5478])

- **sandbox：** 强制 PowerShell 使用 UTF-8 控制台，使 CJK 工具输出在 Windows
  上不再乱码。命令运行器通过 UTF-8 管道读取器捕获 stdout，但 Windows
  PowerShell 5.1 除非显式切换，否则以遗留的 OEM 代码页写出控制台输出——
  在 zh-CN Windows 上是 GBK——因此每个 CJK 字符到达时都是乱码，而又因为读取
  器是替换无法解码的字节而不是抛错，损坏是静默的。现在每个 PowerShell
  `-Command` 载荷都会在用户命令运行前把 `InputEncoding`、`OutputEncoding`
  和 `$OutputEncoding` 设为 UTF-8。([#5440])

- **sandbox：** 以感知平台的方式校验 Windows 宿主机上托管的 Lark CLI 沙箱
  运行时。该检查要求一个 POSIX 可执行位，而 NTFS 并不保留它，因此每个候选
  都报告 `st_mode & 0o111 == 0`，Gateway 抛出
  `ValueError: Managed Lark CLI sandbox runtime file is not executable`
  ——使托管的 Lark 运行时在 Windows 开发宿主机上、以及把托管的 Linux CLI
  运行时挂载进沙箱的 Windows Docker 宿主机上都无法使用。POSIX 保持严格的可
  执行位契约不变；在 Windows 上，仅限 Linux 的构件改由内容校验，要求各架构
  二进制具备可执行镜像魔数、启动器具备 shebang。([#5442])

- **sandbox：** Docker-outside-of-Docker 沙箱的端口绑定在 Docker Desktop 上
  默认绑定到回环地址。`DEER_FLOW_SANDBOX_HOST` 在 DooD 模式下默认为
  `host.docker.internal`，它在容器内解析为 Docker Desktop VM 网关，而把沙箱
  端口发布到该地址会让宿主机套接字层以 `WSAEADDRNOTAVAIL` 拒绝绑定——因此
  即使启动成功了，第一个沙箱 shell 动作仍以 `ports are not available` 失败。
  当 Docker server 是 Docker Desktop 且未配置
  `DEER_FLOW_SANDBOX_BIND_HOST` 覆盖时，绑定主机现在是 `127.0.0.1`，
  Docker Desktop 会转发它；显式覆盖仍然优先，原生 Linux DooD 不受影响。
  ([#5446])

- **sandbox：** 在取消被当作失败清理之前排空技能同步 worker。默认的
  `sync_agent_skills_async()` 包装器使用裸的 `asyncio.to_thread()`，因此取消
  等待方会在同步的沙箱变更尚未完成时返回，而 `SandboxMiddleware` 随即在
  provider 工作仍在途中时释放执行持有者——破坏了生命周期契约：代表某个
  持有者启动的阻塞工作必须在该持有者离开边界之前排空。现在该包装器改经
  既有的取消栅栏运行，因此对那些自身不对同步与释放做串行化的第三方和基于
  上传的 provider，顺序也能成立。([#5350])

- **frontend：** 让人工输入卡片与请求它的回合待在一起。在多轮对话中，一张
  既有的 `needYourHelp` 卡片可能漂到下一条用户消息下方，于是时间顺序变得
  误导，一个已回答的请求可能读起来像新一轮的一部分。一条提交前的基线消息
  可能被编进新持久化的用户消息之后，一张仅通过 REST 历史确认的卡片可能
  永远进不了 checkpoint 基线，而已经为当前 run 持久化的步骤可能在一次中断
  之后被抬进上一轮。现在基线消息会恢复在待处理的人类消息之前，经 REST
  确认的卡片算作已确立的历史，而当前 run 自身的步骤留在启动它们的消息
  之下。([#4892])

- **frontend：** 在实时内容合并中保留服务端分配的消息位置。流式更新在替换
  消息内容的同时也会丢掉它的 `deerflow_seq`，于是服务端已经定妥的排序被在
  客户端重算并算错——已加载的 `1,3,5` 历史窗口与 `2,5` 的实时尾部合并后
  渲染为 `1,3,2,5`，长线程（历史分页，或压缩之后恢复的对话）会以乱序显示
  其步骤，直到一次刷新。现在内容与位置分开处理，合并、压缩桥接和渲染账本
  共用同一份位置优先级，使上游已排序的结果不会在下游被重新排序，而异常
  序列值（null、字符串、NaN、非整数、非安全整数）永远不会覆盖一个已知位置。
  ([#5293])

- **frontend：** 在增量流重连之后恢复用户的输入。在较晚一个回合期间刷新，
  可能让重连流在当前人类输入进入持久历史 feed 之前先回放 AI 与工具 chunk，
  于是用户的消息短暂消失，其推理步骤被归到上一轮之下。现在活动 run 的输入
  会在加入增量流之前先从 `kwargs.input` 恢复并合并入最新的持久线程状态，按
  id 去重；如果元数据或状态读取不可用，则原样沿用先前的重连路径。([#5428])

- **frontend：** 即使一个智能体的工具组显式为空，也显示它的技能徽章。徽章
  容器的空值合并链停在工具组计数 `0` 上，因此一个声明为 `tool_groups: []`
  且 `skills: ["data-analysis"]` 的智能体在 Agents gallery 中丢掉了徽章——
  尽管显式为空的工具组列表是有效的，并受 Agent API 与 `update_agent` 工具
  支持。现在容器在两个列表中任意一个至少有一项时即显示。([#5326])

- **frontend：** 把 composer 的斜杠技能建议限定到活动智能体。自定义智能体
  对话可以限制自己能激活哪些技能，包括限定为一个显式空列表，但 composer
  仍提供全局的已启用技能目录——于是智能体可能建议一个它无权激活的技能。
  现在建议会经过活动智能体的允许列表过滤，显式空列表被视为没有可用技能，
  而不是在智能体加载期间短暂泄露全局目录；当一份保存的、带有已选技能 chip
  的 composer 草稿被恢复时，也应用同样的限定。([#5451])

- **frontend：** 删除侧边栏会话前先确认。在某个最近会话的菜单中选择 Delete
  会立即移除该对话及其文件，没有任何确认步骤，尽管删除是不可逆的。现在一个
  对话框会点明该对话并警告删除不可逆，聚焦 Cancel，并在 Cancel、Escape 或
  关闭时保持会话完好；删除待处理期间操作被禁用、驳回被阻止，而删除失败会让
  对话框保持打开并带上底层错误，以便用键盘重试。该对话框挂在虚拟化的侧边栏
  行之外，因此一次列表刷新无法在一次部分删除之后移除重试 UI。([#5406])

- **agents：** 让 Custom Agent 设置对话框留在视口内。选择 **Selected
  subagents** 可能使对话框高于窗口，在一条长长的 worker 描述填满嵌套列表时
  把标题、关闭控件和 Save/Cancel 按钮推到屏幕之外。现在头部与操作按钮位于
  单一滚动表单区域之外，子智能体描述显示两行预览，并有可通过键盘访问的展开
  在不移动焦点或改变复选框状态的前提下滚动进视区，而长名称与描述会换行而
  不缩小复选框。([#5458])

- **frontend：** 让 MCP 配置对话框留在视口内。在 Capability Center 中打开
  一份很长的 MCP server 定义会让 JSON textarea 长过窗口，于是居中的对话框
  裁掉了标题、关闭控件和 Save/Cancel 按钮，在较小的窗口上变得难以编辑或
  关闭。现在对话框受视口约束、在桌面上有更多横向空间，长 JSON 在编辑器内部
  滚动，而标题、Close、Save 和 Cancel 留在滚动区域之外，即使在极小的视口下、
  或遇到很长的服务器名称或校验消息时也是如此。([#5492])

- **frontend：** 在那些可点击、却仍显示默认光标而使其可操作性不清晰的交互
  控件上显示指针光标。现在一个全局选择器覆盖原生按钮、`role="button"` 元素、
  下拉菜单项和命令项，排除原生禁用控件和任何标记了 `aria-disabled="true"`
  的元素；生成的 `ui/` 与 `ai-elements/` 组件不受影响。([#4921])

- **frontend：** 中文本地化文档链接。本地化文档中的 MDX 链接与 Nextra 卡片
  此前在改写时并不知道活动的文档语言，于是跟着快速上手链接走的中文读者被
  送到了英文页面。现在本地化文档布局通过 context 提供该语言，链接改写会
  尊重它。([#5275])

- **runtime：** 仅内存部署在计划清理之下保留其 run 历史。`cleanup()` 此前
  无条件淘汰，因此一个按文档默认 `store=None` 构建 `RunManager()` 的内嵌
  消费者会在清理触发时从历史中丢掉已完成的 run——`get(run_id)` 返回 `None`，
  `list_by_thread()` 丢掉该记录，因为这些读取没有持久副本可以回退。现在淘汰
  以存在后端存储为前提，恢复了仅内存模式此前永久保留的行为；有存储支撑的
  manager 仍在宽限期后淘汰。([#5453])

- **events：** 读取含有 U+0085、U+2028 或 U+2029 的 JSONL 事件记录。三个
  读取器都会把这些 Unicode 分隔符当作记录边界来切分，因此携带其中之一的
  记录在读取时会被跳过——这会在重新打开之后复用事件序列号，并把幂等插入
  变成重复。现在线程读取、run 读取与序列恢复都按物理换行切分；既有有效
  文件无需重写。([#5429])

- **events：** 把每线程的 JSONL 写锁一直保留到文件系统工作落定。在其 worker
  释放期间取消一次存储调用会在追加仍在途中时丢掉锁，于是稍后的一次删除
  可能在被取消的追加重建该记录之前就完成，而一个被取消的混合 run 批可能
  回滚掉一次它已经确认的写入。现在被接纳的变更会在传播取消之前，一直持有
  其锁跨过文件 I/O、回滚与簿记，覆盖 `put`、`put_if_absent`、批量写入和两种
  删除方法；排队的调用方仍可在被接纳前取消，无关的线程保持彼此独立。
  ([#5439])

- **events：** 阻止 JSONL 线程变更在一次删除中分裂到两代锁。
  `delete_by_thread()` 在仍持有每线程锁的同时把它从注册表中移除，因此一个
  已排在旧锁上的变更可能与一个稍后为同一线程解析出新建锁的变更并发运行
  ——在紧跟删除边界处出现重叠的序列号分配与文件变更。现在注册表是一个
  `WeakValueDictionary`，且不再弹出该条目，于是持有者与排队的等待者让同一代
  保持存活直到它们排空，之后该条目自行消失。([#5455])

- **channels：** 让渠道的首次线程创建只使用一代锁。清理逻辑在当前创建者
  退出时无条件移除每会话锁，于是一个失败或被取消的创建者会释放并注销自己的
  锁，而一个排队的创建者正通过它进入，一个迟到的到达者还可能装上新锁并发
  进入——两个调用方为同一会话创建 Gateway 线程，靠后的映射写入胜出，相邻的
  消息被拆到被孤立的线程上。现在手工管理的生命周期被替换为既有的、感知等待者
  的键控锁表，于是会话键跨异常和取消保持同一代可发现，空闲键只在最后一个
  参与者离开后才被回收。([#5480])

- **gateway：** 以数据属主、而非授权身份读取一个线程的 run。列表、keyset
  分页和单 run 读取端点按调用方的授权身份过滤 run 行，而 `start_run` 给它们
  盖的是数据身份戳——两者只在本来就是安全的属主取值上重合，因此受信任的
  内部调用方即使在自己有权操作的线程上也总是看到一个空 run 列表和 404，
  而这个症状很容易被误读为 run 丢失。现在内部调用方会跳过每用户存储过滤器，
  而这些端点的线程可见性已经做了授权；浏览器与 API 会话则保持各自确切的每
  用户过滤器；两个消息读取端点有同样的混淆，也以同样方式修正。([#5448])

- **gateway：** 对消息编辑与重新生成的 helper 路径应用同样的数据身份限定。
  那三个 helper 仍在解析授权身份并把它当作数据过滤器传入，因此内部调用方在
  自己有权的线程上 `regenerate/prepare` 与 `edit-regenerate/prepare` 会以 409
  失败。现在它们按与读取端点相同的方式解析自己的过滤器 id，浏览器与 API
  会话则保持先前的每用户过滤器、以及对跨用户 run 的 409。([#5483])

- **conversation：** 让会话读取器的页面留在内联范围内，并说明何时丢掉了
  文本。一个页面此前是靠切掉放不下的最后一条消息来填满其 20,000 字符上限的，
  而被切掉的后缀永远无法翻页取回——六条各 3,500 字符的消息中最旧的一条回来
  时约 2,500 字符，且 `has_more: false`。更糟的是，超出默认 12,000 字符工具
  输出预算的页面会被 `ToolOutputBudgetMiddleware` 外置，于是模型只看到一份
  摘要加上一份源文本的文件副本，而这是在目标线程里。现在页面按实际适用于
  `read_conversation` 的预算来确定大小（每工具覆盖，否则
  `externalize_min_chars`，以及 `fallback_max_chars`），仍以 20,000 文本字符
  为上限，而放不下的一条消息会完整地开启下一页——于是一项运维设置始终当家，
  且 `tool_output.tool_overrides.read_conversation` 只调整这一个工具。现在
  被截断的结果会带上一条提示，要求智能体承认这一省略、并在声称完整覆盖之前
  索取缺失的材料。([#5421])

- **goal：** 在澄清卡片仍打开时停下目标循环。目标评估器只读取人类与 AI
  消息，因此通过 `ask_clarification` 提出的问题——它以工具结果的形式到达
  ——对它不可见；它判定目标未达成，worker 便排入一次隐藏延续，告诉智能体
  继续工作、除非真正被阻塞否则不要问用户。智能体于是按自己的猜测行事，
  包括对 `risk_confirmation` 问题，而卡片就那样在 UI 里等着。现在一次尾部的
  人类输入请求会在评估器运行之前被检测到，并以既有原因
  `blocked:needs_user_input` 让目标退场；用户的回答是一条新的人类消息，于是
  下一次 run 正常评估，而前面没有助手文本的卡片会报告它为何停下，而不是
  `run_failed`。([#5467])

- **client：** 发出后又被后续某个节点改写的 AI 消息，其新增文本现在也能流式送
  出。`LoopDetectionMiddleware`、`TokenBudgetMiddleware`、
  `SafetyFinishReasonMiddleware`、`SubagentLimitMiddleware` 与
  `TerminalResponseMiddleware` 都会在各自的节点里用同一个 id 改写最后一条 AI
  消息，但流只会把首次见到的 id 记下来，之后一律跳过，因此改写从未送达
  `messages-tuple` 消费方：`chat()` 与 headless `--print` 返回的是改写之前的文
  本，而不是终态错误或强制停止提示；TUI 从未显示停止提示或安全提示；模型节点
  之后追加的 `token_usage_attribution` 也始终没到。values 路径现在会为每个 id
  记住最后一次见到的消息对象，并在快照中持有另一个对象时重新检查它，只把新增的
  文本作为又一次 delta 发出，并把新的 `additional_kwargs` 走既有的仅元数据后续
  事件；未变化的消息仍会被跳过，不再重新抽取文本。不会扩展已发送文本的替换则不
  会重新发出。([#5479])

- **mcp：** 并发初始化时 MCP 会话池不再超出容量上限。`MCPSessionPool` 只在会话
  创建开始之前检查 LRU 容量，而由于初始化需要 await，多个不同的 key 可能各自观
  察到还有空余容量、各自进入 `_inflight`，随后在没有二次检查的情况下被提升进
  `_entries`——让持久会话注册表突破 `MAX_SESSIONS`，并连带保留其所暗示的额外子
  进程与连接。现在会话被提升时会原子地重新检查并强制执行容量，提升时的淘汰受害
  者则经由其属主任务生命周期，在注册表锁之外关闭。([#4962])

- **mcp：** 并行的同步 MCP 调用不再互相取消对方的连接。当内嵌客户端向同一个
  stdio server 派发两次同步调用时，每个包装器都跑在自己的事件循环上，而池会把
  兄弟循环上的存活会话与进行中的创建视为过期——把它们取消或关闭，并以
  `CancelledError` 中止某个工具步骤，而不是返回两个结果。已建立的会话与进行中
  的创建现在按 `(server_name, scope_key, owning_loop)` 归键，因此同一循环内的
  调用方仍共享创建与状态，而不同的循环各自独立，每个属主也只回收自己的记录，包
  括在正常的 `asyncio.run()` 关闭之后。同步调用仍使用彼此独立的子进程会话，也
  不获得任何共享的服务端状态。([#5396])

- **web-fetch：** 抽取出的 Markdown 里的相对目标现在会按其来源页面解析。Jina、
  Browserless 与 InfoQuest 原样返回 HTML 中书写的链接，因此位于
  `https://example.com/docs/current` 的页面会产出 `[Next](../next)`，让智能体拿
  不到任何可以继续跟进的 URL。三个 provider 现在都会把请求的 URL 传给共享抽取
  器，由它把锚点与图片目标相对该 URL、或相对首个可用的文档 `<base>` 解析；只改
  写目标属性的取值，而不是序列化另一棵解析树，因此畸形的标记、注释、脚本与属性
  格式都原封不动地保留，并仍以原样到达 Readability.js。fetch 校验、4096 字符的
  输出上限与线程外抽取均未改变，Python 回退路径也保持纯文本行为。([#5310])

- **community：** Firecrawl 的 `web_fetch` 与 `web_search` 工具现在遵循该工具的
  `base_url`。`_get_firecrawl_client` 只读取 `api_key`，因此 `FirecrawlApp` 总是
  回退到 `https://api.firecrawl.dev`——并且由于只要目标是云端 API 而未设置 key，
  SDK 就会抛出 `Error: No API key provided`，自托管的 Firecrawl 无论怎么配置都
  无法访问。`base_url` 现在会作为 `api_url` 转发，让本地的 Firecrawl 无需云端
  key 即可同时服务这两个工具；未配置 `base_url` 的配置仍与原先完全一样地构造客
  户端。([#5392])

- **community：** Tavily 抽取现在从 `web_fetch` 条目而非搜索配置读取凭据。当
  `web_search` 用 Serper、`web_fetch` 用 Tavily 时，fetch 用 Serper 的 key 构造
  客户端，把独立的 Tavily fetch key 完全忽略了。现在每个工具都从自己的条目读取
  `api_key`，并在未提供时回退到 SDK 的 `TAVILY_API_KEY`，与既有的 Exa 辅助函数保
  持一致。只在 `web_search` 下放置共享 Tavily key 的配置，必须同时在
  `web_fetch` 下也设置它，或让两者都依赖 `TAVILY_API_KEY`。([#5496])

- **client：** `DeerFlowClient.stream()` 现在会把流式工具调用只发出一次，并带上
  完整参数。OpenAI 风格的模型把工具名与 id 放在第一个 chunk 里，不带 id 的参数
  片段放在其余 chunk 里，而客户端为每个 chunk 都发出一个 `messages-tuple`
  tool_calls 事件，每个都只依据那一个 chunk 解析——因此完整调用（它确实出现在
  values 快照里）反而因为其消息 id 已在 `streamed_ids` 中而被跳过。工具本身仍以
  正确的参数运行；错的只是事件流，在 TUI 里工具卡片显示的是 `bash` 而详情为空，
  而不是那条命令。现在每个消息从 values 快照只发出一个事件，而非流式模型的完整
  AI 消息与流式文本则不受影响。([#5408])

- **browser：** 浏览器会话的拆除不再随调用方的取消而中断。
  `BrowserSessionManager.close_session()` 会在 await 其关闭之前先把会话从注册表
  中移除，而该关闭又直接 await 私有的 Playwright 循环，因此此刻的取消会穿过
  `asyncio.wrap_future()` 传播到清理逻辑本身——留下浏览器进程与 context 成为孤
  儿，会话却已不在注册表中，也没有属主再来重试。`close_all_sessions()` 在更大规
  模上有同样的属主问题：它先清空整个注册表，因此关闭第一个会话时的取消会让之后
  每个会话都彻底没有安排任何拆除。现在拆除会在任何可取消的 await 之前提交给私有
  循环，并在 `asyncio.shield()` 之后 await，而 close-all 会在其首个 await 之前先
  安排好每个会话，并对组等待加 shield。调用方仍会收到 `CancelledError`；只有已
  经启动的清理的属主身份与它隔离了。([#5444])

- **browser：** 无论工具字段顺序如何都能检测到浏览器依赖。启动期的依赖检测只
  在 `name` 是 YAML 列表项的第一个 key 时才认得该工具名，因此把 `name` 移到
  `use` 或 `group` 之后，工具配置仍能工作，却静默地把 browser extra 从
  `uv sync` 中漏掉，让浏览器工具没有必需的依赖。现在直接的 `name` 字段在工具条
  目中任何位置都能被认得，按缩进追踪可防止嵌套选项内部的名称去启用该 extra，而
  检测器仍保持仅用标准库，因为它运行在依赖安装之前。([#5456])

- **setup：** 同一个 pre-sync extras 检测器现在按 `utf-8-sig` 读取
  `config.yaml`。PyYAML 能接受前导的 UTF-8 BOM，但检测器按纯 `utf-8` 读取该文
  件，把 BOM 留在了第一行上，因此其锚定的章节模式无法认出合法配置的开头章节，
  并漏掉了它声明的 extras——`postgres`、`browser` 与 `ollama` 的检测在其章节位
  于最前时都以同样方式失败，而同一份文件的纯 UTF-8 副本却可以正常工作。
  ([#5504])

- **video：** 把 `--aspect-ratio` 转发进 Gemini Veo 请求。该技能 CLI 接受此旗标
  并传给 `generate_video()`，但 Gemini 分支仅用 `instances` 构造它的
  `predictLongRunning` 请求体，把该值丢掉了，因此无论参数是什么，每次 Veo 请求
  都按 provider 默认比例渲染。现在它作为 `parameters.aspectRatio` 发送。
  ([#5388])

- **channels：** WeCom 的两条对外路径都发送无上限的文本，而 bot 协议把内容上限
  压到 20480 UTF-8 字节，这个门槛一份深度研究报告轻易就能越过。超过上限时，
  `_send_with_retry` 重试三次后放弃：流式路径让回复卡在中途，从未发送过
  `finish=true`；推送路径则把回复整个丢弃。流式回复现在在 UTF-8 字符边界上截
  断，其后带一个可见的截断标记——一个流承载整条回复，因此不会在中途断开——而
  没有可回复帧的主动推送（例如定时任务通知）则按换行边界拆成顺序的 markdown 消
  息，让完整内容仍能送达。两条路径现在都以 UTF-8 字节而非字符来度量载荷。
  ([#5148])

- **channels：** 入站 WeChat（iLink）与 WeCom 媒体在任何大小限制生效之前就已
  被完整下载，而下载目标又是一个直接取自消息 payload、未做任何目的地校验的
  URL，于是一个确实超限的附件会在遭到拒绝之前先把 Gateway 的内存顶上去。两个
  频道现在都会流式传输，一旦超过 `max_inbound_image_bytes` /
  `max_inbound_file_bytes` 就在传输途中中止，而精确的解密后大小检查仍保留为
  第二道防线。入站 `full_url` 被限制为 http/https 加一份按点边界的主机后缀允
  许列表，默认为 `qq.com` 系列与已配置的 CDN 主机，可用
  `channels.wechat.allowed_media_hosts` 与
  `channels.wecom.allowed_media_hosts` 扩展，其中 WeCom COS 门禁固定为已验证的
  Tencent Cloud APPID 形态，WeCom 管理端读取器还有 50 MB 的传输中上限。读取
  器会请求 `Accept-Encoding: identity` 并拒绝任何残留的 `Content-Encoding`，
  因此 httpx 无法在测量之前把压缩过的响应体膨胀到超过上限。格式正确且未超限
  的媒体不受影响；超限或不在允许列表中的媒体现在会被跳过，并附上指明原因的警
  告。([#5225])

- **channels：** 现在单条无法解码的 WeChat 消息不会再拖累同批其余消
  息。`_poll_loop` 在收到整批消息后立刻持久化 `get_updates_buf` 游标，随后逐
  条迭代 `data["msgs"]` 且没有按消息隔离错误，于是只要有一条消息的处理抛出异
  常，现实中的触发因素是损坏或无法解密的附件，例如被截断的加密图片 payload，
  循环就会中断，而游标此时已经越过整批消息。失败消息之后的每条消息都会被永久
  丢弃，下一次轮询也不会重新拉取它们。现在 `_handle_update` 在按消息包裹的
  `try`/`except` 中运行，因此同批消息仍能送达 bus，失败会连同其消息 id 一起
  记入日志，而游标仍会在整批消息全部尝试过之后前进。([#4231])

- **channels：** 当 Discord 客户端线程死亡时，原因是 token 失效或不可恢复的
  关闭，`Client.start()` 会返回，并留下一个已停止但未关闭的事件循环，于是
  `call_soon_threadsafe` 排入了一个永远不会执行的回调，而 `send`、`send_file`
  与 `_get_channel_or_thread` 中那个没有上限的
  `await asyncio.wrap_future(...)` 会永远挂住。每次向已死频道发出的消息都会
  从默认五人的 worker 池里永久占用一个 `ChannelManager` worker，因此区区几条
  消息就能冻结所有 IM 频道的入站处理，而不仅是 Discord。这些跨循环调用现在统
  一经由一个辅助函数，把等待时间限制在 `DISCORD_OUTBOUND_TIMEOUT_SECONDS`（30
  秒），文件上传则另有 `DISCORD_UPLOAD_TIMEOUT_SECONDS`（120 秒），这样缓慢
  的上行链路加上较长的 429 retry-after 就不会取消一次健康的传输，事件循环缺
  失或已停止时则会关闭该协程并立即抛出异常。`DiscordChannel.is_running` 现在
  也要求客户端线程存活，正如 `FeishuChannel` 此前的做法，因此就绪轮询会重启
  频道，而不是把一个已死的频道当作健康；`start()` 失败时，半启动状态的实例现
  在会被停止并丢弃，这样反复的就绪重试就不会在 bus 上累积陈旧的对外监听
  器。([#5227])

- **channels：** Discord 线程映射在线程创建之后于事件循环之外持久化，因此进
  程若在创建与其后台写入之间被杀掉，仍可能丢失最新的映射，并让某个 Discord
  线程在重启后无法访问。`stop()` 现在会把内存中的映射刷写到磁盘，并做了包
  装，使关闭路径永不被阻塞，这是在硬杀窗口之上的一张尽力而为的兜底网，而不是
  新的写入路径。([#5461])

- **channels：** 在 Telegram 频道配置中启用 `rich_messages` 会让每条最终对外
  消息都渲染成一行损坏的单行文本：像 `/help` 这样的命令菜单与普通的错误回复
  都被经 `sendRichMessage` 以 `rich_message.markdown` 发送，而后者会合并单个
  换行，并剥掉菜单所依赖的 `<name>` / `<skill-name>` / `<task>` 尖括号
  token。现在只有 `rich_messages` 已启用 *且* 文本确实包含某种富文本构造，即
  围栏代码块、表格行或分隔行、任务列表、`[text](url)` 链接、粗体、斜
  体、`<details>` 块或 `$$` 数学式时，消息才会以富文本形式发送。该检测器刻意
  保守，要求表格必须让该行以 `|` 开头，因此 `/help` 中像
  `/goal [condition|clear]` 这样的一行永远不会触发它。([#5470])

- **community：** InfoQuest 的 reader、web search 与 image search 调用
  `requests` 时没有设置传输层超时，因此即使配置了远程 crawl 的 `timeout` 字
  段，端点停滞仍会让同步 worker 无限期等待。三处调用点现在共享一个 30 秒的连
  接/读取非活动上限；crawl 超时与导航 payload 字段、成功的解析以及既有的
  `Error:` 返回都未改变。这限制的是非活动时间，而非总墙上时钟时间。([#5315])

- **models：** 请求准入限流器在两次独立的加锁中分别决定立即准入与入队，因此
  一个阻塞型调用方可能观察到下一个许可尚未到期、在入队之前被挂起，随后在许可
  到期而等待队列仍为空时被更新的调用方抢先：新来者拿走了许可，较早的调用方只
  能再等一个间隔，或在 `max_wait_seconds` 较短的情况下超时，而较晚的那个请求
  却成功了。立即准入与 FIFO 入队现在是一次加锁保护的单一决策。非阻塞调用仍会
  快速失败且永不入队，队列化限速、取消、超时、队列容量与无突发行为均未改
  变。([#5459])

- **uploads：** 上传文档的大纲把任何以 `#` 开头的行都当作标题，因此一份在
  `# Real section` 之前有 51 行 `#tag` 的文档会耗尽所有大纲槽位，把真正的章
  节藏起来；缩进四个空格或用制表符的注释会变成假标题，可选的结尾井号也会留在
  标题里。提取器现在按原始行匹配根层级的 ATX 语法，即一到六个井号、空格或制
  表符分隔符或行尾、最多三个前导空格，并在既有的粗体清理之前剥掉合法的结尾井
  号。物理行号、PDF 结构标题、围栏代码排除与标题数量上限均未改变，扫描器仍保
  持有界，而不会变成一个 Markdown 解析器。([#5316])

- **uploads：** 单个 200,000 字符的段落会产出 199,999 字符的上传预览，尽管有
  五行的限制；过长的合法标题也会绕过 50 条的上限，而该上限实际上是上下文大小
  的约束。大纲标题现在统一截断到 200 字符，回退预览文本则截断到 2,000 字符并
  跨所有行，省略标记也计入这些预算。物理行号、短文本、既有的标题与预览数量，
  以及原始文件字节都得到保留；这约束的只是返回的摘要文本，而不是文件扫描内
  存，也不是跨上传的总预算。([#5323])

- **doctor：** 在全新克隆上，先 `make config` 再 `make doctor` 会报出四个错
  误，而其中只有一个是真实的：`config.example.yaml` 提供的 `models:` 键里每
  个条目都被注释掉了，它解析为 `None`，于是 `.get("models", [])` 里的 `[]`
  默认值从未生效，一个宽泛的 `except` 又把由此产生的 `TypeError` 渲染成三条
  `'NoneType' object is not iterable` 检查结果。新用户会在 `make doctor` 本
  应减少困惑的那一刻看到一副安装损坏的样子，而他们其实只是还没有配置任何模
  型。现在当没有配置任何模型时 LLM 检查会跳过，只留下可操作的
  `models configured` 失败及其 `make setup` 提示；一旦配置了模型，一切都不会
  改变。([#5296])

- **scripts：** `detect_uv_extras.py` 从 `config.yaml` 解析 uv extras，使
  `make dev` 不会在每次重启时清掉可选依赖，但它没有针对 Ollama 的规则，于是
  配置了 Ollama 模型时它什么都不返回，`serve.sh` 便运行了不带 `--extra ollama`
  的 `uv sync`，`langchain-ollama` 就从一套能正常工作的环境里被卸载了。随后
  配置的模型会以 `ModuleNotFoundError: No module named 'langchain_ollama'`
  失败，而没有任何线索指向 `make dev` 才是原因，尽管 `make doctor` 刚刚报告
  该包已安装。现在配置 Ollama 模型会让 `make dev` 传入 `--extra ollama`，与
  `database.backend: postgres` 传入 `--extra postgres` 的方式相同；不含 Ollama
  模型的配置不受影响，`config.example.yaml` 中被注释掉的 Ollama 示例也会被正
  确地忽略。([#5318])

- **docker：** 在 Windows Git Bash 上，`make docker-start` 与 `make up` 会无
  条件中止，并报出 `Docker socket not found at /var/run/docker.sock —
  AioSandboxProvider (DooD) will not work.` MSYS2/Git Bash 在该路径下并没有
  物理的 Unix socket，Docker Desktop 使用的是命名管道，尽管守护进程原生支持把
  `/var/run/docker.sock` 挂载进 Linux 容器，因此这项检查永远不可能通过。在
  `MINGW*`、`MSYS*` 与 `CYGWIN*` 下，预检现在改为验证 `docker info` 的连通
  性，而不再要求存在 socket 文件；POSIX 主机在缺少 socket 时仍会快速失
  败。([#5371])

- **deploy：** 在 Windows Git Bash 上，`make up` 会在容器启动阶段失败，报出
  `mkdir C:\Program Files\Git\var: Access is denied.` `scripts/deploy.sh` 导
  出了 `DEER_FLOW_DOCKER_SOCKET=/var/run/docker.sock`，而 MSYS 在调用原生
  `docker compose` 时把这个已导出的值转换成了 Windows 主机路径，于是
  `docker-compose.dood.yaml` 挂载了
  `C:\Program Files\Git\var\run\docker.sock`，守护进程便试图创建主机上并不存
  在的目录。socket 现在保存在一个未导出的局部变量里，正如 `scripts/docker.sh`
  此前的做法；在 Windows Git Bash 上，当该变量持有默认值时会将其 unset，让
  Compose 展开它自己的字面量 `/var/run/docker.sock`；运维人员设置的自定义
  socket 路径仍会照常传入。([#5402])

- **MCP：** 从工作区变更排除内部 stdio 临时目录 `.mcp/tmp`。([#4898])
- **MCP：** 持久任务提交中途取消时同时取消远端任务。([#4933])
- **沙箱：** 接受文档中的 E2B reconciliation 配置字段。([#4772])
- **沙箱：** 按文件、挂载及整个上传过程限制 E2B mount 上传的大小、文件数和时间。([#4812]、[#4842])
- **沙箱：** 保留 E2B 同步文件名尾部空白并容忍越界远端 mtime。([#4861])
- **沙箱：** 配置解析时拒绝 Redis 所有权中的非有限租约时间值。([#4960])
- **沙箱：** 结构化技能读取经沙箱 provider 路径映射解析，与 `ls`/shell 使用同一启用状态投影。([#4792])
- **技能：** moderation scanner 支持 Responses API content block，合法技能管理决策不再误判不可解析。([#4936])
- **记忆：** Honcho 与 Mem0 在配置解析时拒绝非正或非有限的 timeout/字符上限。([#4783]、[#4823])
- **记忆：** 自定义智能体 bootstrap 事实限定到所选智能体 bucket。([#4804])
- **Artifact：** Windows 支持原子保存；读取响应提供 SHA-256 ETag，使普通 HTTP LAN
  等无 `crypto.subtle` 环境也能预览和编辑。([#4629]、[#4865])
- **前端：** 长 run 前后保持会话顺序稳定，用户消息不再重复或落到自身步骤之后，
  mid-run 页面重载后回合步骤也不再出现在触发该 run 的用户消息之前。([#4620]、
  [#4660]、[#4834])
- **前端：** HTML artifact 注入 base href 时不再把 `<header>` 误判为 `<head>`。([#4625])
- **前端：** 落地页案例通过公开只读 `/showcase/` 路由打开。([#4635])
- **前端：** 聊天页按置顶状态排序。([#4643])
- **前端：** Markdown inline code 中的 `<think>` 保持原样，并恢复纯 reasoning 回合的复制按钮。([#4647])
- **前端：** 模型加载失败时显示工作区错误 banner 与重试操作。([#4840]、[#5021])
- **前端：** 后续回合流式输出时仍保留已完成助手消息的复制等操作。([#4844])
- **前端：** Browser Live 重连成功后保持新连接，不再立即拆除并再次重连。([#4951])
- **前端：** 复制 Lark 授权链接时复用 clipboard fallback。([#4767])
- **前端：** 统一使用“DeerFlow”大小写并修复落地页 “What's New” 标题。([#4970])
- **渠道：** 用固定 worker pool 与有界队列限制入站流量，关闭时等待真实跨线程任务。([#4800]、[#4816])
- **渠道：** 飞书、Telegram 与企业微信发送附件时把文件 IO 移到 worker 线程。([#4633])
- **渠道：** Telegram connection identity 查询回到 Gateway 事件循环执行。([#4815])
- **飞书：** 接收文件保持事件循环非阻塞，避免重名覆盖、越界写入，并让单个附件失败不阻塞其余消息。([#4627]、[#4903])
- **钉钉：** 命令分类前剥离前导 `@bot`，群聊中的 `/new` 等命令可被识别。([#4724])
- **Discord：** 渠道停止后不再启动 typing-indicator 循环。([#4752])
- **企业微信：** 序列化 WebSocket 启停并等待 SDK 接收任务真正结束。([#4762])
- **Buzz：** 用持久 seen-id store 丢弃重连后的重复事件。([#4888])
- **Lark：** 沙箱内 CLI lock 目录保持可写，含凭据的 config 根目录仍为只读。([#4701])
- **调度器：** 手动触发也遵守全局 `max_concurrent_runs`，达到上限返回 HTTP 409。([#4769])
- **调度器：** 读取时转换序列化的任务时间戳。([#4785])
- **调度器：** 支持安全的多实例恢复，启动时不会把 peer 的活动 run 当成本地残留；
  通过 `scheduler.multi_instance` 显式启用。([#4713])
- **调度器：** busy 的定时 occurrence 改为进入持久队列而非跳过，由
  `scheduler.queue_timeout_seconds` 限制等待并可跨 Gateway 重启。([#4918])
- **CLI：** headless `--print`、`--json` 与 `--cli` 新增 `--recursion-limit`。([#4615])
- **开发：** backend `make dev` 的 Uvicorn watcher 排除运行时状态，智能体写文件不再重启 Gateway。([#4759])
- **开发：** 诊断脚本按自身位置解析路径，可从任意工作目录运行根诊断命令。([#4736])
- **Docker：** 加固本地与容器启动：`make up` 等待健康检查，允许缺失 `.env`，生产
  环境可写 extensions 配置，运行数据不进入构建上下文，日志命令正确解析 checkout，
  默认回环 origin 可完成 dev setup hydration。([#4658]、[#4806]、[#4852]、[#4853]、[#4956]、[#4959])
- **网关：** 为持久化消息标记服务端权威的 feed 位置，避免历史超过一页且触发上下文
  压缩后，较早的用户消息消失或跳到步骤流中间。([#4696])
- **Lark：** 托管凭据切换时，先清除旧应用的 OAuth 数据再写入替换项，从而保留新
  app secret，后续浏览器授权不再解析到空的 `client_secret`。([#4820])
- **消息：** 移除旧版 `<uploaded_files>` 标签处理：后端将 #4174 之前的写法视为
  普通内容，仅剥离 `<current_uploads>`；前端继续剥离旧标签，确保历史会话仍能干净
  渲染。([#4826])
- **技能：** 在写入门控处拒绝空的 `SKILL.md` description，与 loader 的既有要求
  保持一致；编辑自定义技能时，空 description 不再先写入一个随后被 loader 拒绝、
  从而破坏磁盘技能的文件。([#4867])
- **沙箱：** 将 `bash`、`ls`、`glob`、`grep`、`read_file`、`write_file`、
  `str_replace` 和 `task` 面向模型的 `description` 参数统一改为可选（默认空），
  provider 省略该参数时不再在执行前被拒绝。([#4878])
- **沙箱：** 限制 Windows 命令执行：host 命令在新进程组中运行，超时后通过
  `taskkill /T /F` 终止，避免子进程使调用一直保持打开；输出继续使用现有的
  10 MiB 有界捕获。([#4946])
- **沙箱：** 将 Windows MSYS 路径转换排除限定到安全的虚拟路径前缀，不再全局
  禁用转换，使依赖正常路径转换的 host-native CLI launcher 恢复工作。([#5003])
- **技能：** app config 热重载后重新构建按用户的技能存储，避免其继续绑定到旧配置
  实例中的路径。([#4972])
- **技能：** 解析可移植的 `allowed-tools` scalar 时感知括号，使 `Bash(tvly *)`
  这类条目保持完整；未匹配括号会被拒绝而非静默拆分，参数限定条目保持字面含义，
  不会扩大访问范围。([#4984])
- **智能体：** 规范化 `Command` 结果中返回的 `ToolMessage`，错误 payload 不再默认
  获得成功回执，工具进度追踪也能正确识别。([#4977])
- **config：** `use_previous_response_id` 在 `config.yaml` 的模型条目里是可
  用的；它并非 `ModelConfig` 字段，只经由模型工厂的 `extra="allow"` 透传抵达
  `ChatOpenAI`；但它从未被记录，读起来又像是 `use_responses_api` 的同义词。
  事实并非如此：`use_responses_api` 选择的是端点，而
  `use_previous_response_id` 则把 Responses API 从每轮重放完整历史切换为在服
  务端状态上串接。`config.example.yaml` 中的 OpenAI Responses API 示例新增了
  一行被注释掉的 `use_previous_response_id: false`，并注明它会原样转发给
  `ChatOpenAI`、串接起来的上下文仍按 input token 计费、以及客户端的历史改写
  只在历史被重放时才生效。仅新增注释，没有 schema 变更，没有新的 `ModelConfig`
  字段，也没有 `config_version` 版本号提升。([#5359])

- **MCP：** `get_session` 在 eviction 期间被取消时拆除 in-flight session owner，
  避免调用方取消后泄漏 owner task 或超时后仍保持挂起。([#5008])
- **MCP：** 普通 stdio 工具在 transport 断开后可重新连接：仅当失败的 pooled
  session 仍在注册时将其淘汰，原始错误照常返回且不自动重放，后续重试会启动新的
  子进程。([#5018])
- **MCP：** 持久 MCP 任务轮询发生协议超时时保留 pooled stdio session——408
  并非断开——使任务状态得以保留，下一次轮询不再报告 `task_not_found`。([#5027])
- **MCP：** 在配置边界拒绝无法作为 HTTP header value 传输的凭据（尾部换行或空白、
  非 ASCII），避免 transport 异常回显完整值并将 secret 泄漏到模型上下文、
  checkpoint 和 trace。([#5066])
- **子智能体：** poller 意外退出时清理后台任务条目，提交失败时移除 PENDING registry
  条目，避免失败或崩溃的轮询泄漏条目，或让子智能体在无人管理的情况下继续运行。
  ([#5069])
- **子智能体：** 在提交失败路径停止僵尸 PENDING registry 条目，并直接根据 waiter
  长度计算容量快照中的 queued 数量，避免遍历被其他线程并发修改的 deque。([#5086])
- **渠道：** 将 `ChannelStore` 读取与 mutation 同步，`get_thread_id()`/
  `list_entries()` 不再触发 `dictionary changed size during iteration`。([#5083])
- **Discord：** 强引用 ack-reaction task，并在关闭时将其 drain，避免 GC 静默丢弃
  reaction 或在重启周期之间固定住 channel。([#5049])
- **Buzz：** 将 seen-event 持久化移出事件循环，使用合并的原子写入；写入过程中有
  新事件时保留 dirty generation，并在关闭时等待最终 flush。([#5103])
- **流式传输：** subscriber 使用过期 cursor 重连到空或已 drain 的 stream 时，
  `MemoryStreamBridge._make_gap` 不再触发 `IndexError`。([#5047])
- **上传：** dedupe 文件名时在 UTF-8 code point 边界截断 stem，使其保持在 255-byte
  上限内；两个仅 dedupe suffix 不同的最大长度文件现在都能成功上传，不再导致整个
  batch 失败。([#5059])
- **前端：** 格式化结构化上传错误详情（FastAPI validation issue、对象、数组），
  不再显示 `[object Object]`。([#5071])
- **前端：** 无需重载即可在当前聊天 header、document title、搜索结果和 metadata
  cache 之间同步重命名后的会话标题。([#5045])
- **前端：** 将已选模型名称限制在 selector button 宽度内，过长名称会在 composer
  和 sidecar 中显示省略号，而不再溢出。([#5050])
- **前端：** 长子任务卡片标题截断为单行并提供 tooltip；当委派模型省略
  `description` 而回退到完整 prompt 时，不再撑破聊天布局。([#5136])
- **开发：** 所有平台的前端开发服务器默认使用 Webpack
  （`DEER_FLOW_DEV_BUNDLER=turbo` 可重新启用 Turbopack），避免 Turbopack 在
  macOS 上泄漏 PostCSS worker、在 Windows 上发生 runtime panic。([#5036]、[#5133])
- **脚本：** 使用显式 interpreter（`bash scripts/...`）运行仓库 shell script，
  避免 zip/tarball 下载、`core.fileMode=false` 或非 POSIX 文件系统导致 executable
  bit 丢失后，`make docker-start` 等命令以 `Permission denied` 失败。([#5031])
- **依赖：** 改为依赖重命名后的 `tenki` package，而非已从 PyPI 移除的
  `tenki-sandbox`（import 仍为 `tenki_sandbox`），使干净 checkout 能在
  `make dev`/`uv sync` 时正常解析依赖。([#5087])
- **记忆：** 配置为终止回合的记忆读取现在会抛出与后端无关的 `MemoryReadError`，
  且 prompt 装配阶段不会再吞掉它：严格模式的 OpenViking（`read: raise`）、Mem0
  与 Honcho 读取都会传播；OpenViking 作用域解析失败遵循配置的读取策略；5 秒注入
  deadline 同样遵循该策略（fail-open 时无上下文继续，严格模式以超时为原因抛出）。
  ([#4726])
- **persistence：** 在不启用它的前提下，先加上按线程的 incarnation token 所
  需的存储基础。新增可空的 `threads_meta.incarnation` 与
  `mcp_tasks.thread_incarnation` 列，即一个新的 Alembic head，使任务可以绑定
  到被复用的线程 ID 所属的那个具体线程，因为已删除线程的 ID 可能被后来的线程
  占用，而持久化的 MCP 工作会比这次删除活得更久。新建的线程记录会被赋予一个
  随机的 32 字符 incarnation，并仅在该线程属于任务用户、或是无属主的遗留行时
  才复制进新的 MCP 任务行；查询与插入在 SQLite 上通过标量子查询、在 PostgreSQL
  上通过 share lock 保持原子。目前还没有任何代码读取这些字段，它们也被排除在
  线程与 MCP 任务的 API 响应之外，且两列都可空、无默认值，从而让较旧的二进制
  文件在滚动部署期间仍能继续写入。([#5216])

- **scripts：** 在原生 Windows 上，`shutil.which("pnpm")` 遵循
  `PATH`/`PATHEXT` 的解析规则，可能选中一个通用的 `pnpm` 匹配，即 `.exe` 或
  `.bat`，或位于更早路径上的包装脚本，而不是 npm 安装的 `pnpm.cmd` 包装脚
  本。共享的主机运行器现在会先检查 `pnpm.cmd` 与 `corepack.cmd`，再检查那些
  通用名称，与仓库既有文档中记录的 Windows 命令选择顺序一致；POSIX 上的解析
  顺序未变。([#5305])

- **tests：** 在一位 Windows 贡献者的主机上，后端测试套件跨七个文件失败了 68
  个 shell 脚本测试，而它们没有一个是由于被测代码本身有问题。CreateProcess
  会先搜索 `System32` 再搜索 `PATH`，因此 WSL 的 `bash.exe` 启动器赢下了每一次
  `["bash", ...]` 的派发，却又无法针对 Windows 检出路径运行仓库脚本：在非英语
  Windows 上，它那条本地化的 UTF-16LE 警告会击穿 harness 的管道解码，把真正
  的失败埋在 `TypeError` 背后；`sh` 在 MSYS2 之外并不存在；而
  `dev-entrypoint.sh` 的 `command -v python3` 探测选中的是 Microsoft Store
  的别名存根，它们在执行时会以 49 退出。各套件现在通过一个共享辅助函数来解析
  shell，它镜像了仓库的 Git Bash 包装脚本发现逻辑，并显式拒绝 WSL 启动器与
  Store 存根；在不存在 Git Bash 的地方则干净地跳过。POSIX 与 CI 的行为未
  变。([#5404])

- **tests：** 在 Windows 主机上，跨三个套件的六个测试纯粹因路径分隔符的写法
  而失败。provisioner 的 `join_host_path` 有意保留主机原生风格，甚至有一条显
  式的 `PureWindowsPath` 分支，而 `os.path.normpath` 在那里会把 POSIX 形式的
  输入用反斜杠重新拼写，因此它构造的 `hostPath` 字符串、docker `--mount` 的
  `src=` 写法，以及 review CLI 的 `PYTHONPATH` 都与 POSIX 风格的字面量对不
  上。断言现在会在比较之前先把主机原生的一侧规范化，这在 POSIX 上是空操作，
  因此 CI 的期望值保持逐字节一致；生产行为未变。([#5413])

- **tests：** 技能 request-scoped-secrets 套件中的五个测试在 Windows 主机上
  失败，而两个负向检查则以空洞的方式通过，因为探针里嵌入了 POSIX 语
  法：`LocalSandbox._get_shell()` 在那里解析为 PowerShell，其中 `$VAR` 是一
  个未定义的 PowerShell 变量，会展开为空，因此正向检查永远看不到注入的值，而
  `"secret" not in out` 断言实际上是在与空输出比较。探针现在会按生产实际解析
  出的 shell 的语法来渲染，PowerShell 下为 `$env:NAME`，cmd.exe 下为
  `%NAME%`，POSIX shell 下为 `$NAME`，因此负向检查在 Windows 上真正验证了擦
  除效果，而按调用划分作用域的用例也证明了注入的值确实到达了第一个子进
  程。POSIX 上的输出在形式上未变。([#5415])

- **tests：**
  `test_run_on_isolated_subagent_loop_survives_caller_loop_teardown` 在 CI
  负载下、在无关的 PR 上，以及 `main` 自身上都间歇性失败。竞态出在测试里，而
  不是 `run_on_isolated_subagent_loop` 中：那个辅助函数就是
  `asyncio.run_coroutine_threadsafe`，它的 `concurrent.futures.Future` 只有
  在协程返回之后才会被标记为完成，但测试从协程内部发出信号并立刻断言
  `done()`，于是主线程可能在 future 仍处于 `pending` 时就醒了过来。断言现在
  会在检查 `done()` 之前先阻塞在 `result(timeout=10)` 上；没有引入 `sleep`，
  被测行为也未改变。([#5299])

- **tests：** checkpoint 保留需要一份可执行的声明，说明一次删除绝不可以破坏
  什么；一个只保留最新 N 个的提案就曾在评审显示它会静默破坏分支与时间旅行的
  父链语义之后被撤回。新套件把六种保留场景固定在 memory、SQLite 与 Postgres
  三套 checkpointer 上：完整 schema 与 delta schema 各自按步骤的增长基线；删
  除分支祖先会以 `CheckpointLineageError` 大声失败，而不是静默破坏分支或重新
  生成；删除一个显式的恢复目标会移除恢复入口；挂起的写入是被保留的状态，而非
  垃圾；末尾仅含时长的叶子与叶子的同级分支（真正的分叉路径）可以被安全删除。
  一份配套草案记录了受保护的集合、可证明安全的删除形态，以及带孤儿记账的联合
  表机制，供未来任何 `max_checkpoints_per_thread` 或 TTL 工作对照校
  验。([#5255])

- **记忆：** 删除或清空自定义智能体时会取消缓冲中的记忆抽取，待处理的防抖定时器
  不再复活已删除的按智能体记忆作用域，也不会用过期的待处理更新覆盖新的清空结果。
  ([#5123])
- **智能体：** 当上传（或其他）上下文包装被注入消息文本时，会话标题改用用户的原始
  消息内容生成，标题不再引用服务端注入的 `<current_uploads>` 上下文；仅含附件的
  消息保持 `New Conversation` 兜底。([#4729])
- **智能体：** 分数形式的摘要触发阈值会基于模型声明的 `context_window` 解析（现已
  转换为 LangChain profile），无法解析的分数子句降级为永不触发的阈值并给出告警，
  而不是让整个智能体构建崩溃；百分比风格与非有限的触发值会在配置加载时被拒绝。
  ([#4901])
- **智能体：** 仅当搜索模式无法解析主应用配置时，自定义智能体存储才回退到文件存储
  ——非法配置与缺失配置路径会直接暴露，而非静默切换存储后端——异步智能体路由中的
  store IO 也移出事件循环。([#4952])
- **中间件：** 循环检测的硬停止在整个工具调用批次内生效：选中软告警后不再结束检查
  ，同一响应中较晚跨过运营方配置硬上限的调用会被拒绝，而不是随早前的告警一起放行
  。([#5245])
- **沙箱：** 五个远程沙箱 provider（E2B、OpenSandbox、AIO、Tenki、BoxLite）的
  `list_dir` 与 `glob` 原样返回文件名，不再剥离空白，名称以空格开头或结尾的文件
  不会列在不存在的路径下。([#4980])
- **沙箱：** 共享同一会话沙箱的并发子智能体在进程级执行租约与任务作用域的 AIO
  shell 会话下运行：一个兄弟节点完成不再在他方仍在运行时释放共享沙箱，也不会损坏
  隐式持久会话；发生损坏后会晋升健康的替换会话，而不是继续使用它。([#5134])
- **沙箱：** Bash 工具引导智能体用证据（`uname -s`、`sw_vers`、`uname -a`）检测
  执行环境，而非依赖模型假设；被拒绝的 host 路径会指引它改用纯命令探测或允许的
  虚拟路径，而不是重复被拦截的命令。([#5111])
- **沙箱：** Docker AIO 兼容 capability allowlist 加入 `FOWNER`，启动时会
  `chmod /run/user/1000` 的 AIO 镜像（如 1.11.0）在加固后的默认 capability 下
  可以再次启动，`no-new-privileges` 保持开启。([#5163])
- **沙箱：** 文件追加不再在预读失败时破坏已有内容：E2B 追加只把“文件不存在”类
  错误视为空文件，其他错误直接抛出，不再用追加的尾部覆盖整个文件；AIO 追加改用
  服务端原生 append 模式，完全不需要预读。([#5261]、[#5278])
- **技能：** 技能 Markdown 显式以 UTF-8 读取，默认代码页非 UTF-8 的 Windows 主机
  上，本地化技能不再以 `UnicodeDecodeError` 校验失败。([#4995])
- **MCP：** 运行时配置变更后 MCP 工具缓存可以重新初始化：此前的模块级
  `asyncio.Lock` 绑定到已关闭的事件循环，且初始化标志无同步保护，导致更新后的
  每次调用都以 `Lock is bound to a different event loop` 失败，或在多个 worker
  线程间产生初始化竞态。([#5062])
- **MCP：** 同步包装的 MCP 工具保持 LangGraph `ToolRuntime` 注入（无注解的同步
  包装器现在对 `functools.wraps` 透明），按用户的作用域解析与持久任务提交不再以
  `runtime=None` 运行——此前这会让完成通知 run 落到默认 lead 智能体而非该会话的
  自定义智能体。([#5164])
- **认证：** 重复的 OAuth 身份不再误报“Email already registered”——两类完整性
  冲突已区分——OAuth 身份的部分索引也声明了 `postgresql_where`，Postgres 会按
  意图构建部分索引而非全量索引。([#5026])
- **前端：** 移动端侧边栏触发按钮在普通与自定义智能体欢迎页保持可点击；此前换行的
  （较长的本地化）欢迎文案在相同 `z-index` 覆盖层中可能盖住 header 的可点区域。
  ([#5149])
- **子智能体：** `SubagentResult` 生命周期时间戳在所有写入点都使用带 UTC 的时区，
  遵循仓库统一约定，非 UTC 主机上不再写入本地挂钟时间。([#5153])
- **浏览器：** 后台 live-frame 调度任务保持强引用，GC 不再因回收任务而丢失其
  `finally` 中的 pending guard 清理，Browser Live 视图不再静默停止刷新。([#5155])
- **运行时：** 同一 LangChain run id 的重复 `on_llm_end` 回调只持久化一条
  `llm.ai.response` 事件（重放的 usage 按生成位置合并，首个回调为准），provider
  重发带回 usage 的回调时，追加式消息 API 不再返回重复响应。([#5187])
- **运行时：** completion hook 或任务停止扇出内抛出的取消会先让终态收尾完成——
  扩展 observer 得以运行、流的 END 标记得以发布——然后再重新抛出中断；收尾尾部
  仍可被中断。([#5191])
- **模型：** 被取消的 LLM 调用会释放其持有的熔断器恢复探测（覆盖 provider 执行、
  并发准入与退避），取消后同中间件的后续调用不再看到 `CircuitBreakerOpen`；探测
  所有权按每次调用的 token 加围栏，取消较旧的调用不会释放其他调用的探测。([#5197])
- **运行时：** 内嵌 `DeerFlowClient` 的图缓存在任何授权模式下都按生效用户建立键，
  并在运行时上下文中落实同一用户，顺序复用于不同用户时不再提供用其他用户的 prompt
  与工作区状态装配的图。([#5206])
- **运行时：** 被取消的工作区变更快照捕获会排空已在运行的扫描并清理该 run 的文本
  缓存，不再泄漏 `deerflow-workspace-changes-*` 目录；仅元数据的捕获则立即传播
  取消，不再等待扫描完成。([#5232]、[#5234])
- **持久化：** Gateway 启动时容忍数据库已被迁移到经明确评审的更新版本
  （`0019_thread_incarnations`），使部署更新后仍可回滚到本镜像；其他未知版本、
  空版本表与多行版本表仍然快速失败。([#5219])
- **社区工具：** Tavily Extract 结果缺少 `title` 时回退到结果 URL 或请求 URL 作为
  展示标题，不再因 `KeyError` 丢弃可用页面内容。([#5280])
- **上传：** 上传文档的大纲排除围栏代码块，代码注释与围栏内的粗体示例不再挤占
  50 条标题预算中的真实章节。([#5281])
- **子智能体：** 压缩之后，委派账本会区分“执行完成”与“任务验收”，并保留已完成
  子智能体未满足与未验证验收标准的有界示例，主智能体会修复剩余缺口，而不是把已完成
  的结果当作全部完成。([#5287])
- **开发：** `_pick_python()` 通过 `/usr/bin/env` 校验解释器候选，与前端实际的
  启动方式保持一致；在 Microsoft Store Python 桩能通过 Bash 探测却无法通过
  `env` 的 Windows 上，`make dev` 不再无法启动前端。([#5181])

### 性能优化

- **运行时：** 为 `MemoryRunStore` 按 `thread_id`、`MemoryRunEventStore` 事件按
  `run_id` 建立索引，避免 O(n) 扫描。([#3562]、[#3686])
- **子智能体：** 通过 seen-id 集合对流式 AI 消息去重（O(n²) -> O(n)）。([#3687])
- **沙箱：** `LocalSandbox` 的路径改写正则与本地路径脱敏模式改为按实例缓存，不再
  每次搜索命中都重新编译。([#3648]、[#3713])
- **消息：** 按组为工具调用结果建立索引。([#4411])
- **前端：** 流式渲染按帧预算合并，而非逐 chunk 渲染。([#4425])
- **前端：** 不再在每个流式 chunk 上重新推导消息内容。([#4441])
- **沙箱：** `read_file` 只从沙箱读取请求的行范围，不再先获取整个文件。([#3824])
- **浏览器：** Browser Live 进度帧改用 JPEG 编码，减小传输负载。([#4836])
- **中间件：** 通过 `wrap_model_call` 注入 `view_image` 内容，而非使用进入 checkpoint
  的隐藏消息，避免每张已查看图片最多 20 MB 的 base64 数据同时存在于两个
  checkpoint 中，也避免中断的 run 遗留该 payload。([#5014])
- **前端：** 在流式 chunk 之间缓存已稳定消息的 copy-data 推导结果，不再让每个
  chunk 都为每条已稳定消息重新计算 toolbar/copy 文本。([#5095])
- **运行时：** 限制终态 run 结束后的 Gateway 内存，阻止 GC 后的低水位随已完成
  session 持续上升。([#5112])
- **前端：** 聊天流改为请求 `messages-tuple` + `updates` + `custom`，不再请求完整
  的 `values` 状态快照——重传的历史 `values` 消息约占 SSE 负载的 75%——在本地把
  reducer 事件折叠进渲染状态，完整快照仅保留用于回放缺口恢复。([#5159])

### 安全

- **上传：** 文档转换不再按文件名重新打开上传文件。此前 Gateway 转换的是已提交的文件，嵌入式
  客户端转换的是刚放入线程 uploads 目录的副本，因此沙箱若在此期间把该文件名替换为符号链接，
  宿主文件的内容就会被转换成该线程的 `.md` 配套文件。现在 Gateway 通过自己写入时持有的文件
  描述符，转换 uploads 之外的私有副本；客户端则转换调用方提供的源文件。([#5611])
- **客户端：** `DeerFlowClient.upload_files` 不再写穿符号链接。沙箱可写的 uploads 目录中，
  若在上传文件名或其 Markdown 配套文件名处放置符号链接，嵌入式客户端此前会覆盖链接指向的宿主
  文件并报告成功。现在该文件会被跳过并列入 `skipped_files`，`success` 为 `false`，与 Gateway
  一致；不安全的配套文件会被省略，原上传保留。复制时保留源文件的权限位与时间戳。([#5578])
- **上传：** 删除上传文件时不再跟随符号链接删除另一个文件。沙箱可写的 uploads 目录中若被
  放置符号链接，`DELETE /api/threads/{id}/uploads/{filename}`（以及
  `DeerFlowClient.delete_upload`）此前会删除链接指向的上传文件及其配套 `.md`，却仍报告
  删除的是请求的文件名。现在符号链接返回 404，与上传列表一致；指向 uploads 目录之外的
  链接仍以 400 拒绝。([#5547])
- **前端：** 工具步骤不再把非 Web URL 渲染为链接。思维链面板中的 `web_fetch` URL 与
  `web_search` / `image_search` 结果链接此前绕过了 Markdown 链接使用的协议白名单，
  被提示注入的工具调用可在聊天中放入 `file:` 或系统协议处理程序链接（`ms-msdt:`、
  `vscode:` 等）。现在它们会经过 `isSafeHref`，不安全的 URL 与 Markdown 链接一样显示
  “Unsafe link omitted” 标记；缺少 args 的工具调用或非字符串的 `web_fetch` URL 也不再导致
  消息列表崩溃。([#5526])
- **技能：** 修复公共技能审查门禁中文件可绕过 SkillScan 的缺口。审查分析器此前只把解码为
  文本的文件交给 SkillScan，可执行二进制文件和嵌套压缩包从未被检查；豁免了任意层级
  `evals/fixtures/` 目录下的所有文件；重复的压缩包成员或仅大小写不同的文件名会在扫描前静默
  覆盖先前的文件。现在 SkillScan 会逐字节接收每个文件，仅 eval fixture 的 `SKILL.md` 样本
  仍被豁免，路径冲突会将审查标记为不完整。SkillScan 此前还会跳过含有 NUL 或非 UTF-8 字节
  的代码文件，注释中的一个字节就能让反弹 shell 躲过审查门禁，NUL 字节也会让安装时的静态
  分析被跳过。此类文件现在会报告 `package-undecodable-script` 并照常分析，`CRITICAL`
  命中仍会拦截。SkillScan 的 Mach-O 检测遗漏了安装器会拦截的 32 位小端和 fat 变体；安装器、
  导出校验与 SkillScan 现在共用同一份代码文件与可执行文件魔数定义。审查快照为二进制文件
  新增 `content_base64` 字段。([#5431])
- **提示词注入：** 新增输入净化中间件防御提示词注入，输入护栏中伪造的框架标签会
  被拦截，系统上下文以 `SystemMessage` 注入以隔离角色。([#3662]、[#4155]、[#3661])
- **提示词注入：** 对渲染进模型 prompt 的不可信内容进行 HTML 转义——记忆事实与摘
  要、`SOUL.md`、子智能体描述、技能元数据，以及记忆更新 prompt 中的会话块——并中
  和 `web_capture` 工具结果中的提示词注入标签。([#4028]、[#4119]、[#4137]、[#4157]
  、[#4162]、[#4099]、[#4060]、[#4097]、[#4128])
- **prompt-injection：**对 MindIE 工具响应框架进行转义。该 provider 的
   `_fix_messages` 在把工具调用名称与参数渲染进
   `<tool_call>` / `<function=...>` 标签前会对其进行转义，但把 `ToolMessage`
  包进 `<tool_response>` 的姊妹路径却原样传递文本——而该输出到达时大体未经净化，
  因为工具结果净化器只覆盖其允许列表中的远程内容工具（`web_fetch`、
  `web_search`、`image_search`、`web_capture`），并有意不处理本地
   `bash` / `read_file` 输出以及名称不同的 MCP 工具。因此 `read_file` 结果中一
  个字面的 `<tool_response>` 会提前闭合框架，其后的一切都以仿佛位于工具响应之
  外的方式呈现给 MindIE 模型，于是埋在不可信文件中的负载可以伪造
   `<system-reminder>`。内容现在用 `quote=False` 做 HTML 转义，与工具调用路径
  一致；模型仍会将实体解码回来，因此只有框架受到保护，合法结果的理解方式与之前
  完全一致。([#4253])

- **提示词注入：** 修复两处输入净化绕过。`hide_from_ui` 与人类消息上的
  `name="summary"` 会让 `is_genuine_user_message` 认定该消息由框架写入，从而完全跳
  过净化；现在携带这两者的不可信 run 输入与线程状态写入会在服务端被标记并照常净化，
  调用方再也无法把原样的 `<system-reminder>` 放到 user-input 边界标记之外——而主智能
  体 prompt 正是把边界外的内容声明为可信的框架数据。标记本身会被保留，因此仅用
  `hide_from_ui` 来不显示在对话记录中的消息——引用的会话上下文、sidecar 上下文、保存
  智能体命令、HumanInputCard 回复——行为不变，受信任的内部启动路径也不受影响。净化范围也从"仅最新一轮"扩大到*每一条*真实用户消息：该变换只作用于单次请
  求，因此仅处理最后一轮只能让载荷在一次模型调用中失效，下一轮起就会被原样回放。
  ([#5375])
- **机密：** 从技能环境中清除继承来的密钥环境变量（`MYSQL_PWD`、`REDISCLI_AUTH`
  、缩写形式的 `*_PASS` 与 Postgres 的 `PGPASSFILE`）；请求作用域的密钥对斜杠激
  活与自主调用的技能都会绑定。([#4018]、[#4026]、[#3871]、[#3938])
- **web_fetch：** 针对自托管 provider 的 SSRF 防护。([#3942])
- **护栏：** 空的 allowlist 现在会拒绝所有工具，而非放行（fail open）。([#4067])
- **鉴权：** 全局技能管理接口现在要求管理员权限；旧版 skills 挂载按用户可见性门
  控；artifact 遵循受信任的 `owner-user-id` header；受信任的鉴权主体透传到运行时
  。([#3855]、[#3985]、[#3982]、[#4203])
- **认证：** 在 access-token 生命周期内持久化 `csrf_token` cookie。([#3872])
- **存储：** 不再在 checkpoint 状态中持久化 base64 图片数据。([#4140])
- **MCP：** 拒绝 run metadata 中的旧版 MCP 凭据。([#4448])
- **MCP：** 在配置 API 中限制 stdio launcher 参数与环境变量，防止 allowlist 中的
  `npx`/`uvx` 注册被参数或环境变量转化为任意代码执行。([#4617])
- **认证：** 加固登录后 `next` 路径校验。([#4587])
- **运行时：** 在智能体、上传、ThreadData、记忆与技能中遵循 LangGraph Server 的
  已认证用户身份，并拒绝客户端提供的身份字段。([#4538])
- **前端：** 分离 origin 部署中，模型、工作区变更和 range artifact 请求会发送 session cookie。([#4827])
- **前端：** 恢复自定义 Streamdown rehype 链的净化，artifact Markdown 与记忆设置
  摘要不再能渲染 `javascript:` 链接或 `on*` handler 等恶意 HTML。([#4987])
- **技能：** 投影技能文件改为复制而非 hardlink，沙箱写入不能再修改规范来源；所有
  平台（含 Windows）遇到漂移的投影命名空间都会 fail closed。([#4825]、[#4830])
- **脚本：** support bundle 中任意位置的 secret-shaped key（如 `db_pass`、
  `signing_key`）都会脱敏。([#4242])
- **沙箱：** MCP 来源的工具结果现在会通过与内置网络工具相同的信任边界进行净化，
  恶意或被攻陷的 MCP server 无法再向模型传入伪造的 `<system-reminder>` 或用户输入
  边界标签。([#4839])
- **沙箱：** 加固本地 Docker sandbox container：sandbox host 非 loopback 时，
  发布端口默认绑定 Docker bridge gateway 而非 `0.0.0.0`
  （`DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0` 可恢复广泛绑定）；使用 Docker 默认
  seccomp profile 替代无条件 `seccomp=unconfined`
  （`DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED=1` 可重新启用）；container 还会丢弃
  所有 capability、启用 `no-new-privileges` 并使用有界资源。([#4986])
- **鉴权：** 在无状态 stream/wait endpoint 上强制 run-create 权限
  （`runs:create`）；创建、更新、恢复和手动触发定时任务 mutation 时，同时要求
  `threads:write` 与 `runs:create`。([#5030])
- **鉴权：** 复用持久化 sandbox 前重新检查授权策略，使被撤销的
  `sandbox:execute` grant 在下一次 sandbox-backed 回合立即生效，而不会随缓存的
  sandbox 继续存活。([#5006])
- **技能：** 在 sandbox 文件系统层强制 Custom Agent 技能 allowlist：显式 `skills`
  策略会生成签名的按用户/会话技能视图，带 shell 或文件工具的 Custom Agent 不再能
  读取策略排除的技能。([#5077])
- **run：** GET stream join 上的取消/回滚 action 现在返回
  `405 Method Not Allowed`——取消后继续 stream 应使用 POST——关闭 safe method 上
  被 CSRF middleware 有意豁免的状态变更；不带 action 的 GET join 保持不变。
  ([#5092])
- **Lark：** Windows 上的 Lark CLI 凭据目录强制私有 ACL（仅 Gateway SID 的受保护
  DACL、拒绝 reparse point、基于句柄的遍历），把 POSIX `0700`/`0600` 的保密性
  契约扩展到继承授权、junction 重定向、硬链接别名与 TOCTOU 替换等场景。([#5141])
- **沙箱：** 沙箱子进程环境会清除 `SSH_AUTH_SOCK`——继承宿主机 ssh-agent socket
  会让沙箱内代码用智能体持有的所有密钥签名与认证——除非技能通过 required-secrets
  显式声明。([#5145])
- **Artifact：** XML 产物现在与 HTML、SVG 一样以下载附件形式返回。
  `GET /api/threads/{id}/artifacts/{path}` 此前会在应用源内联渲染 `.xml`、`.xsl`、
  `.rdf` 文件（以及宿主 MIME 数据库映射为 `+xml` 的 `.rss` 等类型），被 prompt
  注入的智能体写出带 XHTML 命名空间 `<script>` 的 XML 后，用户从聊天链接打开即可
  以其会话调用 API。所有 XML MIME 类型（`text/xml`、`application/xml`、`text/xsl`
  及任意 `+xml` 子类型）现均视为主动内容，`.skill` 归档成员同样适用；Artifact
  面板仍通过 Range 请求预览 XML。([#5353])

### 文档

- **文档：** 说明生产 Docker 下 `LocalSandboxProvider` 如何解析
  `sandbox.mounts[].host_path`，并给出 Gateway bind-mount 与配置示例。([#3833])
- **文档：** 说明 Crawl4AI >= 0.9 需要 bearer token。([#4518])
- **文档：** 记录 GitHub 入站去重 TTL 语义及不会被去重的重投递，并收紧测试。([#4274])
- **文档：** 更新智能体 `AGENTS.md` 与 `ARCHITECTURE.md` 指南。([#4817])
- **文档：** 新增 Honcho 记忆后端专门指南，并在 README 加入长期记忆入口。([#4822])
- **文档：** 自定义智能体文档与 API 对齐（中英文 agents / threads / lead-agent
  页面）：必填的 ASCII `name` 请求字段、小写存储、`/api/agents/check` 的名称可用
  性行为，以及不再声称从 `display_name` 自动派生 slug。([#4944])

### 内部改进

- **测试：** 前端单元测试迁移到 rstest，并在 DOM 环境运行 hook 级测试。([#3703]、[#4453])
- **测试：** live client 测试要求显式 opt-in。([#4482])
- **测试：** LLM 错误测试替身不再复用共享 `FakeError`。([#4744])
- **测试：** 工具输出测试用自构造失败条件替代魔法不可写绝对路径。([#4722])
- **测试：** 新增多回合消息流图集成不变量测试。([#3708])
- **测试：** 使用 Monocle Test Tools 新增 trace 行为测试，校验路由、工具调用和 token/时长成本。([#4025])
- **测试：** 覆盖 MCP 层中被动技能的工具可见性。([#4247])
- **测试：** 为感知租约的孤儿恢复增加 SQL 与并发 reconciler 覆盖。([#4427])
- **测试：** 恢复 memory updater 回归测试。([#4490])
- **测试：** 锁定 Gateway offline banner 的 POST logout 行为。([#4506])
- **测试：** 在 SkillScan 测试中记录已知 instance-client 假阴性。([#4644])
- **重构：** 抽取并测试前端 placeholder 检测工具。([#3783])
- **重构：** 合并 E2B client 生命周期 helper，并在 warm-pool 淘汰时复用 kill helper。([#4262]、[#4298])
- **重构：** 命名 E2B capacity ledger 的 meta-field 数量，使 admission offset 明确。([#4764])
- **开发：** blocking-IO detector 的调用图追踪 self/cls 属性链和本地别名。([#4200])
- **CI：** 发布 lark-cli-init 与 lark-broker 镜像。([#4558])
- **开发：** host 侧 pnpm 调用统一经带 Corepack fallback 的 runner。([#4405])
- **基准：** 新增隔离的 checkpoint channel-mode 基准，对比 `full` 与 `delta` 的延迟、存储和回放。([#4395])
- **deps：** 升级 `cryptography` 49.0.0 -> 50.0.0、`postcss` 8.4.31 -> 8.5.25、
  `h2` 4.3.0 -> 4.4.1、`langgraph-checkpoint-sqlite` 和
  `langgraph-checkpoint-postgres` 3.1.0 -> 3.1.1、`nanoid` 5.1.6 -> 5.1.16、
  `h3` 1.15.6 -> 1.15.9，以及 `next` 16.2.11 -> 16.3.3。其中 `next` 的升级修复
  了两条未经身份验证的远程代码执行公告，一条位于 Image Optimization API 的
  AVIF 路径，一条影响部署在 Windows 上的服务器；
  `h3` 则阻止经过双重编码的 `.` 段越出静态路由目录。
  ([#4211], [#4681], [#4683], [#4737], [#4738], [#4747], [#4748], [#5377])

- **依赖：** 升级 `cryptography` 49.0.0 -> 50.0.0、`postcss` 8.4.31 -> 8.5.25、
  `h2` 4.3.0 -> 4.4.1、两个 `langgraph-checkpoint-*` 3.1.0 -> 3.1.1，以及
  `nanoid` 5.1.6 -> 5.1.16。([#4681]、[#4683]、[#4737]、[#4738]、[#4747]、[#4748])
- **基准：** 在 `backend/scripts/benchmark/deermem_eviction/` 下新增可复现的混合
  memory eviction 评测，为 #4789 策略提供按构造实现 blind 的确定性 grader。
  ([#4810])
- **基准：** 在 checkpoint benchmark 中同时测量 Postgres checkpoint/blob/write
  的存储增长，并与内存和 SQLite 对照。([#5051])
- **测试：** 将 `tests/blocking_io/` 从 `make test` 中排除；专用的
  `make test-blocking-io` suite（及其 CI workflow）仍是该目录的 owner。([#5105])
- **重构：** 在五个远程 sandbox provider 间共享 sandbox identity 推导和 acquire
  serialization（RFC #4741），替换五张会随进程生命周期无限增长的 provider 专用
  lock table；每个 provider 的 golden vector 保证推导出的 id 逐字节一致。([#5089])
- **CI：** 后端单元测试 workflow 拆分为四个并行分片——各自独占 runner 与隔离的
  Postgres/Redis——使用 `pytest-split` 与提交的时长基线，基线缺失时直接失败；
  `make test` 仍是完整的离线套件入口。([#5137])
- **开发：** Playwright `webServer` 的 Next.js 改经 `pnpm exec` 启动，Windows 的
  E2E 运行可解析平台对应的包二进制，不再因无扩展名的 POSIX shim 失败。([#5185])
- **测试：** Windows 上跳过 POSIX mode-bit 技能权限断言（`chmod` 契约在该平台不可
  观测），使 Windows 贡献者可以获得绿色的后端套件基线。([#5244])

## [2.0.0] — 2026-06-15

DeerFlow 2.0 是围绕"超级智能体"框架的彻底重写，核心包含子智能体、持久化记忆、
沙箱执行以及可扩展的技能（Skill）/工具系统。本版本与 1.x 系列**没有共享代码**，
原有的 Deep Research 框架仍在
[`main-1.x` 分支](https://github.com/bytedance/deer-flow/tree/main-1.x)上维护。

本次发布关闭了
[2.0.0 里程碑](https://github.com/bytedance/deer-flow/milestone/1)，
自首个 2.0 里程碑标签以来累计合并 **180 个 Pull Request**。

### ⚠ 不兼容变更（Breaking Changes）

- **harness：** 从 `RunStore` 重新加载历史 run，并持久化"已中断（interrupted）"
  状态。run 的取消 / 多任务调度语义现在要求拥有该 run 的 worker 上具备可用的
  RunStore；跨 worker 的取消请求将返回 `409`，不再静默"伪成功"。([#2932])

### 新增

#### 智能体与运行时
- **智能体：** 自定义智能体支持自我更新，并按用户隔离 —— 智能体可在普通对话中
  持久化对自身 `SOUL.md` / `config.yaml` 的修改。([#2713])
- **循环检测：** 支持配置开关，并可按工具维度覆盖触发频率。([#2586]、[#2711])
- **循环检测：** 警告注入延后执行，避免与工具调用生命周期错位。([#2752])
- **运行：** 将 `model_name` 从 gateway 请求一直透传到运行时与持久化层（SQLite
  存储）。([#2775])
- **子智能体：** 通过终态任务事件，把子智能体的 token 用量流式上报到 header。
  ([#2882])
- **记忆：** 新增 `memory.token_counting` 配置，支持在受限网络环境下禁用
  tiktoken。([#3465])
- **建议：** AI 追问（follow-up）建议改为可选。([#3591])

#### 模型与集成
- **模型：** 新增 StepFun 推理模型适配器。([#3461])
- **社区工具：** 新增 Brave Search 网络检索工具。([#3528])
- **渠道：** Discord 增加"仅响应 mention"模式、话题路由（thread routing）以及
  正在输入指示。([#2842])
- **IM：** 新增"用户自有 IM 渠道连接"——用户可以在运营方配置的 bot 之上，绑定
  自己的 Slack / Telegram / Discord / 飞书 / 钉钉 / 微信 / 企业微信 账号。
  ([#3487])
- **模型：** 新增 MiMo 推理内容（reasoning content）的补丁支持。([#3298])
- **模型：** 新增 MiniMax provider，用于图像 / 视频 / 播客类技能，并新增"音乐
  生成"技能。([#3437])
- **社区工具：** 新增 SearXNG 与 Browserless 的网络检索 / 抓取工具。([#3451])
- **社区工具：** 为 `image_search` 新增 Serper Google 图片 provider。([#3575])
- **渠道：** Telegram 智能体回复改为就地编辑占位消息的方式流式输出。([#3534])

#### 可观测性
- **追踪：** LangGraph 追踪名设置为 `lead_agent`（自定义智能体则使用其
  `agent_name`），让 Langfuse / LangSmith 中的 trace 更清晰。([#3101])
- **前端：** 优化 token 用量的展示模式。([#2329])
- **默认值：** 默认开启 token 用量统计。([#2841])
- **默认值：** 提高默认的上下文摘要触发阈值。([#3174])
- **追踪：** 把子智能体的 span 归属到父线程的 Langfuse trace 上。([#3611])

#### 技能
- **技能：** 新增 `blocking-io-guard` 技能，用于阻塞 IO 排查与运行时锚点。
  ([#3503])
- **技能：** 新增面向维护者的 issue 与 PR 工作流技能。([#3554])
- **技能：** 增强维护者编排（orchestrator）的评审工作流。([#3606])

### 性能优化

- **harness：** 把 thread 元数据过滤下推到 SQL，不再在 Python 侧后过滤。
  ([#2865])
- **运行时：** 为 run 增加 `thread_id` 索引，避免 `RunManager` 中的 O(n) 扫描。
  ([#3499])
- **运行时：** 为 `MemoryRunEventStore` 中的消息建立索引，避免 O(n) 扫描。
  ([#3531])
- **持久化：** 按类缓存 `Base.to_dict` 的列反射结果。([#3654])
- **沙箱：** 加快 glob/grep 遍历中的 `should_ignore_name` 判断。([#3657])

### 安全

- **上传：** 拒绝指向符号链接的上传目标。([#2623])
- **上传：** 在 Windows 上支持基于符号链接保护的安全上传。([#2794])
- **MCP：** 在 MCP 配置接口的响应中对敏感字段进行脱敏。([#2667])
- **MCP：** 加固 MCP 配置接口对异常输入的处理。([#3425])
- **认证：** 拒绝跨站点（cross-site）的认证 POST 请求。([#2740])
- **网关：** 限制 skill artifact 预览的解压上限，避免被 zip-bomb 类构造滥用。
  ([#2963])
- **沙箱：** 仅在 aio（DooD）沙箱模式下挂载宿主机的 Docker socket。([#3517])
- **沙箱：** 默认不再 bind-mount 宿主机的 CLI 认证目录。([#3521])

### 修复

#### 运行时、网关与持久化
- **运行时：** rollback 恢复的 checkpoint 现在能够覆盖更新的 checkpoint。
  ([#2582])
- **运行时：** 持久化 run 的消息摘要。([#2850])
- **运行时：** 限制 `write_file` 执行失败时上报的观测信息长度，避免失败 trace
  撑爆上下文。([#3133])
- **运行时：** 加锁保护同步单例的初始化与 reset 路径。([#3413])
- **运行时：** 为 run events 移除 PostgreSQL 上不必要的聚合
  `FOR UPDATE`。([#2962])
- **运行：** gateway 重启后从持久化存储中恢复历史 run。([#2989])
- **网关：** threads 接口返回 ISO 8601 格式的时间戳。([#2599])
- **网关：** 对已经处于 interrupted 状态的 run，cancel 接口幂等返回。
  ([#3058])
- **网关：** 将 `stream_existing_run` 拆分为按 HTTP 方法区分的多个路由，确保
  OpenAPI `operationId` 唯一。([#3228])
- **事件：** 序列化结构化的 DB event 内容。([#2762])
- **持久化：** SQLite 后端的存储统一返回带时区的时间戳。([#3130])
- **持久化：** 复用 token 用量按模型分组的 SQL 表达式。([#2910])
- **运行：** 忽略已过期的 run reconnect 冲突。([#3284])
- **nginx：** 把 CORS 策略下放到 gateway 的 allowlist，避免双重应用。
  ([#2861])
- **持久化：** 修复运行时 journal 中 run 生命周期事件的记录。([#3470])
- **网关：** 在无状态（stateless）run 接口上强制校验 thread 归属。([#3473])
- **运行时：** 通过 SSE values 事件把 interrupt 透传给 LangGraph SDK。([#3605])
- **序列化：** 从流式 values 事件中剥离 base64 图片数据。([#3631])
- **历史：** 从 REST 接口响应中剥离 base64 图片数据。([#3535])
- **网关：** token 用量归因到实际使用的模型。([#3658])

#### 智能体、子智能体与中间件
- **子智能体：** 让"子智能体超时"成为原子化的终态。([#2583])
- **子智能体：** 工具与中间件按 model 覆盖（model override）来构造。([#2641])
- **子智能体：** 把 `system_prompt` 与 skills 合并到单条 `SystemMessage`。
  ([#2701])
- **子智能体：** 子智能体与父 run 的 checkpointer 隔离。([#3559])
- **智能体：** `update_agent` 与 `setup_agent` 一致，遵循 `runtime.context` 的
  `user_id`。([#2867])
- **智能体：** 解决 `TodoMiddleware` 中 `todos` 通道的类型冲突。([#3200])
- **智能体：** 把自定义智能体路由中的阻塞文件 IO 移出事件循环。([#3457])
- **智能体：** 新智能体的 bootstrap 流程保持在用户作用域内。([#2784])
- **循环检测：** 注入 warn 时仍保持 tool-call 配对。([#2725])
- **中间件：** 同步原始 tool-call 元数据。([#2757])
- **中间件：** dangling 配对中间件正确处理非法 tool call。([#2891])
- **中间件：** 防止 todo 完成提醒消息泄漏到 IM 渠道。([#2907])
- **中间件：** 调用模型前先把 tool result 的相邻关系规范化。([#2939])
- **智能体：** `resolve_agent_dir` 要求存在 `config.yaml`，从而跳过仅含记忆的
  目录。([#3481])
- **智能体：** 在 context / configurable 间同步 `agent_name`，并拒绝空的
  soul。([#3553])
- **中间件：** 把 `UploadsMiddleware` 中的上传扫描移出事件循环。([#3311])
- **中间件：** 把记忆注入移出事件循环，避免 tiktoken 造成阻塞。([#3411])
- **中间件：** 针对非挂载型沙箱，把超限的工具输出外置到沙箱中。([#3417])
- **中间件：** 在中间件 state 中保留 sandbox reducer。([#3629])
- **子智能体：** general-purpose 的 `max_turns` 提升到 150，默认超时提升到 30
  分钟。([#3610])

#### 记忆与追踪
- **记忆：** 用常驻事件循环替换短生命周期的 `asyncio.run()`。([#2627])
- **记忆：** 队列化的 memory 更新按智能体维度隔离。([#2941])
- **记忆：** 解析被外层包裹的 memory 更新 JSON 响应。([#3252])
- **追踪：** 把 `session_id` 与 `user_id` 透传到 Langfuse trace。([#2944])
- **追踪：** 修复中文 memory trace 信息显示为 unicode 转义序列的问题。
  ([#3104])

#### 工具、沙箱与 MCP
- **MCP：** 修复 MCP 配置中列表型变量的环境变量解析。([#2556])
- **模型：** Codex 的 token 用量记录到 `usage_metadata`。([#2585])
- **沙箱：** 在 `RemoteSandboxBackend` 中补上 `list_running`。([#2716])
- **沙箱：** Windows / Git Bash 下关闭 MSYS 路径转换。([#2766])
- **沙箱：** 沙箱就绪轮询不再阻塞事件循环。([#2822])
- **沙箱：** `Sandbox` API 边界统一遵守 `/mnt/user-data` 契约。([#2881])
- **沙箱：** Provisioner 的 PVC 数据按用户隔离。([#2973])
- **沙箱：** 合并幂等的沙箱状态更新。([#3518])
- **工具：** 引入 `Runtime` 类型别名，消除 Pydantic 序列化告警。([#2774])
- **工具：** 在重入式 `get_available_tools` 调用之间保留 `tool_search` 的提升
  状态。([#2885])
- **harness：** 为同步客户端封装仅异步可用的 config 工具。([#2878])
- **harness：** 同步客户端可用所有原本仅异步的工具（统一封装）。([#2935])
- **工具检索：** 通过移除 ContextVar，可靠地隐藏延迟加载的 MCP schema。
  ([#3342])
- **检索：** 修复 DDGS 的维基百科区域处理。([#3423])
- **web_fetch：** 在受限网络环境下为 Jina reader 支持代理。([#3430])
- **沙箱：** 通过 `Command` 持久化懒加载获取到的沙箱状态。([#3464])
- **沙箱：** 修复 AIO 沙箱缓存被陈旧复用的问题。([#3494])
- **沙箱：** 在使用全新 id 重试前先创建 shell session。([#3577])
- **沙箱：** 不再把字符串字面量路径片段误判为不安全的绝对路径。([#3623])
- **沙箱：** `read_file` 命中二进制文件时返回可操作的提示信息。([#3624])
- **MCP：** 让 stdio MCP 产出的文件可通过虚拟沙箱路径解析。([#3600])
- **MCP：** 在设置页的工具列表上展示"需要管理员权限"的状态。([#3533])
- **MCP：** 新增工具缓存重置接口。([#3602])
- **上传：** 修复上传文件大小的接口契约。([#3408])

#### 技能与渠道
- **技能：** 强制校验 `allowed-tools` 元数据。([#2626])
- **技能：** 在各聊天渠道下加固 `/skill` 斜杠激活。([#3466])
- **技能：** 修复自定义 skill 安装时的权限问题。([#3241])
- **渠道：** Gateway 的命令请求需要鉴权。([#2742])
- **技能：** SKILL.md 出现 YAML 错误时，展示出错行号与引号提示。([#3335])
- **技能：** 把技能压缩包的安装移出事件循环。([#3505])
- **渠道：** 提取回复时忽略隐藏的控制消息。([#3270])
- **渠道：** 渠道重启时重新加载配置。([#3514])
- **渠道：** 暴露企业微信（WeCom）WebSocket 连接失败的信息。([#3526])
- **渠道：** Discord 上传完成后关闭文件句柄。([#3561])
- **渠道：** 用户自有 IM 消息要求绑定身份。([#3578])
- **渠道：** IM 文件与辅助命令限定在 owner 作用域内。([#3579])
- **渠道：** 以运行时的 provider 状态为权威来源。([#3580])
- **渠道：** 加固运行时凭证管理接口。([#3581])
- **渠道：** 让渠道连接流程可确定（deterministic）。([#3582])
- **渠道：** 集中各渠道共享的重试辅助逻辑。([#3583])
- **渠道：** 增加运行态的防护约束（operational guardrails）。([#3584])
- **渠道：** 按相等性（equality）退订渠道监听器。([#3608])

#### 认证
- **认证：** 用缓存响应替换 setup-status 接口的 429 限流。([#2915])
- **认证：** 自动生成的 JWT secret 持久化保存，重启后仍可用。([#2933])
- **认证：** 对齐"认证禁用（auth-disabled）"模式与 mock 历史加载行为。
  ([#3471])

#### 前端
- **前端：** 在 prod 模式下恢复 `getGatewayConfig` 的 `localhost` 兜底。
  ([#2718])
- **聊天：** 修复新会话第一条用户消息被吞掉的问题。([#2731])
- **前端：** header 总计 token 数采用后端线程级 token 用量。([#2800])
- **前端：** 异步 chat submit 完成后再清空输入框。([#2940])
- **前端：** 修复登录页闪烁与 ResizeObserver 死循环。([#2954])
- **前端：** 对恢复出的会话消息去重。([#2958])
- **前端：** 避免乐观渲染产生重复的用户消息。([#3002])
- **前端：** 流式中的 assistant 消息不再展示复制按钮。([#3176])
- **前端：** 新建 thread 后立即在侧边栏显示。([#3283])
- **前端：** 新建会话的 thread 消息相互隔离。([#3508])
- **前端：** 限制深层嵌套列表的缩进，避免渲染崩溃。([#3393]、[#3570])
- **token 用量：** token 用量按 message id 去重聚合。([#2770])
- **前端：** 剪贴板复制回退到 Streamdown。([#3397])
- **前端：** 移除用 Backspace 删除 prompt 附件的快捷键。([#3410])
- **前端：** 把记忆设置的工具栏重排为两行。([#3433])
- **建议：** 解析追问问题前先剥离内联的 `<think>` 推理内容。([#3435])
- **前端：** 追问建议被禁用时不再发起请求。([#3599])
- **前端：** 工作区会话列表在超过 50 个 thread 后分页加载。([#3485])
- **前端：** 避免长串不可断行文本导致用户消息气泡溢出。([#3488])
- **前端：** SSR 鉴权探测无法连通 gateway 时仍保持工作区可交互。([#3495])
- **前端：** 用户消息按纯文本渲染，并限制引用（blockquote）嵌套层级。
  ([#3502])
- **前端：** 删除后重置当前激活的会话。([#3519])
- **前端：** 优化移动端工作区布局。([#3646])
- **前端：** 多段（multi-part）AI 消息渲染完整内容。([#3649])

#### 构建、部署、脚本与配置
- **打包：** 新增 `postgres` extra 以支持 store / checkpointer，并完善安装
  说明。([#2584])
- **harness：** 运行时路径以项目根目录为基准解析。([#2642])
- **Docker：** 让 nginx 在每次请求时再解析 upstream 名称。([#2717])
- **Docker：** 把 Gateway 默认改为单 worker，避免多 worker 模式下出现异常。
  ([#3475])
- **脚本：** `make dev` 重启时保留 `uv` extras。([#2767]、[#2754])
- **脚本：** 停止时清理本地 nginx。([#3005])
- **部署：** 没有 `python3` 时，secret 生成回退到 `python` / `openssl`。
  ([#3074])
- **配置：** 让 reload boundary 在代码层面可发现。([#3144]、[#3153])
- **replay-e2e：** 重放 fixture 按调用方与会话作为 key。([#3453])
- **安装向导：** 更新 LLM provider 向导的默认值。([#3421])
- **配置：** 把 `config.yaml` 中为 null 的列表字段归一为空列表。([#3434])
- **脚本：** gateway reload 时排除运行时状态目录。([#3426])
- **脚本：** 在 uvicorn 的 reload-exclude 生效前先创建 backend/sandbox 目录。
  ([#3460])
- **脚本：** 修复 `make start-daemon` 之后无法用 `make stop` 正确停止
  next-server 的问题。([#3498])
- **Makefile：** 修复 per-commit hooks 的安装。([#3569])
- **replay-e2e：** 重放匹配改为按会话，而非使用当前系统 prompt。([#3436])

### 变更

- **provider（重构）：** 各 provider 间共享 assistant payload 的回放匹配逻辑。
  ([#3307])
- **lead-agent（重构）：** 把 `build_middlewares` 改为 public，去掉最后一个跨
  模块的私有导入。([#3458])
- **todo（重构）：** 移除未使用的完成提醒计数器。([#3530])

### 文档

- 补充 blocking-IO 检测的使用与维护说明。([#3233])
- 清理文档中残留的"独立 LangGraph 服务器"相关内容。([#3301])
- 在 PR 模板与 CONTRIBUTING 中补充 AI 辅助声明。([#3398])
- 补充自定义 AIO 沙箱镜像的文档。([#3548])

### 内部改进

- **开发：** 新增 async / thread 边界检测器。([#2936])
- **运行时：** 增加 lifecycle 端到端测试覆盖。([#2946])
- **Windows：** 后端 Makefile 各 target 加入 `PYTHONIOENCODING` 与
  `PYTHONUTF8`。([#3069])
- **blocking-io：** 检测器以"显式失败（fail-loud）"方式解析仓库根目录，并提供
  共享 CLI 入口。([#3512])
- **运行时：** 为 `JsonlRunEventStore` 的异步 IO 增加 Blockbuster 运行时锚点。
  ([#3313])
- **CI：** 统一 PR / issue 打标签逻辑，修复 reviewing 任务的崩溃与标签抖动。
  ([#3455])

[2.0.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.0.0

[#2329]: https://github.com/bytedance/deer-flow/pull/2329
[#2556]: https://github.com/bytedance/deer-flow/pull/2556
[#2582]: https://github.com/bytedance/deer-flow/pull/2582
[#2583]: https://github.com/bytedance/deer-flow/pull/2583
[#2584]: https://github.com/bytedance/deer-flow/pull/2584
[#2585]: https://github.com/bytedance/deer-flow/pull/2585
[#2586]: https://github.com/bytedance/deer-flow/pull/2586
[#2599]: https://github.com/bytedance/deer-flow/pull/2599
[#2623]: https://github.com/bytedance/deer-flow/pull/2623
[#2626]: https://github.com/bytedance/deer-flow/pull/2626
[#2627]: https://github.com/bytedance/deer-flow/pull/2627
[#2641]: https://github.com/bytedance/deer-flow/pull/2641
[#2642]: https://github.com/bytedance/deer-flow/pull/2642
[#2667]: https://github.com/bytedance/deer-flow/pull/2667
[#2701]: https://github.com/bytedance/deer-flow/pull/2701
[#2711]: https://github.com/bytedance/deer-flow/pull/2711
[#2713]: https://github.com/bytedance/deer-flow/pull/2713
[#2716]: https://github.com/bytedance/deer-flow/pull/2716
[#2717]: https://github.com/bytedance/deer-flow/pull/2717
[#2718]: https://github.com/bytedance/deer-flow/pull/2718
[#2725]: https://github.com/bytedance/deer-flow/pull/2725
[#2731]: https://github.com/bytedance/deer-flow/pull/2731
[#2740]: https://github.com/bytedance/deer-flow/pull/2740
[#2742]: https://github.com/bytedance/deer-flow/pull/2742
[#2752]: https://github.com/bytedance/deer-flow/pull/2752
[#2754]: https://github.com/bytedance/deer-flow/pull/2754
[#2757]: https://github.com/bytedance/deer-flow/pull/2757
[#2762]: https://github.com/bytedance/deer-flow/pull/2762
[#2766]: https://github.com/bytedance/deer-flow/pull/2766
[#2767]: https://github.com/bytedance/deer-flow/pull/2767
[#2770]: https://github.com/bytedance/deer-flow/pull/2770
[#2774]: https://github.com/bytedance/deer-flow/pull/2774
[#2775]: https://github.com/bytedance/deer-flow/pull/2775
[#2784]: https://github.com/bytedance/deer-flow/pull/2784
[#2794]: https://github.com/bytedance/deer-flow/pull/2794
[#2800]: https://github.com/bytedance/deer-flow/pull/2800
[#2822]: https://github.com/bytedance/deer-flow/pull/2822
[#2841]: https://github.com/bytedance/deer-flow/pull/2841
[#2842]: https://github.com/bytedance/deer-flow/pull/2842
[#2850]: https://github.com/bytedance/deer-flow/pull/2850
[#2861]: https://github.com/bytedance/deer-flow/pull/2861
[#2865]: https://github.com/bytedance/deer-flow/pull/2865
[#2867]: https://github.com/bytedance/deer-flow/pull/2867
[#2878]: https://github.com/bytedance/deer-flow/pull/2878
[#2881]: https://github.com/bytedance/deer-flow/pull/2881
[#2882]: https://github.com/bytedance/deer-flow/pull/2882
[#2885]: https://github.com/bytedance/deer-flow/pull/2885
[#2891]: https://github.com/bytedance/deer-flow/pull/2891
[#2907]: https://github.com/bytedance/deer-flow/pull/2907
[#2910]: https://github.com/bytedance/deer-flow/pull/2910
[#2915]: https://github.com/bytedance/deer-flow/pull/2915
[#2932]: https://github.com/bytedance/deer-flow/pull/2932
[#2933]: https://github.com/bytedance/deer-flow/pull/2933
[#2935]: https://github.com/bytedance/deer-flow/pull/2935
[#2936]: https://github.com/bytedance/deer-flow/pull/2936
[#2939]: https://github.com/bytedance/deer-flow/pull/2939
[#2940]: https://github.com/bytedance/deer-flow/pull/2940
[#2941]: https://github.com/bytedance/deer-flow/pull/2941
[#2944]: https://github.com/bytedance/deer-flow/pull/2944
[#2946]: https://github.com/bytedance/deer-flow/pull/2946
[#2954]: https://github.com/bytedance/deer-flow/pull/2954
[#2958]: https://github.com/bytedance/deer-flow/pull/2958
[#2962]: https://github.com/bytedance/deer-flow/pull/2962
[#2963]: https://github.com/bytedance/deer-flow/pull/2963
[#2973]: https://github.com/bytedance/deer-flow/pull/2973
[#2989]: https://github.com/bytedance/deer-flow/pull/2989
[#3002]: https://github.com/bytedance/deer-flow/pull/3002
[#3005]: https://github.com/bytedance/deer-flow/pull/3005
[#3033]: https://github.com/bytedance/deer-flow/pull/3033
[#3058]: https://github.com/bytedance/deer-flow/pull/3058
[#3069]: https://github.com/bytedance/deer-flow/pull/3069
[#3074]: https://github.com/bytedance/deer-flow/pull/3074
[#3101]: https://github.com/bytedance/deer-flow/pull/3101
[#3104]: https://github.com/bytedance/deer-flow/pull/3104
[#3130]: https://github.com/bytedance/deer-flow/pull/3130
[#3133]: https://github.com/bytedance/deer-flow/pull/3133
[#3144]: https://github.com/bytedance/deer-flow/pull/3144
[#3153]: https://github.com/bytedance/deer-flow/pull/3153
[#3174]: https://github.com/bytedance/deer-flow/pull/3174
[#3176]: https://github.com/bytedance/deer-flow/pull/3176
[#3183]: https://github.com/bytedance/deer-flow/pull/3183
[#3191]: https://github.com/bytedance/deer-flow/pull/3191
[#3200]: https://github.com/bytedance/deer-flow/pull/3200
[#3228]: https://github.com/bytedance/deer-flow/pull/3228
[#3233]: https://github.com/bytedance/deer-flow/pull/3233
[#3241]: https://github.com/bytedance/deer-flow/pull/3241
[#3252]: https://github.com/bytedance/deer-flow/pull/3252
[#3270]: https://github.com/bytedance/deer-flow/pull/3270
[#3283]: https://github.com/bytedance/deer-flow/pull/3283
[#3284]: https://github.com/bytedance/deer-flow/pull/3284
[#3298]: https://github.com/bytedance/deer-flow/pull/3298
[#3301]: https://github.com/bytedance/deer-flow/pull/3301
[#3307]: https://github.com/bytedance/deer-flow/pull/3307
[#3311]: https://github.com/bytedance/deer-flow/pull/3311
[#3313]: https://github.com/bytedance/deer-flow/pull/3313
[#3335]: https://github.com/bytedance/deer-flow/pull/3335
[#3342]: https://github.com/bytedance/deer-flow/pull/3342
[#3377]: https://github.com/bytedance/deer-flow/pull/3377
[#3393]: https://github.com/bytedance/deer-flow/pull/3393
[#3396]: https://github.com/bytedance/deer-flow/pull/3396
[#3397]: https://github.com/bytedance/deer-flow/pull/3397
[#3398]: https://github.com/bytedance/deer-flow/pull/3398
[#3408]: https://github.com/bytedance/deer-flow/pull/3408
[#3410]: https://github.com/bytedance/deer-flow/pull/3410
[#3411]: https://github.com/bytedance/deer-flow/pull/3411
[#3412]: https://github.com/bytedance/deer-flow/pull/3412
[#3413]: https://github.com/bytedance/deer-flow/pull/3413
[#3417]: https://github.com/bytedance/deer-flow/pull/3417
[#3421]: https://github.com/bytedance/deer-flow/pull/3421
[#3423]: https://github.com/bytedance/deer-flow/pull/3423
[#3425]: https://github.com/bytedance/deer-flow/pull/3425
[#3426]: https://github.com/bytedance/deer-flow/pull/3426
[#3428]: https://github.com/bytedance/deer-flow/pull/3428
[#3430]: https://github.com/bytedance/deer-flow/pull/3430
[#3433]: https://github.com/bytedance/deer-flow/pull/3433
[#3434]: https://github.com/bytedance/deer-flow/pull/3434
[#3435]: https://github.com/bytedance/deer-flow/pull/3435
[#3436]: https://github.com/bytedance/deer-flow/pull/3436
[#3437]: https://github.com/bytedance/deer-flow/pull/3437
[#3442]: https://github.com/bytedance/deer-flow/pull/3442
[#3451]: https://github.com/bytedance/deer-flow/pull/3451
[#3453]: https://github.com/bytedance/deer-flow/pull/3453
[#3455]: https://github.com/bytedance/deer-flow/pull/3455
[#3457]: https://github.com/bytedance/deer-flow/pull/3457
[#3458]: https://github.com/bytedance/deer-flow/pull/3458
[#3460]: https://github.com/bytedance/deer-flow/pull/3460
[#3461]: https://github.com/bytedance/deer-flow/pull/3461
[#3464]: https://github.com/bytedance/deer-flow/pull/3464
[#3465]: https://github.com/bytedance/deer-flow/pull/3465
[#3466]: https://github.com/bytedance/deer-flow/pull/3466
[#3470]: https://github.com/bytedance/deer-flow/pull/3470
[#3471]: https://github.com/bytedance/deer-flow/pull/3471
[#3473]: https://github.com/bytedance/deer-flow/pull/3473
[#3475]: https://github.com/bytedance/deer-flow/pull/3475
[#3481]: https://github.com/bytedance/deer-flow/pull/3481
[#3485]: https://github.com/bytedance/deer-flow/pull/3485
[#3487]: https://github.com/bytedance/deer-flow/pull/3487
[#3488]: https://github.com/bytedance/deer-flow/pull/3488
[#3494]: https://github.com/bytedance/deer-flow/pull/3494
[#3495]: https://github.com/bytedance/deer-flow/pull/3495
[#3498]: https://github.com/bytedance/deer-flow/pull/3498
[#3499]: https://github.com/bytedance/deer-flow/pull/3499
[#3502]: https://github.com/bytedance/deer-flow/pull/3502
[#3503]: https://github.com/bytedance/deer-flow/pull/3503
[#3505]: https://github.com/bytedance/deer-flow/pull/3505
[#3506]: https://github.com/bytedance/deer-flow/pull/3506
[#3508]: https://github.com/bytedance/deer-flow/pull/3508
[#3512]: https://github.com/bytedance/deer-flow/pull/3512
[#3514]: https://github.com/bytedance/deer-flow/pull/3514
[#3517]: https://github.com/bytedance/deer-flow/pull/3517
[#3518]: https://github.com/bytedance/deer-flow/pull/3518
[#3519]: https://github.com/bytedance/deer-flow/pull/3519
[#3521]: https://github.com/bytedance/deer-flow/pull/3521
[#3526]: https://github.com/bytedance/deer-flow/pull/3526
[#3528]: https://github.com/bytedance/deer-flow/pull/3528
[#3530]: https://github.com/bytedance/deer-flow/pull/3530
[#3531]: https://github.com/bytedance/deer-flow/pull/3531
[#3533]: https://github.com/bytedance/deer-flow/pull/3533
[#3534]: https://github.com/bytedance/deer-flow/pull/3534
[#3535]: https://github.com/bytedance/deer-flow/pull/3535
[#3548]: https://github.com/bytedance/deer-flow/pull/3548
[#3551]: https://github.com/bytedance/deer-flow/pull/3551
[#3553]: https://github.com/bytedance/deer-flow/pull/3553
[#3554]: https://github.com/bytedance/deer-flow/pull/3554
[#3556]: https://github.com/bytedance/deer-flow/pull/3556
[#3557]: https://github.com/bytedance/deer-flow/pull/3557
[#3559]: https://github.com/bytedance/deer-flow/pull/3559
[#3561]: https://github.com/bytedance/deer-flow/pull/3561
[#3562]: https://github.com/bytedance/deer-flow/pull/3562
[#3563]: https://github.com/bytedance/deer-flow/pull/3563
[#3565]: https://github.com/bytedance/deer-flow/pull/3565
[#3566]: https://github.com/bytedance/deer-flow/pull/3566
[#3569]: https://github.com/bytedance/deer-flow/pull/3569
[#3570]: https://github.com/bytedance/deer-flow/pull/3570
[#3573]: https://github.com/bytedance/deer-flow/pull/3573
[#3575]: https://github.com/bytedance/deer-flow/pull/3575
[#3577]: https://github.com/bytedance/deer-flow/pull/3577
[#3578]: https://github.com/bytedance/deer-flow/pull/3578
[#3579]: https://github.com/bytedance/deer-flow/pull/3579
[#3580]: https://github.com/bytedance/deer-flow/pull/3580
[#3581]: https://github.com/bytedance/deer-flow/pull/3581
[#3582]: https://github.com/bytedance/deer-flow/pull/3582
[#3583]: https://github.com/bytedance/deer-flow/pull/3583
[#3584]: https://github.com/bytedance/deer-flow/pull/3584
[#3585]: https://github.com/bytedance/deer-flow/pull/3585
[#3590]: https://github.com/bytedance/deer-flow/pull/3590
[#3591]: https://github.com/bytedance/deer-flow/pull/3591
[#3592]: https://github.com/bytedance/deer-flow/pull/3592
[#3599]: https://github.com/bytedance/deer-flow/pull/3599
[#3600]: https://github.com/bytedance/deer-flow/pull/3600
[#3601]: https://github.com/bytedance/deer-flow/pull/3601
[#3602]: https://github.com/bytedance/deer-flow/pull/3602
[#3605]: https://github.com/bytedance/deer-flow/pull/3605
[#3606]: https://github.com/bytedance/deer-flow/pull/3606
[#3608]: https://github.com/bytedance/deer-flow/pull/3608
[#3610]: https://github.com/bytedance/deer-flow/pull/3610
[#3611]: https://github.com/bytedance/deer-flow/pull/3611
[#3623]: https://github.com/bytedance/deer-flow/pull/3623
[#3624]: https://github.com/bytedance/deer-flow/pull/3624
[#3627]: https://github.com/bytedance/deer-flow/pull/3627
[#3629]: https://github.com/bytedance/deer-flow/pull/3629
[#3631]: https://github.com/bytedance/deer-flow/pull/3631
[#3637]: https://github.com/bytedance/deer-flow/pull/3637
[#3644]: https://github.com/bytedance/deer-flow/pull/3644
[#3646]: https://github.com/bytedance/deer-flow/pull/3646
[#3648]: https://github.com/bytedance/deer-flow/pull/3648
[#3649]: https://github.com/bytedance/deer-flow/pull/3649
[#3651]: https://github.com/bytedance/deer-flow/pull/3651
[#3654]: https://github.com/bytedance/deer-flow/pull/3654
[#3657]: https://github.com/bytedance/deer-flow/pull/3657
[#3658]: https://github.com/bytedance/deer-flow/pull/3658
[#3661]: https://github.com/bytedance/deer-flow/pull/3661
[#3662]: https://github.com/bytedance/deer-flow/pull/3662
[#3663]: https://github.com/bytedance/deer-flow/pull/3663
[#3665]: https://github.com/bytedance/deer-flow/pull/3665
[#3673]: https://github.com/bytedance/deer-flow/pull/3673
[#3674]: https://github.com/bytedance/deer-flow/pull/3674
[#3675]: https://github.com/bytedance/deer-flow/pull/3675
[#3685]: https://github.com/bytedance/deer-flow/pull/3685
[#3686]: https://github.com/bytedance/deer-flow/pull/3686
[#3687]: https://github.com/bytedance/deer-flow/pull/3687
[#3698]: https://github.com/bytedance/deer-flow/pull/3698
[#3703]: https://github.com/bytedance/deer-flow/pull/3703
[#3708]: https://github.com/bytedance/deer-flow/pull/3708
[#3709]: https://github.com/bytedance/deer-flow/pull/3709
[#3711]: https://github.com/bytedance/deer-flow/pull/3711
[#3713]: https://github.com/bytedance/deer-flow/pull/3713
[#3714]: https://github.com/bytedance/deer-flow/pull/3714
[#3718]: https://github.com/bytedance/deer-flow/pull/3718
[#3719]: https://github.com/bytedance/deer-flow/pull/3719
[#3729]: https://github.com/bytedance/deer-flow/pull/3729
[#3730]: https://github.com/bytedance/deer-flow/pull/3730
[#3733]: https://github.com/bytedance/deer-flow/pull/3733
[#3740]: https://github.com/bytedance/deer-flow/pull/3740
[#3753]: https://github.com/bytedance/deer-flow/pull/3753
[#3760]: https://github.com/bytedance/deer-flow/pull/3760
[#3764]: https://github.com/bytedance/deer-flow/pull/3764
[#3768]: https://github.com/bytedance/deer-flow/pull/3768
[#3769]: https://github.com/bytedance/deer-flow/pull/3769
[#3770]: https://github.com/bytedance/deer-flow/pull/3770
[#3772]: https://github.com/bytedance/deer-flow/pull/3772
[#3775]: https://github.com/bytedance/deer-flow/pull/3775
[#3783]: https://github.com/bytedance/deer-flow/pull/3783
[#3786]: https://github.com/bytedance/deer-flow/pull/3786
[#3790]: https://github.com/bytedance/deer-flow/pull/3790
[#3791]: https://github.com/bytedance/deer-flow/pull/3791
[#3794]: https://github.com/bytedance/deer-flow/pull/3794
[#3797]: https://github.com/bytedance/deer-flow/pull/3797
[#3800]: https://github.com/bytedance/deer-flow/pull/3800
[#3809]: https://github.com/bytedance/deer-flow/pull/3809
[#3810]: https://github.com/bytedance/deer-flow/pull/3810
[#3812]: https://github.com/bytedance/deer-flow/pull/3812
[#3821]: https://github.com/bytedance/deer-flow/pull/3821
[#3824]: https://github.com/bytedance/deer-flow/pull/3824
[#3826]: https://github.com/bytedance/deer-flow/pull/3826
[#3828]: https://github.com/bytedance/deer-flow/pull/3828
[#3833]: https://github.com/bytedance/deer-flow/pull/3833
[#3837]: https://github.com/bytedance/deer-flow/pull/3837
[#3839]: https://github.com/bytedance/deer-flow/pull/3839
[#3843]: https://github.com/bytedance/deer-flow/pull/3843
[#3845]: https://github.com/bytedance/deer-flow/pull/3845
[#3854]: https://github.com/bytedance/deer-flow/pull/3854
[#3855]: https://github.com/bytedance/deer-flow/pull/3855
[#3856]: https://github.com/bytedance/deer-flow/pull/3856
[#3858]: https://github.com/bytedance/deer-flow/pull/3858
[#3860]: https://github.com/bytedance/deer-flow/pull/3860
[#3866]: https://github.com/bytedance/deer-flow/pull/3866
[#3869]: https://github.com/bytedance/deer-flow/pull/3869
[#3870]: https://github.com/bytedance/deer-flow/pull/3870
[#3871]: https://github.com/bytedance/deer-flow/pull/3871
[#3872]: https://github.com/bytedance/deer-flow/pull/3872
[#3874]: https://github.com/bytedance/deer-flow/pull/3874
[#3877]: https://github.com/bytedance/deer-flow/pull/3877
[#3878]: https://github.com/bytedance/deer-flow/pull/3878
[#3880]: https://github.com/bytedance/deer-flow/pull/3880
[#3881]: https://github.com/bytedance/deer-flow/pull/3881
[#3883]: https://github.com/bytedance/deer-flow/pull/3883
[#3885]: https://github.com/bytedance/deer-flow/pull/3885
[#3886]: https://github.com/bytedance/deer-flow/pull/3886
[#3887]: https://github.com/bytedance/deer-flow/pull/3887
[#3889]: https://github.com/bytedance/deer-flow/pull/3889
[#3897]: https://github.com/bytedance/deer-flow/pull/3897
[#3900]: https://github.com/bytedance/deer-flow/pull/3900
[#3902]: https://github.com/bytedance/deer-flow/pull/3902
[#3904]: https://github.com/bytedance/deer-flow/pull/3904
[#3906]: https://github.com/bytedance/deer-flow/pull/3906
[#3907]: https://github.com/bytedance/deer-flow/pull/3907
[#3908]: https://github.com/bytedance/deer-flow/pull/3908
[#3912]: https://github.com/bytedance/deer-flow/pull/3912
[#3917]: https://github.com/bytedance/deer-flow/pull/3917
[#3920]: https://github.com/bytedance/deer-flow/pull/3920
[#3924]: https://github.com/bytedance/deer-flow/pull/3924
[#3926]: https://github.com/bytedance/deer-flow/pull/3926
[#3927]: https://github.com/bytedance/deer-flow/pull/3927
[#3928]: https://github.com/bytedance/deer-flow/pull/3928
[#3931]: https://github.com/bytedance/deer-flow/pull/3931
[#3934]: https://github.com/bytedance/deer-flow/pull/3934
[#3935]: https://github.com/bytedance/deer-flow/pull/3935
[#3938]: https://github.com/bytedance/deer-flow/pull/3938
[#3940]: https://github.com/bytedance/deer-flow/pull/3940
[#3941]: https://github.com/bytedance/deer-flow/pull/3941
[#3942]: https://github.com/bytedance/deer-flow/pull/3942
[#3944]: https://github.com/bytedance/deer-flow/pull/3944
[#3945]: https://github.com/bytedance/deer-flow/pull/3945
[#3949]: https://github.com/bytedance/deer-flow/pull/3949
[#3950]: https://github.com/bytedance/deer-flow/pull/3950
[#3951]: https://github.com/bytedance/deer-flow/pull/3951
[#3956]: https://github.com/bytedance/deer-flow/pull/3956
[#3959]: https://github.com/bytedance/deer-flow/pull/3959
[#3961]: https://github.com/bytedance/deer-flow/pull/3961
[#3964]: https://github.com/bytedance/deer-flow/pull/3964
[#3966]: https://github.com/bytedance/deer-flow/pull/3966
[#3967]: https://github.com/bytedance/deer-flow/pull/3967
[#3969]: https://github.com/bytedance/deer-flow/pull/3969
[#3971]: https://github.com/bytedance/deer-flow/pull/3971
[#3976]: https://github.com/bytedance/deer-flow/pull/3976
[#3980]: https://github.com/bytedance/deer-flow/pull/3980
[#3981]: https://github.com/bytedance/deer-flow/pull/3981
[#3982]: https://github.com/bytedance/deer-flow/pull/3982
[#3985]: https://github.com/bytedance/deer-flow/pull/3985
[#3986]: https://github.com/bytedance/deer-flow/pull/3986
[#3988]: https://github.com/bytedance/deer-flow/pull/3988
[#3989]: https://github.com/bytedance/deer-flow/pull/3989
[#3990]: https://github.com/bytedance/deer-flow/pull/3990
[#3991]: https://github.com/bytedance/deer-flow/pull/3991
[#3992]: https://github.com/bytedance/deer-flow/pull/3992
[#3993]: https://github.com/bytedance/deer-flow/pull/3993
[#3994]: https://github.com/bytedance/deer-flow/pull/3994
[#3996]: https://github.com/bytedance/deer-flow/pull/3996
[#4003]: https://github.com/bytedance/deer-flow/pull/4003
[#4004]: https://github.com/bytedance/deer-flow/pull/4004
[#4008]: https://github.com/bytedance/deer-flow/pull/4008
[#4009]: https://github.com/bytedance/deer-flow/pull/4009
[#4012]: https://github.com/bytedance/deer-flow/pull/4012
[#4016]: https://github.com/bytedance/deer-flow/pull/4016
[#4017]: https://github.com/bytedance/deer-flow/pull/4017
[#4018]: https://github.com/bytedance/deer-flow/pull/4018
[#4023]: https://github.com/bytedance/deer-flow/pull/4023
[#4024]: https://github.com/bytedance/deer-flow/pull/4024
[#4025]: https://github.com/bytedance/deer-flow/pull/4025
[#4026]: https://github.com/bytedance/deer-flow/pull/4026
[#4028]: https://github.com/bytedance/deer-flow/pull/4028
[#4033]: https://github.com/bytedance/deer-flow/pull/4033
[#4034]: https://github.com/bytedance/deer-flow/pull/4034
[#4035]: https://github.com/bytedance/deer-flow/pull/4035
[#4036]: https://github.com/bytedance/deer-flow/pull/4036
[#4038]: https://github.com/bytedance/deer-flow/pull/4038
[#4040]: https://github.com/bytedance/deer-flow/pull/4040
[#4051]: https://github.com/bytedance/deer-flow/pull/4051
[#4052]: https://github.com/bytedance/deer-flow/pull/4052
[#4053]: https://github.com/bytedance/deer-flow/pull/4053
[#4055]: https://github.com/bytedance/deer-flow/pull/4055
[#4058]: https://github.com/bytedance/deer-flow/pull/4058
[#4059]: https://github.com/bytedance/deer-flow/pull/4059
[#4060]: https://github.com/bytedance/deer-flow/pull/4060
[#4064]: https://github.com/bytedance/deer-flow/pull/4064
[#4065]: https://github.com/bytedance/deer-flow/pull/4065
[#4067]: https://github.com/bytedance/deer-flow/pull/4067
[#4069]: https://github.com/bytedance/deer-flow/pull/4069
[#4072]: https://github.com/bytedance/deer-flow/pull/4072
[#4073]: https://github.com/bytedance/deer-flow/pull/4073
[#4074]: https://github.com/bytedance/deer-flow/pull/4074
[#4076]: https://github.com/bytedance/deer-flow/pull/4076
[#4077]: https://github.com/bytedance/deer-flow/pull/4077
[#4078]: https://github.com/bytedance/deer-flow/pull/4078
[#4079]: https://github.com/bytedance/deer-flow/pull/4079
[#4080]: https://github.com/bytedance/deer-flow/pull/4080
[#4081]: https://github.com/bytedance/deer-flow/pull/4081
[#4082]: https://github.com/bytedance/deer-flow/pull/4082
[#4084]: https://github.com/bytedance/deer-flow/pull/4084
[#4085]: https://github.com/bytedance/deer-flow/pull/4085
[#4090]: https://github.com/bytedance/deer-flow/pull/4090
[#4094]: https://github.com/bytedance/deer-flow/pull/4094
[#4095]: https://github.com/bytedance/deer-flow/pull/4095
[#4096]: https://github.com/bytedance/deer-flow/pull/4096
[#4097]: https://github.com/bytedance/deer-flow/pull/4097
[#4098]: https://github.com/bytedance/deer-flow/pull/4098
[#4099]: https://github.com/bytedance/deer-flow/pull/4099
[#4100]: https://github.com/bytedance/deer-flow/pull/4100
[#4101]: https://github.com/bytedance/deer-flow/pull/4101
[#4102]: https://github.com/bytedance/deer-flow/pull/4102
[#4103]: https://github.com/bytedance/deer-flow/pull/4103
[#4104]: https://github.com/bytedance/deer-flow/pull/4104
[#4105]: https://github.com/bytedance/deer-flow/pull/4105
[#4108]: https://github.com/bytedance/deer-flow/pull/4108
[#4114]: https://github.com/bytedance/deer-flow/pull/4114
[#4115]: https://github.com/bytedance/deer-flow/pull/4115
[#4117]: https://github.com/bytedance/deer-flow/pull/4117
[#4118]: https://github.com/bytedance/deer-flow/pull/4118
[#4119]: https://github.com/bytedance/deer-flow/pull/4119
[#4122]: https://github.com/bytedance/deer-flow/pull/4122
[#4124]: https://github.com/bytedance/deer-flow/pull/4124
[#4128]: https://github.com/bytedance/deer-flow/pull/4128
[#4129]: https://github.com/bytedance/deer-flow/pull/4129
[#4130]: https://github.com/bytedance/deer-flow/pull/4130
[#4131]: https://github.com/bytedance/deer-flow/pull/4131
[#4133]: https://github.com/bytedance/deer-flow/pull/4133
[#4136]: https://github.com/bytedance/deer-flow/pull/4136
[#4137]: https://github.com/bytedance/deer-flow/pull/4137
[#4140]: https://github.com/bytedance/deer-flow/pull/4140
[#4141]: https://github.com/bytedance/deer-flow/pull/4141
[#4143]: https://github.com/bytedance/deer-flow/pull/4143
[#4146]: https://github.com/bytedance/deer-flow/pull/4146
[#4147]: https://github.com/bytedance/deer-flow/pull/4147
[#4154]: https://github.com/bytedance/deer-flow/pull/4154
[#4155]: https://github.com/bytedance/deer-flow/pull/4155
[#4157]: https://github.com/bytedance/deer-flow/pull/4157
[#4160]: https://github.com/bytedance/deer-flow/pull/4160
[#4161]: https://github.com/bytedance/deer-flow/pull/4161
[#4162]: https://github.com/bytedance/deer-flow/pull/4162
[#4166]: https://github.com/bytedance/deer-flow/pull/4166
[#4169]: https://github.com/bytedance/deer-flow/pull/4169
[#4170]: https://github.com/bytedance/deer-flow/pull/4170
[#4171]: https://github.com/bytedance/deer-flow/pull/4171
[#4174]: https://github.com/bytedance/deer-flow/pull/4174
[#4178]: https://github.com/bytedance/deer-flow/pull/4178
[#4181]: https://github.com/bytedance/deer-flow/pull/4181
[#4187]: https://github.com/bytedance/deer-flow/pull/4187
[#4188]: https://github.com/bytedance/deer-flow/pull/4188
[#4190]: https://github.com/bytedance/deer-flow/pull/4190
[#4192]: https://github.com/bytedance/deer-flow/pull/4192
[#4193]: https://github.com/bytedance/deer-flow/pull/4193
[#4197]: https://github.com/bytedance/deer-flow/pull/4197
[#4199]: https://github.com/bytedance/deer-flow/pull/4199
[#4200]: https://github.com/bytedance/deer-flow/pull/4200
[#4202]: https://github.com/bytedance/deer-flow/pull/4202
[#4203]: https://github.com/bytedance/deer-flow/pull/4203
[#4208]: https://github.com/bytedance/deer-flow/pull/4208
[#4209]: https://github.com/bytedance/deer-flow/pull/4209
[#4210]: https://github.com/bytedance/deer-flow/pull/4210
[#4211]: https://github.com/bytedance/deer-flow/pull/4211
[#4215]: https://github.com/bytedance/deer-flow/pull/4215
[#4217]: https://github.com/bytedance/deer-flow/pull/4217
[#4218]: https://github.com/bytedance/deer-flow/pull/4218
[#4219]: https://github.com/bytedance/deer-flow/pull/4219
[#4222]: https://github.com/bytedance/deer-flow/pull/4222
[#4225]: https://github.com/bytedance/deer-flow/pull/4225
[#4229]: https://github.com/bytedance/deer-flow/pull/4229
[#4230]: https://github.com/bytedance/deer-flow/pull/4230
[#4231]: https://github.com/bytedance/deer-flow/pull/4231
[#4234]: https://github.com/bytedance/deer-flow/pull/4234
[#4235]: https://github.com/bytedance/deer-flow/pull/4235
[#4238]: https://github.com/bytedance/deer-flow/pull/4238
[#4239]: https://github.com/bytedance/deer-flow/pull/4239
[#4241]: https://github.com/bytedance/deer-flow/pull/4241
[#4242]: https://github.com/bytedance/deer-flow/pull/4242
[#4245]: https://github.com/bytedance/deer-flow/pull/4245
[#4246]: https://github.com/bytedance/deer-flow/pull/4246
[#4247]: https://github.com/bytedance/deer-flow/pull/4247
[#4250]: https://github.com/bytedance/deer-flow/pull/4250
[#4251]: https://github.com/bytedance/deer-flow/pull/4251
[#4253]: https://github.com/bytedance/deer-flow/pull/4253
[#4255]: https://github.com/bytedance/deer-flow/pull/4255
[#4256]: https://github.com/bytedance/deer-flow/pull/4256
[#4260]: https://github.com/bytedance/deer-flow/pull/4260
[#4262]: https://github.com/bytedance/deer-flow/pull/4262
[#4264]: https://github.com/bytedance/deer-flow/pull/4264
[#4266]: https://github.com/bytedance/deer-flow/pull/4266
[#4267]: https://github.com/bytedance/deer-flow/pull/4267
[#4268]: https://github.com/bytedance/deer-flow/pull/4268
[#4274]: https://github.com/bytedance/deer-flow/pull/4274
[#4275]: https://github.com/bytedance/deer-flow/pull/4275
[#4277]: https://github.com/bytedance/deer-flow/pull/4277
[#4278]: https://github.com/bytedance/deer-flow/pull/4278
[#4279]: https://github.com/bytedance/deer-flow/pull/4279
[#4283]: https://github.com/bytedance/deer-flow/pull/4283
[#4284]: https://github.com/bytedance/deer-flow/pull/4284
[#4287]: https://github.com/bytedance/deer-flow/pull/4287
[#4288]: https://github.com/bytedance/deer-flow/pull/4288
[#4292]: https://github.com/bytedance/deer-flow/pull/4292
[#4293]: https://github.com/bytedance/deer-flow/pull/4293
[#4298]: https://github.com/bytedance/deer-flow/pull/4298
[#4301]: https://github.com/bytedance/deer-flow/pull/4301
[#4302]: https://github.com/bytedance/deer-flow/pull/4302
[#4306]: https://github.com/bytedance/deer-flow/pull/4306
[#4309]: https://github.com/bytedance/deer-flow/pull/4309
[#4311]: https://github.com/bytedance/deer-flow/pull/4311
[#4314]: https://github.com/bytedance/deer-flow/pull/4314
[#4315]: https://github.com/bytedance/deer-flow/pull/4315
[#4316]: https://github.com/bytedance/deer-flow/pull/4316
[#4324]: https://github.com/bytedance/deer-flow/pull/4324
[#4326]: https://github.com/bytedance/deer-flow/pull/4326
[#4337]: https://github.com/bytedance/deer-flow/pull/4337
[#4347]: https://github.com/bytedance/deer-flow/pull/4347
[#4348]: https://github.com/bytedance/deer-flow/pull/4348
[#4354]: https://github.com/bytedance/deer-flow/pull/4354
[#4355]: https://github.com/bytedance/deer-flow/pull/4355
[#4356]: https://github.com/bytedance/deer-flow/pull/4356
[#4358]: https://github.com/bytedance/deer-flow/pull/4358
[#4360]: https://github.com/bytedance/deer-flow/pull/4360
[#4361]: https://github.com/bytedance/deer-flow/pull/4361
[#4364]: https://github.com/bytedance/deer-flow/pull/4364
[#4365]: https://github.com/bytedance/deer-flow/pull/4365
[#4370]: https://github.com/bytedance/deer-flow/pull/4370
[#4371]: https://github.com/bytedance/deer-flow/pull/4371
[#4373]: https://github.com/bytedance/deer-flow/pull/4373
[#4374]: https://github.com/bytedance/deer-flow/pull/4374
[#4376]: https://github.com/bytedance/deer-flow/pull/4376
[#4377]: https://github.com/bytedance/deer-flow/pull/4377
[#4381]: https://github.com/bytedance/deer-flow/pull/4381
[#4382]: https://github.com/bytedance/deer-flow/pull/4382
[#4383]: https://github.com/bytedance/deer-flow/pull/4383
[#4384]: https://github.com/bytedance/deer-flow/pull/4384
[#4385]: https://github.com/bytedance/deer-flow/pull/4385
[#4391]: https://github.com/bytedance/deer-flow/pull/4391
[#4392]: https://github.com/bytedance/deer-flow/pull/4392
[#4394]: https://github.com/bytedance/deer-flow/pull/4394
[#4395]: https://github.com/bytedance/deer-flow/pull/4395
[#4402]: https://github.com/bytedance/deer-flow/pull/4402
[#4403]: https://github.com/bytedance/deer-flow/pull/4403
[#4405]: https://github.com/bytedance/deer-flow/pull/4405
[#4406]: https://github.com/bytedance/deer-flow/pull/4406
[#4407]: https://github.com/bytedance/deer-flow/pull/4407
[#4408]: https://github.com/bytedance/deer-flow/pull/4408
[#4411]: https://github.com/bytedance/deer-flow/pull/4411
[#4414]: https://github.com/bytedance/deer-flow/pull/4414
[#4423]: https://github.com/bytedance/deer-flow/pull/4423
[#4424]: https://github.com/bytedance/deer-flow/pull/4424
[#4425]: https://github.com/bytedance/deer-flow/pull/4425
[#4426]: https://github.com/bytedance/deer-flow/pull/4426
[#4427]: https://github.com/bytedance/deer-flow/pull/4427
[#4429]: https://github.com/bytedance/deer-flow/pull/4429
[#4430]: https://github.com/bytedance/deer-flow/pull/4430
[#4431]: https://github.com/bytedance/deer-flow/pull/4431
[#4432]: https://github.com/bytedance/deer-flow/pull/4432
[#4434]: https://github.com/bytedance/deer-flow/pull/4434
[#4437]: https://github.com/bytedance/deer-flow/pull/4437
[#4439]: https://github.com/bytedance/deer-flow/pull/4439
[#4441]: https://github.com/bytedance/deer-flow/pull/4441
[#4442]: https://github.com/bytedance/deer-flow/pull/4442
[#4443]: https://github.com/bytedance/deer-flow/pull/4443
[#4444]: https://github.com/bytedance/deer-flow/pull/4444
[#4446]: https://github.com/bytedance/deer-flow/pull/4446
[#4447]: https://github.com/bytedance/deer-flow/pull/4447
[#4448]: https://github.com/bytedance/deer-flow/pull/4448
[#4450]: https://github.com/bytedance/deer-flow/pull/4450
[#4453]: https://github.com/bytedance/deer-flow/pull/4453
[#4456]: https://github.com/bytedance/deer-flow/pull/4456
[#4459]: https://github.com/bytedance/deer-flow/pull/4459
[#4460]: https://github.com/bytedance/deer-flow/pull/4460
[#4468]: https://github.com/bytedance/deer-flow/pull/4468
[#4469]: https://github.com/bytedance/deer-flow/pull/4469
[#4471]: https://github.com/bytedance/deer-flow/pull/4471
[#4472]: https://github.com/bytedance/deer-flow/pull/4472
[#4480]: https://github.com/bytedance/deer-flow/pull/4480
[#4482]: https://github.com/bytedance/deer-flow/pull/4482
[#4486]: https://github.com/bytedance/deer-flow/pull/4486
[#4489]: https://github.com/bytedance/deer-flow/pull/4489
[#4490]: https://github.com/bytedance/deer-flow/pull/4490
[#4493]: https://github.com/bytedance/deer-flow/pull/4493
[#4497]: https://github.com/bytedance/deer-flow/pull/4497
[#4500]: https://github.com/bytedance/deer-flow/pull/4500
[#4501]: https://github.com/bytedance/deer-flow/pull/4501
[#4504]: https://github.com/bytedance/deer-flow/pull/4504
[#4505]: https://github.com/bytedance/deer-flow/pull/4505
[#4506]: https://github.com/bytedance/deer-flow/pull/4506
[#4509]: https://github.com/bytedance/deer-flow/pull/4509
[#4510]: https://github.com/bytedance/deer-flow/pull/4510
[#4512]: https://github.com/bytedance/deer-flow/pull/4512
[#4513]: https://github.com/bytedance/deer-flow/pull/4513
[#4516]: https://github.com/bytedance/deer-flow/pull/4516
[#4518]: https://github.com/bytedance/deer-flow/pull/4518
[#4519]: https://github.com/bytedance/deer-flow/pull/4519
[#4524]: https://github.com/bytedance/deer-flow/pull/4524
[#4527]: https://github.com/bytedance/deer-flow/pull/4527
[#4528]: https://github.com/bytedance/deer-flow/pull/4528
[#4530]: https://github.com/bytedance/deer-flow/pull/4530
[#4533]: https://github.com/bytedance/deer-flow/pull/4533
[#4534]: https://github.com/bytedance/deer-flow/pull/4534
[#4535]: https://github.com/bytedance/deer-flow/pull/4535
[#4538]: https://github.com/bytedance/deer-flow/pull/4538
[#4539]: https://github.com/bytedance/deer-flow/pull/4539
[#4540]: https://github.com/bytedance/deer-flow/pull/4540
[#4556]: https://github.com/bytedance/deer-flow/pull/4556
[#4558]: https://github.com/bytedance/deer-flow/pull/4558
[#4559]: https://github.com/bytedance/deer-flow/pull/4559
[#4564]: https://github.com/bytedance/deer-flow/pull/4564
[#4570]: https://github.com/bytedance/deer-flow/pull/4570
[#4574]: https://github.com/bytedance/deer-flow/pull/4574
[#4575]: https://github.com/bytedance/deer-flow/pull/4575
[#4577]: https://github.com/bytedance/deer-flow/pull/4577
[#4578]: https://github.com/bytedance/deer-flow/pull/4578
[#4582]: https://github.com/bytedance/deer-flow/pull/4582
[#4584]: https://github.com/bytedance/deer-flow/pull/4584
[#4587]: https://github.com/bytedance/deer-flow/pull/4587
[#4589]: https://github.com/bytedance/deer-flow/pull/4589
[#4590]: https://github.com/bytedance/deer-flow/pull/4590
[#4596]: https://github.com/bytedance/deer-flow/pull/4596
[#4599]: https://github.com/bytedance/deer-flow/pull/4599
[#4600]: https://github.com/bytedance/deer-flow/pull/4600
[#4604]: https://github.com/bytedance/deer-flow/pull/4604
[#4611]: https://github.com/bytedance/deer-flow/pull/4611
[#4615]: https://github.com/bytedance/deer-flow/pull/4615
[#4617]: https://github.com/bytedance/deer-flow/pull/4617
[#4618]: https://github.com/bytedance/deer-flow/pull/4618
[#4620]: https://github.com/bytedance/deer-flow/pull/4620
[#4623]: https://github.com/bytedance/deer-flow/pull/4623
[#4624]: https://github.com/bytedance/deer-flow/pull/4624
[#4625]: https://github.com/bytedance/deer-flow/pull/4625
[#4627]: https://github.com/bytedance/deer-flow/pull/4627
[#4629]: https://github.com/bytedance/deer-flow/pull/4629
[#4631]: https://github.com/bytedance/deer-flow/pull/4631
[#4633]: https://github.com/bytedance/deer-flow/pull/4633
[#4634]: https://github.com/bytedance/deer-flow/pull/4634
[#4635]: https://github.com/bytedance/deer-flow/pull/4635
[#4636]: https://github.com/bytedance/deer-flow/pull/4636
[#4638]: https://github.com/bytedance/deer-flow/pull/4638
[#4639]: https://github.com/bytedance/deer-flow/pull/4639
[#4643]: https://github.com/bytedance/deer-flow/pull/4643
[#4644]: https://github.com/bytedance/deer-flow/pull/4644
[#4647]: https://github.com/bytedance/deer-flow/pull/4647
[#4649]: https://github.com/bytedance/deer-flow/pull/4649
[#4657]: https://github.com/bytedance/deer-flow/pull/4657
[#4658]: https://github.com/bytedance/deer-flow/pull/4658
[#4659]: https://github.com/bytedance/deer-flow/pull/4659
[#4660]: https://github.com/bytedance/deer-flow/pull/4660
[#4665]: https://github.com/bytedance/deer-flow/pull/4665
[#4667]: https://github.com/bytedance/deer-flow/pull/4667
[#4668]: https://github.com/bytedance/deer-flow/pull/4668
[#4677]: https://github.com/bytedance/deer-flow/pull/4677
[#4681]: https://github.com/bytedance/deer-flow/pull/4681
[#4683]: https://github.com/bytedance/deer-flow/pull/4683
[#4684]: https://github.com/bytedance/deer-flow/pull/4684
[#4690]: https://github.com/bytedance/deer-flow/pull/4690
[#4693]: https://github.com/bytedance/deer-flow/pull/4693
[#4696]: https://github.com/bytedance/deer-flow/pull/4696
[#4701]: https://github.com/bytedance/deer-flow/pull/4701
[#4703]: https://github.com/bytedance/deer-flow/pull/4703
[#4707]: https://github.com/bytedance/deer-flow/pull/4707
[#4709]: https://github.com/bytedance/deer-flow/pull/4709
[#4713]: https://github.com/bytedance/deer-flow/pull/4713
[#4719]: https://github.com/bytedance/deer-flow/pull/4719
[#4722]: https://github.com/bytedance/deer-flow/pull/4722
[#4724]: https://github.com/bytedance/deer-flow/pull/4724
[#4726]: https://github.com/bytedance/deer-flow/pull/4726
[#4727]: https://github.com/bytedance/deer-flow/pull/4727
[#4729]: https://github.com/bytedance/deer-flow/pull/4729
[#4730]: https://github.com/bytedance/deer-flow/pull/4730
[#4735]: https://github.com/bytedance/deer-flow/pull/4735
[#4736]: https://github.com/bytedance/deer-flow/pull/4736
[#4737]: https://github.com/bytedance/deer-flow/pull/4737
[#4738]: https://github.com/bytedance/deer-flow/pull/4738
[#4744]: https://github.com/bytedance/deer-flow/pull/4744
[#4745]: https://github.com/bytedance/deer-flow/pull/4745
[#4747]: https://github.com/bytedance/deer-flow/pull/4747
[#4748]: https://github.com/bytedance/deer-flow/pull/4748
[#4750]: https://github.com/bytedance/deer-flow/pull/4750
[#4752]: https://github.com/bytedance/deer-flow/pull/4752
[#4755]: https://github.com/bytedance/deer-flow/pull/4755
[#4758]: https://github.com/bytedance/deer-flow/pull/4758
[#4759]: https://github.com/bytedance/deer-flow/pull/4759
[#4760]: https://github.com/bytedance/deer-flow/pull/4760
[#4762]: https://github.com/bytedance/deer-flow/pull/4762
[#4764]: https://github.com/bytedance/deer-flow/pull/4764
[#4767]: https://github.com/bytedance/deer-flow/pull/4767
[#4769]: https://github.com/bytedance/deer-flow/pull/4769
[#4772]: https://github.com/bytedance/deer-flow/pull/4772
[#4780]: https://github.com/bytedance/deer-flow/pull/4780
[#4783]: https://github.com/bytedance/deer-flow/pull/4783
[#4785]: https://github.com/bytedance/deer-flow/pull/4785
[#4789]: https://github.com/bytedance/deer-flow/pull/4789
[#4792]: https://github.com/bytedance/deer-flow/pull/4792
[#4797]: https://github.com/bytedance/deer-flow/pull/4797
[#4800]: https://github.com/bytedance/deer-flow/pull/4800
[#4804]: https://github.com/bytedance/deer-flow/pull/4804
[#4806]: https://github.com/bytedance/deer-flow/pull/4806
[#4810]: https://github.com/bytedance/deer-flow/pull/4810
[#4812]: https://github.com/bytedance/deer-flow/pull/4812
[#4815]: https://github.com/bytedance/deer-flow/pull/4815
[#4816]: https://github.com/bytedance/deer-flow/pull/4816
[#4817]: https://github.com/bytedance/deer-flow/pull/4817
[#4820]: https://github.com/bytedance/deer-flow/pull/4820
[#4822]: https://github.com/bytedance/deer-flow/pull/4822
[#4823]: https://github.com/bytedance/deer-flow/pull/4823
[#4825]: https://github.com/bytedance/deer-flow/pull/4825
[#4826]: https://github.com/bytedance/deer-flow/pull/4826
[#4827]: https://github.com/bytedance/deer-flow/pull/4827
[#4830]: https://github.com/bytedance/deer-flow/pull/4830
[#4833]: https://github.com/bytedance/deer-flow/pull/4833
[#4834]: https://github.com/bytedance/deer-flow/pull/4834
[#4836]: https://github.com/bytedance/deer-flow/pull/4836
[#4838]: https://github.com/bytedance/deer-flow/pull/4838
[#4839]: https://github.com/bytedance/deer-flow/pull/4839
[#4840]: https://github.com/bytedance/deer-flow/pull/4840
[#4842]: https://github.com/bytedance/deer-flow/pull/4842
[#4844]: https://github.com/bytedance/deer-flow/pull/4844
[#4846]: https://github.com/bytedance/deer-flow/pull/4846
[#4848]: https://github.com/bytedance/deer-flow/pull/4848
[#4852]: https://github.com/bytedance/deer-flow/pull/4852
[#4853]: https://github.com/bytedance/deer-flow/pull/4853
[#4860]: https://github.com/bytedance/deer-flow/pull/4860
[#4861]: https://github.com/bytedance/deer-flow/pull/4861
[#4863]: https://github.com/bytedance/deer-flow/pull/4863
[#4865]: https://github.com/bytedance/deer-flow/pull/4865
[#4867]: https://github.com/bytedance/deer-flow/pull/4867
[#4868]: https://github.com/bytedance/deer-flow/pull/4868
[#4876]: https://github.com/bytedance/deer-flow/pull/4876
[#4877]: https://github.com/bytedance/deer-flow/pull/4877
[#4878]: https://github.com/bytedance/deer-flow/pull/4878
[#4882]: https://github.com/bytedance/deer-flow/pull/4882
[#4884]: https://github.com/bytedance/deer-flow/pull/4884
[#4887]: https://github.com/bytedance/deer-flow/pull/4887
[#4888]: https://github.com/bytedance/deer-flow/pull/4888
[#4892]: https://github.com/bytedance/deer-flow/pull/4892
[#4898]: https://github.com/bytedance/deer-flow/pull/4898
[#4901]: https://github.com/bytedance/deer-flow/pull/4901
[#4903]: https://github.com/bytedance/deer-flow/pull/4903
[#4911]: https://github.com/bytedance/deer-flow/pull/4911
[#4918]: https://github.com/bytedance/deer-flow/pull/4918
[#4921]: https://github.com/bytedance/deer-flow/pull/4921
[#4928]: https://github.com/bytedance/deer-flow/pull/4928
[#4933]: https://github.com/bytedance/deer-flow/pull/4933
[#4936]: https://github.com/bytedance/deer-flow/pull/4936
[#4938]: https://github.com/bytedance/deer-flow/pull/4938
[#4944]: https://github.com/bytedance/deer-flow/pull/4944
[#4946]: https://github.com/bytedance/deer-flow/pull/4946
[#4951]: https://github.com/bytedance/deer-flow/pull/4951
[#4952]: https://github.com/bytedance/deer-flow/pull/4952
[#4953]: https://github.com/bytedance/deer-flow/pull/4953
[#4955]: https://github.com/bytedance/deer-flow/pull/4955
[#4956]: https://github.com/bytedance/deer-flow/pull/4956
[#4959]: https://github.com/bytedance/deer-flow/pull/4959
[#4960]: https://github.com/bytedance/deer-flow/pull/4960
[#4962]: https://github.com/bytedance/deer-flow/pull/4962
[#4963]: https://github.com/bytedance/deer-flow/pull/4963
[#4965]: https://github.com/bytedance/deer-flow/pull/4965
[#4970]: https://github.com/bytedance/deer-flow/pull/4970
[#4972]: https://github.com/bytedance/deer-flow/pull/4972
[#4977]: https://github.com/bytedance/deer-flow/pull/4977
[#4980]: https://github.com/bytedance/deer-flow/pull/4980
[#4983]: https://github.com/bytedance/deer-flow/pull/4983
[#4984]: https://github.com/bytedance/deer-flow/pull/4984
[#4986]: https://github.com/bytedance/deer-flow/pull/4986
[#4987]: https://github.com/bytedance/deer-flow/pull/4987
[#4995]: https://github.com/bytedance/deer-flow/pull/4995
[#4998]: https://github.com/bytedance/deer-flow/pull/4998
[#5003]: https://github.com/bytedance/deer-flow/pull/5003
[#5006]: https://github.com/bytedance/deer-flow/pull/5006
[#5008]: https://github.com/bytedance/deer-flow/pull/5008
[#5010]: https://github.com/bytedance/deer-flow/pull/5010
[#5014]: https://github.com/bytedance/deer-flow/pull/5014
[#5017]: https://github.com/bytedance/deer-flow/pull/5017
[#5018]: https://github.com/bytedance/deer-flow/pull/5018
[#5021]: https://github.com/bytedance/deer-flow/pull/5021
[#5022]: https://github.com/bytedance/deer-flow/pull/5022
[#5023]: https://github.com/bytedance/deer-flow/pull/5023
[#5025]: https://github.com/bytedance/deer-flow/pull/5025
[#5026]: https://github.com/bytedance/deer-flow/pull/5026
[#5027]: https://github.com/bytedance/deer-flow/pull/5027
[#5028]: https://github.com/bytedance/deer-flow/pull/5028
[#5030]: https://github.com/bytedance/deer-flow/pull/5030
[#5031]: https://github.com/bytedance/deer-flow/pull/5031
[#5036]: https://github.com/bytedance/deer-flow/pull/5036
[#5039]: https://github.com/bytedance/deer-flow/pull/5039
[#5041]: https://github.com/bytedance/deer-flow/pull/5041
[#5045]: https://github.com/bytedance/deer-flow/pull/5045
[#5047]: https://github.com/bytedance/deer-flow/pull/5047
[#5049]: https://github.com/bytedance/deer-flow/pull/5049
[#5050]: https://github.com/bytedance/deer-flow/pull/5050
[#5051]: https://github.com/bytedance/deer-flow/pull/5051
[#5056]: https://github.com/bytedance/deer-flow/pull/5056
[#5057]: https://github.com/bytedance/deer-flow/pull/5057
[#5059]: https://github.com/bytedance/deer-flow/pull/5059
[#5062]: https://github.com/bytedance/deer-flow/pull/5062
[#5064]: https://github.com/bytedance/deer-flow/pull/5064
[#5066]: https://github.com/bytedance/deer-flow/pull/5066
[#5069]: https://github.com/bytedance/deer-flow/pull/5069
[#5071]: https://github.com/bytedance/deer-flow/pull/5071
[#5074]: https://github.com/bytedance/deer-flow/pull/5074
[#5076]: https://github.com/bytedance/deer-flow/pull/5076
[#5077]: https://github.com/bytedance/deer-flow/pull/5077
[#5083]: https://github.com/bytedance/deer-flow/pull/5083
[#5086]: https://github.com/bytedance/deer-flow/pull/5086
[#5087]: https://github.com/bytedance/deer-flow/pull/5087
[#5089]: https://github.com/bytedance/deer-flow/pull/5089
[#5090]: https://github.com/bytedance/deer-flow/pull/5090
[#5092]: https://github.com/bytedance/deer-flow/pull/5092
[#5095]: https://github.com/bytedance/deer-flow/pull/5095
[#5099]: https://github.com/bytedance/deer-flow/pull/5099
[#5103]: https://github.com/bytedance/deer-flow/pull/5103
[#5105]: https://github.com/bytedance/deer-flow/pull/5105
[#5109]: https://github.com/bytedance/deer-flow/pull/5109
[#5110]: https://github.com/bytedance/deer-flow/pull/5110
[#5111]: https://github.com/bytedance/deer-flow/pull/5111
[#5112]: https://github.com/bytedance/deer-flow/pull/5112
[#5117]: https://github.com/bytedance/deer-flow/pull/5117
[#5119]: https://github.com/bytedance/deer-flow/pull/5119
[#5123]: https://github.com/bytedance/deer-flow/pull/5123
[#5133]: https://github.com/bytedance/deer-flow/pull/5133
[#5134]: https://github.com/bytedance/deer-flow/pull/5134
[#5136]: https://github.com/bytedance/deer-flow/pull/5136
[#5137]: https://github.com/bytedance/deer-flow/pull/5137
[#5141]: https://github.com/bytedance/deer-flow/pull/5141
[#5145]: https://github.com/bytedance/deer-flow/pull/5145
[#5148]: https://github.com/bytedance/deer-flow/pull/5148
[#5149]: https://github.com/bytedance/deer-flow/pull/5149
[#5152]: https://github.com/bytedance/deer-flow/pull/5152
[#5153]: https://github.com/bytedance/deer-flow/pull/5153
[#5154]: https://github.com/bytedance/deer-flow/pull/5154
[#5155]: https://github.com/bytedance/deer-flow/pull/5155
[#5156]: https://github.com/bytedance/deer-flow/pull/5156
[#5159]: https://github.com/bytedance/deer-flow/pull/5159
[#5162]: https://github.com/bytedance/deer-flow/pull/5162
[#5163]: https://github.com/bytedance/deer-flow/pull/5163
[#5164]: https://github.com/bytedance/deer-flow/pull/5164
[#5166]: https://github.com/bytedance/deer-flow/pull/5166
[#5167]: https://github.com/bytedance/deer-flow/pull/5167
[#5168]: https://github.com/bytedance/deer-flow/pull/5168
[#5170]: https://github.com/bytedance/deer-flow/pull/5170
[#5178]: https://github.com/bytedance/deer-flow/pull/5178
[#5181]: https://github.com/bytedance/deer-flow/pull/5181
[#5183]: https://github.com/bytedance/deer-flow/pull/5183
[#5185]: https://github.com/bytedance/deer-flow/pull/5185
[#5187]: https://github.com/bytedance/deer-flow/pull/5187
[#5191]: https://github.com/bytedance/deer-flow/pull/5191
[#5197]: https://github.com/bytedance/deer-flow/pull/5197
[#5206]: https://github.com/bytedance/deer-flow/pull/5206
[#5209]: https://github.com/bytedance/deer-flow/pull/5209
[#5214]: https://github.com/bytedance/deer-flow/pull/5214
[#5216]: https://github.com/bytedance/deer-flow/pull/5216
[#5217]: https://github.com/bytedance/deer-flow/pull/5217
[#5219]: https://github.com/bytedance/deer-flow/pull/5219
[#5224]: https://github.com/bytedance/deer-flow/pull/5224
[#5225]: https://github.com/bytedance/deer-flow/pull/5225
[#5227]: https://github.com/bytedance/deer-flow/pull/5227
[#5228]: https://github.com/bytedance/deer-flow/pull/5228
[#5232]: https://github.com/bytedance/deer-flow/pull/5232
[#5234]: https://github.com/bytedance/deer-flow/pull/5234
[#5236]: https://github.com/bytedance/deer-flow/pull/5236
[#5239]: https://github.com/bytedance/deer-flow/pull/5239
[#5244]: https://github.com/bytedance/deer-flow/pull/5244
[#5245]: https://github.com/bytedance/deer-flow/pull/5245
[#5247]: https://github.com/bytedance/deer-flow/pull/5247
[#5249]: https://github.com/bytedance/deer-flow/pull/5249
[#5254]: https://github.com/bytedance/deer-flow/pull/5254
[#5255]: https://github.com/bytedance/deer-flow/pull/5255
[#5261]: https://github.com/bytedance/deer-flow/pull/5261
[#5264]: https://github.com/bytedance/deer-flow/pull/5264
[#5265]: https://github.com/bytedance/deer-flow/pull/5265
[#5275]: https://github.com/bytedance/deer-flow/pull/5275
[#5278]: https://github.com/bytedance/deer-flow/pull/5278
[#5280]: https://github.com/bytedance/deer-flow/pull/5280
[#5281]: https://github.com/bytedance/deer-flow/pull/5281
[#5282]: https://github.com/bytedance/deer-flow/pull/5282
[#5283]: https://github.com/bytedance/deer-flow/pull/5283
[#5284]: https://github.com/bytedance/deer-flow/pull/5284
[#5286]: https://github.com/bytedance/deer-flow/pull/5286
[#5287]: https://github.com/bytedance/deer-flow/pull/5287
[#5288]: https://github.com/bytedance/deer-flow/pull/5288
[#5289]: https://github.com/bytedance/deer-flow/pull/5289
[#5291]: https://github.com/bytedance/deer-flow/pull/5291
[#5293]: https://github.com/bytedance/deer-flow/pull/5293
[#5294]: https://github.com/bytedance/deer-flow/pull/5294
[#5296]: https://github.com/bytedance/deer-flow/pull/5296
[#5299]: https://github.com/bytedance/deer-flow/pull/5299
[#5304]: https://github.com/bytedance/deer-flow/pull/5304
[#5305]: https://github.com/bytedance/deer-flow/pull/5305
[#5306]: https://github.com/bytedance/deer-flow/pull/5306
[#5309]: https://github.com/bytedance/deer-flow/pull/5309
[#5310]: https://github.com/bytedance/deer-flow/pull/5310
[#5312]: https://github.com/bytedance/deer-flow/pull/5312
[#5315]: https://github.com/bytedance/deer-flow/pull/5315
[#5316]: https://github.com/bytedance/deer-flow/pull/5316
[#5318]: https://github.com/bytedance/deer-flow/pull/5318
[#5321]: https://github.com/bytedance/deer-flow/pull/5321
[#5323]: https://github.com/bytedance/deer-flow/pull/5323
[#5324]: https://github.com/bytedance/deer-flow/pull/5324
[#5326]: https://github.com/bytedance/deer-flow/pull/5326
[#5329]: https://github.com/bytedance/deer-flow/pull/5329
[#5332]: https://github.com/bytedance/deer-flow/pull/5332
[#5338]: https://github.com/bytedance/deer-flow/pull/5338
[#5341]: https://github.com/bytedance/deer-flow/pull/5341
[#5344]: https://github.com/bytedance/deer-flow/pull/5344
[#5347]: https://github.com/bytedance/deer-flow/pull/5347
[#5350]: https://github.com/bytedance/deer-flow/pull/5350
[#5353]: https://github.com/bytedance/deer-flow/pull/5353
[#5357]: https://github.com/bytedance/deer-flow/pull/5357
[#5359]: https://github.com/bytedance/deer-flow/pull/5359
[#5363]: https://github.com/bytedance/deer-flow/pull/5363
[#5367]: https://github.com/bytedance/deer-flow/pull/5367
[#5369]: https://github.com/bytedance/deer-flow/pull/5369
[#5371]: https://github.com/bytedance/deer-flow/pull/5371
[#5373]: https://github.com/bytedance/deer-flow/pull/5373
[#5374]: https://github.com/bytedance/deer-flow/pull/5374
[#5375]: https://github.com/bytedance/deer-flow/pull/5375
[#5377]: https://github.com/bytedance/deer-flow/pull/5377
[#5380]: https://github.com/bytedance/deer-flow/pull/5380
[#5381]: https://github.com/bytedance/deer-flow/pull/5381
[#5382]: https://github.com/bytedance/deer-flow/pull/5382
[#5384]: https://github.com/bytedance/deer-flow/pull/5384
[#5388]: https://github.com/bytedance/deer-flow/pull/5388
[#5389]: https://github.com/bytedance/deer-flow/pull/5389
[#5390]: https://github.com/bytedance/deer-flow/pull/5390
[#5392]: https://github.com/bytedance/deer-flow/pull/5392
[#5393]: https://github.com/bytedance/deer-flow/pull/5393
[#5395]: https://github.com/bytedance/deer-flow/pull/5395
[#5396]: https://github.com/bytedance/deer-flow/pull/5396
[#5397]: https://github.com/bytedance/deer-flow/pull/5397
[#5399]: https://github.com/bytedance/deer-flow/pull/5399
[#5401]: https://github.com/bytedance/deer-flow/pull/5401
[#5402]: https://github.com/bytedance/deer-flow/pull/5402
[#5403]: https://github.com/bytedance/deer-flow/pull/5403
[#5404]: https://github.com/bytedance/deer-flow/pull/5404
[#5405]: https://github.com/bytedance/deer-flow/pull/5405
[#5406]: https://github.com/bytedance/deer-flow/pull/5406
[#5407]: https://github.com/bytedance/deer-flow/pull/5407
[#5408]: https://github.com/bytedance/deer-flow/pull/5408
[#5410]: https://github.com/bytedance/deer-flow/pull/5410
[#5411]: https://github.com/bytedance/deer-flow/pull/5411
[#5413]: https://github.com/bytedance/deer-flow/pull/5413
[#5415]: https://github.com/bytedance/deer-flow/pull/5415
[#5416]: https://github.com/bytedance/deer-flow/pull/5416
[#5418]: https://github.com/bytedance/deer-flow/pull/5418
[#5419]: https://github.com/bytedance/deer-flow/pull/5419
[#5421]: https://github.com/bytedance/deer-flow/pull/5421
[#5422]: https://github.com/bytedance/deer-flow/pull/5422
[#5424]: https://github.com/bytedance/deer-flow/pull/5424
[#5426]: https://github.com/bytedance/deer-flow/pull/5426
[#5427]: https://github.com/bytedance/deer-flow/pull/5427
[#5428]: https://github.com/bytedance/deer-flow/pull/5428
[#5429]: https://github.com/bytedance/deer-flow/pull/5429
[#5431]: https://github.com/bytedance/deer-flow/pull/5431
[#5432]: https://github.com/bytedance/deer-flow/pull/5432
[#5433]: https://github.com/bytedance/deer-flow/pull/5433
[#5436]: https://github.com/bytedance/deer-flow/pull/5436
[#5439]: https://github.com/bytedance/deer-flow/pull/5439
[#5440]: https://github.com/bytedance/deer-flow/pull/5440
[#5441]: https://github.com/bytedance/deer-flow/pull/5441
[#5442]: https://github.com/bytedance/deer-flow/pull/5442
[#5443]: https://github.com/bytedance/deer-flow/pull/5443
[#5444]: https://github.com/bytedance/deer-flow/pull/5444
[#5446]: https://github.com/bytedance/deer-flow/pull/5446
[#5447]: https://github.com/bytedance/deer-flow/pull/5447
[#5448]: https://github.com/bytedance/deer-flow/pull/5448
[#5449]: https://github.com/bytedance/deer-flow/pull/5449
[#5451]: https://github.com/bytedance/deer-flow/pull/5451
[#5453]: https://github.com/bytedance/deer-flow/pull/5453
[#5454]: https://github.com/bytedance/deer-flow/pull/5454
[#5455]: https://github.com/bytedance/deer-flow/pull/5455
[#5456]: https://github.com/bytedance/deer-flow/pull/5456
[#5458]: https://github.com/bytedance/deer-flow/pull/5458
[#5459]: https://github.com/bytedance/deer-flow/pull/5459
[#5461]: https://github.com/bytedance/deer-flow/pull/5461
[#5463]: https://github.com/bytedance/deer-flow/pull/5463
[#5465]: https://github.com/bytedance/deer-flow/pull/5465
[#5467]: https://github.com/bytedance/deer-flow/pull/5467
[#5468]: https://github.com/bytedance/deer-flow/pull/5468
[#5469]: https://github.com/bytedance/deer-flow/pull/5469
[#5470]: https://github.com/bytedance/deer-flow/pull/5470
[#5474]: https://github.com/bytedance/deer-flow/pull/5474
[#5477]: https://github.com/bytedance/deer-flow/pull/5477
[#5478]: https://github.com/bytedance/deer-flow/pull/5478
[#5479]: https://github.com/bytedance/deer-flow/pull/5479
[#5480]: https://github.com/bytedance/deer-flow/pull/5480
[#5483]: https://github.com/bytedance/deer-flow/pull/5483
[#5485]: https://github.com/bytedance/deer-flow/pull/5485
[#5486]: https://github.com/bytedance/deer-flow/pull/5486
[#5488]: https://github.com/bytedance/deer-flow/pull/5488
[#5492]: https://github.com/bytedance/deer-flow/pull/5492
[#5496]: https://github.com/bytedance/deer-flow/pull/5496
[#5501]: https://github.com/bytedance/deer-flow/pull/5501
[#5504]: https://github.com/bytedance/deer-flow/pull/5504
[#5505]: https://github.com/bytedance/deer-flow/pull/5505
[#5524]: https://github.com/bytedance/deer-flow/pull/5524
[#5526]: https://github.com/bytedance/deer-flow/pull/5526
[#5534]: https://github.com/bytedance/deer-flow/pull/5534
[#5547]: https://github.com/bytedance/deer-flow/pull/5547
[#5578]: https://github.com/bytedance/deer-flow/pull/5578
[#5611]: https://github.com/bytedance/deer-flow/pull/5611
[#5673]: https://github.com/bytedance/deer-flow/pull/5673
