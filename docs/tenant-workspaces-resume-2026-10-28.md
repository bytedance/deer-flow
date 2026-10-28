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
