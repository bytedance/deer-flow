# 原生 ECS 工作池测试与复验

更新：2026-10-09。先复验主干，再根据实际缺陷补定向用例。本文记录当前本地证据，不代替完整功能、云或部署验收。

## 当前状态

| 层次 | 实际证据 | 边界 |
| --- | --- | --- |
| 原生 submit 身份 | 真实 ToolNode / ordinary driver / interceptor 调用链，SPEC 与质量审查通过 | 不单独证明物理执行 |
| B 程序主干 | 原生任务持久跟踪、真实 TCP/PostgreSQL/Docker、输入快照、原生结果文件、重启与取消通过 | 不证明云 NAS 或 C |
| B/C 共享资源池 | PostgreSQL、两个出站 worker、三条真实程序任务，排队与容量复用通过 | 此用例中的 C 只验证准入 |
| C 原生执行 | 两个真实 Gateway、DeepSeek、AIO 工具、checkpoint/events、Redis END、affinity、跨实例取消与 STOP 通过 | Scheduler 配置验收见下文；原生记忆验收见下文；完整浏览器仍待集成 |
| C→B→C | 最新真实主干 1 passed / 142.71 秒；冻结收口 282 passed / 1 live deselected | SPEC 与质量复审通过；完整配置及部署仍待验收 |
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

最新组合主干已通过（1 passed / 142.71 秒），使用两个原生 Gateway、真实 ordinary MCP、Alpine B 和同一个共享工作节点。断言检查真实动态资源释放顺序、同节点、B attempt=1、恰好两个原生 Run、原目标和累计预算，以及 present_files 结果交付；测试拥有的资源已清理。后续共享通知与恢复修复已通过离线 ASGI/SQL 回归、独立 SPEC 和质量复审。最终冻结代码收口为 282 passed / 1 live deselected，15.36 秒。完整配置及部署验收仍待完成。复验使用上面的私有模型路径环境：

```bash
ECS_NATIVE_LIVE=1 .venv/bin/python -m pytest \
  tests/test_ecs_executor_bc_main.py -m live -q -s --tb=short
```

本次依赖合同已验证：同一最小工作机上 C 提交 B，C 真实释放动态容量，B 执行并发布结果，经既有原生通知继续原目标；旧目标、取消、新消息及重复事件不得造成错误续跑。累计预算和 Scheduler overlap 保护必须保持。

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

## 配置完整的原生 Scheduler 主干（2026-10-09）

真实认证 API 创建 once 定时任务，由控制端原生 ScheduledTaskService 自动派发到出站 C 工作机，经 ordinary MCP/Docker B 继续原目标 C。唯一此轮模型主干：1 passed / 72.92 秒；测试拥有的容器和进程已清理。检查同一 occurrence、恰好两个原生 Run、run_count=1、原生目标与累计预算、C 物理收尾先于 B 启动、同一 2CPU/4GiB 节点、B attempt=1、present_files 交付和最终目标清理。

两端保持 scheduler.enabled/tool_enabled/multi_instance；可信工作机仅关闭后台派发，保留原生前台工具与完成回调。UI 入口为控制端。此证据不包含浏览器、记忆或云部署。

从 backend/ 复验，仅选择这一条 live 用例，模型配置路径沿用前文只读私有输入：

```bash
ECS_NATIVE_LIVE=1 PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m pytest \
  tests/test_ecs_executor_bc_main.py::test_real_scheduled_native_c_mcp_b_same_occurrence_goal_c -q -s --tb=short
```

冻结回归 528 passed / 2 live deselected / 1 已有 Starlette-httpx 警告，17.52 秒：

```bash
PYTHONPATH=.:packages/ecs-executor uv run --no-sync pytest \
  tests/test_ecs_native_scheduler.py tests/test_scheduler_tools.py \
  tests/test_scheduler_capability_access.py tests/test_scheduled_task_service.py \
  tests/test_gateway_lifespan_shutdown.py tests/test_scheduled_task_router_behavior.py \
  tests/test_scheduled_task_cron_preview.py tests/test_ecs_executor_bc_main.py \
  tests/test_multi_worker_postgres_gate.py tests/test_features_router.py \
  tests/test_harness_boundary.py -m 'not live' -q
```

root 独立复验 test_ecs_native_scheduler.py：5 passed / 1.95 秒。首试缺少 ECS 包 PYTHONPATH，4 passed / 1 import failure；按扩展文档修正命令后通过。12 个改动 Python 文件 Ruff lint/format 与 diff check 通过。独立 SPEC 与质量审查 PASS。完整 Task4 和 Task6 保持未完成。

## 原生记忆共享与本地索引（2026-10-09）

原生 DeerMem 配置无需运行时代码修改。两个 Gateway 使用同一 DEER_FLOW_HOME 事实目录，每实例设置独立的本地检索目录；开启原生 tool mode，通过 memory_search/get/add 管理事实。本地共享目录的验证不替代真实云 NAS 锁与持久化验收。

首条实际主干 1 passed / 43.66 秒，证明隐藏 UUID 事实检索、工作机写入、两端可见、另一注册用户隔离和不同本地 FTS 索引。审查补强交付断言后，必要的同用例复跑 1 passed / 46.71 秒，进一步检查 present_files 精确路径、匹配 tool_call_id 的成功结果、原生 state.artifacts 及控制端 artifact HTTP 200 和正文。测试保持同一最初准入的远程 Run 和工作机 owner，不新增记忆存储；其拥有的运行时与容器已清理。

使用前文只读模型配置环境，从 backend/ 仅选此用例：

```bash
ECS_NATIVE_LIVE=1 PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m pytest \
  tests/test_ecs_executor_c_live.py::test_native_remote_memory_shared_facts_and_owner_isolation -q -s
```

此前原生记忆/隔离/边界回归 61 passed / 4.59 秒、用户身份 27 passed / 1.24 秒。配置测试经 SPEC 修正，实际 AppConfig loader 解析本地路径环境变量并验证基础 model/database/auth/Redis 保留：实现者 2 passed / 0.95 秒，root 独立 2 passed / 1.02 秒。61 用例命令在项目根目录执行：

```bash
backend/.venv/bin/python -m pytest backend/tests/test_ecs_native_memory_config.py \
  backend/tests/test_memory_tools.py backend/tests/test_memory_get_tool.py \
  backend/tests/test_memory_retrieval_index_local.py \
  backend/tests/test_memory_updater_user_isolation.py backend/tests/test_harness_boundary.py -q
backend/.venv/bin/python -m pytest backend/tests/test_user_context.py -q
```

配置叠加文件与安全合并命令见 examples/ecs-native/README.md；memory-only 文件不能直接作为完整启动配置。独立 SPEC 与质量审查 PASS。浏览器和 Task6 仍待完成。
