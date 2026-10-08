# 原生 ECS 工作池库表说明

更新：2026-10-09。字段核对自当前已审查代码；依赖协调正在实现，其新增结构将在代码和验收稳定后补齐。旧 docs/ecs-fleet-database.md 属于上一版 Fleet，不能作为本次重做的部署 schema。

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
| 物理收尾 | physical_stopped、cleanup_pending | 资源释放和终态清理证据 |
| C 跨库收尾 | settlement_pending、settlement_kind、settlement_error、settlement_cancel_action | 原生 terminal commit / END / 执行账收尾的恢复意图 |
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

Scheduler 复用 scheduled_tasks 与 scheduled_task_runs，active occurrence 的 queued/launching/running 唯一保护、租约和全局预算仍由原生仓库管理。Task5 将补充等待依赖时保持原 occurrence 的接点，当前未宣称完成。

## 初始化、迁移与旧版兼容

目前三张 executor 表由各自 SQLAlchemy MetaData.create_all 初始化，原生表由原有数据库迁移管理。create_all 只创建缺失对象，不是生产 schema 升级协议；版本化运维与升级验证属于 Task6 未完成项。

旧 fork 数据库可能位于 0022_fleet_main_merge，包含 0018_thread_execution_bindings 和 0019_scheduled_execution 以及 scheduled_tasks.execution。必须保留原 revision ID 并提供兼容 merge/upgrade 路径，显式处置旧执行绑定和配置。禁止以新迁移目录覆盖旧库、直接删表或假设旧数据库等于全新数据库。

后续依赖关联结构、索引与迁移脚本须按最终代码补入本文，并验证全新库与旧 fork 升级。架构入口：[ecs-native-architecture.md](ecs-native-architecture.md)。
