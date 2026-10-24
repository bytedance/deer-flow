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
