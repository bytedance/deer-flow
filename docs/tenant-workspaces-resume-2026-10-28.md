# Resume checkpoint — 2026-10-28: step39 GREEN (#20) + 两机 slice 1 GREEN

> **执行中，M4 两机主流程 slice 1 已验证。** 本会话完成：step39 撤权/STOP 单测 RED→GREEN（Jenkins #19/#20）、两机只读审计与内存核算修正、两机 B 主流程 slice 1（真实 VPC TCP + 共享 PG 账本 + 真实 Docker）。产品代码零改动；租户入口保持关闭。

## 已验证（证据入口）

- step39 撤权：`docs/tenant-workspaces-evidence/native-shared-bc-revocation-20.json`（#19 RED 诊断 transfer_owner 双 revoke，一行测试修复 `727c4b882`；#20 GREEN 全故事标记 true）。
- 两机审计+内存修正：`docs/tenant-workspaces-evidence/native-shared-bc-two-host-readiness.md`（VPC 直连、镜像依赖 8/8 同版本、2048=AIO1024+Gateway1028、无需升配）。
- 两机 slice 1：`docs/tenant-workspaces-evidence/two-host-b-slice-20261028-51.json`；runner `scripts/tenant_two_host_slice.py`；测试 `backend/tests/test_workspace_two_host_physical.py`。真实链：签名 scope 提交 → McpTaskRow 种子（MCP 层由 #20 物理覆盖）→ status 管理 scope 激活 staged→queued → worker 经 `http://192.168.0.190:8021` 认领 → 真实受限 Docker 执行发布 → 精确 STOP → 容量归零。

## 环境事实（复用，勿再探测）

- controller `139.196.30.22`（私网 `192.168.0.190`，2C/7.35G）；worker `47.117.5.254`（私网 `192.168.0.189`，2C/3.54G）；Jenkins `106.14.210.163`（`/root/.jenkins-admin-password` 服务器本机用）。SSH：root + `genbalde-drama-keypair.pem`。
- 镜像：两机 `deerflow-native:production-repaired-contract-c6af94a95ae7`（依赖与 uv.lock 逐项一致）；controller `postgres:16-alpine 721873c3…`、`redis:7-alpine 858f009f…`；worker `all-in-one-sandbox 6328d7fd…`(13.1G)、`alpine:3.20 d9e853e…`（B small profile）。
- 运行纪律：phase 目录/容器带 `org.deerflow.tenant.owned=<PHASE>` 标签，runner `clean_phase` 精确清理；源码包=钉死日期 commit-tree+`gzip -n`（可复现）；容器恒等挂载 phase 根（内外同路径）。

## 下次接续：两机 slice 2 —— C 侧跨机（已定蓝图）

目标：worker 上**真实初始化**的 `NativeWorkerHost`（不再 `__new__` 桩）跑确定性 C 图，checkpoint 落共享 PG，流走 controller Redis；controller 侧 NativeDispatchHost + Scheduler 经真实 TCP 驱动 C1→（复用 slice 1 的 B）→C2 续跑。

精确接线点（全部已读核）：
- worker 轮询/执行：`backend/packages/ecs-executor/ecs_executor/agent_dispatch.py` `NativeWorkerHost.run()`（L915 起：poll→claim envelope→`execute(job, capability)`→`verify_native_launch_for_receiver`→`adopt_owned`→跑图→HTTP report）；构造需要 config `artifact_root/node_id/credential_env/executor_url`、`pool-mount-id`、env `credential_env` 与 `DEER_FLOW_INTERNAL_AUTH_TOKEN`。
- 单机参照（要移植的接线）：`backend/tests/test_workspace_native_dependencies.py` `_exercise_native_dependency`（central_app/worker_app 的 app.state 组装 L100-135、NativeDispatchHost/scheduler L120-165、`request_worker` 经 ASGI 的位置即要换真实 TCP 的点）；C 图为确定性图；`verify_native_launch_for_receiver` 在 `app/gateway/native_admission.py`。
- checkpoint：`make_checkpointer`/`AsyncPostgresSaver`（harness `deerflow/persistence`），两进程同一测试 PG、`checkpoint_channel_mode=full`；流桥 `RedisStreamBridge`（`deerflow/runtime/stream_bridge/redis.py`，controller 起 redis 容器绑私网）。
- B 侧复用：slice 1 全部组件（`create_app`+uvicorn、OutboundStore、LocalWorker）；C2 等 B 通知后从 checkpoint 续跑（调度 occurrence 语义同 `_exercise_native_dependency(scheduled=True, pool_b=True)`）。
- runner 扩展：`tenant_two_host_slice.py` 加 redis 容器、native-worker 路由端口、worker 侧 native role 环境变量；新测试文件或 `test_workspace_two_host_physical.py` 加 `TENANT_TWO_HOST_ROLE=native-worker`。

再后：跨机撤权/重启恢复 → M5（记忆/检索/凭据隔离）→ M6-M11。完整验收边界以 `openspec/changes/tenant-workspaces-self-service/tasks.md` 为准；不能用局部通过换算完成度。

## 边界（不变）

- 本会话未运行真实模型、未部署、未推送、未开租户入口（`_WORKSPACE_RUNTIME_INTEGRATED=False`）。
- slice 1 不含：NAS 字节级读取、真实 C1 AIO、C2 续跑、真实 Scheduler 发射、跨机撤权/重启。


## Slice 2 调试检查点（2026-10-28 深夜，用户要求 00:55 停止保留进度）

### 已完成（slice 2 = 两机 native C 派发）
- 测试代码：`backend/tests/test_workspace_two_host_physical.py` 新增 `native-controller`/`native-worker` 双角色；runner `scripts/tenant_two_host_slice.py` 加 `TENANT_TWO_HOST_SLICE=2` 模式（PG+Redis 容器、bootstrap+种子、恒等挂载、双端 pytest）。约 19 个提交（4e16d8d9f…b66d02771）。
- **controller 侧已通**：`admitted_native=true`（NativeDispatchHost+install_native_dispatch+make_native_snapshot 真实路径）、uvicorn 8022 自探测 403（鉴权门正常）、goal checkpoint 落共享 PG（`shared_checkpoints=1`，AsyncPostgresSaver 跨机可见）。
- 修复链：redis 镜像完整 ID、迁移容器 stdin→文件挂载、os.environ 读取、RunContext/DbRunEventStore/ThreadMetaRepository 导入路径、scheduled 包循环导入（必须 tasks 先于 runs，且用 importlib 显式顺序防 isort 重排）、owner 必须为 UUID + 可解析邮箱域名、create_or_reject 需包 set_current_workspace。

### 当前卡点（精确隔离）
worker 侧 `NativeWorkerHost` 轮询 300 秒全部 `ConnectError: All connection attempts failed`，但**同一进程同一时刻**：
- 裸 socket 到 192.168.0.190:8022 → OK（socket_trace 前 ~280 秒全 ok，仅 controller 退出后 refused）
- 普通 `httpx.AsyncClient` POST 同一 URL → **403 正常响应**（httpx_precheck 证据）
即网络、URL、httpx/anyio 本身全部正常；**故障被隔离在 NativeWorkerHost 自建的 AsyncClient**（`agent_dispatch.py:661` 附近 `httpx.AsyncClient(headers={Authorization, X-DeerFlow-Internal-Token}, timeout=30)`）。

### 下次第一步（从这里继续）
1. 对比复现：在 worker 测试里用与 NativeWorkerHost 完全相同的构造参数（含两个 header）新建 AsyncClient 发 poll——若它失败而去掉 header 成功，则是 header/环境交互；若同样成功，则在 host.start() 之前/之后分别构造对比（怀疑 __init__ 里 fcntl.flock/事件循环时序），必要时打印 `host.client._transport` 与工作 client 的差异。
2. 备选检查：anyio snuffio 后端检测、`HTTPX_DEBUG=1` 抓 host client 的详细错误。
3. 修复后按原计划收敛：worker 认领→adopt_owned 跑图（共享 PG checkpoint）→controller 断言 run success；然后 C1→B→C2 串联。

### 环境/证据
- 证据：`/srv/deerflow-twohost/two-host-b-slice-20261028-51/evidence/native-{controller,worker}.json`（两机）；本地 `/private/tmp/two-host-slice2-run*.log`。
- 00:55 定时器（automation-5bd77544）会 pkill 本地 runner 并精确清理两机 phase 标签容器/目录；PG/Redis 是 phase 标签容器，一并清理，下次运行重建。
- 重跑命令：`TENANT_TWO_HOST_SLICE=2 python3 scripts/tenant_two_host_slice.py`。


## 00:55 收尾补充（诊断闭环 + 下一修复已定）

run20 判别数据（清理前抢救）：`identical_client_trace = [403×10, ConnectError×2]`、`socket_trace = [ok×10, refused×2]` —— **与 NativeWorkerHost 完全相同构造的客户端全程正常**，唯 host 自建实例失败。结合时序（mount-id 早于 uvicorn 绑定，worker 在 mount-id 出现后即启动）：host 客户端首次 poll 落在 uvicorn 起来前，首次 ConnectError 后该客户端实例未恢复。预检/复刻客户端因重试到 403 才开始，错过毒化窗口，故正常。

**下一步修复（不动产品）**：runner 把 worker 启动门槛从"mount-id 出现"改为"controller 8022 端口 TCP 可达"（生产语义本如此）；若仍复现再深入 httpx 池行为。清理已执行：两机 phase 标签容器（含 pg/redis）与目录已删，本地 runner 已停。重跑：`TENANT_TWO_HOST_SLICE=2 python3 scripts/tenant_two_host_slice.py`。


## 2026-10-29 slice 2 GREEN（终局）

`config.yaml` 缺失是 25 轮 RED 的真正根因（`deps.get_config()` 503 → execute 异常 → refuse 循环 → run pending；可见的 ConnectError 全部是 controller 300s 超时退场后的尾部噪音）。修复后 slice 2 全绿：controller `run_status=success`、共享 PG 6 条跨进程 checkpoint、worker 真实认领/采用/执行/上报。证据 `two-host-c-slice-20261028-51.json`。下一片：C1(AIO 工具)→B→C2 调度串联（复用 slice 1 的 B 组件 + slice 2 的 C 通道 + ScheduledTaskService 语义），然后跨机撤权/重启 → M5。


## 2026-10-29 slice 3（合龙 C1→B→C2）进展检查点

24 轮修复后主干已通（run24 证据）：
- 调度 occurrence 排队→control 服务发射 ✓（需显式起 `dispatch_enabled=True` 的 ScheduledTaskService）
- C1 真实运行：native 派发→worker NativeWorkerHost 采用→确定性图执行 ✓（run success）
- C1 工具经**真实 MCP HTTP**（http://192.168.0.190:8022/mcp）提交 B ✓（`b_task_submitted_over_mcp_http`）
- **B 在合龙流程里由 worker 经共享池真实 Docker 执行完成** ✓（job cf980ff4 completed）
- 9 条共享 checkpoint；occurrence 停在 running（controller 600s 超时打断）

修复链：模块级预导 tasks→runs（导入环免疫）；list_by_task 查 occurrence（无 user_id 参数）；等待段全程 set_current_workspace；`task_runtime.set_mcp_task_submitter(tasks)`；工具 schema 需 `input_refs`（可传空 dict）；fresh_thread_per_run → input 改内联 base64；DNS rebinding 421 → 遍历 routes 置 `manager.security_settings=None`；task 读需 thread_id+thread_incarnation 且包 workspace scope；从 submit request 捕获线程身份；捕获放 service 层（TaskSubmission 无 task_id）。

### 剩余尾巴（下次第一步）
1. 第二个 B 提交（35b61cce failed）来源待查：疑 C2 图实例的 plan 在 created_tasks 尚空时又发了一次（图按 run 重建、registry 共享但 C2 启动时序）或驱动重试。对照 worker 完整日志中两次 submit 的调用栈。
2. task 行状态 failed（对应第二次提交）：修 1 后应消失。
3. occurrence 收敛：controller 等待循环里 status 仍 running——C2 完成路径（通知→launch→worker claim→checkpoint 续跑→answer 读已发布报告）未在 600s 内走完，先修 1/2 再观察。
4. GREEN 判据保持：occurrence success + ≥2 个 success run + ≥1 个 completed B + worker 零残留容器。

重跑：`TENANT_TWO_HOST_SLICE=3 python3 scripts/tenant_two_host_slice.py`（最新提交 e1a2276df，归档 4e465e3a…b94f）。


## 2026-10-29 slice 3 尾巴收敛到通知一步（run28 诊断）

已确认链路：调度发射→C1 真实运行 success→工具经真实 MCP HTTP 提交（input_files 内联修复生效）→**真实 Docker B completed**→task completed。run28 新证据：worker 显式 `tasks.run_once` 返回 ok 但 `mcp_tasks.notification_status` 停在 **pending**、无 notification_error、C2 未发射、occurrence 卡 running。

### 下次第一步（通知为何不派发）
`app/mcp_tasks/service.py` `run_once`→通知分支的触发条件（notified_version/event_version、next_notify_at/lease、workspace scope）。对比依赖测试 L838-846：他们在 execute 内部轮询期间由 poller 驱动通知，且 `capture_real_submission` 后 task 的 event_version 在 B 完成时 bump。可加证据：run_once 前后读 task 的 event_version/notified_version/notification_lease 字段；在 launch_notification lambda 里 try/except 记录异常（当前异常被服务层吞掉只递增重试）。另一疑点：`services.launch_mcp_task_notification_run(app=worker_app)` 需要 worker 侧 get_run_context（已补）与 forward 路由 workspace scope。
- 提交链注意：f-string 曾因 heredoc 丢收尾引号且 ruff 管道掩码退出码导致坏提交（run27 教训）——以后 lint 用 `set -o pipefail` 或不用管道。
- 最新提交 ab52ea8d3；重跑 `TENANT_TWO_HOST_SLICE=3 python3 scripts/tenant_two_host_slice.py`。
