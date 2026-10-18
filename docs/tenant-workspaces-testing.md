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
- 单机 B 的物理主干已验证；pool、其他资源域撤权、原生 MCP 的完整 HTTP 入口、C 启动/
  恢复/通知及完整 C→B→C 仍须实施。撤权后的缺少可信 STOP 回执时原生 task 保持原状态，
  不通过被撤销的成员授权写业务结果。
- 原生权限 fence 会锁 workspace、actor、私有线程、Run 和 task；M10 需要验证实际
  数据库角色的查询/行锁权限，配对备份恢复和镜像/配置清单。
- 实际资料、研究、带来源报告及持续跟进的模型业务验收属于 M9。
  本测试不调用模型，也不替代完整产品验收。


## 原生 MCP 持久取消与停止回执（本轮 M4）

沿用上面的上海物理专属任务与固定镜像。渲染流水线时增加
`--suite control`，运行 `backend/tests/test_workspace_execution_control.py`。
默认不设置物理 opt-in 时，在 fixture 创建前跳过。不要在本机 Docker Desktop
运行，也不需要生产 key 或真实模型。

先跑通主干，再做必要边界。本轮主干是：原生工具持久提交 B，真实容器启动，
源 Run 结束且 UI 切换空间，原生所有权转移使旧成员版本失效；同一事务写入停止
意图并阻断旧轮询结果；独立控制服务请求 STOP；worker 真正移除容器后返回签名
回执，原生 outbox 和原 task 才结算。另一个场景验证排队用户取消、不启动容器、
缺少服务时拒绝、重复意图、伪造/过期/错用途回执拒绝、租约过期和服务重启。

控制凭据只允许 STOP，不能提交或读输出。回执只携带目标绑定、规格摘要、观察
时间和停止证据；取消/撤权事务不做远程 IO。根撤权事件仍 pending，不能用 MCP
子项完成替代 Run、browser、Scheduler、credential 等资源域的撤权验收。

当前链路用 ASGI 与可信内部准入 fixture；真实 Gateway/JWT、网络/NAS、pool、
远程 C、通知、账号/策略撤权和重启故障仍待实施。总租户门禁保持关闭。执行回执
追加在 progress JSON 的 `native_mcp_stop_control`，保留失败历史和最终源码摘要。

A historical/ordinary terminal B state without `physical_stopped` remains pending.
The control request now persists `cleanup_pending` for the existing worker to
verify exact owned-container absence/removal. Terminal metadata alone cannot
produce a STOP receipt or settle native cancellation; a running or unobservable
object still retains uncertainty. The companion test uses actual Docker
observation after the old ordinary queued-cancel path.

## 原生 Run 成员撤权与清理阻塞（M4）

测试入口是 `backend/tests/test_workspace_revocation.py`。这是原生 LangGraph/RunManager
与 SQLite/PostgreSQL 的确定性检查，不调用模型；测试容器不需要 Docker socket。
可信内部 principal/准入 fixture 不代表公开 Gateway/JWT 已接通。

先验证实际 graph 运行，成员版本在原生事务中变化，持久 cancel intent 与 run_stop
同时提交；UI 选择另一个空间后，原生心跳仍消费原始 Run 的 interrupt。分别持有
图清理和 native completion hook：即使 Run 元数据已 interrupted，另一个 worker
也不能建立新 Run，原 owner 仍可为清理续约。实际 worker task 退出、stream/
journal/生命周期/sandbox lease 清理成功且 owner 租约有效后，才能确认 native
execution closed。失败或未知保留阻塞，绝不从租约过期推断 STOP。

共三类场景，各覆盖两种数据库：正常主干、同一主干的真实 finalizer 报错分支、
排队且未附 worker task 的 NoStart。排队检查同时覆盖错误 owner/原始快照/父代次/
创建时间、过期租约、普通孤儿回收拒绝、重建父线程不被旧清理改写和幂等确认。
这里的 NoStart 只描述 native graph 未开始；C 容器停止仍必须由执行账本证明。

可复跑的专属 SQL CI：

```bash
# 保存本地提交后生成只含版本库文件的源码归档；不包含私有配置或 key。
git archive --format=tar.gz HEAD -o /private/tmp/tenant-run-control-source.tar.gz
shasum -a 256 /private/tmp/tenant-run-control-source.tar.gz
python scripts/render_tenant_run_control_pipeline.py tenant-run-control <归档SHA256> \
  > /private/tmp/Jenkinsfile.tenant-run-control
```

将源码包以 `tenant-run-control-source.tar.gz` 上传到上海 Jenkins 专属任务目录，
使用渲染的 Jenkinsfile 更新 `deerflow-tenant-execution-m4-sql`，先验证再构建。
目标工作目录固定 `/data/jenkins-agent/deerflow/tenant-execution-m4-sql`；先确认没有
本任务正在运行/排队。认证仅在 Jenkins 本机，权限沿用已授权范围。

仓库模板 `examples/ecs-native/deploy/Jenkinsfile.tenant-run-control.in` 校验源码 SHA，
固定 tools/PG 镜像 ID、内部网络及 CPU/内存；容器只读挂载源码包。Python/SQL/graph
在上海运行，不挂生产/NAS/模型凭据、不发布服务端口。宿主仅启动带本次精确标签
的测试容器，清理并记录专属 PG 匿名卷，保留日志与 `run-control-<BUILD_NUMBER>/`
中的卷名回执。旧未记录卷不推测归属，不做全局 prune。

新增控制记录复用通用 outbox，无 ORM 迁移（native 0040/executor e0003）。实际
运行需要 native ownership heartbeats；失败的关闭确认保留 pending，完整故障恢复
仍在 M10/M11。完整 Run HTTP/JWT、直接用户取消、checkpoint/journal/工具发布权限
栅栏，以及先进入终态再撤权的生命周期窗口尚未完成；不要据此启用租户总门禁。
其他执行域、browser、Scheduler、凭据和完整 C→B→C 仍需实施。

## Run 从准入到关闭的持久生命周期

`run_execution` 在新 scoped normal Run 准入的同一事务中建立；原生 Run 仍是执行
权威，该记录只保存“尚未确认关闭”的事实。pending handoff/adopt 仅同事务转移
native owner，不改原始用户、空间、线程代次、创建时间和授权快照。历史缺失记录
不自动补。没有新增表或迁移（native 0040 / executor e0003）。

`Run.status=success/interrupted` 不等于清理已结束。生命周期未关闭时，另一个
worker 仍不能准入；原 owner 可为清理续约。正常结束、终态清理期撤权和另一
worker 发起 interrupt 均由实际 native graph/heartbeat 验证。外空间或已撤销
成员不能复用缓存来取消。只有原生最后关闭边界和有效 owner 绑定能关闭 OPEN
记录；已提交的精确回执可幂等识别，过期租约不能新释放资源。

另一个真实状态检查覆盖未启动 rollback：记录最初请求，但只消费 interrupt，
明确 NoStart 后，迟到消费者也不能恢复或删除 checkpoint。测试用实际 SQLite
checkpointer，检查前后 checkpoint ID 和内容。正在运行的 scoped rollback
仍拒绝，直到完整 checkpoint 权限栅栏接通；不把未实现能力当已支持。

复跑时沿用上一节源码包/专属任务步骤，渲染命令增加白名单 suite：

```bash
python scripts/render_tenant_run_control_pipeline.py tenant-run-lifetime <归档SHA256> \
  --suite lifetime > /private/tmp/Jenkinsfile.tenant-run-lifetime
```

源码包须命名 `tenant-run-lifetime-source.tar.gz`，与 phase 对齐。该套件共十四项：
八项生命周期/真实 checkpoint 检查，加原有六项 Run 撤权/失败清理/NoStart 检查。
新增场景先跑主干，之后回归既有实现；不把完整后台功能当已完成。应用测试只在上海；本机仅做标准库打包/渲染、Git、OpenSpec 和静态格式检查。
复跑需要的镜像、内部 PG 和精确卷清理仍由同一仓库模板管理。

全部 scoped Run 都不走旧的“租约过期即孤儿释放”，即便历史生命周期记录缺失。
仍需完成受认证的 owner/实例恢复与远程 C 物理 STOP。M8 配额必须计入未关闭
生命周期。清理通过原始 workspace-first 锁序避开审计 FK 与成员变更的反向等待，
不依赖仍有效的成员授权；锁 workspace 也不授予执行或读取结果权限。

完整 worker checkpoint/journal/goal/外部工具写入权限、真实 JWT/HTTP、account/
policy/Scheduler/browser/credential 撤权、实际 C→B→C 和成套恢复仍未验收。
本轮仅内部确定性 graph/SQL/SQLite-checkpoint 及已有 MCP 物理回归，没有真实模型、
新公开接口或租户启用。最新回执将记录在 `native_run_execution_lifetime`。

## 原生 worker 的 checkpoint 提交保护

本轮复用 native Run/graph 与 AsyncSqliteSaver，并先保存已有私人报告。正常生成
可以追加报告；成员版本变更、用户 interrupt、native lease 过期或 owner 更换后，
迟到输出不能改变 checkpoint 的 ID、内容和 pending writes。失去 owner/lease
不等于可以关闭生命周期，持久阻塞记录仍保留。

Jenkins SQL #53 先复现撤权漏洞，#54 主干四项通过。#55 的旧输入 checkpoint
尚在后台落盘，#56 的同步 SQLite 夹具写阻塞异步事务：测试现改为观察真实 saver
commit，并用 async session 建账号。#57 十项通过（34.16 秒）；#58 复用已有
十九项撤权、生命周期和 worker context 回归，没有增加其他场景。所有证据/hash
及精确资源清理见 `native_worker_checkpoint_fence`。本机没有运行应用或测试。

复跑沿用同一专属 SQL 任务及固定镜像，先渲染 checkpoint 主干，再跑旧回归：

```bash
python scripts/render_tenant_run_control_pipeline.py tenant-worker-checkpoint <归档SHA256> \
  --suite checkpoint > /private/tmp/Jenkinsfile.tenant-worker-checkpoint
python scripts/render_tenant_run_control_pipeline.py tenant-worker-regression <归档SHA256> \
  --suite checkpoint-regression > /private/tmp/Jenkinsfile.tenant-worker-regression
```

每次 source tar 的 `<phase>-source.tar.gz`、SHA 和实际上传 phase 必须相符，沿用
前述本机 Jenkins 凭据、own-job busy 检查、只读源码/internal PG 及精确卷清理；
不挂 Docker socket、NAS、生产凭据或真实模型配置。

该保护核验原始 workspace/actor/线程代次/Run 创建时间/worker、open lifetime、
实时成员权限及 native lease；只在准备好的 saver IO 期间持 SQL 锁并 drain，
不会锁住模型推理。取消/撤权不能变成新的 checkpoint 清理授权；active rollback、
copy/prune/delete 仍拒绝。普通 Run 的 goal/duration 若经过该 saver，也受同一
保护；其他 producer 仍需独立接入。

这是 full-mode SQLite checkpoint + SQLite/PostgreSQL 元数据库证据，尚未覆盖
PostgreSQL checkpoint、delta/cache、同文件 SQLite、跨库事务/崩溃未知结果。
Journal/SSE/发布、通用 Run 状态/进度、工具和其他权限效应、真实 HTTP/JWT、
远端 C 与 C→B→C 仍未完成；不能据此开启租户功能或声明整条业务已验收。

## 原生 SQL 日志与普通 Run 元数据写入

这一步用实际 `run_agent`、编译图、异步 `BaseChatModel` 回调和 SQL 日志跑通
正常报告，再持住生成过程，分别撤权、取消、让 native lease 过期或更换 owner。
模型输出为确定性夹具，没有调用 DeepSeek 或其他真实服务。两种元数据库都验证
正常日志保存原 user/workspace，迟到正文和 Run 完成统计被拒绝。失去 owner/lease
不能确认清理完成；取消/撤权在实际 native 关闭后才解除生命周期屏障。

#59 RED 四项复现缺失空间及撤权后落库；#60 主干四项通过（21.81s），#61 必要
边界十项通过（33.04s），含空 Context 中旧接口不得覆盖 scoped Run 或写入私人
日志。#62 原有回归暴露四项逻辑 interrupted 状态被一并拒绝（27 passed）。新增
仅消费精确 pending STOP 的控制状态通道后，保留原断言；#63 最终 46 passed
（96.58s），十三文件 Ruff。它复用先前的生命周期、checkpoint、事件读取检查
及五项直接相关旧路径回归，没有增加其他业务场景。

日志/普通 Run 元数据在各自原生数据库事务内重查原始执行权；只持有短 SQL 锁，
不会锁住模型或工具。已知权限拒绝会丢弃被拒绝的缓冲并 drain/detach，不把正文
重新排队；真正 IO 失败仍保留既有重试与未知清理语义。逻辑 interrupted 不能写
正文/统计/错误/goal，也不能作为 STOP 回执或提前释放准入。

同一固定模板提供两个白名单 suite：`--suite effects` 跑本轮业务主干和边界，
`--suite effects-final` 跑最终固定组合。示例：

```bash
python scripts/render_tenant_run_control_pipeline.py tenant-worker-effects <归档SHA256> \
  --suite effects-final > /private/tmp/Jenkinsfile.tenant-worker-effects
```

源码包、phase、SHA 对齐，使用同一专属 SQL job、固定镜像、内部 PG 和精确 label/
匿名卷清理。回执 `native_worker_journal_metadata_fence` 含每次构建、归档/日志哈希、
最终源码和已移除资源，不猜测旧无记录卷归属，不做全局 prune。

未涵盖 SSE/缓存/发布、ThreadMeta 标题和状态、模型工具调用及外部副作用、scoped
pending dispatch 和 owner/实例恢复、active rollback、真实 HTTP/JWT/browser、
quota/billing 或远端 C。被拒绝的 token 统计不能作为完整计费证据。仍需完成所有
撤权域及真实 C→B→C；启动旗标和 schema fence 不变，不据此启用租户功能。

## 原生流生产与线程状态保护

这一步直接扩展上一节的同一业务用例，用 `MemoryStreamBridge.subscribe` 读取实际
重放队列，并检查 ThreadMeta。没有新增场景矩阵。#64 RED：正常两项通过，但
撤权后迟到的完整 AI 响应仍在原生流队列中（两种元数据库各失败一项，21.19s），
说明 SQL 日志保护不能替代流生产保护。#65 主干四项通过（21.50s）；#66 原有
固定 46 项全部通过（97.72s），十五文件云端 Ruff。

取消/撤权后，迟到正文不能进入队列；实际 native 结束后可发无载荷 end，并更新
原私有线程的结束状态。lease 过期或 owner 被替换后，旧 worker 不能写迟到帧、
结束新 owner 的流或覆盖其 idle 状态/标题，生命周期仍保持 open。实际关闭的
状态回写不依赖已撤销的成员权限，只能针对原始线程代次；title writer 接同一
效应 fence，但这里没有宣称完整 held-title 发布/UI 已验收。

短 SQL fence 只包住准备好的原生队列写入并 drain，不包模型、工具或 SSE
subscriber 的 socket 发送。它不能让独立的 SQL/Redis 变为一个分布式事务。
生产者 view 不提供 subscribe/删除权限；消费端仍需既有 fresh observer 验证。

复跑先用 `--suite stream-main` 运行同一用例的正常/撤权对照，再用原有
`--suite effects-final` 固定组合覆盖已有取消/过期/换 owner 和旧路径回归：

```bash
python scripts/render_tenant_run_control_pipeline.py tenant-worker-stream <归档SHA256> \
  --suite stream-main > /private/tmp/Jenkinsfile.tenant-worker-stream
```

沿用同一专属 SQL job、源码包 phase/SHA 核验、固定镜像与精确 label/匿名卷清理。
所有构建、源码/日志哈希、已移除的精确资源见 `native_worker_stream_thread_fence`。
本机只做 Git/标准库打包/OpenSpec/静态格式，没有运行应用或测试。

验证限于 MemoryStreamBridge 生产/重放与 SQL，不是 Redis、HTTP/JWT/browser
socket、跨进程 generation、背压/故障/重启或跨库未知结果验收。模型/工具调用
发生前的权限、文件/发布/网络等外部效应、scoped dispatch/recovery/active rollback
和远端 C 仍待完成。不得把丢弃输出当成已阻止工具副作用或开启租户的依据。

## 普通异步原生模型与工具的调用前检查

本轮用真正的 `run_agent`、`create_agent`、完整共享 lead runtime middleware、模型
工厂、BaseTool 以及实际临时文件，检查调用发生前的权限。provider 为确定性夹具，
没有调用外部模型服务。#67 RED 两项撤权用例显示排队 handler 仍执行；#68 进一步
用实际文件存在断言复现副作用，并抓到上一轮流 view 拒绝全部 cleanup 的回归。
#69 主干 14 passed（42.48s）；主干通过后再补三个直接模型边界，#70 共
26 passed（66.74s）；#71 最终固定 63 passed（133.41s），22 文件云端 Ruff。

四个调用点都检查正常/成员版本撤销及两种元数据库：排队工具、合法工具完成后的
第二次模型、显式 callbacks=[] 的独立工厂模型、限流队列放行。被拒绝的新 handler
和 provider 不进入，工具不会新写文件；第二次模型场景保留先前合法生成的文件。
正常业务仍完成。模型工厂保留 provider 类型及原 limiter，暴露的 max_retries
字段归零，避免 SDK 隐式 retry 绕过 native 调用准入。缓存 worker 模型在没有
当前 worker 的情况下也拒绝调用。此处不是实际 DeepSeek/429/SDK 网络重试证据。

十个既有流/元数据用例新增精确 cleanup 断言：completed 原 Run 可清理本 lane，
open/失去 owner/过期生命周期保留，foreign lane 拒绝。旧版生产者直接拒绝延迟
cleanup 的后台异常现已修复。延迟在 SQL 锁之外，延迟后再检查回执和原绑定。
六项相关旧检查覆盖原生 lead/subagent 顺序、模型默认选择/追踪、FIFO 及声明式
排序。现有 middleware 数量/索引断言同步到新的最外层门禁，没有放宽控制/权限。

复跑仍使用同一固定 SQL job/镜像/internal PG/RO 归档和精确 label/匿名卷清理：

```bash
python scripts/render_tenant_run_control_pipeline.py tenant-invocation <归档SHA256> \
  --suite invocation > /private/tmp/Jenkinsfile.tenant-invocation
python scripts/render_tenant_run_control_pipeline.py tenant-invocation-final <归档SHA256> \
  --suite invocation-final > /private/tmp/Jenkinsfile.tenant-invocation-final
```

phase/source tar/SHA 必须一一对应；凭据仍仅 Jenkins 本机使用，不挂生产/NAS/
模型密钥。完整构建、归档/日志/源码哈希和已清理精确资源：
`native_invocation_admission_fence`。本机没有执行应用或测试。

SQL 检查完成后才进入 handler/provider，模型与工具 IO 不持 SQL 锁。当前仅验证
普通 async run_agent 主体；已准入 IO、HostModelInvoker 的 shielded 实际 provider
任务、title/summary/goal 的 fallback 控制信号、非 Run/嵌入/同步模型入口及各类
SDK/transport/cache 仍须审计。Scoped callback 要求原生所属 async loop；不能
用缺少上下文推导出权限。账户/token/policy 等撤权域、外部效应、scoped dispatch/
recovery、真实 HTTP/JWT/browser/Redis/NAS/C、计费配额和完整租户验收继续保留。


## M4 模型服务实际生命周期与停止信号（2026-10-17）

上海 `deerflow-tenant-execution-m4-sql`：#72 是夹具签名错误，不能作为业务 RED；
修正后 #73 在两种数据库复现四处提前退出，#74 再复现六处停止信号被吞。
#75 主干先通过 12 项；#76 增加必要边界后 14 项通过；#77 最终 `85 passed, 4 warnings in 166.83s (0:02:46)`，
二十六文件云端 Ruff check/format 通过。原有 63 项复用，新增本轮 14 项，
另复用 8 项直接相关的模型服务/标题/摘要旧检查；没有扩展到全套后端测试。

真实 native Run、SQL 成员变更/心跳、HostModelInvoker、模型工厂及 BaseChatModel
继承的线程执行链：调用者退出后实际线程仍被持有，同线程替代任务被拒绝，lease
持续续租；不同空间在同一个服务/预算上可独立完成报告。provider Task 被直接
cancel 也须等真实线程停止；正常 completion hook 仍可调用模型收尾。先 drain
主体遗留调用，完成钩子后再封住新调用并 drain，最后才清日志/沙箱和确认 native
生命周期关闭。模型构造/执行不持 SQL 锁，不以全局服务预算阻塞其他 Run。

扩展服务、异步标题 fallback、摘要构造及同步/异步 fallback 保留 GraphBubbleUp；
撤权不会转成普通 provider failure、None 或本地标题后继续执行。普通失败仍保留
原有清洗/降级语义。本轮 title/summary 的证明是停止信号，**不是其直接模型调用
底层线程生命周期的完整验收**；goal fallback、直接 lead/system 模型 lifetime、
非 Run/同步/嵌入入口和外部传输仍待接通。

固定复跑入口：

```bash
python scripts/render_tenant_run_control_pipeline.py tenant-service <归档SHA256> \
  --suite service-lifetime > /private/tmp/Jenkinsfile.tenant-service
python scripts/render_tenant_run_control_pipeline.py tenant-service-final <归档SHA256> \
  --suite service-final > /private/tmp/Jenkinsfile.tenant-service-final
```

同一上海 internal PostgreSQL/RO 归档/固定镜像、专属 job，无生产挂载或模型密钥；
精确容器/网络/匿名卷清理与源码/日志/归档哈希见 `native_model_service_lifetime`。
LangChain inline callback 拒绝时存在 `ahandle_event was never awaited` 警告，
RED/GREEN 均可见，未隐瞒或声称无警告。未调用真实 DeepSeek，也没有 physical C、
HTTP/JWT/browser/Redis/NAS/计费及完整租户验收；M0–M11 父项保留，启动关闭。


## M4 原生直接模型生命周期与目标停止信号（2026-10-17）

上海 SQL job #78 先复现 lead/title 取消后仍有真实线程、native worker 却已关闭：
四失败、四正常对照通过。#79 目标评估实际吞掉 WorkerInvocationDenied 并写入普通
失败 verdict：两失败、六个既有命名 STOP 路径通过。#80 主干先 8 passed；#82
复用同一夹具补 summary/goal 与必要边界，36 passed；#83 最终 `114 passed in 226.63s (0:03:46)`，
二十七文件云端 Ruff check/format 通过。旧 85 项复用，本轮仅二十个直接入口用例、
两个目标 STOP 用例及七个相关目标旧回归；不跑无关全套。

invoke_worker_model 仅在 host 私有 guard 内保留实际工作，调用前核验、登记原 Run
任务并 shield；被保留任务本身取消时也 drain。普通 lead 全共享 middleware、
异步 title/summary、goal evaluator 接入同一入口。目标 usage sink 随实际调用一起
执行；未绑定 guard 的旧入口保留原语义。模型类型/算力服务/观测协议没有替换。
目标的读/准备/评估/持久化/重读路径保留原生权限拒绝与停止信号，普通 provider
及 JSON 错误仍按原规则记录评估失败。停止信号不是普通 verdict。

正常/取消覆盖四入口和两种数据库；#81 的两失败仅为 fixture 错把 provider 自身取消预期为用户中断；LangGraph 正确以
NodeCancelledError 记为 error，线程等待/隔离已通过；#82 修正预期后全通过。
这些用例同时覆盖 lead 成员版本撤销、title 保留任务被直接
cancel 两处必要边界。复用原有续租、同线程拒绝、另一个空间独立完成、实际线程
退出后清理、合法 completion 模型收尾断言。不以全局任务 drain 代替按 Run 所有权。

```bash
python scripts/render_tenant_run_control_pipeline.py direct-main <归档SHA256> \
  --suite direct-main > /private/tmp/Jenkinsfile.direct-main
python scripts/render_tenant_run_control_pipeline.py direct-final <归档SHA256> \
  --suite direct-final > /private/tmp/Jenkinsfile.direct-final
```

仍是固定上海 internal PG/RO 源码/既有镜像/专属 job、精确资源清理，没有本机应用/
pytest/Docker；归档、日志、源码哈希和清理回执：`native_direct_model_lifetime`。
目标 STOP 场景使用实际内存 saver/accessor 加真实 SQL 成员权限；不是完整持久化
scoped goal continuation/recovery 验收。确定性同步线程模型证明已命名调用点的
生命周期，不证明任意外部 SDK、网络流或物理 C。工具/FS/进程/网络/发布效应、
其他撤权域、dispatcher/recovery、HTTP/JWT/browser/Redis/NAS/配额和完整 M0–M11
仍须推进；租户启动关闭，不推送、不部署。

后续源码检查已确认 sandbox.lease.run_sync_lifecycle_operation 本来就 shield/drain
实际同步线程，sandbox.tools 的异步原生工具也在使用它。下一步先复用、验收原始
Run/私有空间绑定、延迟调用准入和输出效应，不重写沙箱执行器。该阅读结论不算
scoped 工具业务验收。


## 2026-10-18 原生沙箱调用与写入前检查验收

恢复后核验暂停前的同一 Jenkins #88，没有重启测试。`sandbox-final` 固定回归
**134 passed in 250.07s**，30 文件 Ruff 检查/格式通过；当前 33 个相关源码文件
与归档逐字节一致。上海专属 job：`deerflow-tenant-execution-m4-sql`。

- #84 RED：2 failed / 2 passed（21.23s），实际就绪等待后撤权仍写出报告。
- #85 主干：4 passed（20.84s），实际原生 owner 与租约释放断言通过。
- #86 RED：2 failed / 6 passed（28.93s），写入前检查吞掉原生 STOP 并 fail-open。
- #87 必要边界：12 passed（36.83s），包括完整 create_agent 共享 middleware。
- #88 固定回归：沿用此前 114 项，加本轮 12 项及八项既有沙箱兼容检查。

工具就绪/复用返回及同步线程执行前重新检查私有 Run guard；先记录 sandbox_id
以允许拒绝时正确退还已有租约。复用原生 run_sync_lifecycle_operation 的 drain，
没有新造执行器。工具错误归一化与 read-before-write 检查/读标记保留 GraphBubbleUp；
旧 sandbox 授权 provider 的单次判断及普通写入保护不变。

用例复用实际 SQL 成员版本、原生 Run、LocalSandbox、真实报告文件与原生租约。
正常报告内容正确，撤权后文件不存在、停止未被转成普通工具错误、owner 无遗留。
外层切换空间不会改变原 Run 捕获的身份。确定性模型只用于触发实际 SDK 工具链。

复跑入口（仅上海；归档摘要需匹配本次源码）：

```bash
python scripts/render_tenant_run_control_pipeline.py sandbox-main <归档SHA256> --suite sandbox-main
python scripts/render_tenant_run_control_pipeline.py sandbox-final <归档SHA256> --suite sandbox-final
```

归档/日志/33 文件摘要、五轮精确移除的 PG 临时卷、空容器/网络和固定镜像回执见
`progress.json -> native_sandbox_dispatch_fence`。#88 归档：
`1ea76044aef8e18c7526c307b4c35b4df3514a7c37655690675a8f61c65b18cb`。
仅核实已记录的临时卷，没有推断旧卷所有权或全局 prune。

这不是主机文件系统隔离、进程/网络/外部发布原子性、任意 provider SDK、远端 C
物理停止或全部缓存命名空间验收。下一步审计实际 provider 的空间/线程代次身份
及旧缓存复用，先证明主干问题再修。完整 M0–M11、其他撤权域、scoped dispatcher/
recovery/API 和产品验收仍待推进。租户开关 false、启动 schema fence 不变；
没有本机应用/pytest/Node/浏览器/Docker 测试、真实模型调用、部署或推送。


## 2026-10-18 原生 Local 删除重建主干：复用现有机制

上海 `deerflow-tenant-execution-m4-sql #90 SUCCESS`，**4 passed in 23.64s**，
30 文件 Ruff 检查和格式通过。SQLite/PostgreSQL 各运行正常续跑和真实删除重建：

1. 实际原生 Run、LocalSandbox 和 write_file 写出报告并成功关闭、退还租约。
2. 同一线程代次正常续跑，可读回完整报告。
3. 走真实 `delete_private_thread`：持有原生删除预约，使用生命周期回执完成文件/
   checkpoint/session/metadata 清理。然后同 ID 重建，确认 incarnation 改变。
4. 新 Run 即使携带原先 sandbox ID，也无法读回旧报告；成功状态与 owner 清理明确断言。

首轮 #89 四项失败是夹具漏开必需的 ownership heartbeat，业务节点未执行，不是
产品 RED；#90 按原生配置启用心跳、120 秒 lease，并显式等待实际 worker task。
最初仅从缓存键推断的泄漏没有被真实 Local 删除主干证实。直接删除 SQL 行会绕过
原生文件清理，不能作为产品故障证据；本次没有据此改生产命名空间或旧 token 契约。

```bash
python scripts/render_tenant_run_control_pipeline.py sandbox-recreation <归档SHA256> --suite sandbox-reuse
```

#90 归档 SHA256：`a27912fab097f3b7e78a1beae44f62459cfc7e47dab577345034fbce22f3447c`。
32 个源码摘要与当前版本匹配；renderer 随后只格式化原有 tuple，实际生成的
Jenkinsfile 与 #90 逐字节相同，另存摘要。本文件此前 12 项用例未改，沿用 #88 的固定
134 项回归证据，不因新增四项夹具重复跑全部。归档、日志、精确移除的两个 PG
临时卷及空容器/网络回执见 `native_sandbox_recreation_main`。

这是实际内部删除入口和本机 Local 沙箱证据，不是完整 HTTP/JWT/browser、崩溃/
撤权中清理、任意自定义 provider、AIO/远端 C、NAS 或进程隔离验收。继续按计划
接 scoped dispatcher/远端 C 准入与恢复；AIO namespace、外部效应及 account/token/
policy 等撤权域保留未完成。M4/M0–M11 父项不勾选、租户启动 false、启动 schema
fence 不变；无部署、推送、真实模型请求或本机应用/pytest/Node/浏览器/Docker 运行。
