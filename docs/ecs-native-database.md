# 原生 ECS 工作池库表说明

更新：2026-10-09。B/C 基础字段核对自已审查代码；下述 Task5 依赖字段已通过主干、离线回归和独立 SPEC/质量复审。旧 docs/ecs-fleet-database.md 属于上一版 Fleet，不能作为本次重做的部署 schema。

## 数据权威与逻辑关系

| 数据 | 权威存储 | 责任 |
| --- | --- | --- |
| 用户、线程 incarnation | 原生 users、threads_meta | 权限、线程生命周期 |
| Agent Run | 原生 runs | 准入、状态、owner、取消、幂等 |
| Agent 状态与目标 | 原生 LangGraph checkpoint | 消息、工具结果、GoalState、累计预算 |
| 事件和实时桥 | 原生 DB run events + Redis | 历史、跨实例流和 END |
| B 用户任务 | 原生 mcp_tasks | 远程 handle、轮询、结果、通知、取消重试 |
| B/C 物理执行 | ecs_execution_jobs | 队列、assignment、资源预留、start/STOP 与清理 |
| 节点配置与心跳 | ecs_execution_nodes | 操作者容量定义和已观察的活动 |
| 线程执行节点 | ecs_native_affinities | owner/thread/incarnation 固定节点 |

B 通过 mcp_tasks.remote_task_id 对应 ecs_execution_jobs.id；C 通过执行记录的 native.run_id 对应原生 runs.run_id。它们是跨组件逻辑关联，没有跨库外键。执行服务不直接写 mcp_tasks；跨库不能假设原子提交，需要幂等、持久意图和恢复。

## ecs_execution_jobs

定义：backend/packages/ecs-executor/ecs_executor/job_store.py。

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| id | String(64) | 主键，opaque job ID |
| namespace | String(64) | 非空；B 为可信身份摘要，C 为 native-C |
| request_key | String(128) | 非空；B 为请求键，C 为原生 Run ID |
| version | Integer | 非空；乐观 CAS 版本 |
| state | String(32) | 非空，索引；执行队列状态 |
| record | JSON | 非空；不可变 spec、身份及物理执行记录 |

唯一约束 uq_ecs_execution_request(namespace, request_key)。同键不同 spec_digest 拒绝；重试不生成第二个执行。mutate 使用 id+version CAS，terminal 状态不能复活。

| record 字段组 | 主要字段 | 含义 |
| --- | --- | --- |
| 共同身份 | kind、id、created_at、spec_digest | B/C 类型和不可变请求摘要 |
| B 原生范围 | user_id、thread_id、incarnation、run_id | 来自签名 native submit，不能由模型授权 |
| C 原生快照 | native、affinity_node、node_budget | 同一原生 Run 的执行信息和选定节点预算 |
| 执行规格 | spec、profile | 命令/输入/profile 及 CPU、内存等限制 |
| 暂存 | staged_deadline | 未完成本地持久跟踪的暂存到期边界 |
| 分配 | node_id、worker_owner、generation、attempt、lease_until | 所属节点及报告 fence |
| 启动/取消 | start_intent、started_at、cancel_requested | 未知启动禁止重放 |
| 物理收尾 | physical_stopped、physical_stopped_at、cleanup_pending | 资源释放和终态清理证据；时间戳用于核对 C 收尾后 B 才启动 |
| C 跨库收尾 | settlement_pending、settlement_kind、settlement_error、settlement_cancel_action | 原生 terminal commit / END / 执行账收尾的恢复意图 |
| 依赖等待 | dependency_wait | Task5 的原生任务成员、目标快照、可见消息签名与续跑 Run 关联；非目标权威 |
| 结果 | error、exit_code、artifact、native_artifact_uri | 程序/执行结果和原生文件引用 |

状态：staged → queued → starting → running → completed/failed/cancelled；starting/running 的未知结果可以进入 uncertain。取消未启动的任务可直接终止；已启动的任务不能跳过物理确认。终态结果可能保留 cleanup_pending，不能把业务结果终态当作容器已删除。

容量查询在 SQL 中汇总同节点未 physical_stopped 的 CPU、内存和数量，包含 B 和 C。FIFO claim 在 SQL 中筛选 kind/profile/affinity/容量后 LIMIT 1；不先加载历史大 payload。C settlement recovery 按 JSON 标记筛选，单次上限 100。

## ecs_execution_nodes

定义：ecs_executor/scheduling.py。

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| id | String(64) | 主键，操作者固定节点 ID |
| record | JSON | 非空；config 与 heartbeat_at |

config 保存 cpu_millis、memory_mib、resident_cpu_millis、resident_memory_mib、max_concurrency、profiles、kinds、drain、worker_version。配置由操作者提供，节点心跳本身不释放未知执行。

共享准入使用 PostgreSQL advisory transaction lock 731908241；单机测试 SQLite 使用 BEGIN IMMEDIATE。先计算剩余额度，再持久 assignment；不是依据瞬时 CPU 空闲率调度。

## ecs_native_affinities

定义：ecs_executor/agent_dispatch.py。

| 列 | 类型 | 约束 / 用途 |
| --- | --- | --- |
| user_id | String(255) | 联合主键 |
| thread_id | String(255) | 联合主键 |
| incarnation | String(255) | 联合主键，隔离同名重建线程 |
| node_id | String(64) | 非空，固定执行节点 |

以原生 owner/thread/incarnation 定位；并发 INSERT ON CONFLICT DO NOTHING 后核对已有节点。既有 affinity 不静默迁移，避免丢失保温沙箱及浏览器等状态。节点失效后的恢复/迁移需要明确物理与状态协议。

## 复用原生 runs 与 mcp_tasks

runs 保留 run_id、thread_id、user_id、status、owner_worker_id、lease_expires_at、cancel_action、cancel_requested_at、idempotency_key、goal_verdict、metadata_json、kwargs_json、token usage 等。uq_runs_thread_active 对 pending/running 的 thread_id 建唯一索引；uq_runs_idempotency_key 保证重复准入复用同一 Run。

C 不新增平行 Run。pending 所有权通过用户、线程、owner、状态及取消 fence 交接；执行接管后沿用原生 pending→running CAS、heartbeat 与 terminal 持久化。取消采用原生 first-action-wins。

mcp_tasks 保留本地 id、user/thread/incarnation/run/tool_call、server/driver/remote_task_id，以及 status/result、轮询、取消和 notification 的各自 lease/token/version/attempt。uq_mcp_tasks_user_server_remote 防止重复追踪远程 handle；due 索引分别覆盖 poll、cancel 和 notification。

通知持久记录 dispatch_version、dispatch_attempt、dispatch_event、notification_run_id；C→B→C 必须复用这条通知身份和恢复机制，不能另设第二条投递通道。

## Goal 与 Scheduler

GoalState 存在原生 checkpoint：objective、status、created_at、updated_at、continuation_count/max_continuations、no_progress_count/max_no_progress_continuations、last_evaluation。不是新 goal 表，不能把执行账里的快照当作最新目标权威。

Scheduler 复用 scheduled_tasks 与 scheduled_task_runs，active occurrence 的 queued/launching/running 唯一保护、租约和全局预算仍由原生仓库管理。Task5 通过 scheduled_task_runs.run_id 和 scheduled_tasks.last_run_id 将同一 occurrence 移交给续跑 Run，不新增 occurrence 或重记 run_count。移交在原生 pending Run 准入之后、执行队列可见之前完成，事务先锁父 task，再锁 occurrence，并核对 owner/thread/任务关联及源 Run 的成功、等待和取消状态。

### dependency_wait：原生依赖合同

字段存于 C 的 ecs_execution_jobs.record，不新增 goal 表或通知表：

| 字段 | 含义 |
| --- | --- |
| source_run_id | 原生等待来源 Run |
| task_ids | 同 owner/thread/incarnation/run 的原生 mcp_tasks 成员 |
| goal | 原生 GoalState 快照，用于识别目标及累计预算 |
| conversation_signature | 可见消息签名，用于识别等待后的新用户消息 |
| active | 等待凭据是否仍有效 |
| continuation_run_id | 已准入续跑的原生 Run ID，用于恢复确认 |

续跑幂等键为 mcp-dependencies:<source_run_id>，使用原生 runs 的既有幂等查询和准入；本字段写回失败时，恢复先查询原生 Run。通知仍使用 mcp_tasks 的 dispatch_version/dispatch_attempt/dispatch_event 和现有 launcher。所有成员终态后才允许续跑，并在执行时再次核对最新原生 checkpoint，以 CAS 累加原目标预算。

原生 Run 的 goal_verdict.native_dependency_wait 表示此执行已持久记下等待，不能单独作为无限占位依据。恢复先只读快照需要检查的 scheduled source，再由扩展精确检查当前凭据、目标、消息、取消和 occurrence 关联，区分 checked 与 valid Run ID；原生仓库在锁内再次核对身份。刚完成但未检查的 source 延后一轮，租约接管 CAS 败给并发成功时也重做同一保护判定。续跑 Run 已创建但尚未关联 occurrence 时，原等待仅在有效租约与目标下暂保留；关联已完成才确认续跑。过期准入复用原生租约 CAS 收敛。无扩展或已检查但无有效凭据时正常结算，不永久保留历史标记。过期结果采用内部 notification_only 策略，经同一通知路径展示，禁用工具执行和目标续跑，不改写当前目标。

## 初始化、迁移与旧版兼容

执行器使用独立数据库和版本表 ecs_executor_alembic_version，当前版本 e0001_execution_ledger 管理三张执行表。生产 B 服务与控制端只读检查兼容性，不自动 create_all；离线升级命令可以创建缺失对象，或接纳经过严格结构核对的旧无版本执行账，保留已有记录、版本和状态。原生 Run、MCP、Scheduler、checkpoint 仍由原生数据库管理，不能与执行账共用一个库。

原生版本 0035_native_fork_compatibility 合并原生 0034 与旧 fork 0022，保留 0018_thread_execution_bindings、0019_scheduled_execution 的版本和父节点。真实 PostgreSQL 测试已验证全新库、原生 0034 和旧 Fleet 0022 升级及代表性数据保留。发现旧绑定、非 NULL 的 scheduled_tasks.execution 或任意 fleet_* 表时，Gateway 在恢复和调度之前拒绝激活；不自动转换、删除或重放旧执行意图。

依赖等待使用执行记录的 JSON 字段和原生仓库合同，不新增目标或通知表。离线升级、只读清点、旧数据隔离与完整备份回退步骤见 [fork 兼容文档](ecs-native-fork-integration.md)。实际启停、镜像和云环境验证仍属 Task6B。架构入口：[ecs-native-architecture.md](ecs-native-architecture.md)。

## 原生记忆数据位置

记忆继续由原生 DeerMem 管理，不新增 ECS 记忆表。默认 DEER_FLOW_HOME 下 users/{user_id}/memory.json 保存共享摘要、revision 与时间；users/{user_id}/agents/{agent}/facts/{prefix}/{fact_id}.md 保存事实。事实写入沿用原生跨进程锁、revision 和恢复日志。省略 memory.backend_config.storage_path，保持正常原生用户路径。

memory.backend_config.retrieval_index_path 指向每实例独立的本地目录。SQLite FTS 及 WAL/SHM 是可重建检索数据，不放 NAS，不作为事实来源。examples/ecs-native/native-memory.yaml 通过 DEER_FLOW_MEMORY_INDEX_PATH 提供此目录；只合并 memory 段到完整配置。实际两 Gateway 主干验证共享事实、原生工具/身份、另一用户隔离和两份不同的本地索引；真实云 NAS 仍待验收。

## 浏览器状态边界

浏览器复用 ecs_native_affinities 的 owner/thread/incarnation 节点绑定，不新增浏览器持久表。Live 连接、原始 Cookie/Authorization、页面状态和有界会话登记保持进程内存。删除/reset 通过原生线程 incarnation 撤销对应会话；进程重启不从数据库恢复页面或重放输入。
