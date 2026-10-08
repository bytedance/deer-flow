# 原生 ECS 工作池测试与复验

更新：2026-10-09。先复验主干，再根据实际缺陷补定向用例。本文记录当前本地证据，不代替完整功能、云或部署验收。

## 当前状态

| 层次 | 实际证据 | 边界 |
| --- | --- | --- |
| 原生 submit 身份 | 真实 ToolNode / ordinary driver / interceptor 调用链，SPEC 与质量审查通过 | 不单独证明物理执行 |
| B 程序主干 | 原生任务持久跟踪、真实 TCP/PostgreSQL/Docker、输入快照、原生结果文件、重启与取消通过 | 不证明云 NAS 或 C |
| B/C 共享资源池 | PostgreSQL、两个出站 worker、三条真实程序任务，排队与容量复用通过 | 此用例中的 C 只验证准入 |
| C 原生执行 | 两个真实 Gateway、DeepSeek、AIO 工具、checkpoint/events、Redis END、affinity、跨实例取消与 STOP 通过 | 完整浏览器/记忆/Scheduler 仍待集成 |
| C→B→C | 正在编码 | 尚无主干通过证据 |
| fork 升级、启动/回滚与云 | 待完成 | 两台 ECS 保持停机，本轮未部署 |

最新 C 主干：1 passed，49.78 秒；独立 SPEC 与质量复审通过。其定向回归集合 609 passed；root 独立复验停机屏障及拒绝恢复两例 2 passed，1.18 秒。此前 root 还独立跑通相同 C 主干，1 passed，43.94 秒。

B 最新真实主干 1 passed，16.48 秒。资源池最终真实主干 2 passed，19.90 秒；root 独立复验 2 passed，17.60 秒。Task3 时的锁定环境完整后端门禁为 26,762 passed / 412 skipped，blocking-I/O 229 passed；该历史门禁不能替代后续 C/组合改动的最终门禁。

## 环境

从当前 `ecs-native-reuse` 工作树使用其自身 backend/.venv，不复用旧 Fleet 工作树的 editable 安装。

```bash
cd backend
uv sync --locked --extra postgres --extra redis
```

主干使用 Docker。已用镜像：postgres:16-alpine、redis:7-alpine、alpine:3.20、原生 AIO 1.11.0。测试使用自己生成的 UUID 容器前缀、临时端口、目录与数据库；清理只能删除本用例拥有的资源。

真实模型凭据通过 ECS_NATIVE_MODEL_CONFIG / ECS_NATIVE_MODEL_ENV 指向操作者已有的私有文件，只读加载进内存和子进程环境。不要把 key 放进命令正文、Git、SQL 执行快照或测试日志。

## 复验顺序与命令

以下命令均在 backend 目录执行。只复验发生变化的层次；主干通过后再补必要取消/恢复边界，不重复跑全矩阵。

### 1. B/C 共享资源池主干

```bash
ECS_EXECUTOR_POOL_TEST=1 .venv/bin/python -m pytest \
  tests/test_ecs_executor_dispatch_main.py -q --tb=short
```

这个已有用例自动创建自己的 PostgreSQL 和 TCP 服务，运行两个出站 worker 与三条 Docker 程序。应观察两个任务占用容量、第三个等待；清理并确认 STOP 后第三个才获得资源。每条执行 attempt=1；跨节点凭据及协议/挂载标记不匹配必须拒绝。

独立 B 输入/重启/取消主干需要操作者准备专用测试 PostgreSQL，并通过环境提供 ECS_EXECUTOR_TEST_DB（同步驱动）和 ECS_EXECUTOR_NATIVE_TEST_DB（异步驱动）。不要使用生产库。

```bash
ECS_EXECUTOR_DOCKER_TEST=1 ECS_EXECUTOR_TCP_TEST=1 \
  .venv/bin/python -m pytest \
  tests/test_ecs_executor_b_main.py::test_native_sql_http_docker_main_cancel_restart \
  -q --tb=short
```

测试验证提交暂存→原生任务落库→首次 status 激活、不可变输入、精确容器重启身份、Docker 限额、owner 文件权限及取消后的物理停止。专用数据库的设置和历史详细证据见 packages/ecs-executor/LOCAL_B_EVIDENCE.md。

### 2. C 实际原生执行主干

先由操作者设置模型配置文件路径，不在本文内嵌任何私有文件内容：

```bash
export ECS_NATIVE_MODEL_CONFIG=/absolute/private/config.yaml
export ECS_NATIVE_MODEL_ENV=/absolute/private/.env
ECS_NATIVE_LIVE=1 .venv/bin/python -m pytest \
  tests/test_ecs_executor_c_live.py -m live -q -s --tb=short
```

用例启动自己的 PostgreSQL、Redis、两个正常原生 Gateway 和 AIO 沙箱。必须确认：

- 原生 SQL 中是最初准入的 Run ID，执行 owner 为工作机。
- 实际模型调用原生 bash、read_file、present_files；正常交付校验保持启用。
- 另一 Gateway 能读取原生 checkpoint、事件和 Redis END。
- 后续交互仍落在原节点，复用同一容器及其 /tmp 状态。
- 控制端取消到达工作机；原生完整 finalizers 与严格物理 STOP 之后才释放动态预留。
- 测试退出后，其拥有的进程、数据库、沙箱被清理。

### 3. 组合及最终门禁

C→B→C 用例正在实现，本文暂不提供未存在的运行命令或通过声明。最终应证明：同一最小工作机上 C 提交 B，C 真实释放动态容量，B 执行并发布结果，经既有原生通知继续原目标；旧目标、取消、新消息及重复事件不得造成错误续跑。累计预算和 Scheduler overlap 保护必须保持。

完成整个功能批次、审查通过后，执行正式后端门禁：

```bash
make test
make test-blocking-io
```

格式使用 backend/ruff.toml。不能用筛选测试替代正式门禁，也不能把可选 live 跳过当作通过真实主干。

## 记录验收结果

每次主干记录代码 revision、命令、环境边界、退出码、结果、具体断言及 owned cleanup 是否完成。失败时保留脱敏且有界的原生 SQL status/error/owner/cancel_action 与 checkpoint/event 诊断；API 没有 error 字段不表示数据库没有错误。

观察超时只表示尚未观察到结果，不表示任务已停止。继续检查原执行 handle，不重复启动同一模型测试。unknown/start intent/物理清理失败仍须保留资源预留。

本地共享临时目录不能证明跨 ECS NAS 锁或 Linux Gateway cgroup。云阶段重启资源前，还需可复用部署脚本、Jenkins 发布入口、健康检查、NAS 和 cgroup 证据、重启与回滚记录。由用户重新授权启动后再运行。

关联：[架构](ecs-native-architecture.md)、[库表](ecs-native-database.md)、[全程证据](superpowers/plans/2026-10-08-ecs-native-reuse-audit-notes.md)。
