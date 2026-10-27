# DeerFlow 核心源码阅读路线

核对日期：2026-10-23。基线：本地 HEAD 99367100f 及当前工作区；行号是本轮定位参考，后续代码变化时按符号重新查找。

本文件是唯一学习路线：先按项目文件夹分类精读范围，再用 R 编号定位到具体函数与阅读顺序。其他学习计划已按用户要求删除，不再并行执行旧课程、算法或企业/个人轮换排期。[学习会话协议](../DEERFLOW_STUDY_PROTOCOL.md)只规定如何开始、讲解和结束，[学习日志](../learn-codebase-journal.md)是唯一进度来源。

## 学习目标与验收

- 背景：熟悉Python和后端开发，每次参考90分钟。说“开始学习”恢复同一源码停点，说“结束今天的学习”立即保存并收尾。
- 目标：读懂DeerFlow核心源码，能沿实际调用解释请求、Agent组装、模型/工具执行、状态保存和流式返回，并能定位问题和完成二次开发。
- 模块阅读按“尚未阅读、已讲解、能独立解释、能独立修改并验证”记录，明确教师支持和运行验证范围；不以读过的行数或日期晋级。
- 一个模块结束后，能说明调用者、输入输出、状态变化、正常/失败分支，并用一个变化场景检查理解。需要改动时遵守仓库TDD和文档要求。
- 最终用一个范围明确的小功能验证跨模块理解，包含独立实现、测试、故障定位、设计说明与新需求变化；不要求记住所有适配器源码。
- 旧DF单元及等级仅作为日志中的历史证据保留，不再按已删除的60单元课程排课。实际进度只查日志，不在本文件另开第二份进度表。

## 按项目文件夹分类

下表 Harness 目录均位于 backend/packages/harness/deerflow/；App 和前端单独标全路径。精读一个目录指系统读懂其核心入口、接口、控制流、状态变化和错误处理；其中重复的供应商/后端适配器先选一个实现读通，再比较其他实现的差异。

### 第一组：必须系统精读的主干

用户指定的 agents、models、runtime、sandbox、subagents、tools 六个目录全部列入本组；补充配置来源 config 和请求入口 backend/app/gateway。

| 文件夹 | 必须精读的范围 | 优先入口 |
| --- | --- | --- |
| [agents/](../../backend/packages/harness/deerflow/agents/) | 主 Agent 组装、提示词、中间件生命周期、ThreadState/reducer；记忆主接口随后专题读 | lead_agent/agent.py、lead_agent/prompt.py、thread_state.py、middlewares/ |
| [models/](../../backend/packages/harness/deerflow/models/) | 模型选择、参数合并、provider 实例化，以及对象创建与实际推理调用的关系 | factory.py 的 create_chat_model |
| [runtime/](../../backend/packages/harness/deerflow/runtime/) | Run 管理、worker、图流消费、事件桥、序列化、Checkpoint 访问、事件历史及终态 | runs/worker.py、runs/manager.py，再到 stream_bridge/、checkpoint_state.py、events/ |
| [sandbox/](../../backend/packages/harness/deerflow/sandbox/) | 工具到执行环境的调用、文件/命令接口、获取/复用/释放、Runtime 与状态更新 | tools.py、sandbox.py、sandbox_provider.py、middleware.py |
| [subagents/](../../backend/packages/harness/deerflow/subagents/) | 子代理类型、执行器、父子输入与结果、并发/取消/超时和生命周期 | builtins/、executor.py；入口工具另在 tools/builtins/task_tool.py |
| [tools/](../../backend/packages/harness/deerflow/tools/) | 工具注册、参数 schema、运行上下文、内置工具、调用结果和 Command | tools.py、types.py、builtins/present_file_tool.py、builtins/task_tool.py |
| [config/](../../backend/packages/harness/deerflow/config/) | 配置加载、优先级、环境变量、运行覆盖、模型/沙箱等关键配置结构 | app_config.py，再按模型、工具、沙箱专题读对应配置类 |
| [backend/app/gateway/](../../backend/app/gateway/) | HTTP 参数校验、启动 Run、上下文准备、SSE 返回、状态查询与取消接口 | app.py、run_models.py、routers/thread_runs.py、services.py |

### 第二组：学到对应功能时精读核心接口和主流程

这些目录直接影响二次开发，安排独立源码章节，但不要求在当前 worker 章节一次读完全部实现。

| 文件夹 | 精读内容与边界 |
| --- | --- |
| [skills/](../../backend/packages/harness/deerflow/skills/) | 发现、解析、加载、激活与工具策略；安装和扫描再按需求展开 |
| [mcp/](../../backend/packages/harness/deerflow/mcp/) | 工具发现、名称映射、调用与错误返回；OAuth、会话池和后台任务作为后续专题 |
| [extensions/](../../backend/packages/harness/deerflow/extensions/) | 插件加载、贡献注册、生命周期契约；安装事务和打包后读 |
| [persistence/](../../backend/packages/harness/deerflow/persistence/) | Run/事件/线程等数据模型与仓储契约，选一个数据库实现；迁移和事务在持久化章节展开 |
| [authz/](../../backend/packages/harness/deerflow/authz/) | 请求身份、授权 provider、工具筛选与用户/线程边界；先跟实际主路径再读策略实现 |
| [frontend/src/core/](../../frontend/src/core/) | 重点读 threads/、api/、artifacts/，理解提交、流消费、状态合并和文件读取；React 组件按调用跟进 |
| [backend/app/scheduler/](../../backend/app/scheduler/) | 调度进入普通 Run 的公共流程，再读一个队列/恢复场景 |
| [backend/app/channels/](../../backend/app/channels/) | 公共消息到 Run 的流程，再选一个平台适配器完整追踪 |

### 第三组：跟随调用或选择代表实现阅读

- [community/](../../backend/packages/harness/deerflow/community/)：选当前任务使用的模型/沙箱/外部工具实现精读，其他集成比较接口和差异。
- [agents/memory/backends/](../../backend/packages/harness/deerflow/agents/memory/backends/)：先读 MemoryManager 契约和一种实现，其余后端做迁移阅读。
- [tracing/](../../backend/packages/harness/deerflow/tracing/)、[utils/](../../backend/packages/harness/deerflow/utils/)：在调用主线中按需要读，不逐个工具函数开课。
- [docker/](../../docker/)、[scripts/](../../scripts/)、根 [Makefile](../../Makefile)：部署与排障章节读实际使用的启动链及代理配置。
- [backend/tests/](../../backend/tests/)、[frontend/tests/](../../frontend/tests/)：每个模块配套读代表性正常与失败用例；不是等全项目读完才看测试。

按已有进度，近期以 runtime 的 worker 为起点，进入 agents，再跟进 models/config、tools、sandbox、subagents；运行状态和持久化回到 runtime 深化。skills/MCP 等按章节穿插。下一段实际源码仍是 worker 的 Agent 构建调用，具体停点只在学习日志更新。

## 阅读方式

- 主要活动是阅读真实源码，像此前 worker 一样逐段讲解，按需要逐行分析。先给调用背景，再讲参数来源、执行顺序、返回值、状态变化和关键分支。
- 每次围绕一个连续代码段，通常约 10～40 行；遇到被调函数可进入精读，读完返回原函数停点。不能只解释函数名而跳过实际控制流。
- 普通 import、重复日志和未启用的适配器可以说明用途后略读；核心分支和用户追问要展开。大文件分段完成，不要求一口气读完整文件。
- 一个模块讲清后做少量复述、变化练习或读测试。生成 study.md 是贯穿案例，不要求每轮抄网络字段或先完成填空才能继续。
- 源码事实、合成示例和真实运行分别说明；阅读或教师解释不自动等于独立掌握。

## 阅读顺序总览

R01–R03 先建立请求到执行和返回的骨架，再从工厂调用进入 R04–R07；R08–R12 深化状态、协作与应用，R13 汇合到二次开发。编号用于定位，不强制按数字压平函数调用关系。

| 编号 | 主题 |
| --- | --- |
| R01 | Gateway 应用与 HTTP 入口 |
| R02 | 创建 Run 与安排后台执行 |
| R03 | worker 执行与事件返回（当前衔接） |
| R04 | 配置解析与模型对象 |
| R05 | 主 Agent 组装与中间件 |
| R06 | 工具、Runtime、沙箱与文件产物 |
| R07 | Skill、MCP 与 Python 扩展 |
| R08 | 状态、运行终态与持久化 |
| R09 | 上下文与长期记忆 |
| R10 | 子 Agent 委派与执行 |
| R11 | 前端提交、流消费与产物 |
| R12 | 其他入口、部署和运行保障 |
| R13 | 嵌入式调用与独立二次开发 |

当前衔接建议：R01/R02 只定位已讲过的交接点；从 R03 的 run_agent 构建 Agent 段续读，遇到 agent_factory 调用进入 R05，模型/配置问题关联 R04，最后返回 worker 消费图流。已经讲过的 _publish_stream_item、模式、批处理与 seq 等记录继续使用，不要求重来。

## R01 Gateway 应用与 HTTP 入口

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [应用启动](../../backend/app/gateway/app.py) | create_app L594；lifespan L198 | 应用实例、启动初始化、路由挂载。 |
| [请求模型](../../backend/app/gateway/run_models.py) | RunCreateRequest L14 | input/config/context/stream_mode 等字段与校验。 |
| [运行路由](../../backend/app/gateway/routers/thread_runs.py) | stream_run L872 | 接收请求、调用 start_run、返回 StreamingResponse。 |

后续专题：历史分页、编辑重跑、归档和完整账户初始化。

## R02 创建 Run 与安排后台执行

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [请求到运行](../../backend/app/gateway/services.py) | resolve_agent_factory L605；start_run L1226 | 输入与配置准备；create_or_reject L1465；create_task L1491。 |
| [运行记录与管理](../../backend/packages/harness/deerflow/runtime/runs/manager.py) | RunRecord L156；create_or_reject L1424；try_start L819 | 运行 ID、状态、后台 Task、取消信号；接纳与开始执行的区别。 |

后续专题：多实例租约、持久化重试、并发准入细节在 R08 复读。

## R03 worker 执行与事件返回（当前衔接）

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [执行主流程](../../backend/packages/harness/deerflow/runtime/runs/worker.py) | run_agent L761；_stream_once L1187；_publish_stream_item L2909 | 构建 Agent、调用/消费 astream、发布事件、处理结果和结束。 |
| [模式映射](../../backend/packages/harness/deerflow/runtime/stream_modes.py) | normalize_stream_modes L28；to_langgraph_stream_modes L43 | 公共模式到图模式的映射，可完整精读。 |
| [数据序列化](../../backend/packages/harness/deerflow/runtime/serialization.py) | serialize L134；serialize_messages_tuple L126 | 图对象如何变为 JSON 友好的结构；消息与其他模式的分派。 |
| [事件桥接口](../../backend/packages/harness/deerflow/runtime/stream_bridge/base.py) | publish L82；publish_end L86；subscribe L90 | 生产、订阅、结束三种动作。 |
| [桥的内存实现](../../backend/packages/harness/deerflow/runtime/stream_bridge/memory.py) | publish L108；subscribe L125 | 事件入缓冲、通知等待者、按游标消费。 |
| [SSE 输出](../../backend/app/gateway/services.py) | sse_consumer L1669；format_sse | 订阅 Bridge，将事件编码为 HTTP SSE。 |

后续专题：Redis 桥、回滚、goal 续跑和交付收据分支在对应专题再深入。已讲过的批处理、seq 和解包保留笔记，按调用点复习。

### runs 文件夹内部的阅读顺序

对应目录：backend/packages/harness/deerflow/runtime/runs/。manager.py 分两遍读，先认识它交给 worker 的数据和接口，再结合真实执行理解状态与控制，避免一开始停在重试、租约和锁实现中。

| 顺序 | 源码位置 | 具体阅读范围 |
| --- | --- | --- |
| 1 | [__init__.py](../../backend/packages/harness/deerflow/runtime/runs/__init__.py) | 快速浏览对外导出的类和函数，只建立目录地图 |
| 2 | [schemas.py](../../backend/packages/harness/deerflow/runtime/runs/schemas.py) | 短文件可完整精读；RunStatus 六种状态、DisconnectMode、ThreadOperationKind |
| 3 | [manager.py 的 RunRecord](../../backend/packages/harness/deerflow/runtime/runs/manager.py) 与 [worker.py 的 RunContext](../../backend/packages/harness/deerflow/runtime/runs/worker.py) | RunRecord L156：ID、status、task、abort_event及错误；RunContext L568：checkpointer、store、event_store等执行依赖。分别认识“本次运行记录”与“执行用基础设施” |
| 4 | [worker.py 的 run_agent](../../backend/packages/harness/deerflow/runtime/runs/worker.py) | 沿主流程：开始屏障→准备上下文→构建Agent→_stream_once消费图流→完成或异常→finally收尾；已学发布辅助函数按调用复习 |
| 5 | [manager.py 的 RunManager](../../backend/packages/harness/deerflow/runtime/runs/manager.py) | 第二遍读create_or_reject L1424、try_start L819、set_status L917、set_status_if_not_cancelled L976、cancel L1235、cleanup L1874，结合worker调用解释状态转换；shutdown随后读 |
| 6 | [store/base.py](../../backend/packages/harness/deerflow/runtime/runs/store/base.py) → [store/memory.py](../../backend/packages/harness/deerflow/runtime/runs/store/memory.py) | 先RunStore契约，再用MemoryRunStore读懂put/get/list_by_thread、start_run/update_status和运行摘要更新。保存的是Run元数据/状态，不是文件正文或图Checkpoint |
| 7 | [naming.py](../../backend/packages/harness/deerflow/runtime/runs/naming.py) | 按run_agent中的调用完整读小函数resolve_root_run_name；它为LangChain/LangSmith追踪选择根运行名，不负责生成聊天标题 |

首次精读主线后，再回到manager的准入冲突、持久化失败和取消传播；租约、心跳、多实例接管、worker回滚/goal续跑/交付收据作为后续专题。它们不是不读，而是在理解正常Run之后补齐。

当前衔接：此前主要讲过worker的流事件处理，先短读schemas与RunRecord/RunContext补齐词汇和参数来源，再回到worker.py:1084的Agent工厂调用，不重讲已读的_publish_stream_item。每次只围绕一个真实代码段讲解，模块完成后再验证理解。

## R04 配置解析与模型对象

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [应用配置](../../backend/packages/harness/deerflow/config/app_config.py) | AppConfig L185；from_file L405；get_app_config L672 | 配置路径、结构、加载、模型选择与缓存入口；只用 example 和实现学习。 |
| [模型工厂](../../backend/packages/harness/deerflow/models/factory.py) | create_chat_model L174 | 选择配置、解析 provider、合并参数、创建模型实例；区分创建对象与调用推理。 |

后续专题：provider 专用参数、热更新细节和 tracing。

## R05 主 Agent 组装与中间件

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [主组装入口](../../backend/packages/harness/deerflow/agents/lead_agent/agent.py) | make_lead_agent L757；assemble_lead_agent L762；create_agent 调用 L1186 | 沿常规分支读模型、工具、middleware、prompt、state_schema 怎样组成图。 |
| [系统提示词](../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py) | apply_prompt_template L1061；get_skills_prompt_section L872 | 框架指令、技能说明、记忆和委派说明的来源。 |
| [错误处理中间件](../../backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py) | ToolErrorHandlingMiddleware L56 | 工具调用包裹、普通异常与图控制异常、共享中间件链。 |
| [线程准备中间件](../../backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py) | ThreadDataMiddleware L24；before_agent L82 | 执行前准备 workspace/uploads/outputs 及状态。 |
| [上传上下文](../../backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py) | _create_files_message L120；before_agent L202 | 上传元数据怎样变为模型能使用的文件上下文。 |

后续专题：bootstrap、完整授权链和全部内置中间件。图内部的模型/工具调度部分由 LangChain/LangGraph 实现，不能把依赖代码当成本仓库实现。

## R06 工具、Runtime、沙箱与文件产物

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [工具集合](../../backend/packages/harness/deerflow/tools/tools.py) | get_available_tools L59 | 配置工具、内置工具、外部工具的组合与去重，回到主 Agent 工厂继续筛选。 |
| [工具运行上下文](../../backend/packages/harness/deerflow/tools/types.py) | Runtime L11 | ToolRuntime 的类型别名、context 与 state；与图运行时 Runtime 分清。 |
| [文件和命令工具](../../backend/packages/harness/deerflow/sandbox/tools.py) | read_file_tool L2422；write_file_tool L2517；ensure_sandbox_initialized_async L1609 | 模型参数、运行上下文、异步包装，到 sandbox.write_file 的真实调用。 |
| [执行环境接口](../../backend/packages/harness/deerflow/sandbox/sandbox.py) | Sandbox L44；write_file L183 | 工具最终调用哪些文件和命令能力。 |
| [执行环境生命周期](../../backend/packages/harness/deerflow/sandbox/sandbox_provider.py) | SandboxProvider L14；get_sandbox_provider L161 | acquire/get/release 与 provider 选择；接口不保证每个会话都新建容器。 |
| [沙箱中间件](../../backend/packages/harness/deerflow/sandbox/middleware.py) | SandboxMiddleware L51；abefore_agent L350；aafter_agent L460 | 惰性初始化、状态回写与资源收尾。 |
| [产物登记](../../backend/packages/harness/deerflow/tools/builtins/present_file_tool.py) | present_file_tool L84；Command 更新 L116 | 文件写入与 artifacts/messages 状态更新的边界，可完整精读。 |

后续专题：先对一个实际 provider 深读，再比较其他 provider；路径授权、池、租约和输出截断按专题展开。

## R07 Skill、MCP 与 Python 扩展

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [技能发现](../../backend/packages/harness/deerflow/skills/storage/skill_storage.py) | SkillStorage.load_skills L277 | 目录发现、覆盖、启用状态与加载。当前入口已不是旧 skills/loader.py。 |
| [技能解析](../../backend/packages/harness/deerflow/skills/parser.py) | parse_skill_file L190 | SKILL.md、frontmatter、allowed-tools 到运行时 Skill。 |
| [MCP 工具](../../backend/packages/harness/deerflow/mcp/tools.py) | get_mcp_tools L745 | 服务器配置、工具发现与 Agent 可用工具，随后跟进一次调用。 |
| [Python 扩展](../../backend/packages/harness/deerflow/extensions/loader.py) | load_extensions L150 | 扩展导入、贡献注册和加载错误，与 MCP 传输方式区分。 |

后续专题：激活策略中间件按调用跟进；远程安装、安全扫描、OAuth、会话池和扩展安装事务另开专题。

## R08 状态、运行终态与持久化

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [图状态与合并](../../backend/packages/harness/deerflow/agents/thread_state.py) | ThreadState L277；merge_artifacts L90 | 状态字段、Annotated/reducer，预测多次更新结果。 |
| [状态访问边界](../../backend/packages/harness/deerflow/runtime/checkpoint_state.py) | CheckpointStateAccessor L112 | bind/aget/ahistory/aupdate；图与 checkpointer 结合后怎样读取和修改状态。 |
| [Checkpoint 实现选择](../../backend/packages/harness/deerflow/runtime/checkpointer/provider.py) | get_checkpointer L196；checkpointer_context L268 | 持久化后端和生命周期，首次只读一个配置分支。 |
| [事件和消息历史](../../backend/packages/harness/deerflow/runtime/events/store/base.py) | RunEventStore L46 | put/list_messages/list_events；与 checkpoint、文件存储和临时 Bridge 对照。 |

后续专题：回读 RunManager/worker 的成功、失败、取消和 finally；再选一个存储实现。delta 通道、迁移、租约和竞争场景最后专题阅读。

## R09 上下文与长期记忆

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [记忆契约](../../backend/packages/harness/deerflow/agents/memory/manager.py) | MemoryManager L102；get_memory_manager L914 | add/get_context/search 与后端选择。 |
| [记忆生命周期接点](../../backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py) | MemoryMiddleware L29；aafter_agent L109 | 一轮 Agent 执行与长期记忆读写怎样连接。 |
| [一种记忆实现](../../backend/packages/harness/deerflow/agents/memory/backends/deermem/deer_mem.py) | DeerMem L94 | 沿 add/get_context/search 读队列交接和上下文形成。 |

后续专题：摘要在提示词/中间件调用处接入；再深入默认记忆后端 core，其他后端适配器按一个新案例迁移。

## R10 子 Agent 委派与执行

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [模型可见的委派工具](../../backend/packages/harness/deerflow/tools/builtins/task_tool.py) | task_tool L646；execute_async 调用 L924 | 参数、委派请求、结果返回和父状态更新。 |
| [子任务执行器](../../backend/packages/harness/deerflow/subagents/executor.py) | SubagentExecutor L765；_aexecute L1285；execute_async L1764 | 子 Agent 的输入、上下文、工具筛选、执行和结果。 |

后续专题：先看 builtins 的 general-purpose/bash 类型，再读批次、并发限制、预算、取消和清理。

## R11 前端提交、流消费与产物

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [聊天主 Hook](../../frontend/src/core/threads/hooks.ts) | useThreadStream L1619；thread.submit 调用 L2259 | 提交输入、运行身份、接收消息/事件与结束回调。 |
| [请求模式](../../frontend/src/core/api/stream-mode.ts) | CHAT_RUN_STREAM_MODES；forceChatRunStreamOptions | 前端订阅哪些模式，如何与后端映射对应。 |
| [状态增量合并](../../frontend/src/core/threads/stream-state.ts) | reduceThreadStateUpdates L54 | updates 怎样改变标题、文件、todos 等 UI 状态；消息拼接另由 SDK 负责。 |
| [产物内容](../../frontend/src/core/artifacts/loader.ts) | loadArtifactContent L50；loadArtifactContentFromToolCall L118 | 最终文件 HTTP 读取和 write_file 流式预览。 |
| [API 兼容包装](../../frontend/src/core/api/api-client.ts) | createCompatibleClient L326 | 普通提交读通后，再看 SDK 请求包装、重连和兼容处理。 |

后续专题：分页历史、编辑重跑、缓存、各类媒体组件与完整 SDK 内部。

## R12 其他入口、部署和运行保障

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [调度入口](../../backend/app/scheduler/service.py) | ScheduledTaskService L28；run_once L56；dispatch_task L111 | 定时任务如何通过 _launch_run 回到 Gateway 的普通 Run 入口。 |
| [IM 消息入口](../../backend/app/channels/manager.py) | ChannelManager L1013；_handle_message L1889 | 消息怎样进入 client.runs.wait/stream，先读公共流程再选一个平台。 |
| [统一 HTTP 入口](../../docker/nginx/nginx.local.conf) | /api/langgraph 路径改写与 upstream | 回顾前端、Gateway、Nginx 和端口之间的真实关系。 |
| [本地编排](../../Makefile) | config/install/dev/start/stop | 启动脚本与各服务的边界；深入时跟进 scripts 中实际调用。 |

后续专题：授权从 authz 契约和工具筛选处回读；调度租约、IM 平台适配、容器配置和诊断工具各选代表案例。

## R13 嵌入式调用与独立二次开发

| 文件 | 首读符号 / 参考行号 | 重点读什么 |
| --- | --- | --- |
| [Python 调用入口](../../backend/packages/harness/deerflow/client.py) | DeerFlowClient | 对照 HTTP 入口找共用执行能力，追一次输入和输出。 |
| [程序化组装入口](../../backend/packages/harness/deerflow/agents/factory.py) | create_deerflow_agent L66 | 接收现成模型/工具对象的另一条组装路径；它不是 assemble_lead_agent 的下一层。 |
| [组装说明](../../backend/packages/harness/deerflow/agents/assembly_descriptor.py) | build_assembly_descriptor L441 | 观察最终模型、工具、中间件和提示词信息；理解后再考虑扩展观察者。 |

后续专题：结合此前源码实现有边界的小功能，按正常/边界/失败场景写行为测试，再完成一个未演示变化。

## 当前 worker 的具体续读建议

下一次先读 worker.py 中 agent_factory_kwargs 到 agent 构建的实际代码（本轮 L1084–1090），追清 config、可选 app_config、构建期扩展上下文与工厂返回值；必要时回看上方 Runtime/config 准备段。接着从 agent_factory 的来源进入 assemble_lead_agent，围绕模型、工具、中间件、提示词和 state_schema 逐段读。返回 worker 后接 _stream_once/astream 调用，最后连上正常结束、异常与 finally。

run_agent 的分段地图：

1. 参数、RunContext 依赖、run_id/thread_id。
2. 开始屏障、状态与运行上下文准备。
3. config/Runtime、回调与 Agent 工厂调用。
4. _stream_once：创建图流、消费、发布、流收尾。
5. 正常完成、普通异常、取消的不同处理。
6. finally：状态和持久化收尾、发布结束事件、清理。

此前 await 填空尚未作答，转为后续相关复习，不作为这条源码路线的进入条件。具体已读/未读和理解证据以日志为准。

## 配套测试的阅读入口

以下文件已确认存在，本次只核对位置，没有运行测试。每个模块先选最小正常案例，再对照一个边界或失败案例；后端修改遵守模块的 TDD 要求。

- [Gateway 的交接与 SSE：test_gateway_services.py](../../backend/tests/test_gateway_services.py)
- [Run 接纳和状态：test_run_manager.py](../../backend/tests/test_run_manager.py)
- [Bridge 发布与订阅：test_stream_bridge.py](../../backend/tests/test_stream_bridge.py)
- [Agent 组装与模型选择：test_lead_agent_model_resolution.py](../../backend/tests/test_lead_agent_model_resolution.py)
- [状态 reducer：test_thread_state_reducers.py](../../backend/tests/test_thread_state_reducers.py)
- [工具错误处理：test_tool_error_handling_middleware.py](../../backend/tests/test_tool_error_handling_middleware.py)
- [文件产物登记：test_present_file_tool_core_logic.py](../../backend/tests/test_present_file_tool_core_logic.py)
- [扩展加载：test_extension_loader.py](../../backend/tests/test_extension_loader.py)
- [Checkpoint 状态访问：test_checkpoint_state.py](../../backend/tests/test_checkpoint_state.py)
- [子 Agent 执行：test_subagent_executor.py](../../backend/tests/test_subagent_executor.py)
- [记忆更新：test_memory_updater.py](../../backend/tests/test_memory_updater.py)
- [前端增量状态：incremental-stream-state.dom.test.tsx](../../frontend/tests/unit/core/threads/incremental-stream-state.dom.test.tsx)

进入某模块前按根 AGENTS.md 读取其模块指南。测试位置不是已经通过的证据；涉及真实模型、数据库或沙箱时单独记录验证范围。学习过程不读取或展示真实配置中的凭据。

