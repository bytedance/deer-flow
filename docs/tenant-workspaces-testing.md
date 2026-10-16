# 租户空间测试与上海复现

当前实现按 `docs/superpowers/plans/2026-10-13-tenant-workspaces.md` 顺序推进。
本文件覆盖隔离测试复现；完整 M0–M11 验收、发布和回滚仍以计划、迁移文档及
`tenant-workspaces-progress.json` 的最新回执为准。租户启动门禁保持关闭。

## 本轮单机 B 主干

实际原生 ToolNode 和 durable wrapper 提交任务，经 ordinary driver、MCP HTTP
客户端/服务端、B 执行账本和原生 SQL 持久任务，再由真实 Docker worker 生成报告。
源 Run 已结束，调用方已切换空间；后台仍使用任务保存的原始空间。

| 检查 | 当前证据 |
| --- | --- |
| SQLite / PostgreSQL | 每种数据库都执行相同真实主干 |
| 输入 | 原生文件 SHA256 快照；修改源文件后仍执行原始字节 |
| Docker | 预载固定镜像，非 root 用户、禁网、只读根、CPU/内存/PID 限额 |
| 发布与回流 | 受原生权限锁保护的原线程输出；原 MCP 任务得到 completed 和 artifact URI |
| 清理 | 实际观察容器移除后，才记录 physical_stopped |
| 创建后撤权 | 已创建但未启动的容器被移除，没有 start 调用 |
| 运行中撤权 | 一次观测故障保留运行/未确认停止事实；恢复观测并移除后才确认 STOP |
| 取消与发布 | 原生 task 已有取消意图时，发布被拒绝；撤权任务没有成功结果 |
| 历史 | 未知旧记录的状态 uncertain、版本 7 保持原值 |

原生权限锁只覆盖短的启动意图/结果 SQL 写入，不跨 Docker/HTTP 调用。
启动意图是准入线性化点；其后撤权需要控制通道完成实际 STOP。
单机 worker 会在后续观测时发现权限失效并持久化停止意图。
持久 revocation outbox、原生 task 的控制结算、pool 远端协议仍在 M4 待办中。

## 固定执行环境

- Jenkins 专属任务：`deerflow-tenant-execution-m4-physical`。
- 节点标签：`shanghai-builder`。
- 工作目录：`/data/jenkins-agent/deerflow/tenant-execution-m4-physical`。
- 模板：`examples/ecs-native/deploy/Jenkinsfile.tenant-physical.in`。
- 渲染器：`scripts/render_tenant_physical_pipeline.py`，仅使用 Python 标准库。
- 工具及执行镜像：`sha256:4f269f6b0e50f9579e099e91a23df868ff1b1a49c03cc9b138beac02dafb3f01`。
- PostgreSQL 镜像：`sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`。

模板检查任务名、目录和源包摘要。所有镜像必须已加载，使用 `--pull=never`。
测试容器仅获得专属共享目录、Docker CLI/socket 和内部 fixture 数据库；不挂生产
配置、模型凭据或 NAS。Docker socket 仅用于可信源码的专属测试任务。
执行任务容器只挂自己的 inputs/outputs，不获得 Docker socket。

## 重跑

在已提交的版本上打包和渲染。以下操作只处理 Git 源码和模板，可在本地完成；
应用、pytest、Docker、浏览器验证只在上海执行。

```bash
tenant_phase=m4-b-physical-recheck
tenant_archive=/private/tmp/${tenant_phase}-source.tar.gz
git archive HEAD | gzip > "$tenant_archive"
tenant_sha=$(shasum -a 256 "$tenant_archive" | cut -d ' ' -f 1)
python scripts/render_tenant_physical_pipeline.py "$tenant_phase" "$tenant_sha" > /private/tmp/tenant-physical.Jenkinsfile
```

1. 使用现有 SSH 配置上传源包至该任务目录，保留相同文件名；Jenkins builder
   必须可读（现有 UID/GID 为 999:987，文件 0600）。先确认该任务没有运行或排队。
2. 将渲染后的流水线用于上述专属任务，先校验 Jenkinsfile，再启动构建。
   密码仅在 Jenkins 本机使用，不写源码、不复制到测试容器。
3. 流水线设置 `ECS_EXECUTOR_SCOPE_PHYSICAL_TEST=1`、固定镜像和 owned manifest，
   在容器内执行 `backend/tests/test_workspace_execution_physical.py`。
   默认未 opt-in 时，在 fixture 建立前跳过物理测试。
4. 测试目录在 host/container 使用相同绝对路径，保证真实 Docker bind mount
   指向同一份快照。结果和 manifest 位于 `physical-<BUILD_NUMBER>/`。
5. 测试和 CI trap 均按 manifest 中的 job/spec 标签核对后清理；观测不可用或标签
   不匹配时，不宣称清理完成，不触碰其他容器，不执行全局 prune。专属 fixture 删除时一并清理它自己的匿名卷，卷名保留在
   `*-volumes.txt` 供回执核对；未记录归属的旧卷不自动删除。
6. 保存终态、源包/代码/日志 SHA256、固定镜像 ID 和空自有容器/网络回执。
   最新回执见 progress JSON 的 `native_b_single_host_physical`。

同一测试有三种场景，各执行两种数据库，共六项。先跑主干，再跑必要边界；旧路径
只回归本次受影响的领取、重启、不重放、文件和清理逻辑。

## 后续验收

- MCP 协议当前使用进程内 ASGI transport；TCP、真实 NAS 和 OS 重启仍待验。
- CurrentUser/bootstrap 为可信内部 fixture，数据库角色拥有 fixture 库；公开 JWT、
  最小 SQL 权限和真实 Gateway 租户启动未获此测试证明。
- 单机 B 的物理主干已验证；pool、原生取消/撤权 outbox 与 STOP 控制回执、C 启动/
  恢复/通知及完整 C→B→C 仍须实施。撤权后的原生 task 控制状态尚未结算时保持原状态，
  不通过被撤销的成员授权写业务结果。
- 原生权限 fence 会锁 workspace、actor、私有线程、Run 和 task；M10 需要验证实际
  数据库角色的查询/行锁权限，配对备份恢复和镜像/配置清单。
- 实际资料、研究、带来源报告及持续跟进的模型业务验收属于 M9。
  本测试不调用模型，也不替代完整产品验收。
