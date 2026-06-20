# 更新日志

本文件记录 DeerFlow 的所有重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本规范](https://semver.org/lang/zh-CN/)。

[English](./CHANGELOG.md) | 中文

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
[#3393]: https://github.com/bytedance/deer-flow/pull/3393
[#3397]: https://github.com/bytedance/deer-flow/pull/3397
[#3398]: https://github.com/bytedance/deer-flow/pull/3398
[#3408]: https://github.com/bytedance/deer-flow/pull/3408
[#3410]: https://github.com/bytedance/deer-flow/pull/3410
[#3411]: https://github.com/bytedance/deer-flow/pull/3411
[#3413]: https://github.com/bytedance/deer-flow/pull/3413
[#3417]: https://github.com/bytedance/deer-flow/pull/3417
[#3421]: https://github.com/bytedance/deer-flow/pull/3421
[#3423]: https://github.com/bytedance/deer-flow/pull/3423
[#3425]: https://github.com/bytedance/deer-flow/pull/3425
[#3426]: https://github.com/bytedance/deer-flow/pull/3426
[#3430]: https://github.com/bytedance/deer-flow/pull/3430
[#3433]: https://github.com/bytedance/deer-flow/pull/3433
[#3434]: https://github.com/bytedance/deer-flow/pull/3434
[#3435]: https://github.com/bytedance/deer-flow/pull/3435
[#3436]: https://github.com/bytedance/deer-flow/pull/3436
[#3437]: https://github.com/bytedance/deer-flow/pull/3437
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
[#3553]: https://github.com/bytedance/deer-flow/pull/3553
[#3554]: https://github.com/bytedance/deer-flow/pull/3554
[#3559]: https://github.com/bytedance/deer-flow/pull/3559
[#3561]: https://github.com/bytedance/deer-flow/pull/3561
[#3569]: https://github.com/bytedance/deer-flow/pull/3569
[#3570]: https://github.com/bytedance/deer-flow/pull/3570
[#3575]: https://github.com/bytedance/deer-flow/pull/3575
[#3577]: https://github.com/bytedance/deer-flow/pull/3577
[#3578]: https://github.com/bytedance/deer-flow/pull/3578
[#3579]: https://github.com/bytedance/deer-flow/pull/3579
[#3580]: https://github.com/bytedance/deer-flow/pull/3580
[#3581]: https://github.com/bytedance/deer-flow/pull/3581
[#3582]: https://github.com/bytedance/deer-flow/pull/3582
[#3583]: https://github.com/bytedance/deer-flow/pull/3583
[#3584]: https://github.com/bytedance/deer-flow/pull/3584
[#3591]: https://github.com/bytedance/deer-flow/pull/3591
[#3599]: https://github.com/bytedance/deer-flow/pull/3599
[#3600]: https://github.com/bytedance/deer-flow/pull/3600
[#3602]: https://github.com/bytedance/deer-flow/pull/3602
[#3605]: https://github.com/bytedance/deer-flow/pull/3605
[#3606]: https://github.com/bytedance/deer-flow/pull/3606
[#3608]: https://github.com/bytedance/deer-flow/pull/3608
[#3610]: https://github.com/bytedance/deer-flow/pull/3610
[#3611]: https://github.com/bytedance/deer-flow/pull/3611
[#3623]: https://github.com/bytedance/deer-flow/pull/3623
[#3624]: https://github.com/bytedance/deer-flow/pull/3624
[#3629]: https://github.com/bytedance/deer-flow/pull/3629
[#3631]: https://github.com/bytedance/deer-flow/pull/3631
[#3646]: https://github.com/bytedance/deer-flow/pull/3646
[#3649]: https://github.com/bytedance/deer-flow/pull/3649
[#3654]: https://github.com/bytedance/deer-flow/pull/3654
[#3657]: https://github.com/bytedance/deer-flow/pull/3657
[#3658]: https://github.com/bytedance/deer-flow/pull/3658
