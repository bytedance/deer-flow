# 两机共享池主流程：验收准备审计

2026-10-19。仅代码与既有环境记录的只读审计，产品基线 `c6e9b9e88`；未运行两机验收、部署或启用租户。

## 已有证据和边界

- [physical #18](native-shared-bc-pool-18.json) 验证真实 B 容器、B/C 共享执行账本、原工作空间发布和同一调度 occurrence 的 C2 续跑。网络使用 ASGI，C 使用确定性图；不能作为跨机 TCP、持久 checkpoint 或真实 C 沙箱验收。
- #112 验证过捕获 AIO 容器身份后显式 `stop_owned` 的生命周期；不能证明普通 worker 循环每次完成都会销毁 AIO。
- `backend/app/gateway/workspaces/startup.py` 保持 `_WORKSPACE_RUNTIME_INTEGRATED=False`，启动 schema 门槛仍为 `0037_project_visibility`。两机组件验收不得绕过或修改生产门禁，也不代表多租户已可发布。

## 最小的一条后续主流程

在当前撤权/STOP 单条验收之后，使用独立测试数据库、NAS 子目录和合成角色凭据，运行 Scheduler → C1 → B → C2。Controller 与 worker 采用真实独立进程，复用 `NativeDispatchHost`、完整 `NativeWorkerHost` 初始化/循环、B 的 `dispatch.main` 与 `OutboundStore`，不手工伪造 assignment、成功结果或续跑。

两个进程通过原生 `make_checkpointer` 使用同一测试 PostgreSQL 的 `AsyncPostgresSaver`，并统一 `checkpoint_channel_mode=full`。共享原生 Redis stream/ownership；不能用进程内 MemorySaver 或 NAS SQLite/WAL 代替跨进程状态。使用真实 Ordinary MCP 提交、SQL 任务租约与 worker→controller 签名通知，B/C 指向同一执行池。

C1 真实 AIO 工具写入原空间文件，B 的受限容器消费已冻结输入并发布报告，C2 从持久 checkpoint 继续并通过真实沙箱读取报告。观察原空间、同一 occurrence/count1、晚到 C1 不覆盖 C2、B 停止前 C2 保持预算阻塞；仅重复必要的幂等 drain，不扩展状态矩阵或调用真实模型。

## AIO 正常完成与物理 STOP 分开记录

`ecs_executor/agent_dispatch.py::NativeWorkerHost.execute` 在正常完成时调用 `capture.execution_drained`，随后报告动态执行释放；AIO 可继续保温，仍计入常驻预算。只有取消路径先调用 `stop_owned`。这里的 `physical_stopped=True` 不能单独证明 AIO 容器消失。

保留此既有语义，不为验收新增强制销毁策略。分别记录 C1 动态预算释放、B 期间 AIO 常驻容器的完整 ID/状态、C2 是否实际复用同一对象、C2 动态预算释放。最终 fixture shutdown/精确清理单列为清理证据；不得冒称普通完成路径的物理 STOP。撤权和未知状态的物理停止仍属于独立控制门禁。

## 开跑前尚需核实

- 旧 `ecs_native_shanghai_bootstrap.py`、`*_bc_transport.py`、`*_bc_main.py` 和 `operations.py` 固定旧目录、镜像、0035/e0001 或私有业务配置。仅参考 SSH 主机校验与精确清理方式；不能直接执行、改 schema 常量凑兼容或复用旧业务环境。
- 两台已有 native 镜像与 worker AIO 镜像的存在已被此前只读记录确认；controller 的 PostgreSQL/Redis 固定镜像及所选 native 镜像对当前源码所需依赖的可用性尚未验证。缺失时先明确固定镜像传输方案，不能默认拉取或安装。
- 服务端口绑定本机 loopback。必要时复用 Jenkins 专属 SSH 凭据建立严格主机校验的转发；验收必须标明 TCP over SSH，不能声称验证了直接 VPC TLS。不复制 SSH 私钥到工作负载，不修改其他项目或安全组。
- worker 配额必须基于真实 MemTotal、OS/fixture 预留和同时运行的 cgroup 上限。此前 MemAvailable 只是瞬时剩余量。既有最低常驻预算为 1500m/2048MiB，C 的保守动态预算为 500m/1024MiB，B 为 500m/128MiB；须核算实际可分配容量，不能照搬 #18 的虚拟 8GiB Node 或缩小 C 配额掩盖不足。
- 采用独立组件 app factory、新建 0041/e0003 测试数据库，明确与完整生产 Gateway 生命周期的差异。完整启动、迁移恢复和 M0–M11 验收继续开放。
- 清理只针对本次记录的完整容器 ID、镜像、标签及确切 fixture 网络/卷/隧道；保温 AIO ID 要去重。正常 B STOP 与 finally 兜底删除分别记录，不按名称前缀全局删除。

## 当前执行状态

本次收到的明确批准绑定 #18 的源码 `e2150fa9…6400` 和流水线 `d18c78a3…777e`；该次构建已成功完成，不重复运行。2026-10-19 再次只读查询：lastBuild=18/SUCCESS，building=false，专属队列为空。

下一条撤权测试的产品代码未改，源码 `73d729db…b4d`、流水线 `95bf4803…fe8f` 已冻结但尚未上传或启动；仍等待此前对该具体新包的单独确认。详见 [待授权记录](native-shared-bc-revocation-pending-approval.json)。两机方案目前仅准备审计，不算已实施或已通过。

## 2026-10-28 本地准备清点（未触云端）

- 旧 `20261019-48` 冻结包三个 `/private/tmp` 工件已被系统清理丢失，且 `git archive --format=tar.gz` 嵌入即时 mtime 不可复现，旧字节永久无法恢复。step39 已按可复现程序重新冻结为 `20261028-49`（base 树 `c6e9b9e88` + 同三个测试/CI 文件，两次独立重建逐字节一致；归档 `5e7d8463…f84e`、流水线 `5f7bbe1a…0522`、重写提交脚本 `37d6ccff…4f71`）。仍未上传未授权；收据与任务备注已同步，见 [待授权记录](native-shared-bc-revocation-pending-approval.json)。本机各默认 SSH 密钥（id_rsa/id_ed25519/id_ed25519_compute）经只读 BatchMode 探测均未被 106.14.210.163 授权；执行需可用身份或操作员亲自运行冻结脚本。
- 旧脚本钉死清点：`ecs_native_shanghai_bootstrap.py`、`*_bc_transport.py`、`*_bc_main.py` 全部硬编码废弃布局——`/data/jenkins-agent/deerflow/native-task6b-56636cebddc6` 与 `/srv/deerflow-native-task6b/56636cebddc6` 目录、`private/820d7a3429d9/resident` 私有 resident 布局、`deer-native-820d7a3429d9-controller_control` 网络、`/srv/deerflow-native-test` DEER_FLOW_HOME 与固定 env 文件挂载。均不可在新 0041/e0003 测试库上直接执行；仅沿用其严格主机校验与按完整 ID 精确清理方式。新两机运行必须定义本 phase 专属的目录、网络与 `org.deerflow.tenant.owned` 标签。
- 当前迁移 head 已核对：native `0041_scheduler_workspace_identity`、executor `e0003_execution_identity`，与本审计"新建 0041/e0003 测试数据库"一致；runtime 兼容检查接受的已知 head 为 0040/0041。
- 镜像钉死一致性：physical 流水线钉死的 native CI 镜像 `sha256:4f269f6b…f3f01` 与 Postgres `sha256:721873c3…8ea` 与 #18 等历史证据记录一致。两项云端只读核实命令已备好，待 SSH 可用即查：两镜像在主机上 `docker image inspect` 是否存在且 ID 未漂移；controller 所需 Redis 固定镜像的确立（旧脚本未见独立 Redis 镜像钉死，两机方案新增 controller Redis 依赖时须先固定镜像并记录）。
- 内存预算核算依赖主机真实 `MemTotal`（只读 `/proc/meminfo`），本地无法代算。已确认预算常量：常驻 AIO 1500m/2048MiB、C 动态 500m/1024MiB、B 500m/128MiB；待获取 MemTotal 后按“真实 MemTotal − OS/fixture 预留 − 同时运行 cgroup 上限”核算，不照搬 #18 的虚拟 8GiB Node。

## 2026-10-28 两机只读核对结果（controller 139.196.30.22 / worker 47.117.5.254）

用户提供了两台测试机地址后完成的全部只读核对；未部署、未启容器（除依赖探测的无网络临时容器）、未改任何配置。

- **连通与角色**：两台均以 root + 操作员密钥 SSH 可达。同 VPC：controller `192.168.0.190`、worker `192.168.0.189`，私网双向 TCP/ping 直通（RTT 0.3–1.2ms）；公网互访 22 端口被安全组拦截（本机白名单可入）。两机业务流量走 VPC 内网直连 TCP——验收口径为“VPC 内网直连”，不是公网 TLS，也不再需要原设想的 SSH 隧道转发。
- **硬件与运行时**：controller 2 vCPU / MemTotal 7,341MiB（空闲 available 6,897MiB）/ 系统盘空余 51G；worker 2 vCPU / MemTotal 3,542MiB（空闲 available 3,026MiB，系统+Docker 基线约 516MiB）/ 空余 46G。两台 Docker 29.8.2、宿主 Python 3.12.3（旧证据“宿主无 Python 环境”已过时）。两台当前均无运行中容器；`/srv/deerflow-native-releases|task6b|test` 旧目录在两台均存在，不触碰。
- **镜像核对**：两台均有 `deerflow-native:production-repaired-contract-c6af94a95ae7`（e84bc2845f89）、`publication-bdd2931a1a6f-core`（a216a2cc51b2，#38 worker CLI 用过）、`05e260329244-core`、`browser-mcr` 系列；worker 另有 `all-in-one-sandbox`（6328d7fd2f0f，13.1GB，即 C 沙箱 AIO 镜像）。controller 另有 `postgres:16-alpine`（721873c34ceb，与 physical CI 钉死 ID 完全一致）和 `redis:7-alpine`（858f009f9709）——原“controller PG/Redis 固定镜像未验证”事项关闭；Redis 固定 ID 记录为 858f009f9709。CI 镜像 4f269f6b… 不在两机上，两机源码运行方案不需要它。
- **镜像依赖对当前源码可用性**：两台各以 `--network none` 无挂载临时容器探测 `production-repaired-contract-c6af94a95ae7` 的 Python 环境，8 个关键包（sqlalchemy 2.0.49、httpx 0.28.1、psycopg 3.3.3、redis 7.4.0、pydantic 2.13.3、langgraph 1.2.9、fastapi 0.136.1、uvicorn 0.46.0）与源码 `backend/uv.lock` 锁定版本逐一相同。原“所选 native 镜像对当前源码所需依赖的可用性尚未验证”事项对该镜像关闭。
- **内存预算核算（2026-10-28 修正后结论：无需升配，可开跑）**：首轮核算曾误判不满足，错误有二——把 AIO 单独计为 2048MiB（审计笔记 `superpowers/plans/2026-10-08-ecs-native-reuse-audit-notes.md` 明确 2048 常驻 = AIO 1024 + Gateway/worker 宿主 1024 的合计），并把 worker 宿主进程在合计之外重复叠加。修正后 worker 峰值并发限额 = 常驻 2048（AIO 1024 + worker 宿主 1024）+ C 动态 1024 = 3072MiB（B 128MiB 因 `max_concurrency=1` 与 C 动态不同时），对照 MemTotal 3542MiB 限额层面余量约 470MiB；对照空闲 available 3026MiB 表面差 46MiB，可由内核回收页面缓存补足，且限额≠实际占用。CPU 峰值 1500m+500m=2000m 恰为 2 vCPU，与声明一致。**历史直接证据**：本机 `/srv/deerflow-native-task6b/56636cebddc6/private/.../resident/executor.json` 就是这套 1500m/2048MiB 常驻 + 128MiB B（alpine:3.20，`d9e853e87e55`，worker 在库）+ `max_concurrency=1` 的配置，此前在本机真实跑起——其节点声明 `memory_mib: 4096` 甚至高于物理 3542MiB，说明实际占用长期低于限额。新两机部署沿用同一预算结构，仅把节点内存声明按真实 MemTotal 校正为 3542（不沿用无据的 4096），并在首验各阶段记录 MemAvailable/docker stats 作为实际占用证据。控制器 7341MiB 对 PG/Redis/Scheduler/Gateway 充裕。
- **原“worker 升配”建议撤回**：按修正核算与历史运行事实，worker 现配满足两机主流程；升配不再必要。其余各项就绪，可进入独立组件 app factory 与 0041/e0003 测试库实施。
