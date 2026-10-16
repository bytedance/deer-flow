> 当前恢复点：M4 原生工具/MCP HTTP → B 入账、原生任务确认、v2 管理与原身份后台轮询；上海 SQL #29 SUCCESS（25 tests）。下一步直接接物理 worker 启动/接管/发布与撤权控制，再跑真实 C→B→C；全量 M0–M11 保留，租户启动仍关闭。历史暂停段与旧回执见下文，最新详细回执见文末。

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
