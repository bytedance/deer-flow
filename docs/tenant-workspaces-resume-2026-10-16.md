<!-- 当前状态：2026-10-18 用户恢复执行；历史暂停记录保留，参见文末最新检查点。 -->
> **执行中，M4 部分完成。** Jenkins #106：捕获原沙箱 STOP、失败保留/重试、纯文本 NoStart 与原生图接线，8 项关键验证和 44 文件 Ruff 通过。真实两机/AIO生命周期、恢复及 C→B→C 仍待完成；租户启动关闭。

# 2026-10-16 暂停与恢复检查点

以下为先前用户要求暂停时保存的历史快照。用户已于 2026-10-16 明确要求继续；当前执行状态以文首及文末恢复检查点为准，完整 M0–M11 目标保留，不能把当前子项当作总目标。

- 工作树：`/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2`。
- 分支：`codex/tenant-workspaces-plan`；环境默认的 `1d28/deerflow2` 是另一棵 checkout，不要在那边修改。
- 最后完整验证并提交的代码：`3fb8ed75`，上海 `deerflow-tenant-frontend #100 SUCCESS`。原生预览图片、嵌套 CSS、普通脚本和 GET 数据主干、必要退役/只读边界，40 项原有回归及完整 pnpm check 通过。
- 本次新增模块加载代码按 **WIP** 保存，**尚未验收、未格式化、未运行完整 lint/类型检查**。Git WIP 提交只作恢复快照，不代表通过。

## 当前 WIP 与结果

新增 `frontend/src/core/artifacts/html-module-plan.ts`，用已有缓存版本 `@babel/parser@7.29.9` 解析导入、重导出、动态导入与 import.meta。原生 HTML 计划区分模块脚本、把内联模块接入同一通道；父页面仍用已有同线程 GET 字节读取。子页面用稳定 import-map ID、原生浏览器执行和自身 Blob 装配模块图及循环，动态导入复用模块实例。普通资源主干未宣布新增验收范围；这套模块实现还需要调试和验证。

- `#101 FAILURE` 是实际浏览器 RED：两个空间的图片/CSS/普通脚本/数据刷新正常；相对模块导入报 `Invalid relative url or base scheme isn't hierarchical`，模块内容停在 waiting。说明缺的是 Blob 模块的依赖解析。
- `#102 FAILURE`：已打包新增实现并启动浏览器，但 `page.wait_for_load_state("networkidle")` 在 30000ms 超时；模块主干断言尚未执行，`-html.json` 为空。不能认为模块已跑通，也不能只延长超时来掩盖根因。
- #101/#102 均已终止；按专属 label 核实容器和网络为空。没有留下运行中的 DeerFlow 构建，未处理其他 Jenkins 项目。
- 构建终态、归档摘要、WIP 源文件摘要在 progress JSON 的 `frontend_html_module_wip`。#102 归档与此 WIP 的八个代码/依赖/夹具文件逐字节相同。

## 下次接续

1. 先读此文件和 `docs/tenant-workspaces-progress.json`，核对 Git 状态及 Jenkins 当前状态；不要因观察超时而重启旧构建。
2. 调查 #102：在初始 networkidle 等待失败前收集 pageerror、浏览器请求及模块图/端口情况，确定卡在何处。现有探针的这次超时在结果捕获 try 之外，因而丢失了主干 JSON；先改善失败观测，再修实际根因。
3. 先跑通同一 P/T 模块主干：静态/循环/重导出、内联模块、字面量/计算式动态导入、模块实例复用、import.meta 相对数据请求。之后只补必要的模块拒绝和退役边界。
4. 云端格式、定向 lint、完整 tsc 和 pnpm check 通过后再更新验收。解析器使用缓存中的锁定版本；不要在本机运行 Node/应用/浏览器/pytest 或 Docker Desktop。
5. 剩余 HTML 资源行为、Next/真实 Gateway/主体与双标签页、原生 shell/selector、M4–M11 等仍须推进。全部父项保持未验收，`_WORKSPACE_RUNTIME_INTEGRATED = False`。

## 上海执行约束

Jenkins：`106.14.210.163`，只管理 DeerFlow 专属任务。SSH 密钥位置沿用现有配置。Jenkins 密码只允许在服务器本机内存使用，不输出、不复制。固定镜像沿用 #100 的 compiler/browser IDs，不拉新镜像。只清理本项目精确 label，不做全局 prune、不触碰 assetforge。

无部署、远程推送、模型调用或本地应用运行。当前停在可恢复 WIP，不是功能完成点。


M3 scoped module checkpoint (2026-10-16): resume from WIP 216ac886. #103 records
initial networkidle timeout with no outstanding requests and no main assertions.
Keep production code unchanged, use existing confirmed-space/resource/module
output assertions for readiness: #104 SUCCESS (P/T module main, 16 regressions).
Only then extend the same browser fixture with JSON options and module refusal/
MIME/held-read retirement/reopen: #105 SUCCESS, 40 existing regressions/five files.
A temporary formatter found Next's reserved local variable `module`; rename it
modulePlan while preserving the DTO key. #106 SUCCESS: same main/boundaries,
40 existing regressions, five-file format/target lint, early full tsc and required
full pnpm check. No new Rstest cases. Repeated-import checks now wait for both
async actions to settle. Exact source/archive/image/terminal/empty resources:
frontend_html_modules in progress JSON; earlier #101/#102 pause evidence retained.

Babel plans module source ranges; child import-map IDs/Blobs and a canonical URL
registry leave execution, cycles, top-level await, JSON attributes and instance
caching to the browser. Parent same-thread captured byte reader is unchanged.
Import.meta retains native object identity with logical source URL/resolution.
MIME remains authoritative: text/plain module body does not execute. Dynamic
module reads cannot proxy ordinary APIs/foreign threads. Hidden report aborts
held module and data transport; old bootstrap is revoked; fresh same-space
module/data preview survives. Sandbox/Cookie policy and activation gate stay.

Proof is native React/Auth/Workspace/REST/iframe in pinned Chromium against an
HttpOnly Cookie/scope server and env/router build doubles; not compiled Next,
Gateway/JWT/SQL/NAS, live principal/two-tab or physical proof. Native DOM paragraph/
div and KaTeX diagnostics remain; expected MIME/revoked-Blob console errors belong
to negative probes, page errors are empty. General HTML/import-map/dynamic media/
CSS compatibility remains unaccepted. Next prioritize the approved native space
switcher/shell and actual backend upload/chat/download main; retain these HTML
and other M3/principal/physical requirements. All M0-M11 parent gates unchecked,
M3 partial, activation false. No deployment, push, model call or local app runtime.


M3 native switcher checkpoint (2026-10-16, #113 SUCCESS): actual existing
WorkspaceHeader/Sidebar/Dropdown now selects server-confirmed personal/team
spaces through WorkspaceSession. Only confirmed names display. Pending removes
private report content and keeps the menu usable. Denial has explicit retry,
personal confirmation and sign-in controls; retry retains target, no silent
personal fallback. #108 is actual missing-control RED after #107 fixture setup
repair; #109 main passes before adding two workflow boundaries. #110/#111 reveal
fixture windows-1252 decoding; only fixture UTF-8 response corrected for #112.
#113 final native browser main/all twelve observations, existing Context three
tests (no new Rstest cases), six-file format/target lint, early full tsc and full
pnpm check pass. Exact receipts/source hashes/empty owned resources recorded in
frontend_native_switcher in progress JSON.

This proves the actual control under opted-in native Context plus HTTP auth/scope
fixtures and navigation/env build doubles; actual WorkspaceContent/layout
bootstrap, compiled Next, real Gateway/JWT/SQL/NAS/principal/two-tab and physical
acceptance remain open. Next wire native shell then real backend main. Remaining
HTML/UI/global state and M4-M11 requirements are retained; all M0-M11 parent gates
remain unchecked, M3 partial and runtime activation false. No deployments, pushes,
model calls or local application/browser/Docker tests.


M3 native shell/bootstrap checkpoint (2026-10-16, #116 SUCCESS): WorkspaceContent
uses the server capability before mounting WorkspaceShell; unknown/unavailable
capability fails closed, explicit legacy disabled still works. One confirmed
lifetime QueryClient serves sidebar and page. Mount-only WorkspaceContentBoundary
keeps activity/delete owner/private sidebar/footer and page/extensions/commands/
settings/deep-link features out until confirmation, while Header/switcher remain
available. Account preference synchronizer is legacy-only pending scoped policy.
#114 records two actual pre-confirmation/unknown-capability legacy-mount REDs.
#115 main plus existing context/cache regressions pass before final checks.
#116 final eight tests (only two new cases), five-file format/target lint, early
full tsc and required full pnpm check pass. Retained native control/rich-report
browser main/all twelve observations pass; it does not exercise the new shell.
Exact terminal/source/archive/empty-resource evidence: frontend_native_shell in
progress JSON. Initial formatter-only RequestInfo stringification lint was
corrected in the fixture; no production behavior change from that correction.

Shell DOM proof uses actual root/native Sidebar/Header/Auth/Workspace/cache but
server cookies/capability/navigation and private feature leaves are doubles. It
is not compiled Next/hydration, real feature HTTP/JWT/SQL/NAS/backend business,
principal/two-tab or physical proof. Next handle workspace route/deep-link and
switch-from-private-thread semantics, then compiled Next and backend main.
Actual private clients/global settings/store/title/focus/live WSS, remaining HTML
and M4-M11 remain required. All parent gates unchecked; M3 partial, activation
false. No deployment, remote push, model calls or local application tests.


M3 native route checkpoint (2026-10-16, #123 SUCCESS): URLs now carry a workspace
locator through native links/router/new-thread history and the /workspace entry.
Only server capability enables mode; metadata still confirms actor and scope.
Mask private content until URL and confirmed scope match; missing selector is
confirmed personal and canonicalized before private mounts. Invalid/duplicate
selectors and scoped legacy entry fail closed. Switching retires old content
immediately and opens a fresh chat, clearing old resource locators. Next Link
refs/options/modified-click/prefetch behavior remains native; external/API/auth/
public destinations never get an injected workspace locator. Explicit locators
are never overwritten. Client 401/login guards and root error sign-in links keep
route intent. Server auth-layout return handling is still an identified gap.

#117 domain RED -> #118 root main eight checks GREEN, before broader bindings.
#119 reveals two URL-authority/client-login boundary failures -> #120 nineteen
checks GREEN. #121 shows native server entry dropping selected query; fix preserves
query entries, even duplicates for later rejection. #122 detects the missing custom Agent lifetime accessor during full tsc; keep
the guard and acquire the existing scoped lifetime. #123 final twenty-two checks
(nine files; only five new cases), forty-eight-file format/full pnpm check and
retained control/report browser main/twelve observations pass. Existing native
page workflow additionally checks scoped native history without Next replace.
No duplicate standalone full tsc/target lint is added to the final check. Exact
receipts/source/archives/empty owned resources: frontend_workspace_routes JSON.

Root and server-entry proof uses Next/capability/metadata/leaf fixtures; browser
proof retains native control/report but does not mount the new root routing.
This is not actual Next hydration/history/back/forward/new-tab, SSR auth return,
real feature HTTP/JWT/SQL/NAS/model business or principal/physical acceptance.
Next preserve workspace/resource URI in server login redirects, then run compiled
Next and real backend upload/chat/download. Remaining UI/global stores/private
clients/HTML/M4-M11 stay required. All parent gates remain unchecked; M3 partial,
activation false; no deployment/push/model calls or local application runtime.


M3 SSR/native Next checkpoint (2026-10-16, #128 SUCCESS): native Proxy records
the actual request path/query in an overwritten private request header, never an
auth grant. Workspace unauthenticated redirect retains next; authenticated login
entry follows native safe local next and avoids auth-entry loops. Duplicate and
invalid workspace locators remain intact for refusal; _rsc alone is stripped.
#124 actual lost-return RED -> #125 one layout main GREEN. #126 builds the entire
real Next 16.3.6 app, then native HTTP returns both expected 307s. #127 restores
the same compiled artifact without rebuilding after input/version/port/SHA/BUILD_ID
checks: actual main and forged-header/external-next/generated-demo-route/header-
leak observations pass. #128 nine focused checks (only two new; seven reused),
six-file format and complete pnpm check pass; driver Ruff/static format pass.
Final complete production input digest matches the native build/restoration.
Exact sources, artifacts, HTTP, terminal and empty resources: frontend_ssr_return
in progress JSON. Cloud-only procedure: docs/tenant-workspaces-next-testing.md.

Native Next auth projection is served by a synthetic Gateway; not real JWT/SQL/
NAS/model/task/business proof. No browser hydration/form/RSC/two-tab/principal
claim. Cold build no-cache/Nextra i18n/Git-config diagnostics are recorded; runtime
artifact is fixture-only and not deployable. Next prioritize M4's trusted native
Run/MCP/Scheduler/B/C attribution and execution main; retain all remaining M3 and
M4-M11 requirements. Never bypass startup to fake a tenant Run. Current startup
schema fence remains 0037 while actual read-clock revision is 0038; align with
the complete candidate/release manifest before activation. All parent gates stay
unchecked; activation false, no deployment/push/model/local application tests.


M4 execution signature checkpoint (2026-10-16): deerflow-tenant-execution-m4
#1 RED (existing signer lacks workspace_context), #2 native signature roundtrip
main GREEN, #3 SUCCESS (3 new checks + 7 existing MCP/signature regressions = 10;
Ruff check/format pass). Add explicit version 2 to the existing bounded HMAC
submission protocol. Sign immutable WorkspaceContext and require a separately
resolved receiver expectation; reject cross-space/actor/version mismatch, legacy
downgrade, unsupported/malformed protocol and workspace signatures presented to
unintegrated receivers. Legacy unscoped protocol remains compatible. No ORM
changes, alternate runtime or task authority. Exact cloud source/log/image
receipts and empty own containers: execution_scope_v2 in progress JSON.

This is a transport primitive only: interceptor/worker wiring, native persistent
Run/RunContext, MCP/Scheduler/ledger/parent-child attribution and live membership
checks still need implementation. Revalidation/revocation, publication,
continuation, notifications and unknown physical STOP remain M4 requirements.
Next implement original Run attribution first, without opening or bypassing the
startup guard. All M0-M11 parent gates remain unchecked, M3 incomplete; no
activation/deployment/push/model calls or local application runtime tests.


M4 durable native identity checkpoint (2026-10-16):
`deerflow-tenant-execution-m4-sql` #1 both-dialect missing-snapshot RED -> #2
native short-operation admission/hydration main GREEN. #3 exposes all four
legacy create/upsert and local idempotency bypasses in both dialects; recovery
shape check passes. #4 has 16 passed plus a PostgreSQL teardown error: Alembic
owned engine was not disposed on refused downgrade. env now disposes in finally.
#5 SUCCESS: 16 tests (7 new cases, 9 reused), ten-file Ruff check/format, actual
parent 0038->0039 repeat upgrade/history/NULL authority/refused downgrade/no
leftover PostgreSQL session. Exact code/source/log/image receipts and empty own
containers/networks: native_run_identity in progress JSON. Local code matches
final cloud bytes; OpenSpec strict and diff checks pass.

Native head is now 0039_run_workspace_identity, executor remains e0002. Original
WorkspaceContext and locked parent incarnation persist into the existing Run
row and restore without consulting browser selection; old history is not granted
new authority. Resident overlay and local idempotency require matching durable
identity and live scoped SQL. Legacy create/upsert refuse workspace authority.
This does not yet enable normal Agent Run/RunContext, journal/lease/worker recovery
or remote execution. Next add live parent-incarnation fences to idempotency
recovery and claim/adopt, then finish normal Run/RunContext/worker propagation.
Snapshot equality alone is not live parent or membership authorization. Native
C->B->C, MCP/Scheduler/ledger/signature receiver, publication/continuation/
notifications/revocation and unknown STOP remain M4 requirements. Startup's
existing closed schema fence is older than 0039; align full release candidate
and matched manifest before activation, never bypass the compiled gate. All
M0-M11 parent gates remain unchecked, M3 incomplete; no activation/deployment/
push/model calls or local application runtime tests.


M4 native ordinary Run/worker checkpoint (2026-10-16):
`deerflow-tenant-execution-m4-sql` #6 parent-replacement local replay RED;
#7 new nonce predicates refuse durable replay but expose incorrect access-denial
mapping through IntegrityError context. #8 actual worker/compiled graph exposes
caller workspace-field spoofing. #9 both SQL dialects refuse ordinary scoped
Run at the prior placeholder. #10 main GREEN (7 passed): actual scoped reject
admission -> native handoff -> adoption -> actual deterministic LangGraph in
original workspace despite caller switch; same single persisted Run succeeds.
#11 SUCCESS: 19 passed (5 new worker cases, 14 reused), seven-file Ruff
check/format. Pending nonce/member withdrawal checks leave exact owner/lease/
status/change_seq unchanged; legacy unbound CAS cannot start/transfer a scoped
row. Caller fields are removed from both runtime and configurable. Scope resets
after actual worker cleanup. Native legacy C/trace and Gateway checks retained.
Exact source/code/log/image/empty-container/network receipts: native_run_worker.
Final seven code files match cloud bytes. No new schema: native 0039/e0002.

Only framework/module integration is proved. The fixture uses real SQL native
principal/member rows directly; this is not public HTTP/JWT/cookie auth, live
lead-agent/model, checkpoint/NAS/memory, or physical remote C/B acceptance.
Global compiled startup gate remains false; no bypass or flag activation.
Next persist the original scope into native MCP/B task submission/records and
wire v2 signing/verification without legacy downgrade, then Scheduler/occurrence,
notifications/continuations, browser/remote assignment and owner-fenced leases,
recovery/cancellation/terminal journal/publication and live tool/credential
revocation. Ordinary scoped interrupt/rollback and legacy upsert stay refused.
Unknown physical STOP must keep reservations until physical proof. Remaining
M3 and M0-M11 parent gates stay unchecked. Align current native 0039 and paired
manifest before any activation; no deployment/push/model/local application tests.
Review performed serially against provenance/lock/rollback/context/compatibility
checks; this is not an independent full production audit.


M4 native MCP checkpoint (2026-10-16): SQL job
`deerflow-tenant-execution-m4-sql` #12 typed submission-scope RED -> #13
actual submit/persist/source-end/switch/poll main GREEN. #14 reveals stale
source-worker admission and foreign limit-one thread projection in both
dialects. #15 four pass/two fixture failures: old deliberately denied row uses
the one poll slot, so independent during-poll edge never runs; use two slots
for those two tasks. #16 SUCCESS: 20 checks (8 new DB cases, 12 reused), actual
member/policy/nonce/source-owner/cancel and result-write withdrawal boundaries,
original-scope compensation calls, contextless mandatory-mode legacy exclusion,
actual 0039->0040 repeat migration/history/NULL authority/refused downgrade/no
Postgres session leak. Remote IO is deterministic; no B receiver auth is mocked
or claimed. Native task/Run remain the only metadata authorities.

Scope job `deerflow-tenant-execution-m4` #4 RED actual interceptor still signs
legacy scope -> #5 SUCCESS 11 checks (1 new, 10 reused): typed original runtime
v2 signing, missing/forged identity downgrade refusal, unintegrated receiver
refusal and legacy parity. #6 SUCCESS final 17 Python files Ruff check/format;
no repeated DB/application suite. Exact current bytes match final source and
scope #5 for all 17; 15 MCP/framework code files also match SQL #16, excluding
the separately verified producer/test delta. Source/log/image and empty own
container/network receipts: native_mcp_scope in progress JSON. Native schema is
0040_mcp_workspace_identity; executor remains e0002. Earlier receipts immutable.

MCP snapshots live in a dedicated nullable column. Native tools copy original
WorkspaceContext and server-owned source_worker_id; live SQL checks occur before
IO, again at insert, before poll and at result commit without locks over remote
IO. Historical NULL scope cannot be regenerated from current selection. Original
Run completion does not erase task ownership. Scoped cancellation/notification
queues are not yet available and never fall back to unscoped claims. The B
receiver/management protocol still needs current native metadata authorization,
immutable ledger identity and physical activation/publication proof; current
unintegrated receivers refuse v2. Next implement that paired protocol and actual
native ToolNode-to-B main, then scoped control/notifications/Scheduler and full
runtime/credential/physical revocation. Do not infer physical Stop from metadata
or a fixture cancel call. Remaining M3 and all M0-M11 parent gates stay unchecked.
Startup remains compiled false; align the old schema fence and complete paired
0040 candidate/manifest only after M10/M11. No deployment/push/PR/live model or
local application runtime tests. This is serial self-review plus bounded CI,
not a full independent production/security audit or complete M4 acceptance.


M4 B receiver preflight checkpoint (2026-10-16): `deerflow-tenant-execution-m4-sql`
#17 RED missing native SQL verifier; #18 SUCCESS two SQLite/PostgreSQL main
cases (16.37s); #19 SUCCESS 15 checks (20.67s), four new DB cases plus eleven
reused signature checks. Actual native admission Run/private parent/member SQL
resolves original immutable scope after caller selection changes. Verify HMAC,
authenticated owner, expiry, audience/operation and argument digest before any
SQL lookup. Deny legacy/retargeted scope, ended/cancelled/expired or ownerless Run,
removed/stale membership/policy/account, unverified actor, deleting/replaced
private parent and absent captured scope. Query reuses native membership/account
policy and checks Run snapshot against independently read live versions in one
statement. No ORM/auth-success mocks; mutation boundaries use real SQL transactions.

`verify_native_execution_scope` is a read-only point-in-time submission preflight.
It does not enable ExecutionJobs/HTTP or grant later physical start/publication;
those unintegrated receivers continue refusing v2. No schema changes. Next wire
immutable ledger identity and old-worker schema floor, native MCP commit receipt,
v2 management and start/adopt/publish live fences, followed by actual ToolNode-to-B
and C-to-B-to-C proof. Scoped cancellation/outbox/notifications, Scheduler and
remaining runtime/credentials/physical STOP/restore still required. All M0-M11
parents remain unchecked; compiled startup gate stays false. Serial self-review,
three-file Ruff check/format, strict OpenSpec and diff checks passed. Current
three Python files exactly match #19 source; build/log/source/image/empty owned
resource receipts are `native_b_submission_preflight` in progress JSON. No deployment,
push/PR, live model calls, local application/pytest/Docker runtime or broad test
rerun. Previous evidence remains historical and unchanged.


M4 immutable physical B ledger checkpoint (2026-10-16): SQL job
`deerflow-tenant-execution-m4-sql` #20 RED absent identity column/revision;
#21 SUCCESS two actual SQLite/PostgreSQL original intent/retry/mutation mains
(10.64s); #22 RED actual pool claim bypasses attributed-scope guard in both DBs;
#23 SUCCESS 22 tests (24.72s) and six-file cloud Ruff check/format. Three new
focused functions give six dialect cases; sixteen existing migration/attribution,
legacy submit/cancel/staging, unknown-capacity and schema checks are reused.

Append e0003_execution_identity after frozen e0002; nullable historical values
remain NULL. Preserve old JSON bytes, physical state and versions. Captured B
identity binds original actor/workspace/Run/private thread/incarnation, request
digest and effective input/profile/budget digest. JobStore reads/retries/mutations
validate independent identity; pool claim/adoption reads do too. Workspace
attribution does not produce this grant. Unintegrated local and pool claims
exclude workspace-attributed work; pool predicate precedes limit, while unknown
assigned physical work still counts against capacity. All old processes must stop
before offline schema upgrade; version/shape/wire mismatches fail closed. This
is not acceptance of old-binary restart, rolling upgrade or full physical cleanup.

Exact six current Python files match #23 source; build/source/log/image/empty
owned container/network receipts are native_b_execution_ledger in progress JSON.
Current paired candidate is native 0040 / executor e0003, not the historical
release receipts. Startup remains compiled false with its older closed schema
fence. Next directly wire B submit/v2 management/native MCP commitment, then
actual start/adopt/publication/cleanup and native ToolNode-to-B/C-to-B-to-C main;
do not substitute more unintegrated safety preparations or broad tests for that
flow. C identity, Scheduler/continuation/control/outbox/notification/credential
revocation and M3/M5-M11 remain. Every M0-M11 parent stays incomplete; no tenant
activation/deployment/push/PR/model/local runtime occurred. Review is serial
self-review plus focused CI, not a full independent audit.


M4 native MCP HTTP B checkpoint (2026-10-16): SQL job
`deerflow-tenant-execution-m4-sql` #24 RED missing scoped receiver configuration;
#25 fixture-only 421 invalid Host, preserve FastMCP security and change test URL
to loopback; #26 SUCCESS actual native durable ToolNode wrapper -> service ->
ordinary driver -> MCP HTTP -> B ledger -> native SQL commitment -> background
status after original Run ends and selected space changes (two DB cases, 17.38s).
#27 reaches input/refusal/cancel round-trip but finds expiry mutating a historical
uncertain record with no JSON id; #28 independently proves team data permits
legacy B startup. Fix expiry to staged-only and add native schema/mode downgrade
fence. #29 SUCCESS: 25 tests (two new DB main cases, 23 reused), 29.62s, eight
Python files Ruff check/format. 27 pre-existing adapter deprecation warnings are
retained, not hidden or addressed through an unrelated dependency upgrade.

Scoped B captures immutable original intent, requires committed exact native
server/remote-id/source-Run/private-parent/incarnation and Run/task/job/live
member snapshots before activation. V2 management signs original task-local
workspace with authenticated owner/task/operation/expiry/argument digest; it
never invents a new active Run. File snapshot uses native scope/actor/parent
locks, retains original bytes after edits and refuses revoked access. A valid
orphan signed job remains staged and expires, while unknown history/state/version
stays intact. Wrong scope/legacy/receipt snapshot/source/server/remote/nonce/
cancel/status/revoked member are rejected through real MCP calls. Remote cancel
of unstarted work flows back via native polling; native scoped cancellation
queue/outbox/delivery and physical STOP remain unimplemented.

Real MCP serialization/auth uses in-process ASGI transport, not TCP; real native
SQLite/PostgreSQL and shared-file fixtures run in Shanghai. No SQL/authorization
success mocks; trusted internal CurrentUser/bootstrap is fixture context, not
public JWT/Gateway tenant startup evidence. Fixture database-owner roles do not
prove restricted SQL grants; M10 must check SELECT and scope/actor/parent row-lock
privileges and actual mounts/network. No actual scoped Docker/NAS publication or
C-to-B-to-C proof. Next directly integrate worker start/adopt/publication and
native cancellation/revocation control, then actual physical main. Never mark
staged/queued or a fixture cancellation as physical STOP/capacity release.

Exact eight current Python files match #29 source; source/log/image/build and
empty own container/network receipts: native_b_mcp_http in progress JSON. Native
0040/executor e0003 unchanged; previous receipts remain historical. Every M0-M11
parent is incomplete, Gateway activation stays compiled false with its old
closed schema fence pending the complete M10/M11 candidate. No deployment,
push/PR/model/local runtime. Review remains serial self-review plus focused CI,
not a complete independent audit or full tenant/runtime acceptance.


M4 scoped single-host physical checkpoint (2026-10-16): new owned job
`deerflow-tenant-execution-m4-physical` #1 RED missing scoped claim integration;
#2 SUCCESS actual native ToolNode/durable MCP/SQL -> Docker original-input report
-> native original-thread publication -> original MCP completion after source Run
ends and selected space changes (2 cases, 19.78s). #3 SUCCESS six physical cases
(main plus create/running withdrawal on both DBs, 31.02s). No permission-success
or SQL/Docker execution stubs: the one inspect outage is a denied observation
between real running and real STOP. Native task cancel intent independently
refuses publication under native scope locks. Unknown inspection keeps running/
unconfirmed fact; only actual owned-object removal records STOP. Unknown old
record state/version remains uncertain/7 and no business result is committed
through a withdrawn membership.

Native scope/actor/private-parent/Run/task locks fence short claim/start-intent/
result SQL writes; no Docker/HTTP inside locks. Start intent is the admission
linearization point; withdrawal later requires STOP, not another start or result
grant. Worker reconciliation detects withdrawal and persists a private control
stop request. Original actor scope is not reused as cleanup permission. Native
task control settlement is still pending: revoked task remains working/no result,
not falsely completed/cancelled by a business authorization bypass. Durable
revocation/cancellation outbox/STOP receipt must now settle that state, then wire
pool/remote C/continuation/notification and actual C-to-B-to-C.

Repo template #4 SUCCESS; #5 SUCCESS opt-in before fixture setup; #6 SUCCESS same
six cases (31.04s) using final versioned CI template with exact owned PostgreSQL
anonymous-volume cleanup. Only known owned labels/job-spec IDs are cleaned; old
unrecorded volume ownership is not guessed and no global prune occurs. SQL job
#30 SUCCESS 22 affected regressions + six physical default skips (49.25s), seven
Python files Ruff check/format. Existing adapter deprecation warnings remain
visible (14 physical / 26 regression). Current eight runtime/test/renderer/template
files match physical #6; seven Python files also match SQL #30. Latest template
alone differs from #30 by recorded exact fixture volume cleanup. SHA/log/image/
manifest/empty known resources receipts: native_b_single_host_physical in JSON.

Repeatable artifacts: docs/tenant-workspaces-testing.md,
examples/ecs-native/deploy/Jenkinsfile.tenant-physical.in and
scripts/render_tenant_physical_pipeline.py. Actual Docker, native SQLite/PostgreSQL
and file IO run in Shanghai; MCP uses in-process ASGI and trusted internal user/
admission fixtures. No public JWT, TCP/NAS, pool, remote C/LLM/continuation or
least-privilege DB proof. Full M0-M11 parents stay open; compiled activation false
and old closed startup schema fence pending final paired candidate/restore audit.
No deployment/push/PR/models/local app tests. This is focused CI plus serial
self-review, not independent full audit or complete tenant/runtime acceptance.

M4 captured MCP STOP checkpoint (2026-10-16): physical #7 RED missing control
module; #8 SUCCESS main (2 cases, 20.16s), #9 SUCCESS bounded companion (4 cases,
25.49s), #10 SUCCESS final code (4 cases, 28.72s). SQL #31 records eager-package
Gateway circular import; lazy-load the helper only in member mutations, then
#32 SUCCESS (17 affected native regressions, 10 default physical/control skips,
52.90s; eleven Python files Ruff check/format). Existing MCP client deprecation
warnings remain visible (8 physical / 26 regression), not suppressed.

The native transaction persists captured stop children, fences poll results and
retains pending full revocation parents. Separate operator STOP credentials,
HMAC purpose/audience/expiry and immutable original B identity gate the control
endpoint. Real running Docker must be removed before its signed observation can
settle native cancellation; untouched queued work records explicit NoStart.
No result/Agent execution grant is restored through the old member scope.
The typed native repository checks outbox owner/token/expiry and exact original
task before settlement; false proof, wrong-purpose/expired/unauthenticated calls,
duplicate intents, abandoned leases and service restart are verified. Scoped
user cancellation checks provider readiness before writing intent.

Final fourteen code/config/test/template files match physical #10 and SQL #32.
Native head remains 0040, executor e0003; no migration or deployment this step.
Known owned execution containers, fixture containers/networks and recorded
physical PostgreSQL volumes are confirmed removed. Historical unrecorded volumes
are not attributed by guess and no global prune is done. Full hashes, images,
logs and manifests: native_mcp_stop_control in the progress JSON.

Next: extend durable native control to Run/browser/Scheduler/credential domains,
then pool/remote C and actual C->B->C; retain outstanding M3 and M5-M11 work.
Parent workspace_revoke rows deliberately stay pending. MCP HTTP uses ASGI and
trusted internal native admission; public Gateway/JWT, TCP/NAS, OS reboot,
policy/account-wide revocation, notification delivery and complete product
acceptance are not proved. Tenant startup remains compiled closed; M0-M11
parents stay unchecked. No deployment/push/PR/real model or local app runtime.
This is serial self-review and bounded CI, not independent full audit.

M4 STOP terminal compatibility refinement: #11 RED (two expected missing
cleanup_pending assertions, four prior cases still pass) exposed old ordinary
queued cancellation leaving terminal B metadata without physical STOP. The
control endpoint now persists cleanup_pending for the existing LocalWorker.
Only actual Docker-owned absence/removal can produce its receipt; the terminal
state alone remains insufficient. #12 SUCCESS: all six cases, 29.59s, twelve
existing deprecation warnings. No success/Docker observation stub is used.

Final fourteen code/config/test/template files match #12; twelve also match SQL
#32. The only later runtime/test differences are the terminal cleanup branch and
its real native/SQL/Docker case, both locally Ruff check/format clean. SQL #32's
17-pass/10-default-skip/eleven-file cloud Ruff receipt remains unchanged history.
No broad repeated regression was needed for that isolated branch. OpenSpec strict
validation passed. Exact known owned resources and recorded physical fixture
volumes are absent; no historical volume attribution or global prune.

Continue M4 with native Run and other resource-domain revocation, then pool and
remote C original authority/continuation/notification and real C->B->C. All M0-M11
parent gates remain open, tenant activation compiled closed, no deployment or
remote push. This completes only the captured MCP STOP substep.

M4 active native Run membership control checkpoint (2026-10-16): SQL #33
records fixture-import setup error (not business RED); #34 RED actual native
Run cancel_action remains NULL after member mutation; #35 SUCCESS actual graph/
SQL/heartbeat main, 2 cases in 19.00s. #36 SUCCESS queued/binding/lease companion,
4 cases in 22.51s. #37 RED proves failed completion hook was falsely certified
closed; #38 SUCCESS conservative stream/journal/lifecycle/lease cleanup proof,
6 cases in 27.95s. No second Agent or task authority was introduced.

The same native workspace transaction sets first cancel intent and captures
run_stop identity, using the existing Run clock. Native heartbeat consumes an
interrupt directive even when an unconsumed first action was rollback. The
captured pending/quarantined barrier blocks private-thread admission and ordinary
orphan expiry release after metadata becomes interrupted. Only the original
native owner, valid lease and exact original Run/creation/parent snapshot can
confirm actual closed task/finalizers or its locally unattached pending NoStart.
Registration is rechecked after start_lock; cleanup cannot adopt a peer owner.
Native cleanup uncertainty leaves the barrier pending. Parent workspace_revoke
stays pending and now explicitly includes physical execution as a separate domain.
This native execution receipt does not certify a remote C container's STOP.

SQL #39 retained 21 passing affected regressions plus two old startup-test refusal
message failures: schema fence 0037 rejects current fixture head 0040 before the
compiled integration guard. Keep both production guards unchanged. The negative
test now asserts the compiled flag is false and checks the actual guard's refusal
order; no tenant startup or authorization success is patched. #40 SUCCESS, 23
regressions in 42.00s and eight-file cloud Ruff check/format. Existing MCP adapter
warnings remain visible (26 regression, 12 physical), not suppressed. Physical
#13 SUCCESS, the existing six MCP STOP cases in 30.90s, without new cases there.

#41 SUCCESS, the same six Run cases in 27.82s and seven-file cloud Ruff, using
versioned Jenkinsfile.tenant-run-control.in plus the standard-library renderer.
Its test container has no Docker socket, production/NAS/model mount or published
port; fixed tools/PG IDs, RO source and internal fixture network are enforced.
Current ten runtime/test/config/template files match #40/#41. Exact known owned
containers/networks and both recorded latest SQL/physical PG volumes are absent;
older unrecorded volumes remain unattributed and no global prune is used. Source,
log, images, volume/physical manifests: native_run_member_control in progress JSON.
Native 0040/e0003 unchanged; strict OpenSpec validation passes. Local commit only.

Next prioritize the FULL native Run lifetime: terminal-before-revocation and
direct user cancel, scoped lease/status/progress/journal/checkpoint/goal/external
writes and lost-owner/process recovery. Already-in-flight rollback is not proved
safe by the queued first-intent case. Then integrate browser/Scheduler/credential/
policy/account revocation and pool/remote C/continuation/notification with real
C->B->C. Preserve outstanding M3 and M5-M11. This internal deterministic graph/
SQL fixture is not public JWT, TCP/NAS, actual C, OS reboot, real model/business,
least-privilege SQL or full runtime acceptance. All M0-M11 parent gates remain
open; tenant activation compiled false and old unreleased schema fence unchanged.
No deployment/push/PR or local application/Docker/Node/pytest execution. Serial
self-review plus focused CI is not independent full audit.

M4 new scoped Run execution lifetime checkpoint (2026-10-16): SQL #42 RED
missing run_execution at real native admission; #43 SUCCESS three actual native
graph mains x SQLite/Postgres (6 cases, 23.61s): normal close, member withdrawal
after logical success, and user interrupt during held completion cleanup.
#44 SUCCESS new scope/cache boundaries plus prior Run control (12, 39.03s).
#45 SUCCESS 23 affected native/MCP/owner regressions (45.87s, five-file cloud Ruff).
#46 SUCCESS versioned fixed suite (12, 38.92s); #47 SUCCESS peer cancellation and
cached-scope guard (12, 39.21s); #48 SUCCESS 13 final affected legacy takeover/
cache/ownership regressions (27.75s); #49 SUCCESS locked-time/receipt refinement
(12, 38.99s). Existing MCP client deprecation warnings remain visible, not masked.

The generic native outbox now records run_execution at admission. Immutable
Run/user/space/thread/incarnation/creation/context binding does not depend on
owner, but owner changes only alongside native pending handoff/adopt CAS. Start,
renew and transfer refuse missing/mismatched history. Logical terminal status
cannot release admission while native stream/journal/hooks/sandbox cleanup is
open. Normal actual worker close acknowledges the lifetime at the last native
boundary; dedicated task settlement also closes a requested stop. Awaited native
workers use their real close boundary, not a fabricated completed task. Member
invalidation includes terminal-looking unclosed executions. Fresh-scope user
cancel can request a peer's cleanup without lease-expiry takeover or cache bypass.
All scoped rows stay out of ordinary startup/expiry orphan release. Unknown
historical state is never filled from current membership or assumed stopped.

Source audit found an actual pre-start rollback risk: rollback_point=None can
mean no snapshot captured, but native restoration would delete the prior thread.
#50 RED confirms owner pending cancellation chose restoration action; no actual
delete is asserted as observed there. Fix typed NoStart to consume interrupt,
retain the first persisted rollback request, recognize local interrupted/DB
pending under original valid ownership, and guard late native pre-start consumers.
#51 SUCCESS all 14 cases (42.76s) including a REAL SQLite checkpoint seeded before
admission and exact ID/content preservation after a late native consumer, both
metadata dialects. Running/terminal scoped rollback remains refused until the
real checkpoint write fence is integrated; legacy unscoped behavior is unchanged.

Cleanup now takes the original workspace lock before clock/Run or outbox/task
locks: the new/existing audit FK must not ask for a workspace key-share lock
while already holding the native clock/task in inverse order. This is existence/
ordering, not live-member authorization. Claim/lease time is refreshed after SQL
locks; only exact already-committed receipts are recognized after expiry, never
new release from an expired owner. This ordering is serial source review, not
a claim of complete concurrency/fault acceptance.

#52 SUCCESS final fixed Run suite, 14 cases in 70.27s plus eight-file cloud Ruff;
physical #14 SUCCESS existing six MCP/Docker STOP cases, 46.45s (12 existing
adapter warnings). Final eleven runtime/test/template files match both archives.
Fixed tools/PG IDs unchanged; all known owned containers/networks and recorded
exact latest SQL/physical PG anonymous volumes absent. Old unrecorded volumes
are not guessed and no global prune. Full hashes/logs/manifests are in
native_run_execution_lifetime. SQL CI runtime has RO source/internal PG, no
Docker socket/production/NAS/model mount or published ports. Pure stdlib renderer
supports --suite lifetime; eight new cases plus prior six, not a new broad suite.

Next: complete scoped worker checkpoint/journal/goal/external-tool effect and
lease fences, active rollback and real cancel/launch API binding. Then integrate
account/policy/browser/Scheduler/credential revocation and signed pool/remote C
launch/adopt/recovery/continuation/notification with actual C->B->C. Preserve all
outstanding M3 and M5-M11 product scope. Native execution close is not C container
physical STOP. No public Gateway/JWT, actual C, NAS/TCP/OS reboot, real model,
least-privilege SQL, quota or full product/release proof. Root revocations remain
pending; every M0-M11 parent stays open, compiled tenant flag false and unreleased
startup schema fence unchanged. No deployment/push/PR/local app runtime. Local
Git/OpenSpec/stdlib packaging and static formatting only; serial self-review,
not independent full audit. Save as local checkpoint, then continue the full goal.

M4 native worker checkpoint fence checkpoint (2026-10-16): SQL #53 RED
reproduced actual late-result writes after membership version withdrawal on both
metadata dialects; #54 SUCCESS four main checks (21.74s). #55/#56 were fixture
ordering/synchronous SQLite setup failures, retained as evidence. The final
fixture observes actual initial saver commit and inserts accounts asynchronously;
no timing sleeps or authority mocks. #57 SUCCESS all ten normal/member/cancel/
lease/owner checks (34.16s), and #58 SUCCESS existing nineteen revocation/lifetime/
worker-context regressions. Both final archives match recorded runtime/test/
renderer/template bytes. Fixed tools/PG images unchanged; exact owned fixtures,
networks and recorded anonymous volumes absent. Full receipts and hashes:
native_worker_checkpoint_fence in progress JSON.

run_agent wraps its native saver only for a captured scoped Run. Prepared saver
IO locks original workspace -> actor -> private thread incarnation -> Run ->
open lifetime, validates original Run/creation/owner and live native lease plus
no cancel/stop intent, and drains IO before releasing locks. Every graph/goal/
duration write through that local saver uses the same fence. Model/graph/tool
execution is outside SQL transactions. Original UI selection cannot retarget
checkpoint IO. Missing native fence fails closed. Sync/destructive/copy/prune
operations are unavailable; running scoped rollback still needs explicit control
authority. This adapter adds no Agent loop, table or checkpoint authority.

Proof uses actual full-mode AsyncSqliteSaver with an existing private report and
both native metadata dialects; compares head ID/content/pending writes after
stale generation. Lost owner/lease never closes the lifetime barrier. This is
not Postgres checkpoint, delta/cache, same-file SQLite, cross-store atomicity,
crash recovery or whole-worker output protection. Journal/SSE/publication,
status/progress, tools, other goal producers, credential/account/policy/Scheduler/
browser revocation, admitted APIs and signed pool/remote C remain required.
All M0-M11 parent gates remain open, compiled tenant activation false and startup
schema gate unchanged. No deployment/push/PR, real-model invocation, local app/
Node/browser/pytest/Docker runtime or global prune. Continue remaining effects,
then authenticated launch/cancel/recovery and actual C->B->C. Serial self-review;
not independent full audit.

M4 native worker journal/Run metadata checkpoint (2026-10-16): SQL #59 RED
(four failures, 21.61s) reproduced NULL workspace on normal native journal rows
and real late callback response persistence after member withdrawal. #60 main
four passed (21.81s), #61 ten normal/member/cancel/lease/owner cases passed
(33.04s), including no-ambient legacy writer refusal. #62 existing regression
found four logical interrupted-state failures (27 passed, 77.05s). Fixed with
an exact STOP control-processing transition, preserving all existing assertions.
#63 SUCCESS final 46 cases (96.58s), thirteen-file cloud Ruff, source hashes and
exact fixtures/networks/recorded anonymous volumes verified absent. Evidence:
native_worker_journal_metadata_fence. Images/native 0040/executor e0003 unchanged.

Actual native run_agent/compiled graph and deterministic async BaseChatModel
callbacks drive DbRunEventStore and native RunRepository on both metadata
engines. No real provider/credentials. Ordinary Run status/progress/completion/
model/finalization and journal single/batch/receipt writes use original captured
Run/creation/owner/context/parent incarnation, open lifetime, live membership and
native lease in the same metadata transaction. Checkpoint IO reuses this fence;
model/tool work does not hold its SQL locks. Bound journal stamps original user/
workspace and validates batch identity. Unbound legacy writes/lease update
cannot mutate scoped rows; raw private journal appends are refused.

Known permission refusal drops stale buffered events and drains dependencies,
without endless receipt retries. Genuine IO failure retains existing retry/
buffer uncertainty. Control-only mark_worker_interrupted consumes an exact
captured pending STOP under original live ownership; it writes no response,
statistics, error payload or goal and closes no lifetime. Actual final close can
acknowledge an interrupted run even when business writes were denied. Lost owner/
expired lease remain open. Workspace-first ordering is now in the stop-close
helper; a prior misplaced duplicate lock was removed from execution close.

Next guard stream/publication/model/tool boundaries, ThreadMeta title/status and
cache effects; integrate scoped dispatcher and owner/instance recovery, admitted
APIs and other revocation domains, then signed pool/remote C/continuation and
real C->B->C. Legacy dispatch pending failure remains an explicit later boundary,
not evidence of full scoped dispatch. This is not public JWT/browser, real model,
Postgres/delta checkpoint/shared SQLite, crash/unknown-result, quota/billing,
NAS/TCP or remote C proof. All M0-M11 parents remain open, activation false,
startup schema fence unchanged, root revocations pending. No deployment/push/PR
or local application/test/Docker/Node/browser runtime. Serial self-review only.

M4 native stream/thread producer checkpoint (2026-10-16): #64 RED retained
actual late response in native MemoryStreamBridge replay after member withdrawal
on both metadata engines (two failed/two passed, 21.19s), despite prior journal
and Run SQL protection. #65 main four passed (21.50s). #66 SUCCESS final existing
46 checks (97.72s), fifteen-file cloud Ruff. No new scenario/case matrix: expanded
the existing actual native graph/model callback cases with real subscribe/replay,
end and ThreadMeta state assertions. Final source hashes and exact removed owned
containers/networks/recorded anonymous volumes: native_worker_stream_thread_fence.
Pinned images/native 0040/executor e0003 unchanged; no new migrations.

run_agent captures one immutable NativeRunStopTarget and installs producer-only
ScopedWorkerBridge plus bound ThreadMeta writer views; saver/journal reuse the
same target. Prepared native queue IO uses the existing short drained SQL
execution fence, covering all worker publish helpers; no graph/model/tool or SSE
subscriber socket delivery is under that lock. Known refusal stops through the
native interrupt path, including an error publication that races withdrawal.
End contains no result data and uses original live-owner control, independent of
withdrawn membership; stale/expired/replaced owners cannot end a successor lane.
Exact completed NoStart remains recognizable. The producer grants neither
subscribe/read nor global bridge deletion authority.

Worker ThreadMeta status/title writes use Run effect fencing in the SAME
metadata transaction. Real final close can update only status/time of the
original private parent incarnation; parent existence lock precedes clock/Run.
Deletion/replacement/deleting parents and lost owner/lease are preserved. Cancel/
member cases end correctly after actual close; owner/lease cases preserve the
replacement idle state/title and remain unclosed. Title writer uses this guard,
but full held-title publication/UI acceptance is not claimed by these tests.

Next guard actual native model/tool invocation before handlers/provider calls,
then effect-specific filesystem/publication/network and scoped dispatcher/owner
recovery/APIs, all revocation domains and signed pool/remote C C->B->C. The native
build_lead_runtime_middlewares chain is an appropriate tool-layer entrypoint;
ordinary tool error normalization must not consume a revocation gate. HostModelInvoker
is the extension model service, not the complete lead/middleware model boundary;
do not treat observer callbacks as execution authorization.

This is MemoryStreamBridge producer/replay evidence, not Redis/cross-store
atomicity, HTTP/JWT/browser sockets, backpressure/fault/generation/restart proof.
No real model, active rollback, quotas/NAS/TCP/remote C or full M0-M11 acceptance.
All parent gates remain open; compiled tenant activation false and schema startup
fence unchanged. No deployment/push/PR or local app/Node/browser/pytest/Docker.
Serial self-review; preserve full scope and continue actual invocation effects.

M4 native invocation admission checkpoint (2026-10-16): SQL #67 RED
(two failed/two passed, 21.47s) showed a waiting native tool entering after member
withdrawal. #68 RED (12 failed/two passed, 42.45s) explicitly observed its real
report file and ten existing producer-cleanup refusals. The latter was a real
regression from the preceding producer view, not a fixture exception: worker
teardown calls delayed cleanup but the view rejected every call. Fixed with an
exact completed-lifetime same-lane control path, retaining unknown/foreign lanes.
#69 main fourteen passed (42.48s), #70 necessary boundaries twenty-six passed
(66.74s), #71 final sixty-three passed (133.41s), twenty-two-file cloud Ruff.
Source/archive/log hashes and exact removed containers/networks/recorded PG
volumes: native_invocation_admission_fence. Pinned images/native 0040/executor
e0003 unchanged; no migrations, live model calls, deployment, push or PR.

Tests use actual run_agent, model factory, create_agent and the COMPLETE shared
lead runtime middleware chain, real BaseTool and a temporary report file. No
permission/store mocks. Four held boundaries: waiting tool, second model after a
legitimate tool file, independent factory model with callbacks=[], and model
admission queue. Both metadata dialects, normal and member-version withdrawal.
The normal paths complete; denied tools create no file, denied providers never
enter, and already-legitimate first work remains. Worker-built cached model
cannot become an unbound capability after Run closure. Ten existing stream/
metadata cases now also assert closed-lane cleanup, open/lost retention and
foreign-lane refusal; six directly related legacy checks reused, not a broad
new suite. Existing structural middleware count/index assertions updated for
the new outer guard and real-class relative ordering retained.

Only validated run_agent binds a private task-local guard from its captured
NativeRunStopTarget. Shared lead/subagent middleware gates before-agent/model and
model/tool wrappers; declarative ordering preserves the gate outside IO/receipts/
ordinary error normalization. GraphBubbleUp stop propagates to owning worker.
Root callbacks and stateless model-local callbacks cover normal and independent
calls; factory composes the existing limiter and rechecks AFTER its queue. Scoped
worker models disable exposed SDK max_retries so native retry attempts re-enter
admission. Model type and legacy unscoped construction/pacing remain intact.
No Run/loop reference is cached on the model callback/limiter. Guard closes and
context resets through teardown; locks are released BEFORE model/tool IO.

Next preserve native stop through title/summary/goal fallback and HostModelInvoker
service boundaries, track/drain real shielded provider task lifetimes, then
publication/FS/network protocols, actor/account/token revocation, scoped dispatch/
recovery/APIs, other domains and signed pool/remote C C->B->C. This admission
step is not a guarantee over already-admitted IO or arbitrary provider/extension
transports. Native scoped model execution requires its owning async loop;
embedded/non-run/sync capability entrypoints and all model caches still need
explicit audit. Do not manufacture authority from ambient selected workspace.

No real DeepSeek/429/network, HTTP/JWT/browser, Redis, physical C, quota/billing,
NAS/TCP or complete product acceptance. All M0-M11 parents remain open, compiled
activation false and startup schema fence unchanged. Root revocations remain
pending. No local app/Node/browser/pytest/Docker runtime; local Git/OpenSpec/
stdlib packaging/static formatting only. Serial self-review, not independent
full audit. Continue actual service lifetimes and external effect boundaries.


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


## 2026-10-17 sandbox dispatch WIP 暂停检查点

用户明确要求暂停并保存；目标状态已设置为 paused，不再启动开发或测试。

当前改动：原生 sandbox tools 在就绪/复用返回及同步线程实际执行前重新检查私有
Run guard；复用既有 run_sync_lifecycle_operation drain 与执行租约；工具错误
归一化和 read-before-write 检查/读标记保留 GraphBubbleUp。新测试复用真实 Run/
SQL 成员版本变更、原生 write_file、实际文件及完整 create_agent 共享 middleware。

- #84：2 failed / 2 passed，真实就绪等待后迟到写文件 RED。
- #85：4 passed（20.84s），29 文件 Ruff；增加原生 owner/租约释放断言。
- #86：2 failed / 6 passed，read-before-write 吞掉 WorkerInvocationDenied 的实际 RED。
- #87：12 passed（36.83s），30 文件 Ruff，涵盖两种数据库和完整 SDK 工具链。
- 最后固定回归 sandbox-final 在暂停前提交，确认队列 976，预期 build #88，
  phase=m4-sandbox-dispatch-final；**结果尚未核验，不能称 134 项已通过**。
  归档 SHA256：1ea76044aef8e18c7526c307b4c35b4df3514a7c37655690675a8f61c65b18cb。
- 暂停后的 SSH/Jenkins 状态查询被自动审批拒绝（理由：超出暂停授权）；没有重试
  或绕过。当前提交仅 WIP，最后完整已验证提交仍为 56cf0c0cd（#83：114 项）。

恢复时先检查同一个构建/队列及现有日志，不能直接重启。回执收集脚本为本机
/private/tmp/m4-sandbox-receipt.py；其预置历史为 #84–#88，须按真实状态核验后再用。
成功后收集源码/归档/日志哈希及精确容器/网络/临时卷清理证据，再完成本轮
OpenSpec、计划、测试文档和模块指南。当前尚未追加本轮“已验证”子步。

下一步先审计 sandbox provider 的 workspace/thread-incarnation 身份绑定与缓存
复用（LocalSandboxProvider._thread_key 当前只含 user/thread，尚未完成实际复用
边界验收），再接外部效应/发布、其他撤权域、signed dispatcher/recovery 和完整
M0–M11。LocalSandbox 测试不代表主机隔离或远端 C 停止；启动开关保持 false。

详细代码哈希、构建状态和限制见 progress.json -> sandbox_dispatch_pause_checkpoint。
本轮无新增表/部署/推送，没有本机应用、pytest、Docker Desktop 测试。


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


### 下一主干的源码审计（尚未运行新用例）

Local provider 没有覆写 get_scoped，继承实现返回 None；普通 checkpoint 恢复会
重新 acquire，并比较新路径映射。因此不能由 user/thread 缓存键直接宣称串空间。
仍须核验同 ID 删除重建：Local ID 不含空间/代次，映射替换复制写入提示；线程目录
含空间但不含 incarnation。AIO 的 get_scoped 则仅比较 user/thread；lease owner
短路也复用这个键。以上是源码发现，不是已复现漏洞或物理容器验收。

下一次先复用真实 SQL create/delete/recreate + 原生 Run，观察旧/新报告字节和句柄，
并对照正常同代次续写。先确定存储、API 读取、执行与清理一致的身份，再改 namespace；
仅给 provider ID 加字段不足以解决目录复用。保持旧 scope token 契约及 fork 借用/
owner 清理兼容。不开新的 provider 大矩阵，不启动真实模型或部署。


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


## 2026-10-18 原生 C 快照、持久暂存与 pending 所有权交接

上海 `deerflow-tenant-execution-m4-sql #95 SUCCESS`：**13 passed in 27.75s**，
35 文件 Ruff 检查/格式通过。当前 38 个相关源码摘要与归档一致，五轮测试专属
容器/网络及精确记录的 PG 临时卷均已移除。证据：`native_c_dispatch_staging`。

- #91 两失败仅是新夹具缺少 AppConfig 必填 sandbox；未执行派发，不算产品 RED。
- #92 两种数据库真实 RED：切换空间后，派发使用当前选择读取线程，无法读取原准入线程。
- #93 主干两项通过（18.55s）：实际 SQL Run/线程 → 原生 snapshot → C 账本/亲和性 → pending owner CAS。
- #94 仅在主干后加必要边界：交接前成员版本变化的两项通过；外层空间字段被剥离后内层 scoped C 仍按 legacy 创建，两项失败（22.35s）。
- #95 四项原生主干/撤权边界，加六项既有 B 账本/迁移检查及三项旧签名/接收/操作策略检查，固定十三项通过。没有重跑无关完整套件。

`native_admission_workspace` 只绑定已准入 Run 的私有快照并在 finally 恢复之前的选择；
它的形状检查不授予新权限。读取仍须通过实时空间/成员/父线程检查，交接使用既有
原生短事务 CAS，再检查原代次与 lifetime。SQL 锁不跨快照/外部 IO。

`make_native_snapshot` 保留 workspace_id/context，校对 RunContext 与实际线程；
派发不从 token/客户端 JSON 补授权。既有 e0003 独立 execution_identity 列扩展到
C，绑定整个原生 payload、profile、固定 resident budget 与 affinity。修改身份或
剥离外层空间字段不能降级。亲和性保存原 workspace，已有冲突/未归属行不自动赋权。
B 身份摘要规则和既有旧格式继续回归，无新增表或迁移。

```bash
python scripts/render_tenant_run_control_pipeline.py native-c-stage <归档SHA256> --suite native-dispatch
python scripts/render_tenant_run_control_pipeline.py native-c-stage-final <归档SHA256> --suite native-dispatch-final
```

#95 归档 SHA256：`f07ba8655ed92830ce513e5e712eb8c165d44f44bf2b7d9e1f40c6a0bd2fbd17`。
旧 operator policy 用例改用实际 RunRecord，原有 remote_all 必须为字面 true 的断言保留。
定向用例中 app 容器只是实际依赖的装配；存储/准入/CAS/账本/亲和性不替换为授权 mock。

**限制：这不是已可使用的远端 C。** 本轮到持久暂存/交接为止；旧池仍拒绝领取
scoped C。队列续租与 staged/孤儿/拒绝清理必须先接原生持久控制，撤权不能靠旧空间
读取或猜测 NoStart/STOP。随后才接 scoped claim/owned、v2 原生 launch 的独立 SQL
接收校验、worker RunContext/adoption、重启恢复和物理 C→B→C。这里没有 v2 launch、
远端 worker、AIO、实际网络/模型或物理停止证明。其他撤权域、完整 M0–M11 仍未验收。
租户开关 false，启动 schema fence 不变；无部署、推送或本机应用/pytest/Node/浏览器/
Docker Desktop 运行。串行自审，不代表独立全量审计。


## M4 C queue control checkpoint — 2026-10-18

Shanghai Jenkins #96 reproduced missing workspace scope on dispatcher restart
(two failures). #97 queue main passed two cases. #98 exposed scoped legacy
terminal-update and missing NoStart settlement (four failed/four passed).
#99 passed 20 focused tests in 49.50s and 35-file Ruff checks. Exact archive,
source/log hashes and removed fixture-volume evidence: progress JSON
`native_c_queue_control`; 38 source hashes match the working tree. No owned
fixture containers/networks remain. No repeated 134-case regression.

Control reads compare immutable C locators against canonical native SQL and
return only control facts. Exact original pending ownership renews without an
ambient member context. Revocation can settle NoStart only after ledger CAS
confirms no assignment/attempt/generation/start; native Stop/lifetime/END use
existing captured-target helpers. Legacy finish_dispatch_pending rejects scoped
Runs. Assigned-work fixture retains its native lifetime and pending Stop;
this is not physical STOP evidence. Acknowledged settlement replay is covered;
lost-END acknowledgement on this new scoped path was not separately injected.

Next: scoped claim/owned, independent v2 SQL authorization, receiver context and
adoption, then physical C execution/recovery. Full M0–M11 remains open; activation
false and startup schema fence unchanged. No deployment, push, model call or
local application runtime.


## M4 scoped C receiver checkpoint — 2026-10-18

#100 reproduced scoped legacy-token acceptance and ordinary pool recovery
returning scoped assignments: six failures. #101 passed seven cases, but the
legacy adoption case failed because set_current_workspace rejects None. Fixed
legacy admission to avoid that setter and reject inherited ambient workspace.
#102 passed all eight focused cases and 37-file Ruff checks. Exact timings,
archive/log/source hashes and owned cleanup: progress JSON `native_c_receiver`.
Forty source hashes match the verified tree. No full-suite repeat.

Receiver independently reads canonical native SQL pending authority before
checking v2 claims; admission binds that context through reads, RunContext,
owner CAS and task creation. CAS rechecks scoped lease and pending STOP under
native locks. Ordinary owned recovery filters scoped payloads without releasing
their capacity. Worker/browser entry uses the same preflight; scoped refusal
retains uncertain capacity instead of using legacy settlement.

Evidence limit: real SQL handoff/adoption and captured task context, but the
execution entry is a context-observation stub. Membership-version withdrawal is
an SQL fixture; this does not claim full removal lifecycle, actual graph/model,
physical STOP, browser isolation or distributed delivery. Scoped claim/owned
integration, actual C execution/recovery and C->B->C remain next. Full M0–M11
and activation remain open/closed respectively; no push or deployment.


## M4 scoped C pool-to-native execution — 2026-10-18

#103: four failures at missing poll_envelopes after real native staging/handoff;
this RED proves the missing dispatch entry, not every subsequent boundary.
#104: seven passed in 25.83s, 37-file cloud Ruff. Forty source hashes match the
verified checkout. Exact archive/log/source and removed fixture volume evidence:
progress JSON `native_c_pool_main`; no owned fixture container/network remains.

Real FastAPI ASGI poll/get/report now drives scoped exact-version pool claim,
v2 envelope, original native receiver/adoption, execute_admitted_native_run and
run_agent with a deterministic asynchronous model. SQL Run succeeds with the
private report and 12 tokens; journal rows retain original workspace/user even
when UI selection differs. Running polls carry no launch token or native payload.
Control get/report preserve original assignment/expected-snapshot CAS without
returning inputs/secrets/results; worker retains only its already-held snapshot.
After this in-process graph drains, completion reporting releases its reservation
and a subsequent poll does not relaunch. Membership-version withdrawal prevents
claim; ordinary pool isolation and legacy capability regression also pass.

Defaults still exclude scoped work. Only the explicit C path independently
reauthorizes native pending ownership before/after exact ledger reservation and
before signing. General post-adoption control reads never authorize launch;
unknown ownership/work keeps capacity. Scoped wait/refuse are explicitly rejected
until their lifecycle integration is complete.

Limits: ASGI and deterministic model are in one isolated CI process, not two-host
TCP, real model, AIO sandbox, provider namespace, physical STOP or crash/restart
acceptance. The withdrawal fixture changes SQL membership version; earlier #99
contains actual member-operation NoStart evidence. Next physical C lifecycle and
scoped C->B->C dependencies/notifications, then remaining M4 domains and M0–M11.
Activation remains false; no deployment/push or local runtime.


### 2026-10-18 C physical STOP RED (#105)

One focused cloud regression reproduces wrong-container STOP acknowledgment: actual AIO tracking/ownership/destroy and worker stop_owned return success after inspecting an absent legacy name while the captured policy sandbox remains running. Backend physical state is simulated; this is not Docker acceptance. Jenkins #105 terminal FAILURE, 1 failed in 10.73s; source SHA256 `20dd502e31fe69f09bcdfe1eb717b10cfbf0a65853c4b94ba294f67d65e72708`. Production fix is in progress with the single 6.1-sol medium coding agent under root review: capture actual execution identity rather than recompute mutable projection paths, preserve unknown STOP reservation and no-sandbox completion. No completion claimed. Jenkins reachable; historical ECS public and private SSH endpoints timed out; current IP confirmation pending. No local runtime/deploy/push. Full M0–M11 remains active.

### Captured STOP checkpoint (#106 SUCCESS)

The worker now binds a private capture to the SQL-adopted native Run before task creation. Actual acquire and explicit reuse retain immutable Docker IDs through warm release. Cancellation stops that captured object using existing provider ownership/teardown; late acquisition is sealed. Failed STOP keeps tracking and can retry. NoStart requires the bound task to drain with no acquisition, not an empty provider map. Normal resident warm reuse stays intact. Discovery retains Docker IDs; process restart without a capture remains unknown.

#106: 8 passed in 25.67s, 44-file Ruff check/format. Archive `361200d1a9d52e697b127dd0a2aa2fff6b824bac86b0201b4aab813d94d74eac`; 12 changed code/pipeline file hashes match tested bytes, exact owned containers/networks absent. OpenSpec strict validation passes. Includes actual SQL/ASGI/native graph text completion through worker.adopt_owned. STOP physical backend is simulated: no two-host/AIO acceptance, restart recovery or full M4/M0–M11 completion claimed. No deploy/push/local runtime; activation stays closed.
