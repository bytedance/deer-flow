# 原生 ECS 工作池测试与复验

最新：2026-10-13 新镜像同schema交付主干完成，Jenkins deerflow-native-release #5/#6/#7/#8全部SUCCESS；5守卫通过、严格TLS/双端就绪/Chromium实际启动通过，历史与私有配置保留，继续drain。详见 [交付验证](ecs-native-shanghai-validation-2026-10-13.md)。真实DeepSeek销售C→B→C已于2026-10-12通过，详见 [销售验收](ecs-native-business-sales-validation-2026-10-12.md)。两份证据分开，今天没有重跑模型或完整测试矩阵。

Historical Shanghai acceptance (2026-10-10): production image e84bc2845f89 installed on controller Gateway/MCP and worker resident; Jenkins #65/#66/#67 SUCCESS and recovery #69 SUCCESS. #68 FAILURE remains preserved (stale Nginx upstream); exact source and installed metadata verified, database/NAS history preserved. Admission remains drained with unreleased=0. Current coherent evidence: [Shanghai acceptance](ecs-native-shanghai-acceptance-2026-10-10.md). Historical pending statements below describe their checkpoints.

| Scope | Current result |
| --- | --- |
| B ordinary MCP infrastructure | Main passed; #24 wrapper failed, #26 normal native cleanup succeeded |
| C native remote tool and NAS delivery | #29 SUCCESS; native bash/read_file/present_files, ledger physical STOP and shared output verified independently |
| Native goal C → B → C | Actual installed main PASS in #35; its terminal-notification lease assertion caused wrapper FAILURE. #36 read-only verification SUCCESS, with automatic continuation, goal clear, delivery and physical STOP verified |
| Native browser HTTP / cross-host WSS control | #46 SUCCESS: JPEG delivery, strict WSS input, same-session reconnect and normal retirement; zero model calls |
| Installed lifecycle / remaining operations | #38 SUCCESS: worker native CLI stop/start/restart, controller host Compose stop/start, history/volumes preserved. Same-schema rollback main #48 PASS/restored; final code evidence and installed artifact accepted. Controller installed CLI and OS/automatic NAS reboot remain unverified |
| Frozen-source backend coverage | Composite accepted from immutable #60–#64 evidence: original shards1/2 passed subsets plus whole-file repairs; #62 complete shard3 passed; #62 complete shard4 passed subset plus #64 three repaired whole files (20 passed / 1 skipped); #61 blocking-I/O 229 passed. Ruff passed. Historical failed shards remain FAIL; no fresh full-suite PASS is claimed. Final production #65 and installed recovery #69 SUCCESS; see coherent release evidence |

The selected original DeepSeek subset is now provisioned privately and was used for #27, #29 and the #30 and #35 native BC trials. No credential value is included in these documents or immutable images.

以下为2026-10-09起的历史证据。当前上海结论见上表；历史通过不能替代最终源码检查。

## 历史本地状态

| 层次 | 实际证据 | 边界 |
| --- | --- | --- |
| 原生 submit 身份 | 真实 ToolNode / ordinary driver / interceptor 调用链，SPEC 与质量审查通过 | 不单独证明物理执行 |
| B 程序主干 | 原生任务持久跟踪、真实 TCP/PostgreSQL/Docker、输入快照、原生结果文件、重启与取消通过 | 不证明云 NAS 或 C |
| B/C 共享资源池 | PostgreSQL、两个出站 worker、三条真实程序任务，排队与容量复用通过 | 此用例中的 C 只验证准入 |
| C 原生执行 | 两个真实 Gateway、DeepSeek、AIO 工具、checkpoint/events、Redis END、affinity、跨实例取消与 STOP 通过 | Scheduler 配置验收见下文；原生记忆验收见下文；浏览器模型步骤与完整无模型控制主干分段验收见下文 |
| C→B→C | 最新真实主干 1 passed / 142.71 秒；冻结收口 282 passed / 1 live deselected | SPEC 与质量复审通过；完整配置及部署仍待验收 |
| fork 升级、启动/回滚与云 | 上海安装验收进行中 | 两台 ECS 已授权；共享 NAS 与 Jenkins 构建限额通过，运行角色/B/C 尚待验收 |

最新 C 主干：1 passed，49.78 秒；独立 SPEC 与质量复审通过。其定向回归集合 609 passed；root 独立复验停机屏障及拒绝恢复两例 2 passed，1.18 秒。此前 root 还独立跑通相同 C 主干，1 passed，43.94 秒。

B 最新真实主干 1 passed，16.48 秒。资源池最终真实主干 2 passed，19.90 秒；root 独立复验 2 passed，17.60 秒。Task3 时的锁定环境完整后端门禁为 26,762 passed / 412 skipped，blocking-I/O 229 passed；该历史门禁不能替代后续 C/组合改动的最终门禁。

## 环境

从当前 `ecs-native-reuse` 工作树使用其自身 backend/.venv，不复用旧 Fleet 工作树的 editable 安装。

```bash
cd backend
uv sync --locked --extra postgres --extra redis --extra browser
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
  tests/test_ecs_executor_c_live.py::test_native_http_remote_model_tool_and_peer_cancel -q -s --no-showlocals --tb=short
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
  tests/test_ecs_executor_bc_main.py::test_real_native_c_mcp_b_same_goal_c -q -s --no-showlocals --tb=short
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
  tests/test_ecs_executor_bc_main.py::test_real_scheduled_native_c_mcp_b_same_occurrence_goal_c -q -s --no-showlocals --tb=short
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
  tests/test_ecs_executor_c_live.py::test_native_remote_memory_shared_facts_and_owner_isolation -q -s --no-showlocals --tb=short
```

此前原生记忆/隔离/边界回归 61 passed / 4.59 秒、用户身份 27 passed / 1.24 秒。配置测试经 SPEC 修正，实际 AppConfig loader 解析本地路径环境变量并验证基础 model/database/auth/Redis 保留：实现者 2 passed / 0.95 秒，root 独立 2 passed / 1.02 秒。61 用例命令在项目根目录执行：

```bash
backend/.venv/bin/python -m pytest backend/tests/test_ecs_native_memory_config.py \
  backend/tests/test_memory_tools.py backend/tests/test_memory_get_tool.py \
  backend/tests/test_memory_retrieval_index_local.py \
  backend/tests/test_memory_updater_user_isolation.py backend/tests/test_harness_boundary.py -q
backend/.venv/bin/python -m pytest backend/tests/test_user_context.py -q
```

配置叠加文件与安全合并命令见 examples/ecs-native/README.md；memory-only 文件不能直接作为完整启动配置。独立 SPEC 与质量审查 PASS。浏览器验收见下文；Task6 仍待完成。

## 原生浏览器：分段主干证据（2026-10-09）

原生 Chromium 的 URL/egress/真实关闭探针通过（8.10 秒）。真实模型测试已证明 native navigate/click/get_text、write/read/present_files、最终原生文件交付、首次 UI affinity、HTTP 同状态、Live JPEG/实际鼠标输入、owner/Origin 隔离和 pinned 429。原模型选择器没有整体 GREEN：早期 ASGI method 缺陷已修，随后 fixture 输入参数、可选 psutil 检查和异步 signal 检查先后阻断完整用例；没有把这些失败计为 passed。fixture 修正后停止重复模型调用。

最终无模型 control 主干 1 passed / 19.50 秒，零 Run、零 job、零模型调用：首次 UI affinity、同状态 HTTP、Live JPEG/输入 count2、用户与 Origin 拒绝、pinned 429、断线重连不重复点击、canonical deletion 后释放及另一用户新会话 count0。两端 Gateway 正常退出，ERROR/Traceback 为零，本用例拥有的 Docker 残留为零。此前无模型失败暴露了 stale watcher 误取消其他身份操作，已定点修复并经最终主干验证。

独立 SPEC 与质量审查 PASS，修复登记上限、精确撤销、native finalizers 后清理、unknown 提示和旧 Live 会话重新创建未登记浏览器的问题。root 独立生命周期 6 passed / 1.68 秒、物理关闭竞态 2 passed / 1.34 秒；15 个改动 Python 文件 Ruff lint/format 通过。最终全后端门禁仍属 Task6。

从 backend/ 执行，使用前文只读配置环境与已安装 browser extra/Chromium：

```bash
ECS_NATIVE_LIVE=1 PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m pytest \
  tests/test_ecs_executor_c_live.py::test_native_browser_control_without_model \
  -q -s --no-showlocals --tb=short
```

该控制用例不调用模型。模型完整选择器及配置步骤见 ecs-executor README；本轮不再次运行。所有显式 ECS_NATIVE_LIVE 测试强制关闭 showlocals；浏览器子进程只继承所选模型需要的私有环境项，不携带其他服务凭据。首次失败曾将非目标服务凭据输出到工具诊断，已向用户告知并建议更换；现有自有诊断已检查/脱敏，但历史已发输出不能撤回。不要粘贴原始失败局部变量。

本地目录、进程和 loopback 明文隧道不证明云 NAS、容器 cgroup 或生产 WSS；Task6 和云验收保持待完成。


## Task6B local operator slice (installed acceptance pending)

The native role/Compose, reference-only private generator, resident supervisor,
durable shared-node drain and safe version selector are documented in
[ecs-native-deployment.md](ecs-native-deployment.md). Focused local evidence:
operator lifecycle/remote-all/unknown-physical risk regressions 4 passed; the
SPEC-reported failure-cleanup regression brings the focused set to 5 passed; the
preceding shared-budget/native-handoff set 6 passed (before the added physical
quarantine case); owned reference generation and preflight passed. Changed Python
Ruff/format, strict OpenSpec (1 change) and whitespace checks passed.

The **single** owned zero-model installed selector is prepared but has not run:

```bash
ECS_NATIVE_INSTALLED_IMAGE=sha256:CURRENT_OWNED_ROLE_IMAGE \
  PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m pytest \
  tests/test_ecs_native_installed_ops.py -q -s --no-showlocals --tb=short
```

It uses independent owned native/executor databases, protected synthetic env/TLS
files, normal native Gateway and outbound worker supervision, actual Docker and
kernel resident cgroup checks, Chromium/native browser WSS, drain/stop/restart
and immutable **same-image** selection. No model endpoint is called. Its nginx
frontend is only a resolver stub; it does not establish native UI acceptance or
previous-version rollback. Historical actual-model B/C/BC/Scheduler/memory and
separately accepted browser receipts remain the evidence for those functional
main paths; this infrastructure selector does not replace them.

The current source role-image build was stopped after bounded registry-token and
Debian HTTP-index failures (the latter recovered using HTTPS public indexes),
then an unchanged locked-wheel download stage for over ten minutes. APT/Node/Lark
completed; no final role image exists from that attempt. BuildKit cache is
preserved. A verified host probe of the exact locked anyio wheel returned HTTPS
200 and 1024 bytes in 1.96 seconds; Docker connectivity is separately diagnosed.
No incompatible cached virtualenv or lock mutation is accepted.
No installed acceptance or Task6B completion is claimed. Installed shared-NAS I/O, cross-host
verified TLS/WSS/firewall, previous-image coherent-generation rollback, native UI,
Installed cloud lifecycle remains pending. Jenkins and real shared NAS are now
authorized and their preparatory checks passed. Final whole-backend and
blocking-I/O gates will run once on a stable cloud-owned test container; the
interrupted local gate has no recoverable passing result.

The installed fixture now records exact UUID project/node/native-prefix handles
and selected residue IDs in a protected cleanup receipt. Cleanup fences claims
and requires zero unreleased reservations and zero active/pending native Runs.
Unknown B/native-prefix work or failed teardown retains the private recovery
configuration and NAS stand-in. Only confirmed idle labeled/prefix-owned warm
AIO is stopped/removed; normal B cleanup remains worker-owned. Successful
cleanup verifies project/B/prefix absence and retains a separate receipt.

## Shanghai Task6B build evidence (2026-10-09)

Local Docker/build/testing was stopped at the user request; this phase uses the
existing dedicated Jenkins job. Build #6 reproduced a missing owned `@tmp`
permission boundary; only that directory was created for the agent. Build #7
passed full-source verification and exposed missing target records in the agent's
shared SSH trust store. A dedicated two-target known-hosts file now uses public
keys copied from verified connections, with strict checking retained. Shared
permissions and trust stores were not changed.

Build #8 passed all 3,798 archive entries, all 24 operator file hashes, and
calculated source SHA256
`95ba9f3063f923350a552d5686ffe2578033f9e52864dfad83434071557b05a9`.
The NFS4 source and isolated marker `820d7a3429d9` passed on both peers. The
dedicated builder passed Docker HostConfig and kernel limits: CPU quota/period
100000/100000, `cpu.max=100000 100000`, memory 2147483648 bytes. Build #8 then failed at public base metadata resolution with an
`i/o timeout` to `registry-1.docker.io`; APT, locked Python dependencies and
Chromium had not started. The three preparatory checks remain passing evidence.

No role-image completion or installed B/C/UI/WSS pass is claimed yet. The existing
single-machine fixture remains a local resolver-stub test; it cannot substitute
for actual cross-ECS NAS, browser WSS or native UI acceptance. Reproduction and
reboot mount commands are in `ecs-native-deployment.md`.

Build #9 verified the original three base OCI chains but exposed the cached
BuildKit v0.9.3 frontend lacking named contexts. The owned builder was upgraded
to fixed official v0.33.1, keeping its state and proving the same 1 CPU/2 GiB
kernel limits. Build #10 reached APT with active slow downloads, then was
normally aborted for the reviewed HTTPS mirror/source switch. It is not recorded
as a transport failure. Build #11 verified a fresh 3,798-entry archive with only
the Dockerfile HTTPS ordering changed: source SHA256
`fe217c457deaf4e5a671981e935a100886517366a1d0e92723ce66aafb6b6c92`,
archive SHA256 `07a4fba75b413239e2852d94fb6ea6cedb6751272d20210674be873866c54512`.
Its source/NAS/cgroup gates passed; actual HTTPS TUNA APT reached package
unpacking at 21.23s. These are build/preflight results; final images and installed
B/C/browser/native UI results remain pending. No extra functional test cases or
paid model calls were introduced for the network diagnosis.

Build #11 was normally stopped (`ABORTED`) for a reviewed diagnostic/source
switch after repeated UV download starts; the underlying retry exception has
not yet been observed. No timeout/reset/EOF cause is claimed. The next reviewed
source `305d6f933433` and its complete archive are uploaded and verified, with
build-only scoped retry logging captured in remote 0600 files and excluded
from Jenkins artifacts. It initially waited for the sole executor, occupied by an existing AssetForge
release approval. Its owner completed that task; build #12 then ran and was
normally aborted for a measured, reviewed artifact mirror switch.
The owned builder is stopped and its UV/OCI/state cache retained. No Mac Docker,
additional functional cases or paid model calls were run. Final images and
installed B/C/UI/cross-host WSS acceptance remain pending.

Build #13 proved locked UV installation via same-hash HTTPS mirror artifact
locations: 230 packages installed, UV layer completed in 163.0 seconds, and
original lock SHA restored on all seven visible builder copies. The original
lockfile, registry, dependency versions and hashes were not re-resolved.
Chromium's official download remained active but required an estimated further
99.5 minutes for the current ZIP at the observed rate, so #13 was normally
aborted for the reviewed main-first interim core/UI scope.

Build #14 runs frozen source `05e260329244` (3,799 entries and 25 operator hashes)
with the same actual 1 CPU/2 GiB builder limits. Its controlled `backend-core`
action produces a distinct `-core` tag and explicitly unavailable browser proof;
full `native-role` and production-default targets remain intact. Core image/UI
completion and installed B/C/BC are still pending. No browser acceptance or
complete-system PASS is inferred from the interim build.

Shanghai checkpoint: core image build #14 passed its installed import/original-lock
proof (`sha256:5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338`,
source05e260); its browser capability is `pending_unavailable`. #14's UI work and
frontend-only builds #15/#16 were normally aborted for reviewed memory/build
changes. #16's 3 GiB builder showed user CPU stagnation with increasing reclaim
pressure, without an OOM kill or compile error. Owned builder post-stop completed
and its cache remains intact.

#17 has been queued once using source56636cebddc6/archivee27c3d4c and the reviewed
controller-only frontend build: 1 CPU/5 GiB/zero swap, preflight available memory
at least 6.5 GiB, no controller role startup during compilation. It is waiting
behind `assetforge-shanghai-release #36` staging approval on the single executor;
controller public-input transfer/build has not started. No other task was changed.
The private configuration document is an approved scope/order proposal, not proof
of generated secrets, database bootstrap or installed roles. The historical model
reuse boundary is only the selected DeepSeek model and its required environment
references from `/Users/wenbinwang/Documents/git/deerflow2/config.yaml` and
`/Users/wenbinwang/Documents/git/deerflow2/.env`; actual key values have not been
read or transferred in this phase. Entire historical files are not copied.

Task6 remains unchecked. Installed Shanghai B/C/BC, native UI, cross-host NAS
runtime/WSS, complete browser, safe restart/version rollback and final backend
plus blocking-I/O gates are pending. The interrupted Mac gates have no passing
result. Mutable documentation does not modify the immutable source566 archive or
its historical manifest.

See [the deployment checkpoint and controller build boundary](ecs-native-deployment.md)
for the fixed image/source identities, resource limits and continuation sequence.

After release #36 completed, #17 failed during its fixed official BuildKit image
preparation, before controller source extraction/builder startup. Its four public
inputs were transferred intact; no UI compile or role acceptance occurred.
A cached exact-image recovery candidate is prepared; it has not yet run. This
supersedes the earlier queued checkpoint without altering its immutable source.

Shanghai checkpoint: Jenkins #19 successfully built the current native UI; controller image ID, archive SHA, and stopped owned builder were independently verified. Fixed-artifact transfer #20 is in progress. This is build evidence only: real two-ECS B/C execution and installed lifecycle/browser/final gates remain pending. See [deployment checkpoint](ecs-native-deployment-history-2026-10-10.md#shanghai-frontend-checkpoint-19).

Fixed image transfer #20 passed. Bootstrap #21 refused a known owned-root permission mismatch; #22 passed source extraction and fresh database/MCP/UI startup but failed Gateway configuration validation, so neither is installed acceptance. A B-only configuration correction is being reviewed; B remains infrastructure-only and pending, with actual native C/BC, browser, lifecycle/rollback and final gates still pending.


### Paused Shanghai checkpoint — 2026-10-10

#23 installed roles passed; the real B infrastructure main passed, while Jenkins #24 failed in its outer blank-line receipt parser. Native cleanup queue152 became #25 before the pause check; #25 ended FAILURE without cleanup proof, and no cleanup build remains active. Its continuation is recorded in the [persistent resume checkpoint](ecs-native-shanghai-resume-2026-10-10.md). Shared-node admission is drained with zero unreleased work, and the exact B job has no remaining worker container. No actual model key was read or paid call made; C/BC/browser/lifecycle/rollback/final gates remain pending. The user paused further work until tomorrow. No ECS shutdown, Compose stop, data deletion or other Jenkins task operation was performed.


## Resumed environment — 2026-10-10

The user restarted the two test ECS and authorized continuation. Current public addresses are controller `101.133.235.59` and worker `47.103.28.252`; their original host keys and unchanged private addresses `192.168.0.190` / `.189` were strictly verified. Historical public addresses above describe the earlier deployment. Jenkins transport uses the verified private addresses and its owned known-hosts file, so no transport target or TLS certificate change is required; TLS checks continue against the existing private SAN.

The main NAS mount survived, but the isolated bind did not. Both empty local bind targets were checked before restoring the exact verified NFS namespace to `/srv/deerflow-native-test`. Both now show nfs4, the original NAS endpoint and marker `820d7a3429d9`. Only existing owned Compose containers were started, controller first then worker; both starts waited successfully for health. No bootstrap, native DB login creation, image build or B rerun occurred. Root independently verified strict private-CA readiness. Admission remains drained.

A later retained receipt corrects the pause-time observation: `proof/b-main.json` already exists, root-owned 0600, timestamp `2026-10-09T17:06:29.051558Z`, SHA `a6fd2c864219cc89d18d831d7628078fe90409e9758049d2872150917cbe6cfd`. It was written by #25, not by today's recovery checks. #25's native DELETE returned HTTP 200 and removed the thread metadata, while the native terminal MCP task remained. The thread-delete API intentionally retains MCP task history; #25 failed its incorrect post-delete assertion that those rows must be zero. The task remains completed, ledger attempt1/physical stopped/cleanup_pending false, and thread metadata count is zero.

A narrow recovery candidate is under review: validate the complete retained B proof and the unique deleted-thread pending notification, keep admission drained, enable only the existing controller native MCP notification supervisor with the B-only empty task groups/interceptor configuration, and let the real Gateway callback reject the missing thread through the normal permanent-notification path. Acceptance requires dead_letter, zero pending notifications, zero native runs, and preserved terminal MCP/ledger history. This recovery has not yet executed; no actual model key or paid model call has been used. C/BC and remaining Task6 acceptance stay pending.


### Normal B notification recovery — Jenkins #26 SUCCESS

The reviewed recovery ran once through the existing Jenkins test job. The real Gateway notification service handled the already deleted B thread through its normal permanent-notification path. `proof/b-cleanup.json` records `notification_status=dead_letter`, zero pending notifications and zero native runs, one retained terminal MCP task, preserved execution ledger history, and no model calls. #26 ended SUCCESS; its queue is empty. No B task/thread was recreated and no SQL state patch was used. Admission remains drained while the original MCP configuration and selected DeepSeek model subset are prepared for genuine C/BC. C/BC/browser/lifecycle/rollback/final gates are not yet accepted.

### C main #27: native completion, tool delivery not accepted (2026-10-10)

The selected original DeepSeek model and only its referenced environment key were provisioned through the reviewed in-memory/SSH-stdin path. Both owned Gateway and worker resident were recreated to refresh their environment and became healthy before this single native API run. Jenkins #27 ended FAILURE because the delivery assertions failed: native run `e69ab8b5-7cf7-4181-89a6-02e5f66af011` reached `success`, and C ledger job `20d31d4d1f874b5e897ebcdab10f4dc3` completed at attempt 1 on `native-820d7a3429d9` with physical STOP recorded. Three bash attempts returned sandbox-capacity errors; no requested NAS output or read_file/present_files delivery was verified. This is not C acceptance PASS.

The installed AIO prefix `deer-native-820d7a3429d9` also selects Compose resident `deer-native-820d7a3429d9-worker-resident-1`. Native strict capacity counts this running role container as sandbox occupancy. The proposed repair separates AIO into `deer-native-aio-820d7a3429d9`, synchronizes operator prefixes, and rejects such overlap before future configuration generation. The worker resident later exited with code 0 and no OOM; the exact exit trigger remains unconfirmed. Admission remains drained. Existing run, thread, checkpoint and ledger history are retained; the repaired delivery main will use separate attempt receipts after review.

The historical bootstrap uses its original pinned generator. Changes to the public generator do not rewrite the installed immutable source archive; a future fresh deployment must create and review a new source bundle and matching CI pins. Full browser, BC, captured live sandbox cgroups, lifecycle/version rollback and final cloud gates remain pending.

### Repaired C delivery #29 (2026-10-10)

#28 failed before private writes or model invocation because the existing root-owned namespace parent was 0755 while the repair required 0700. Only that exact parent directory on each test host was tightened to 0700. The same reviewed package was then used once in #29; neither keys nor images were rebuilt or reread. Both peers now use AIO prefix `deer-native-aio-820d7a3429d9` and matching operator prefixes, with unchanged Compose projects.

The actual C delivery main passed: run `86a41bdc-a550-4557-81d9-1165e91ae8c7` completed through the native Gateway and remote worker `28512cfbcc7b:7766d0f431fa48e9a54e6719cae9dd32`. Native bash, read_file and present_files produced and delivered the shared NAS file with result `338350` and `Linux`. Ledger job `4e9c2ef12a0f49bda0c4a3b174582d18` completed at attempt 1 on the owned node, with physical STOP true and no pending cleanup. Controller proof `proof/c-repair-main.json` retains the prior #27 run identity rather than replacing its failed-delivery record. Finally-drain proof records operator_drain true and unreleased 0.

During this installation/run window, the new-prefix AIO container `8ba2dd136bf8b5b2402b375e49d737974ecd08d2f7ff76d235da2def8d8c49cf` was captured live. Docker NanoCpus was 1000000000 and Memory was 1073741824; kernel cpu.max was `100000 100000` and memory.max was `1073741824`. The root reviewer independently verified these selected limits. Worker proof `proof/c-repair-live-aio.json` records the observation; it does not claim a separately established run-to-container binding. BC, live B-container limits, full browser/WSS, lifecycle/version rollback and final cloud gates remain pending.

## Publication derivative checkpoint — 2026-10-10

Jenkins #31 failed before builder start because Docker 29's manifest image identity was incorrectly compared with the OCI config digest. The reviewed identity fix preserves all archive/blob/hash checks. #32 SUCCESS built only `publication.py` over exact core manifest `5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338`, original archive `4bddb0efba126620ac03c6329e8858b10af7a72d01f28dd7293563fbf1cd3cdf`. The immutable derivative is `sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1`, publication patch `bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e`. It retains the original locked dependencies and has no Chromium.

Two owned, network-disabled cloud regressions passed, one case each: real non-root native publication reading and the sandbox/role namespace collision guard. They invoked no models. The exact owned builder stayed at 1 CPU / 3 GiB / zero swap and is stopped after the build. #33 SUCCESS transferred the fixed derivative to both private targets without starting roles or resuming admission. Public proofs are in the Jenkins owned workspace `proof/publication-{builder,image,green,transfer}.json`. Installed roles remain on the original core until the separately reviewed refresh runs; #30's failed continuation/goal/task audit remains intact.

The three-file Ruff check found import ordering, one long test command, and formatting changes. These remain pending source cleanup after the BC main; no formatter candidate has been applied and no claim of formatting PASS is made. The original immutable source566 archive is unchanged. Task6, browser, lifecycle/rollback, final gates and a coherent new cold-start source bundle remain open.


## Installed main acceptance checkpoint — 2026-10-10 (#34–#36)

#34 SUCCESS refreshed only the owned Gateway, MCP service and worker resident to immutable publication derivative `sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1`. Its base remains core `5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338`, with publication patch `bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e`; this is a derivative identity, not a rewritten source566 image. Controller Gateway is healthy without a Docker socket; MCP runs without a healthcheck or socket. Worker resident is healthy with the approved socket, Docker 500m / 1 GiB and matching kernel limits. Strict private-CA readiness passed.

The single repaired native goal C → B → C trial actually passed in #35: thread `native-bc-repair-820d7a3429d9-06c502b422e54e648ba3a4216b0c1fde`, source run `70af1fb0-1d51-4b5f-81fb-4de17bfc47cf`, continuation run `5c4933af-2d51-404a-b2a3-affadf7dd93c`, B job `28aa3063aaf4490f881e2b039efdb752`. Both native Runs succeeded and all three ledger jobs completed physically on node `native-820d7a3429d9`; B used attempt 1 and started after source C physical STOP. Original goal identity and continuation budget, automatic notification, native ecs_submit/read_file/present_files, shared NAS `dependency-proof-338350`, authenticated artifact HTTP 200 and final goal clearing were independently verified.

Jenkins #35 remains FAILURE: its wrapper incorrectly expected terminal `notification_run_id` to retain the continuation ID. Native `finish_notification_run` deliberately clears this dispatch lease on delivered notification. #36 SUCCESS ran only a read-only verifier over that same trial; it invoked no model and created no run/goal. It verified persistent `dependency_wait.continuation_run_id` plus native run idempotency key `mcp-dependencies:<source_run_id>`, delivered status with equal event/notified versions and a cleared lease. Controller root-owned 0600 `proof/bc-repair-main.json` SHA is `1998bdb6079bc28c9c7681904093a5744d0a025fa769b36da18394775b01236c`; Jenkins retains `proof/bc-repair-verification.json`. Prior #30 failed history is preserved.

The root reviewer captured the actual B container `590d3e5813791ddb0647db677eeb28cc42896a0f04ba456c7807879580c39ce5` and independently bound it to this trial: 500m CPU, 128 MiB memory, PID limit 64, network none, user `65534:65534`, with matching kernel cgroups. No extra B trial was run for this observation. Final admission remains drained, unreleased jobs/nonterminal native runs/pending notifications are zero, and the owned roles remain healthy/running as described above.

B infrastructure, genuine C delivery and genuine native BC main are now accepted for this installed two-ECS/NAS scope. At this #36 checkpoint, full Chromium/browser/cross-host WSS, lifecycle/version rollback, final backend/blocking-I/O gates, Ruff source cleanup and a coherent new cold-start source bundle/pins remained pending; see the subsequent lifecycle/static-cleanup checkpoint below. Task6 is still unchecked; no Git commit/push or additional model/build/test phase was performed for this final verification. The immutable source566 archive remains unchanged.


## Installed lifecycle and static source cleanup — 2026-10-10 (#37–#38)

#37 failed before its first snapshot or any service mutation: the lifecycle preflight incorrectly expected the controller operator's Compose path under `ROOT/source`, while its original generated path is `ROOT/frontend-build/source`. The narrow correction accepts only that exact historical controller path, rejects symlinks through every ancestor, and verifies both public Compose files have identical bytes. The worker path remains unchanged. Private operator configuration was not rewritten; the original failed helper and #37 result remain retained. Both corrected read-only host snapshots passed before the one #38 execution.

#38 SUCCESS verified this fixed installed sequence on image `sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1`: worker installed `ecs_executor.operations stop`; controller host Compose stop of Gateway/MCP/frontend/proxy; controller host Compose start of those services; worker installed `start`; worker installed `restart`. Controller PostgreSQL and Redis remained running. Worker commands ran in the bounded trusted oneoff with its separately fenced operator environment; no ledger/admin credentials were added to the resident. Controller native CLI lifecycle was not tested because the host has no installed Python environment; no controller socket container was introduced.

All nine snapshots/action steps passed. Fresh drain/idle/physical-work, real NFS namespace and strict private-CA readiness gates passed. Container IDs and persistent volume identities, complete terminal runs/MCP/ledger row hashes, prior B/C/BC proof hashes and the BC NAS output hash remained identical. Gateway and worker are healthy, MCP runs without a healthcheck, the worker remains 500m / 1 GiB, and admission remains drained. No model, thread, image selection, rollback, key/config change, OS shutdown, volume deletion or prune occurred. Jenkins root/agent-owned 0600 `proof/installed-lifecycle.json` SHA is `d4195da7183a32bbf09b320133f649c428e7b2601158ca93b2529c6dfce96dae`, independently verified by the root reviewer.

To reproduce this installed slice, use the existing Jenkins `deerflow-shanghai-test` normal `shanghai-deploy-ssh` binding with `PHASE=installed-lifecycle` and the unchanged source archive SHA `e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b`. The reviewed coordinator is `scripts/ecs_native_shanghai_lifecycle_transport.py`; it pins `scripts/ecs_native_shanghai_lifecycle_host.py`, uses only the two fixed private hosts, and refuses an existing/partial lifecycle receipt rather than overwriting history or blindly rerunning. A subsequent trial requires a separately reviewed fresh receipt identity.

The future BC admitting script now verifies delivered notification versions and a cleared dispatch lease, using fresh source `dependency_wait.continuation_run_id` plus native run idempotency for durable linkage. This source correction does not rewrite the already installed/frozen #35 script pins and did not rerun the accepted model trial. Static Ruff check and format checks passed for that script, publication.py and its two focused tests (four files); the publication cleanup was import/format only. Current runtime image still contains reviewed publication patch `bdd293…`; the newly formatted public publication source is `0fd2f696…`. A coherent new cold-start source/image/CI bundle remains pending.

Remaining scope: full browser/Chromium and cross-host WSS, immutable version rollback, OS/reboot recovery acceptance, final backend/blocking-I/O gates, and coherent cold-start bundle/pins. The worker CLI/controller host Compose lifecycle slice is accepted; it is not a full controller CLI or rollback acceptance. Task6 remains unchecked.


## Shanghai native browser control checkpoint (2026-10-10)

Jenkins #41 built the exact browser derivative52ce, #42 transferred it and #44 installed the native provider/original tools. #46 SUCCESS verified native HTTP JPEG delivery, strict cross-host WSS navigation input, reconnect without seed with the same browser/affinity, and normal thread/session retirement. Root independently verified receipt SHA `1bdab66abb7e06788320818ca3b0f33e949a1316338f5a827722c009ad333f09`; no model was called and admission remained drained. #45's failed PNG assertion is retained separately; native progress screenshots are JPEG.

The existing owned Jenkins phase is `browser-control-main`, currently pinned to `scripts/ecs_native_browser_control_repair_host.py` and `scripts/ecs_native_browser_control_repair_main.py`. Receipts are immutable: do not rerun the phase over existing owned-thread/proof paths. A further trial requires a reviewed new receipt identity; model B/C/BC mains are not rerun to repair wrappers. See `ecs-native-shanghai-resume-2026-10-10.md` for exact image and build history. Remaining Task6 scopes include compatible rollback/recovery, final code gates and coherent cold-start artifacts.

The nine successful public browser helpers are now retained under `scripts/ecs_native_browser_*`, with exact reviewed SHA pins preserved and eight Python files passing Ruff lint/format checks. Current cloud Jenkins pipeline still retains historical failed-build phases for audit; it must not be copied as a fresh cold-start pipeline without reconciling its helper inventory and pins. #46 post-cleanup returned404 after the main's normal DELETE200; peers remain healthy on52ce, admission drained and owned AIO idle.


## Same-schema version rollback and restoration — #47–#48

#47 failed before its first private preparation write because the executor revision query used the native database table name. The repaired query uses `ecs_executor_alembic_version`; native revision checks continue to use `alembic_version`. A submission-only worker check then exposed host `ps` incompatibility in `docker top`. The repaired guard reads only executable basenames in the verified owned resident, ignores normal process exit races and refuses unexpected read errors. Both final host preparations passed a denied-write diagnostic through their first lock creation before the single #48 retry. Failed scripts/build evidence remain retained.

#48 main PASS verified browser image52ce → compatible publication image a216 → image52ce with both restoration generations prepared before any service stop. Worker selection uses the installed `ecs_executor.operations select-version`; controller selection uses the guarded host operator while PostgreSQL/Redis stay running. This does not claim the controller native CLI selector or a database time rollback was tested. All 20 preparation/action/snapshot steps passed, and root independently verified `proof/compatible-rollback.json` SHA `90448af01e4a20337451407832c2b793225abb143b2a9c392035be14e5ffda03`.

Both roles returned healthy on the original browser image. Original configuration fingerprints, unrelated private-file hashes, full terminal Run/MCP/ledger history hashes, NAS output hashes, persistent volumes and PostgreSQL/Redis/frontend/proxy container records were preserved. Resource limits remain unchanged; admission remains drained, no model calls or new jobs were made. Jenkins #48 finished SUCCESS with independent post `ALREADY_RESTORED_VERIFIED`; post did not stop the restored roles again. OS reboot, automatic NAS remount and final frozen-source backend gates are not accepted by this slice. Final gates and coherent artifact documentation remain pending.


## Frozen-source backend gate — #49 FAILURE (fixture-only repair pending)

The immutable public source snapshot is `779e52ecb2027efd817e90cd9b591b95404afbb7df70f039abd575bf5ef6f320`; archive `deer-native-final-source-779e52ecb202.tar.gz` SHA `139ec6eb73f863884156c6f0c2261e781ba7e2c7c98362ad95a2f793ac3f6ae6` (30,353,723 bytes); embedded entry-manifest SHA `8bb32682ea303b67d1c95b680dc00d1af96e98e3643374d23ca7f70c8b0082e9`. Root verified 3,852 regular entries and preserved the original source566 archive. Upload to Jenkins was hash-verified, UID999/mode0600; `proof/final-source-upload.json` SHA `dd51a0acfbfbbfa82670314d90a029d7fb838044d007b616a487ca5011a15100`.

#49 finished FAILURE using this snapshot in a fresh network-none, root UID, 1 CPU / 3 GiB fixture with only the read-only public archive mount. No credentials, database, NAS or Docker socket were mounted. All four application packages resolved to the freshly verified temporary source. Ruff check and format passed; all four default suite shards exited 2 at collection because the static-detector root resolver requires a `.git` marker. The public package correctly excludes real Git metadata. Blocking-I/O completed with 229 passed and two warnings. This does not count the default backend suite as passed.

The fixture automatically exited and was removed. Independent exact-CID inspection returned the canonical no-such-container error and one LF on stdout (`b'\n'`). The overly strict cleanup wrapper expected zero stdout bytes, so main and post refused before writing an overall gate receipt. No `fixture_cleanup=true` receipt exists; the independent absence observation is the narrower evidence. Original active marker, source archive, logs and failed build are retained. Public log SHA: `3d00c2877b1d0394f97502c6c8824fa1589581a43c03adb68d4ae20ce5877a01`.

The next fixture-only repair generates an empty `.git` marker after complete source verification and accepts only the two verified missing-container stdout shapes, empty or one LF, alongside exact return-code/canonical full-ID stderr checks. No runtime code, private configuration, tests or accepted B/C/browser/rollback mains are changed. The repair uses fresh artifact/active-marker identities, preserving #49. New frozen-source gates have not yet run.

The current gate template is `examples/ecs-native/deploy/Jenkinsfile.shanghai-final-gates-repair`, with `scripts/ecs_native_final_code_gates_repair.py` and `_repair_inner.py`. The original final-gates template/helpers remain historical #49 evidence and should not be selected for a new run. Repair gates retain the unchanged existing suite commands; final runtime acceptance is pending actual execution.


## Git/MIME regressions — #56 focused PASS; complete gate pending

Jenkins #56 completed SUCCESS. The existing artifact-router file and four previously failing benchmark cases passed: 107 passed, one warning, 17.32 seconds. This includes the existing XHTML attachment assertion; no router assertion or active-content classifier was weakened and no test cases were added. The isolated test image remains CI-only image1e10, with source5b plus the explicitly pinned UTF-8 overlay bd40. Its synthetic Git HEAD `44033619b6a0c6c274e1f119de1999795d81096d` describes the public fixture, not the real feature revision. No real Git metadata or credentials were copied.

Root independently verified receipt SHA `375d935c1c0abe8da2a302bb0da714c68f0a1997b6bf2fbafd8fda1062e55729`, public log SHA `99728c60aa24c0411591d3cfdfd38c80e82f1d6c58710e285d72a595a59c8e92`, terminal SUCCESS and exact fixture cleanup. Combined with #53 (104 passed, three skipped), the five diagnosed failures have focused regression evidence. This does not accept the full backend suite. Shanghai roles still use image52ce, which predates the UTF-8 and media-types source corrections.

The next complete gate uses a new coherent public-source freeze containing both corrections and three new complete-gate helpers, without an overlay. It runs only the existing Ruff check/format, four default backend shards and blocking-I/O gate, serially in the isolated CI image. Each pytest shard retains its 900-second bound and retires its owned process group before proceeding. A failed or timed-out gate remains failure evidence; subsequent gates still report their own results. The outer bound is 4,800 seconds, Jenkins stage 85 minutes and global 95 minutes. These are upper bounds, not an ETA. No model mains, installed-role changes, local Docker or new test matrix are part of this gate. Task6 remains incomplete; OS reboot/automatic NAS recovery and production packaging acceptance remain separate pending work.


## Complete gate #57 ABORTED — test-environment repair before another full run

The coherent source snapshot is `edc79ace210edc74943274b518a5da574f72a33a2c70e93242427517f3415a3f`, archive SHA `2d4058d0e7c6ca2ae57711f4f7e37c19171d25ffed6bdd327b21ccf450962b41`, manifest SHA `a7129e690525e93b626dfcbe6adc7373770337c1402998c98234eac3da0edb5b` (3,858 regular entries). Root verified every byte/mode against the public source and independently verified uploaded receipt SHA `63539142b0e5d9b0dc5227995d23a248ca985289df944321f578d8b329949e3c`.

#57 Ruff check/format passed. Shard 1 reached the existing 900-second bound; its structured result is exit143, timed_out=true, elapsed906.124s, process_group_retired=true, and no final counts/summary. Its log SHA is `b469d18ca1db0494e5adfddcceb5eb996c3342893897d4915d5d6f7b7a431574`. Actual failures identified missing CI make, hatchling absent from the empty cache, and global UV_OFFLINE rejecting the extension tests' own localhost Git fixture. Two existing test-contract defects were also identified: an obsolete direct runtime→native-role assertion, and bare import conftest resolving the monocle plugin instead of the backend privacy plugin.

To avoid repeating known invalid-environment failures across remaining shards, only the owned #57 build was stopped through its normal Jenkins endpoint after shard2 began. Root independently verified terminal ABORTED, normal post cleanup, exact fixture absence and no full receipt. Public log SHA `c59fa2643f038d1123d95f793f23c5058a9c6b792470b9fb469e4c0f2b30c949`; durable stop intent SHA `6a49bf8af668eba9b07cf75e518d255ac3394f31bfadd72248463ab604949105`. This is not backend acceptance; earlier failed artifacts remain intact.

The two existing tests now assert the actual runtime→native-core→native-role chain while preserving production-default, Gateway CMD and shutdown-budget checks, and select the already-loaded backend conftest plugin by its exact path while retaining live/ordinary privacy assertions. Ruff check/format passed; runtime regression checks are pending. No test cases were added or removed.

The selected CI repair adds make alongside CI-only Git and retains runtime MIME data. Top-level uv uses --offline --no-sync command flags; that policy is no longer inherited globally by extension-install subprocesses. Trusted public repository tests may download official package-index dependencies and use their own loopback fixtures through an isolated Docker bridge, with no credentials/env files, Docker socket, NAS/database mounts or published ports. This changes the CI environment only; ordinary B job network-none isolation and production tool dependencies remain unchanged. Focused existing regression/extension checks must pass before another full gate.

A bounded source-hash comparison of the installed image52ce against all 917 public app/harness/extension-api/executor entries found 914 identical, three changed and none missing. The changes are the executor README, publication.py (AST-identical formatting), and local_backend.py (the UTF-8 repair). Root verified comparison receipt SHA `b9a774e73f24f7d0f69fda3cdf694ea9a8bb59d967955b1147aceb3d05724732`; exact cleanup passed. Prior comparison attempts stopped at an overly strict public-directory guard or non-root access to publication.py and remain recorded as failures. A production derivative remains pending and must align these public files plus media-types; it must not deploy the CI Git/make image. Installed roles, models, DB/NAS history and earlier main acceptance are unchanged. Task6 remains incomplete.


## CI tools #58 SUCCESS — focused regressions pending

CI-only image `sha256:4f269f6b0e50f9579e099e91a23df868ff1b1a49c03cc9b138beac02dafb3f01` adds Git, make and media-types to base52ce without copying application source. Jenkins #58 finished SUCCESS; metadata verified Git2.39.5, GNU Make4.3, media-types10.0.0 and standard XHTML MIME as non-root UID1000 in a network-none fixture. Root independently verified receipt SHA `e9d9550827b670c273bc1d7ef5d5462d22808962ed8920cf1708b24b8405833e`, exact image ID and original builder stopped. Application source, installed roles and model calls were unchanged. This is dependency metadata acceptance only; selected existing regression/extension tests and full backend acceptance remain pending.


## Focused repair #59 SUCCESS — final complete gate pending

Jenkins #59 completed SUCCESS using CI-only image `sha256:4f269f6b0e50f9579e099e91a23df868ff1b1a49c03cc9b138beac02dafb3f01`. Existing selected tests ran in the full collection context: 15 passed, 6 skipped, 27,250 deselected and one warning in 203.30 seconds. Privacy-plugin selection, actual Docker stage inheritance, client live policy, local extension snapshot rejection and Git extension upgrade passed. No cases were added. The trusted test fixture used an isolated bridge and top-level `uv run --offline --no-sync`, without globally imposing UV_OFFLINE on extension subprocesses.

Root independently verified terminal SUCCESS, receipt SHA `96567c76e2015aaa0eab24c633a57acb9525c0d109c5232fcaa1c4e4b0698be6`, public log SHA `b151d5d82eb40041c5aa96ef8b811b8255d1b0f5032d16c9702011ced480c4df`, actual node outcomes and exact fixture retirement. The historical edc79 source plus two reviewed public test overlays describes this focused run; it is not a coherent final-source full gate. Production roles, models, NAS and database history remained unchanged. Full backend gates, corrected production packaging and coherent delivery remain pending; Task6 is incomplete.


Final environment checkpoint #61 FAILURE: actual complete blocking-I/O passed229 (29.98s), while default shards3/4 timed out with no full counts. Three existing contract failures were repaired without adding cases. The independent source-venv fixture and twelve whole files plus complete shards3/4 remain pending; failed and partial results are preserved. Exact source/receipt/log/cleanup evidence is in the [resume record](ecs-native-shanghai-resume-2026-10-10.md#environment-repair-61-failure--complete-blocking-io-pass-default-groups-incomplete). Installed roles remain52ce; full backend and production packaging acceptance is not claimed.


## 2026-10-12 真实销售业务链路

开机恢复后原 e84 环境的唯一销售 C→B→C 主干在 `deerflow-native-business-sales-20261012 #3` SUCCESS，172.310秒。四行示例 CSV 真实委托 B worker 汇总，原生通知触发 C 续跑，通过 read_file/present_files 交付，认证下载200且金额3400.00/文件字节独立核对正确。两个 native Run success、三项账本工作 completed/physical_stopped、B attempt=1；收尾 drain=true/unreleased=0。前两次失败均在业务提交前，脚本与日志保留。详见 [本轮业务验收](ecs-native-business-sales-validation-2026-10-12.md)；此结果不替代新镜像交付主干验证。
