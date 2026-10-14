# 多租户实施接续记录 — 2026-10-14

用户要求保存当前进度，明天继续。本次暂停不缩小“完成统一计划”的范围；M0–M11完整验收仍未完成。

## 工作位置和已验证提交

- 功能 worktree：`/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2`。
- 分支：`codex/tenant-workspaces-plan`。不要修改环境默认的 `1d28/deerflow2` 上游 worktree。
- `1596886f`：原生 Run 查询按可信空间、原用户、兼容私有 ThreadMeta 父记录过滤；分页/游标/再生成来源/批量/用量均在 SQL 过滤后处理。
- `4c0ea948`：非 Run 的 reject 预约保存 workspace；workspace→actor→thread→clock→Run 锁序；释放匹配捕获空间、用户和 worker，不删除普通 Run；撤权和空间切换不妨碍清理。
- Jenkins `deerflow-tenant-m1-postgres` #42 RED（两数据库跨空间读取），#43 GREEN（8 passed, 21.74s）；#44 RED（预约 workspace NULL），#45 GREEN（7 passed, 21.58s）。
- #42–#45 的每个专属容器/网络 ownership label 已独立查空；最后观察到的 #45 为 SUCCESS。没有为本次未验证草稿启动新构建。
- 证据/源码与归档哈希：`docs/tenant-workspaces-progress.json`；完整设计与计划仍是 `docs/superpowers/specs/2026-10-13-tenant-workspaces-design.md` 和 `docs/superpowers/plans/2026-10-13-tenant-workspaces.md`。

## 暂停时新增草稿，尚未运行

仅修改 `backend/tests/test_workspace_http.py`，扩展已有两数据库真实认证主干，没有新增生产代码：

1. 配置真实 required-scope RunRepository 和原生 RunManager。
2. 新 UUID 会话通过 PUT goal 创建团队私有 ThreadMeta/checkpoint，预约最终清空。
3. 已有团队会话 POST state 更新 title，并同步原生会话标题；个人空间状态不变。
4. 外空间 PUT goal / POST state / DELETE goal 返回404。
5. DELETE goal 清空并可再次读取。
6. 实际 SQL incarnation 在 checkpoint 准备读取时轮换，拒绝旧实例写入，checkpoint ID 不变。
7. 真实 owner admission 后撤销 policy，拒绝写入，checkpoint ID 不变。

草稿只通过本地 Ruff check；未执行 pytest，也未取得 RED/GREEN。已准备本地公开源码归档 `/private/tmp/deerflow-tenant-m3-checkpoint-write-red.tar.gz`，SHA256 `976ec90433e69f4ff8b98f25d404a5ee86937f864703d219c40f7b0fbf4072fb`；尚未上传或触发任务。恢复时以当前源码重新打包，不能依赖临时文件永远存在。

## 明天按此顺序继续

1. 查真实 Git 状态、当前源码和 Jenkins 状态；前一构建已终止，不因观察超时重启运行中的构建。
2. 从现有 PG Jenkins 模板派生 `m3-checkpoint-write-red`，仅运行 `tests/test_workspace_http.py`，确认真正业务失败后再实现。模板位于 `/private/tmp/deerflow-tenant-m3-reservation-red-job.py`；打包脚本 `/private/tmp/prepare-tenant-gate.py` 会生成非PG模板，应在打包后替换成 PG 模板。
3. 为 PUT/DELETE goal 与 POST state 绑定可信 scope，先于 native owner-check；ScopeDenied/HTTPException 必须穿透宽泛异常处理，不能变500。
4. 保留 `/chats/new` 先设置 goal 的原生行为：scoped模式先只建立 SQL ThreadMeta，再取得持久预约，最后受控写 checkpoint；不在预约前写 checkpoint。现有 `_ensure_thread_for_goal` 同时创建 metadata/checkpoint，需拆开或增加明确 metadata-only 路径。
5. 图/schema构建及状态准备在 SQL 锁外进行；捕获私有会话 incarnation，在短提交前重验 live workspace/actor/thread/incarnation。使用专门的 checkpoint 提交边界，不把现有“只用于短文件操作”的 publish_under_live_lock 偷换成模型/图构建锁。回调只允许已准备的原生 checkpoint IO，排除模型/工具/网络业务执行；明确 cancellation drain 和跨库锁序。
6. 重跑相同 HTTP 主干，加入受影响的原生 goal/state 回归；保留失败历史、实际源码哈希及清理证据，更新文档再提交。
7. 继续 M3 生命周期、API/feed/客户端切换，随后依次 M4–M11。不得把已验证的 SQL 预约当作完整后台 Run/租户激活。

## 持续约束

- 所有 pytest、真实后端/模型/Docker 测试在上海 Jenkins/ECS；不启动本地 Docker Desktop或本地 pytest。
- Jenkins 地址 `106.14.210.163`，仅管理 DeerFlow 专属任务。认证只在 Jenkins 本机内存读取已有0600私有文件，不输出/复制凭据；不处理 assetforge 发布审批。
- 测试容器与 PG 使用内部网络、现有测试镜像、CPU/内存限制和专属 label 清理；不挂生产数据库、NAS或Docker socket。
- 已停用的 compiled tenant activation 保持 false；当前 schema0038/e0002。原部署及迁移/恢复/公开注册门禁仍待 M10–M11。当前分支没有新增远程推送或部署。
- 顺序实施，先主干，后必要边界；不派生并行智能体。邮件/域名配置在后续邮件验收阶段处理。

## 恢复后进展

目标已恢复为 active。上述未验证草稿现已跑通：#46–#48失败历史和 #49的双数据库 HTTP 成功均记录在 progress JSON；goal/state生产写入实现与六项未变源码的原生回归已验证。接下来处理 M3 的完整会话生命周期、Run/activity/API和前端空间切换，仍未部署或开启多租户。暂停时记录的源码归档是历史输入，后续以进度文件中的最新哈希为准。

补充：#50发现 owner-check 期间替换会话仍能提交目标，现已按最初准入身份绑定修复。#51完整定向检查8项通过（34.31s），覆盖真实 SQL 替换下 goal/state/clear 不修改 checkpoint。完整生命周期、Run/feed和前端仍是下一工作，不得把这次验收当作整个 M3 完成。

下一轮生命周期准入还需检查：只有 legacy checkpoint、没有 ThreadMeta 的同名 ID，不能因新建元数据而被接管；同时审计原生 POST thread 和 goal 新建路径。当前未验证这一边界，多租户激活继续关闭。

当前接续更新：上一条所列 checkpoint-only ID guard 已由 #52 RED/#53 GREEN 验证，另有真实原生目标交错初始化保护。下次直接从 M3 分支/删除/压缩生命周期及 Run/feed/客户端切换继续；多租户仍未激活或部署。

分支接续更新：#54 RED/#55 GREEN 已验证私有原生分支主干和六项原生回归。源码通过后以当前提交/进度文件哈希为准；接下来处理删除/压缩、Run/feed与前端。失败分支的私有未发布文件/跨库 checkpoint 需要故障回收证据，不得猜测回滚后删除可能已提交的数据；仍未开启多租户部署。

压缩接续更新：#56 RED/#57 GREEN 已完成原生压缩的空间入口/模型前复核/最终 checkpoint fence 主干（8项，36.66s）。实际摘要中间件保留，只有模型响应确定化；租户记忆/归档和真实模型仍未验收。接下来处理删除生命周期、Run/feed和前端空间切换，M4–M11继续保持完整范围，未部署多租户。

## 本次暂停检查点：私有会话删除（用户要求明天继续）

状态：暂停；最后已验证提交 `b8dae318`（压缩）。本次 DELETE 实现和测试以 WIP 保存，尚未通过 GREEN，不代表 M3 完成。

- Jenkins `deerflow-tenant-m1-postgres` #58：RED，2 failed，34.13s；归档 SHA256 `9e352861b80bc6d7cb753b53894e4c2aa337b8dc34cba55f95cafc2e7f734159`。原入口缺可信空间上下文。该构建已观察到终态，尚未独立复核其 ownership label 清理。
- 当前草稿增加删除 tombstone、捕获 incarnation/token 的清理凭据、精确 SQL 子记录清理、原生预约和受控物理清理；失败后保留 tombstone，拒绝盲目重试。legacy 删除入口保留。
- 双数据库 HTTP 主干草稿覆盖私有/个人数据隔离、准入后撤权、删除中禁止读写和重建、失败后保留及拒绝重试。仅本地 Ruff 检查通过；未运行 GREEN，未部署、未推送远程。
- 草稿仅允许 local sandbox 且无 remote admission host，任何持久 MCP task 都拒绝清理；远端 STOP、崩溃恢复、其他执行器清理仍须 M4/M8/M10/M11 完整验收，不能视为已支持。

明天优先：

1. 检查 Git 和 Jenkins 实际状态。不要重复启动运行中的任务。
2. 审查旧上传/转存请求在删除后同 ID 重建时的 generation 隔离：`publish_under_live_lock` 目前没有 expected incarnation 参数。先检查 ingestion/项目文件转存闭包是否已捕获原 incarnation；如缺失，修正最终发布校验，补一条有意义的旧请求跨代拒绝验证。不要直接宣称当前 DELETE 安全完成。
3. 重新打包当前源码，从 `/private/tmp/deerflow-tenant-m3-delete-red-job.py` PG 模板派生 GREEN，仅在上海运行主干及必要原生回归。临时 GREEN 包 `709c3302162ec955b05947dca84c05bfaf7755f013831ddd3aa58b5c6afeddf3` 尚未上传/触发，任何源码变化后作废。
4. 终态后独立检查 #58 和新构建专属容器/网络清理，对照归档源码哈希，更新证据再提交正式实现。
5. 继续 M3 Run/feed/前端切换，然后顺序 M4–M11。全功能范围不变，租户 compiled activation 仍关闭。

本次不启动新测试，不执行云部署或远程推送。所有 pytest/模型/Docker 仍在上海；不运行本地 Docker Desktop。临时打包/实施脚本可能丢失，优先以已提交的源码与本记录恢复，勿重复执行字符串修改脚本。

恢复开发后：删除及文件跨代隔离已由 Jenkins #62 验证（10 passed, 39.38s），
#58–#62 专属容器/网络已独立查空。#59为测试参数遗漏，#60证实旧上传清理
误删新文件，现已以准入 incarnation 和短 SQL 文件栅栏修复。#61两个 HTTP
主干已通过，#62同时通过调整入口后的原生取消 drain 回归。此前“未运行
GREEN”的暂停记录已被本次证据更新；源码哈希以 progress JSON 为准。
当前目标 active，下一项继续 M3 activity/Run/feed（注意 RunManager 内存
缓存不能绕过持久空间和父会话实例）及客户端切换，顺序 M4–M11 不变。
远端 STOP、崩溃恢复和被拒绝清理的数据协调未完成，租户仍未部署/激活。

最新接续：activity HTTP #63 RED/#64 GREEN 已完成（7 passed, 39.36s），
#63/#64 专属资源已独立查空。下一项从 RunManager 内存缓存及 Run/message/
event 读取继续；不可让缓存命中绕过 SQL 私有空间校验，也不可在存储故障时
回退到未验证缓存。随后接 SSE 和客户端切换。目标 active，仍未部署。

最新接续：RunManager 缓存隔离 #65 RED/#67 GREEN（9 passed, 43.47s），
#66为独立原生回归暴露的路径/授权/运行时循环导入，已改为调用时导入。
#65–#67 专属容器/网络已查空；缓存命中现在必须经持久空间授权，撤权、
SQL删除或存储故障不再回退内存，匹配的实时对象与最新状态保留。
下一项接通 Run/message/event HTTP 与 SSE（尤其事件 SQL 分页前空间过滤、
分支历史保留及后台回填），随后前端空间切换。正常 Run 准入和后台
代际/租约/发布仍是 M4，不可把缓存读修复当成执行隔离完成。目标 active。

最新接续：事件 SQL 读取 #68 RED/#69 GREEN（9 passed, 44.47s），
#68/#69 专属资源已查空，源码与归档一致。DbRunEventStore 六类读取在
分页/聚合前过滤事件空间、原用户及 live 私有父会话，保留分支种子历史。
workspace_required 目前只覆盖读取；写入归属/工厂/后台 journal 仍须 M4。
下一项从 HTTP thread_runs 的 Run列表/详情、消息分页、事件入口开始，
保留实时 Run 控制对象，并给 list_run_messages 的 get 传显式用户；
随后 SSE/客户端切换。全局 runs 路由、反馈和后台回填不能遗漏。目标 active。

最新接续：七个 thread Run/message/event HTTP 读取由 #70 RED/#71 GREEN
验证（6 passed, 40.62s），#70/#71 资源查空。实际 SQL 事件与反馈、个人/
团队数据区别、错 Run 路径、其他成员、错误空间和准入时替换实例均覆盖。
下一项从只读 GET join/stream SSE 开始：捕获私有身份，ASGI 发头前复核，
每个传送片段复核并在撤权/删除/实例变化后关闭观察者，不取消后台Run；
关闭时 drain 原生 generator。不能仅给 route 加 decorator 后宣称流式
隔离完成，因为生成器在请求函数返回后才消费。另需全局 /api/runs、
反馈/token/artifact/PUT/history 路径，事件写入/工厂/后台归属仍在 M4。

最新接续：SSE只读观察 #72 RED/#75 GREEN（8 passed, 41.02s）。#73已通过
空间主干；#74额外复现慢订阅关闭拖延创建者取消，现已改为取消意图先发、
清理仍drain。#72–#75专属资源查空，六个源码/测试文件匹配最终归档。
GET join/stream 捕获原实例，ASGI发头前与每片段复核 native权限和SQL
空间/私有会话/Run/凭据版本；版本变化关闭观察，不发END、不取消Run；
Last-Event-ID有效，失效旧JWT重连401。用原生MemoryStreamBridge确定性
帧验收，不代表真实Agent/Redis/物理网络/全账户流程完成。
下一项：全局 /api/runs 读取、反馈、token/workspace-change/artifact/PUT/
history入口（反馈写入必须短SQL事务内复核原incarnation与Run，不能只加
decorator），然后前端空间/缓存切换。事件写入/工厂/正常Run和签名B/C
后台身份仍是M4；M5–M11范围不变。当前active、未推送/部署、激活关闭。

## Global Run locator reads (partial M3)

GET /api/runs/{run_id}/messages and /feedback bind the native authenticated
workspace before resolving the durable Run. In scoped mode the actual actor is
explicit. After discovery of thread_id, the private resource helper captures its
entry incarnation, rechecks the Run/thread association, materializes only that
actor's messages or feedback, then revalidates live scope and original parent
identity before returning. Native unbound calls preserve their original keyword
signatures, envelope/list shape and cursor trimming.

Jenkins #76 RED found missing scope in both metadata dialects; #77 passed 27
checks in 43.96s: actual SQLite/PostgreSQL JWT/SQL HTTP mains and the affected
native global-Run API regressions. Both personal/team payloads are correct,
foreign space and peer IDs return 404, and a real SQL incarnation change after
message/feedback materialization refuses the response. Current runtime/test bytes
match the successful archive. #76/#77 dedicated containers and networks were
independently empty. Existing Starlette TestClient/httpx deprecation remains.

This covers the two global HTTP reads, not FeedbackRepository mutation fencing
or full thread feedback APIs. Token/workspace-change/artifact/PUT/history,
frontend switching, event writes/Run producers and M4-M11 remain requirements;
tenant activation stays closed.

User confirmed native DeerFlow styling; the M7 plan records reuse without a new visual redesign. Next: token/workspace-change read binding, then feedback repository transaction fences and remaining M3 paths. Full M0-M11 scope remains active; no tenant push or deployment.

## Native usage and file-change reads (partial M3)

GET /api/threads/{thread_id}/token-usage and
/api/threads/{thread_id}/runs/{run_id}/workspace-changes now bind the same
private workspace/entry-incarnation wrapper before native owner checks. Existing
SQL aggregation, checkpoint context usage, native Run matching and SQL event
filtering remain authoritative. No new usage engine or file-diff generator.
Both views recheck live scope and captured parent identity after materialization.

#78 RED found missing scope. #79 reached/passed the new two-space usage/change
assertions and eleven native regressions, but its subsequent deletion check had
an outdated fixed personal-event count: the fixture now has one message and one
workspace-change event. Final revision changes only that expectation to exactly
two events (other personal child tables still one; deleted-space children zero).
#80 passed all 13 checks in 45.12s: SQLite/PostgreSQL JWT/SQL HTTP mains and eleven
native token/context/file-change regressions. Personal/team totals are distinct,
include_active keeps the native shape, each diff belongs to its space, summary
and no-diff options work, and foreign space/peer/mismatched Run or changed entry
nonce refuses the response. Real SQL nonce changes after event/context reads
are also rejected. Runtime/test bytes match the final archive; #78-#80 resources
were independently checked empty. Existing TestClient/httpx warning remains.

Feedback repository/HTTP mutation fences, remaining artifact/PUT/history and
frontend flows, event writers/producers/factories and M4-M11 are still required.
This does not enable tenant mode or prove full usage accounting/quota admission.

Latest continuation: #76/#77 global Run reads and #78/#79/#80 usage/file-change reads are recorded; all five builds terminal and exact owned inventories empty. No live validation job remains. User confirmed native UI style. Next: FeedbackRepository scope/read/write transaction guards plus feedback routes, then remaining file/artifact/PUT/history entries and frontend space selection/caches. M0-M11 remains active and incomplete; no tenant push/deployment, compiled activation closed.

## Feedback SQL and HTTP (partial M3)

FeedbackRepository derives private scope from its original actor/thread/Run
relations; no second feedback identity or tenant ownership backfill is guessed.
Reads apply compatible native Run, private parent and live space in SQL before
limit, count or grouping. NULL/unattributed, mismatched-parent and peer rows are
not claimed. Required instances check shape/actor even for empty run-ID batches.
Legacy all-owner aggregate defaults and unbound method signatures are retained.

Scoped create/upsert/delete/delete_by_run require the captured entry incarnation
and lock workspace → actor → thread → Run → feedback in their short transaction.
ID-only delete discovers a read-only locator in a separate session, then rechecks
the exact relation after locking. Generic scoped bulk deletion is refused;
canonical thread deletion uses its existing captured SQL receipt. All six native
feedback routes bind scope before owner admission; scoped reads pass the actor
and matching Run, writes pass the original admission nonce into the repository.

#81 RED reproduced cross-space disclosure and missing HTTP binding on both
metadata dialects. #82 passed 38 checks in 57.61s: real SQLite/PostgreSQL SQL and
JWT/HTTP mains, native feedback and global-feedback compatibility. Actual policy
withdrawal before update/delete preserves the row, and parent replacement before
create leaves zero new rows; owner-admission replacement also refuses writes.
Paging excludes invalid rows before limit; stats/grouping omit peers and invalid
Run parents. Archive/source bytes match; #81/#82 exact resources are empty.
The existing TestClient/httpx warning is unchanged.

These results do not prove all multiprocess/crash/cancellation or credential-reset
and role/OAuth boundaries. Remaining files/artifact/PUT/history, frontend, producer
and scope-required factory integration and M4–M11 still gate tenant activation.

Latest: #81 FAILURE/#82 SUCCESS both terminal, resources empty, four runtime/test files matched #82 archive. Feedback SQL/HTTP main verified, not full M3. Next inspect remaining artifact/archive/PUT/history paths before frontend. Original M0–M11 active, no tenant push/deployment, activation closed.

### Remaining artifact entry audit after #82

Read-only inspection (not a runtime proof): native thread history POST is already
private-scope bound; its deferred history metadata producer still belongs in M4.
The concrete next M3 gaps are:
- GET artifact currently binds general scope then captures its parent after native
  owner admission. Capture private entry identity before owner check to prevent
  adopting a replacement conversation during admission; retain query locators.
- PUT artifact is not yet scope-bound. Preserve native operation reservation,
  digest and UTF-8/size rules; final short mounted-host publication must check
  captured identity under live SQL locks. Never hold SQL locks across remote
  sandbox networking; non-mounted/remote publication needs the explicit M4/M5
  provider protocol, not silent host-only success.
- Native terminal Run archive manifest/download lack workspace binding. Add
  exact private Run/parent checks and before-send response checks around native
  archive generation, preserving real presented delivery events and current
  bytes. The already-open native temporary archive must close on pre-header
  refusal, decorator post-materialization refusal, cancellation and normal send;
  a wrapper must not strand the file or execute unrelated background effects.
- WorkspaceThreadResponse currently guards only before headers; continuous
  credential/role/transport revocation remains explicitly M6/M11, not proven by
  the existing prepared-file tests.

Use one real SQL/JWT/file archive main and directly affected native regressions
before broad fault matrices. No change has been made for these gaps yet; they
remain mandatory under the original full M0–M11 scope and activation gate.

## Terminal Run artifact archives (partial M3)

Native archive manifest GET and download POST bind private workspace/entry
identity before owner admission. Matching terminal Run and SQL delivery events
remain authoritative; client-supplied file lists cannot expand delivery. Native
archive generation and reservation/cancellation behavior are retained.
The download response rebinds its captured context and checks live policy plus
original parent before headers. An explicit owned-file close callback is drained
on normal send, ASGI refusal/cancellation, or decorator post-materialization
refusal. Reservation-release/response-construction failure also retains file
ownership for cleanup. Unrelated background actions are not executed on refusal.

#83 RED found absent scope and close support; #84 passed 9 checks in 47.55s.
Actual SQLite/PostgreSQL JWT/SQL/file mains verify distinct personal/team ZIP
bytes, verified delivery selection, manifest count, peer/foreign/Run mismatch and
owner-replacement denial. Actual policy changes after building or before ASGI
return 404 and the held native temporary file is closed. A cancellation unit
also checks file close and context restoration; native selection, busy conflict,
wrong-thread and repeated-builder-cancel regressions remain passing. Current
source bytes match the archive; #83/#84 exact resources independently empty.
Personal retention fixture now preserves exactly three events: message,
workspace change, delivery. Other personal child tables remain exactly one.

Single-artifact entry identity/PUT, frontend, normal producers/factories and
M4-M11 remain pending. This before-header proof is not continuous credential/
role/physical transport or cross-process/crash/load acceptance. No activation.

## Single-artifact entry identity (partial M3)

GET artifact now captures the private entry incarnation before native owner
admission while retaining query workspace locators. The existing identity helper
rechecks that same nonce before any file-response preparation, and the wrapper
still checks before ASGI headers. It cannot adopt a conversation replaced during
owner admission. Native preview, download, Range and ETag logic is unchanged.

#85 RED reproduced a real SQL nonce change in native owner admission returning
200 file bytes in both metadata dialects. #86 passed six checks in 47.62s: both
JWT/SQL HTTP mains plus four native text/Range/ETag regressions. The interrupted
old request returns 404 and the next fresh request still reads the correct
bytes. Archive/source bytes match, and #85/#86 exact resources are empty.

PUT host/remote publication and filesystem races, frontend switching, normal
producers/factories and M4-M11 remain. This entry identity fix is not continuous
credential/role/physical-transport revocation; tenant activation stays closed.

Latest verified checkpoint: #83/#84 archives and #85/#86 artifact entry identity,
all terminal, exact resources empty and successful archive/source bytes matched.
No active test job remains. Next M3: PUT artifact scope/entry identity, final
mounted-file publication under live SQL fence, CAS/path races and explicit remote
provider protocol (no SQL locks over network, no silent host-only fallback).
Then finish client selection/cache isolation and continue M4-M11. Existing history
read is already bound; deferred producers remain M4. Tenant activation closed;
no tenant push/deployment. Native UI styling remains the approved direction.

## Mounted artifact editing (partial M3)

PUT artifact binds the original private entry before owner admission. Mounted
host writes retain native artifact_write reservation and validate live SQL
workspace/actor/thread plus original nonce under publish_under_live_lock. Only
bounded file IO is inside this lock; no remote sandbox API call is held there.
The POSIX publisher walks absolute directory components using O_DIRECTORY and
O_NOFOLLOW, pins the parent descriptor, opens a regular single-link file without
following links, bounds and validates UTF-8 bytes, and checks the requested digest
and file identity at final publication. A unique owned temp file is flushed and
atomically replaced relative to that same directory; cleanup only unlinks a temp
that was actually created. Successful publication invalidates the native digest
cache. Unbound native remote sync/rollback/cancellation remains unchanged.

Current scoped admission refuses non-mounted providers or native remote executor
hosts with 503 before acquisition/mutation. These paths still require the M4/M5
scoped worker/provider protocol; this is an unfinished integration gate, not removal
of the remote requirement. Unsupported file-descriptor platforms also fail closed.
No local Docker/pytest, real sandbox execution or production NAS proof is implied.

#87 RED found missing entry scope. #88 passed eight native cases but its HTTP
fixture omitted the actual LocalSandboxProvider binding for artifacts and tried
to load absent production config.yaml. Final revision adds only that fixture
binding, matching uploads. #89 passed ten checks in 51.07s: actual SQLite/PostgreSQL
JWT/SQL/file mains and eight native editor cases. Correct personal/team bytes,
digest/size, stale 412, peer/foreign/entry denial, policy/nonce withdrawal before
final publication and changed-revision preservation are verified. An actual parent
directory replacement with a symlink is refused without changing either original
or outside bytes or leaving outside temporary files. Unsupported remote acquisition
is not called. Source/archive bytes match; #87-#89 exact resources are empty.

This proves controlled pre-publication withdrawal and path replacement, not
uncooperative concurrent writers, distributed filesystem/crash/cancellation or
physical STOP. Rename acknowledgement failures return unconfirmed 503 without
backend retry/rollback; durable unknown-outcome reconciliation/admission fencing
still needs M11 proof. A revocation committed after an already authorized write is
not retroactive rollback. Full credential/role checks, sandbox/NAS isolation,
remote producers/factories, frontend and complete M0-M11 remain; activation closed.

Latest continuation: #87 RED, #88 fixture failure, #89 SUCCESS; all terminal and
exact resources empty. Three runtime/test files match final successful archive.
No live build remains. Next M3 client scope/request/cache integration using native
DeerFlow styling; actual real Agent HTTP launch remains M4 and browser onboarding
M7/M11. Scoped remote artifact edits and production filesystem/unknown-outcome
fencing remain mandatory M4/M5/M11; do not call full PUT or M3 acceptance done.
Original M0-M11 goal stays active, no tenant push/deployment, activation closed.

## Frontend Request preservation (partial M3)

The public fetch wrapper now forwards the original Request (or URL input),
keeps Request method/body/headers/AbortSignal and RequestInit override semantics,
and derives CSRF from the actual request method. It never mutates caller headers.
Reducing a Request to only its URL had silently removed an explicit workspace
selector and prevented cancellation; preserving the object fixes that contract.

Shanghai job deerflow-tenant-frontend #2 reproduced both failures. #1 was a
non-root extraction setup failure, not business RED. #3/#4 traced a happy-dom
Request reconstruction limitation: the wrapper's outgoing Headers already had
the correct workspace and CSRF, but the test double discarded the worker Headers
instance. The fixture now normalizes that standard iterable before reconstructing
the outgoing Request, preserving all original header/body/signal assertions.
#5 passed all sixteen checks but needed formatting; #6 SUCCESS passed the same
16 (two new + fourteen native) in 3.74s, modified-file Prettier and full frontend
pnpm check (ESLint + tsc). Full build time 338.094s mainly reflects static checking.
The runtime/test bytes match its successful archive. #1-#6 and probes have empty
owned inventories; a private frozen-lock dependency cache remains for reuse.

This proves explicit Request forwarding and existing static/login compatibility,
not automatic workspace selection or switch cancellation. Tab-local immutable
scope, SDK stream/retry/reconnect binding, query/cache/provider reset, native UI
selector and actual authenticated two-tab browser acceptance remain M3/M7/M11.
No local frontend runtime/test or deployment ran; tenant activation stays closed.

Latest continuation: frontend #6 SUCCESS terminal, full check clean and owned
resources empty. Backend last #89 remains terminal/verified. No live test job.
Next implement immutable tab-local actor/workspace request snapshots: old clients
must abort/refuse, never read a newly selected mutable ID on retry. Apply to REST
and every SDK client/recovery path; do not send selectors to untrusted origins.
Then per-space QueryClient/cache and native-style selector/provider. Do not keep
the current module-global QueryClient as shared viewer/workspace state or use a
cross-tab last-workspace cookie/localStorage to retarget another tab. Switching
must detach old observation without automatically cancelling its background Run;
confirm native SDK/on_disconnect behavior during M4 integration. Preserve full
M0-M11 scope and activation gates; no push/deployment.


M3 explicit SDK workspace checkpoint: frontend #7 RED reproduced shared clients,
missing creation/state/resume selectors and late HTTP acceptance. #8/#9 traced
the abort timeout to locked SDK 1.6's message-prefix retry classification;
cancelled fetches now normalize AbortError and stream/join carry the lifetime
signal into the internal reconnect loop. #10 formatting, #11 test URL lint,
#12 Jenkins @2 permission/setup, #13 formatting and #14 cleanup-callback type
history remain in JSON.
#15 SUCCESS passes 38 checks (three new plus 35 existing), modified-file Prettier
and full frontend pnpm check. Exact runtime/test bytes match its archive and
#7-#15 plus source/format/reader probes have independently empty owned inventories.
Jenkins reconfiguration now retains the no-concurrent-build property.

The explicit SDK API fixes clients to copied actor/workspace metadata, all SDK
transports/replay/recovery, actor/workspace reconnect markers, late Response and
stream cancellation. Scoped onDisconnect continues background Runs; explicit
cancel retains native behavior. Legacy/demo mode remains native. This is still
not React workspace integration: shared REST capture, tab-local provider,
per-lifetime query/cache reset, logout/switch/post-parse publication fences and
React resumable storage are next. Keep original DeerFlow styling as approved.
Real authenticated two-tab browser acceptance, M4-M11 and physical isolation
remain required; M3 unchecked, activation closed, no deployment/push.
