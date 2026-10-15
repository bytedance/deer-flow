# 2026-10-15 暂停与恢复检查点

状态更新：用户已于 2026-10-15 明确要求继续，当前已恢复；最新验证见文末 #100。下面暂停段保留为历史记录。

用户此前要求今天到这里，保存进度并允许本地提交。此检查点是 WIP，不能声称功能验收完成；不要自动继续开发、启动构建、部署或推送。用户再次要求继续后再恢复。

## 代码与已验证范围

- 工作树：`/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2`；分支：`codex/tenant-workspaces-plan`。
- 之前已提交：`0e56c0ac` 上传 hooks；`f17a317c` 普通聊天读写、附件及 SDK 重连存储。最近完整通过的前端构建仍是 `deerflow-tenant-frontend #32`。
- 本次 WIP：侧栏 SDK/归档 REST 搜索、Run 详情、分支/置顶/归档/移动/重命名/删除 hooks 捕获已确认空间客户端；异步缓存操作之后和通知之前检查旧 lifetime。迟到的 sidecar 查询不能继续删除，旧 mutation 不能改投新空间。
- 空间模式删除每个正常枚举的线程直接使用原生 Gateway DELETE，不再先 SDK DELETE 后对同一 ID 再发新 DELETE；未启用空间的原有兼容路径保留。
- 新增三条真实 React/StrictMode 主干，使用真实 Context、REST/SDK/查询/操作 hooks 与网络替身。没有实际浏览器、真实业务后端或物理资源隔离验收证明。

## 最后一轮结果（不能写成通过）

- Jenkins `deerflow-tenant-frontend #33`：RED，三条主干失败，复现缺空间选择器、切换后继续删除、旧归档成功回调。
- `#34`：**FAILURE**。三条新增主干 + 47 条原有回归均通过，共 **50 项**；四文件 Prettier、定向 ESLint 和全库 ESLint 通过；完整 `pnpm check` 的 TypeScript 阶段失败。
- 精确错误：`frontend/tests/unit/core/threads/workspace-actions.dom.test.tsx(275,9): TS2533 Object is possibly 'null' or 'undefined'`。
- 位置：`archived.data?.pages[0]?.[0]?.metadata.deerflow_archived`，`metadata` 的可空类型尚未处理。下次先核实并修正该测试的空值访问，再按现有上海 Jenkins 流程验证；不要把已有行为测试绿色当作完整检查通过。
- `#33/#34` 均终止，独立检查其专属容器和网络为空；`frontend-actions-format` 探针资源为空。依赖缓存保留。没有运行中的本轮构建，不需要明天盲目重启旧句柄。

## 下次顺序

1. 用户明确继续后，先检查工作树、该 WIP 提交及当前 Jenkins 状态。
2. 修正上述测试类型问题，在上海运行相关主干/回归及完整前端检查，记录新的独立源码包和构建号。所有应用运行测试继续仅在上海；不要启动本地 Docker Desktop。
3. 继续绑定 replay prepare、手动 compact、项目内创建线程及页面调用方 await 后的 toast/router/callback；ChatPage 分支、删除对话框和 sidecar 等调用方还需审查。
4. 接项目/产物/预览/下载等剩余资源客户端，按 actor/workspace/reset 生命周期处理 artifact/sessionStorage、线程 UI 状态等。
5. 再接服务端 capability bootstrap、原生样式空间入口和真实浏览器双标签页验收。跨标签页凭据/principal 一致性与主动撤权等仍是必要门槛。

## 不变的总范围

M0–M11 原计划全部保留；当前仍 partial M3，各父验收未完成。M4–M11 的后台执行协议、工具/存储隔离、自助开户团队、配额审计、资料研究报告跟进、迁移恢复和最终验收均不能省略。`_WORKSPACE_RUNTIME_INTEGRATED=False` 保持关闭。此次仅本地 WIP 保存，没有推送、部署或模型调用。

更早的连续记录见 `docs/tenant-workspaces-resume-2026-10-14.md`，详细证据见 `docs/tenant-workspaces-progress.json` 的 `frontend_thread_actions_wip`。


2026-10-15 resumed at explicit user request. M3 thread-action checkpoint:
frontend #33 RED reproduced missing Run selector, old sidecar lookup continuing
to delete, and archive publication after a delayed cache cancellation. #34 passed
50 tests but full check failed on nullable test metadata (TS2533). #35 SUCCESS
reruns the same three mains and 47 native/chat regressions, four-file formatting,
zero-warning target lint and full pnpm check. Optional metadata access still
requires the archive flag to be true; no type assertion bypass. Runtime/test
bytes match its archive; exact #33-#35 and formatter resources independently empty.

Actual SDK/REST sidebar search, Run detail and branch/pin/archive/move/rename/
delete hooks capture the confirmed clients. Post-decode and post-cache-await
checks stop stale mutation publication and callbacks; lookup cancellation cannot
fall through to best-effort deletion. Scoped deletes use the native canonical
Gateway endpoint, avoiding the previous SDK-plus-fresh-REST double request for
each normally enumerated thread. Native unscoped compatibility and its cleanup
retry regressions remain. These are real hooks with network doubles, not actual
browser/backend or physical STOP proof.

Continue with replay prepare, compact and project-thread creation, then UI
callers' await/toast/router fences (ChatPage branch, delete dialog and sidecar).
The native sidecar API's global inFlightCreates map currently keys only parent
thread ID; scope this by confirmed client/lifetime before activation. Other
resource clients, artifact/thread UI storage, actual shell/selector and backend
browser two-tab acceptance still remain. M3 and all M4-M11 gates remain open;
activation stays closed, no deployment/push/local application runtime/model calls.
The earlier user-pause section is historical; the user has explicitly resumed.


M3 replay checkpoint (2026-10-15): frontend #36 RED found missing prepare
selectors; its retained-callback fixture also held a later request and timed out.
#37 fixes that fixture delay and independently reproduces null selectors and
retained callback dispatch. #38 SUCCESS (20 tests), then formatted final source
#39 SUCCESS (same 20 tests, two-file formatting, zero-warning target ESLint and
full pnpm check). Regenerate/edit prepare uses captured REST with full native
success/error decoding fenced; replay checks entry, prepare return and submit
boundaries. Expired callbacks return the native false result quietly, without
starting Runs or publishing cache/toast effects. Exact source hashes and archive
receipt are in tenant-workspaces-progress.json; #36-#39 and formatter inventories
are empty. These are real hooks with network doubles, not browser/backend proof.
Next: compact/project creation and actual page callbacks, sidecar coalescing,
remaining clients/stores/shell integration. M3 and M4-M11 remain incomplete;
activation stays closed. No remote push, deployment or local runtime testing.


M3 create/compact API checkpoint (2026-10-15): frontend #40 RED reproduced
missing selectors and accepted late-decoded create results. #41 passed 13 tests
but failed TS2322 because test afterEach returned RstestUtilities. Explicit
void cleanup fixes the type without weakening assertions. #42 RED independently
reproduced a real delete dialog callback navigating after a confirmed Context
switch. #43 SUCCESS: two
scoped mains + six native API + five chat hooks + four dialog tests (17 total), formatting,
zero-warning target lint and full pnpm check. Optional fixed REST clients and
whole native response decoding now cover createThread and compactThreadContext;
no-options payload/CSRF/conflict compatibility remains. Exact source/archive
receipts are in tenant-workspaces-progress.json; owned #40-#43 and formatter
resources are empty. Actual ChatPage project creation and InputBox compact
callers still need wiring and post-await UI checks. The actual deletion dialog
now captures its lifetime before dispatch and checks before reset/router,
post-await close and failure toast/log/focus; native failure feedback is kept.
Its external deletion operation is doubled, while #35 covers real deletion hooks.
Network doubles do not
supply real browser/backend/physical acceptance. All parent gates remain open.


Next concrete order: bind ChatPage.ensureProjectThread and handleBranchTurn;
bind InputBox compact while retaining its native request epoch; scope sidecar
find/create coalescing and guard restore→create/queued-send/delete publication.
Then activity read clocks/timers, projects and artifacts: loader fencing must
include arrayBuffer decoding and async SHA calculation; direct media/download
URLs cannot carry the workspace header. Reuse the existing allow_query_selector
contract on artifact GET and project-document content GET: append workspace_id
to those browser URLs, keep native authenticated/ACL/before-send checks, and
reject selector conflicts. Other REST paths keep fixed header transport.


M3 actual composer commands (2026-10-15): frontend #44 RED reproduced eight
missing selectors across personal/team goal GET/DELETE/PUT and compact POST.
#45 SUCCESS: 21 tests (13 actual InputBox cases, six native API and two scoped
API), two-file formatting, target ESLint, early tsc and full pnpm check. The
component captures the confirmed REST client, fences full native goal success/
error decoding, passes the client to compact and checks preparation, response
publication and follow-up run boundaries. Native request epochs, permission
gating and prepare→goal-save→run ordering are preserved. Existing late-command
thread cleanup remains effective. Fixture supplies an explicit empty skills
catalog; no localhost server is required. The existing KaTeX happy-dom quirks
warning remains. Exact source/archive receipts and cleanup for #44/#45 and the
formatter are recorded in tenant-workspaces-progress.json. Real component/
Context with HTTP doubles does not prove actual browser/backend authorization.
ChatPage project/branch, sidecar, ancillary input tools, draft/attachment stores,
activity/projects/artifacts and actual shell/browser integration remain. Parent
M3 and all remaining M4-M11 gates stay open; activation stays closed.


M3 actual ChatPage (2026-10-15): frontend #46 RED reproduced missing P/T
precreation selectors, accepted late prepared metadata and retained branch
dispatch. #47 SUCCESS: three real-page/Context mains, formatting, target ESLint,
early tsc and full pnpm check. Native single-user and P/T project creation keep
the same payload. Scoped precreation captures REST and fences entry/decoder/
cache publication; its expired errors do not toast. Send preparation retains
the native conversation epoch and also checks scope. Branch entry/return/error
and reference-attachment URL callbacks refuse expired scopes; the new space's
normal branch still toasts/routes. The page comment now accurately describes
precreation as the membership channel; run requests do not seed projects.

The page and create API are real; leaf UI/stream/branch/catalog operations are
doubled to isolate page callback effects. Native branch hooks and stream/replay
were verified separately in #35/#39, and actual InputBox commands in #45. This
does not supply actual browser/backend/physical acceptance. Exact source/
archive receipts and empty #46/#47/formatter inventories are recorded in
tenant-workspaces-progress.json. Next: sidecar as one bundle (fixed SDK lookup,
REST-client-keyed in-flight creates, guarded restore→create→queued-send and
delete/trigger publication), then activity/resources/stores/shell/browser.
All parent gates remain open; activation remains closed.


M3 sidecar scoped lifecycle checkpoint (2026-10-15): #48 main RED reproduced
unscoped restore lookup; #49 main GREEN (seven cases) came before lifecycle
expansion. #50 was an observer-fixture failure, not behavior evidence. Removing
module wrapping and observing actual API coalescing/MutationCache yielded #51:
main passed, but pending P creation blocked T and late P delete toasted in T.
#52 passed 13 behaviors/format, then failed import/rejection lint; #53 passed
behaviors/target lint, then early typecheck rejected a bound-query generic.
A real textarea check fixes the type without a cast. #54 SUCCESS: same 13
cases, six-file formatting, target lint, early tsc and full pnpm check.

The actual provider uses fixed SDK lookup with post-JSON fences. Creation uses
fixed REST/owned decoding, and per-client WeakMap namespaces retain same-life
coalescing without blocking another actor/workspace/reset lifetime. The panel
checks restore→create→queued first-send and send/delete publication. Scope
expiry rejects queued submit with typed AbortError and removes its listener;
stale errors do not toast. Trigger opening checks lifetime after restoration.
The main preserves P/T reference contents and normal T deletion; native API
and four draft/send regressions remain. HTTP replies/React SDK adapter and
peripheral catalog/router/toast are doubled, while core hooks, composer, SDK
SSE parser/transport and REST remain real. Existing KaTeX warning is retained.
No real browser/backend/model/physical acceptance is implied. Exact receipts
and empty #48-#54/formatter inventories are in tenant-workspaces-progress.json.

Remaining M3 audit includes same-space parent navigation/unmount: native
ChatBox remounts panels through MessageDetailsProvider keyed by threadId, but
SidecarProvider is outside it. Late callbacks and queued/quiet stream gaps
still need targeted UI/fault proof before activation. Continue with activity
clocks/timers, project/artifact clients, direct links and UI stores; then actual
shell/selector and browser/backend two-tab acceptance. Preserve all M4-M11
gates; activation stays closed. No deployment, remote push or local runtime.


M3 activity/read frontend checkpoint (2026-10-15): #55 RED reproduced an
unscoped activity GET; #56 main GREEN (21 cases) preceded the additional
lifecycle case. #57 SUCCESS: 22 cases (two new, 20 native regressions),
two-file Prettier, target ESLint, early tsc and full pnpm check.

Both hooks capture their confirmed REST lifetime. Polls combine Query/workspace
cancellation, fence cursor/clock updates and invalid-cursor recovery. Read
callbacks/timers refuse expired scope, and late read success/errors cannot
update clocks or invalidate lists. Native 15s polling, 1s read debounce, cursor
reseed and monotonic read versions remain. The P/T main uses real Context,
hooks and REST with synthetic HTTP. A held old GET and POST JSON pair is
released after selecting T: reset P state stays empty, old callbacks cannot
POST, and T reads continue. Feature/router fixtures are doubled; this is not
actual browser/backend/principal or physical isolation acceptance.

Source hashes match the final archive, with exact build/formatter resource
inventories empty. See frontend_thread_activity in the progress JSON. Next:
same-space sidecar parent/unmount faults, project/artifact clients/direct URLs
and UI stores, then shell/selector and browser/backend two tabs. M3 remains
partial; all M0-M11 parent gates remain open and runtime activation stays closed.
No deployment, remote push, model call or local runtime was performed.


M3 project/shelf client checkpoint (2026-10-15): #58 RED reproduced project
reads without a selector; #59 main GREEN (39 cases) came before adding one
lifecycle scenario. #60 passed all 40 behaviors but Prettier caught two await
method-chain layouts. Reformatting the same source package showed only those
test-layout changes. #61 SUCCESS: 40 cases (two new, 38 native regressions),
three-file Prettier/target lint, early tsc and full pnpm check.

All 16 native project API functions accept optional fixed REST/signal options;
15 native hooks bind the confirmed lifetime, combine Query cancellation and
workspace abort, and suppress stale onSettled invalidations. Preserve native
request bodies/arguments/errors and full preview Range/text/empty/PDF/binary
decoding inside the response lifetime. No new project execution service exists.
The real Context/hooks/REST main runs P/T project reads/writes, shelf upload,
preview, thread attach/promotion, archive/restore and deletion. Delayed old
upload JSON/preview byte decoding rejects after selection; a retained old
delete cannot dispatch and T upload still works. HTTP replies/router are
fixtures, not actual page/browser/backend or physical authorization proof.

Final source hashes match the verified archive; exact #58-#61 and formatter
resource inventories are empty. Detailed receipts: frontend_project_clients
in progress JSON. Next bind actual project/shelf/settings/sidebar/move-menu
callbacks and preview effects, including same-space project navigation
(the shelf currently has no project key); then document/artifact URLs, relative HTML
assets and remaining UI stores. htmlBaseHref currently strips search, so
adding a workspace query only to a top-level HTML URL cannot scope relative
assets. Preserve the native safe preview architecture and verify that chain.
Same-space sidecar parent/unmount/quiet-stream, actual shell/selector/two-tab
and principal acceptance remain; M3 is partial, all parent M0-M11 gates stay
open and activation remains closed. No deployment, Git remote push, model
call or local runtime was performed.


M3 shelf/composer handoff checkpoint (2026-10-15): #62 main RED showed
preview-null in the actual preview dialog. #63 main GREEN (42 cases) came
before two lifecycle scenarios; its new duplicate sibling keys were spotted
in console and corrected to distinct shelf/files keys. #64 passed 108
behaviors/format, without the key warning, then target lint rejected a test
fixture match() boolean. Replacing it with test() changes no production bytes.
#65 SUCCESS: 108 cases (three new, 105 existing), five-file Prettier/target
lint, early tsc and required full pnpm check. Source hashes match the final
archive; #62-#65 exact owned resources and formatter inventories are empty.

The native attachment list persists per actor/workspace/thread and captures
an immutable lifetime; expired handles cannot read/write/retire it. Native
unscoped keys stay unchanged and are never adopted. Mounted setters also
fence thread/store identity. The real shelf stages into this store; InputBox
reads it and retires sent files using the captured store, with onSent scope
fencing. File-mention prepare/attach awaits use captured REST and guard stale
continuations while native mention behavior stays covered by its regressions.

The actual preview effect uses fixed REST plus scope/effect cancellation.
Document row download and preview iframe/full-file URLs carry the existing
workspace_id selector; it is not a credential. Cached project navigation
remounts distinct shelf/files views; current-view guards stop later files in
an old multi-file loop and stale state/toast/router/save/attach publication.
P/T/P main proves own draft persistence, actual attachment-only composer
submission, legacy isolation and scoped preview/link selection. The two
additional scenarios observe actual old mutation state and old onSent, and
stop an old file loop after navigation while current project upload works.
The first old upload may finish in its original project; no remote STOP or
rollback is claimed. HTTP/router/model/toast/preview-leaf and final onSubmit
are doubled; no real backend/browser download, iframe or Run proof implied.
Existing Radix/KaTeX and native iframe fixture network/cleanup warnings remain;
the newly introduced duplicate-key warning is fixed.

Next: actual settings/sidebar/create/move-menu callbacks, composer text/
reference drafts and other UI stores; explicit scoped file-picker/focus race
proof; artifact/direct/relative HTML and standalone views, then actual shell/
selector/browser/backend two-tab acceptance. Same-space sidecar faults and
principal/session/revocation remain. M3 is partial, every M0-M11 parent gate
remains open and activation stays closed. No deployment, Git remote push,
model call or local application runtime was performed.


M3 composer drafts/native project workflow checkpoint (2026-10-15): #66 RED
proved a scoped composer restored Legacy personal notes from an unscoped
key. The separate project-page fixture hit a label ambiguity (Instructions
tabpanel and textbox); querying the actual textbox fixes the fixture. #67
main GREEN (21 cases: two new, 19 existing) preceded lifecycle expansion.
#68 passed 78 behaviors/format but target lint rejected unknown test-field
string coercion; typeof narrowing fixes only the fixture. #69 SUCCESS:
78 cases (three new, 75 existing), eight files, three-file Prettier/target
lint, early tsc and required full pnpm check. Production bytes match #68;
source/archive hashes and exact empty #66-#69/formatter resource inventories
are captured in frontend_composer_drafts in progress JSON.

The text/reference draft namespace is disjoint from legacy keys and binds
actor/workspace/agent/thread. Captured Storage handles refuse foreign or
legacy keys and all access after expiry. InputBox hydration, save, flush,
retirement/clear and new-thread file-reference transfer use this client/key.
Scoped edits persist the visible snapshot while active: selection aborts
before React cleanup, so relying on a final expired flush would lose the
latest keystrokes. Native unscoped keys, 300ms debounce, disabled-storage
behavior and draft reconciliation stay unchanged. No automatic legacy
adoption occurs. Current namespace remains persistent across own remounts;
old handles cannot change a fresh lifetime's same-space replacement.

Positive UI verification reuses ProjectPage, ProjectsSection and
NewProjectDialog unchanged: P/T instructions editing, rename, archive/restore,
sidebar create, create-then-move and delete navigation pass through real
project/thread hooks and REST. No replacement project UI or extra mutation
layer was necessary. Their unchanged source hashes are recorded alongside
the code changes. Real InputBox P/T immediate switching preserves own draft;
old onSent and expired/foreign Storage cannot clear replacements; stored
reference metadata restores its own chip after P/T/P. HTTP/catalog/router/
toast, layout/document/thread leaves and final onSubmit are fixtures; this
is not actual backend/browser/Run/principal authorization proof. Existing
KaTeX/Radix warnings remain; production styles were not changed.

A bounded existing-image browser inventory (uid 999:987) found no standard
PATH browser or four common cache/install directories; probe exit 0 and
owned resources empty. This does not inventory other images/host/custom or
inaccessible caches; inspect reusable tools before preparing browser gates.

Next: artifact clients/direct/relative HTML/standalone/iframe URLs and remaining
UI-store/global-title audit, explicit scoped file-picker/focus and same-space
sidecar faults, then actual shell/capability/selector and browser/backend
two-tab acceptance. Positive project UI workflow is not every publication
fault. Principal/session/revocation and all M4-M11 gates remain. M3 is partial,
every parent M0-M11 gate stays open and activation remains closed. No
deployment, Git remote push, model call or local application runtime ran.


M3 artifact panel checkpoint (2026-10-15): frontend #70 RED reproduced an
unscoped native artifact read (Report-null-thread-1). #71 main GREEN first:
35 tests (one new, 34 existing), real P/T native detail read/revision save and
archive download plus legacy panel-state non-adoption. Native archive UI
appears only above one file, so the manifest fixture correctly lists two.
Only then add two lifecycle scenarios. #72 passed 50 tests/format; target
lint found four import-order issues and one redundant assertion. #73 SUCCESS
passes the same 50 tests (three new, 47 existing), eight files, nine-file
Prettier/target lint, early tsc and required full pnpm check. Exact archive/
source/image IDs, terminal timings and empty #70-#73/formatter inventories
are recorded in frontend_artifacts in progress JSON.

Native byte/range/ETag/hash/416 preview, revision PUT/error handling, archive
manifest and Blob decoding now accept the captured workspace REST client.
The whole native decoder, including awaited bodies/hashing/errors, is inside
consume; queries retain cancellation. Native unscoped argument counts,
payloads/methods/decoder semantics and styles remain. Save/ZIP completion,
toasts/cache/draft writes and pending flags belong to one mounted resource
incarnation; same-space navigation and A/B/A cannot revive an old callback.
Panel storage is a disjoint actor/workspace/path namespace, never adopting
legacy data. Retained context setters and beforeunload/persistence callbacks
are fenced. Route transitions reset this provider's state without keying/
remounting its chat subtree; draft buffers stay in memory.

The two added scenarios verify delayed same-space save/ZIP decoders and
retained panel callbacks do not touch a replacement view; its new save/ZIP
still work. A separate deterministic client check releases byte/JSON/Blob
decoders after workspace switch and observes AbortError. Real components/
providers/hooks/REST execute against HTTP/catalog/router/toast fixtures and
editor/preview leaves. This is not live ChatPage/Run, backend authorization,
actual ZIP extraction, browser-download or HTML resource proof. Native iframe
cases log happy-dom fetch/abort teardown output; archive rejection logs and
KaTeX warning remain. A detached save may already have reached the server;
no remote cancellation is claimed.

A read-only inventory found the existing DeerFlow browser-mcr image; its
custom /opt/deerflow-browsers installation is documented in native scripts
and historical #41. Prior PATH/standard-directory absence was only a bounded
probe. Fresh exact-image native distribution verification passed as uid/gid
1000:1000, network none: Chromium 149.0.7827.55 launch/input/PNG, owned
resources empty. This proves browser tooling only, not DeerFlow page/backend
acceptance. No image download.

Next: direct/standalone/new-window/media/Markdown and nested HTML/CSS URLs,
remaining UI stores/title/focus/sidecar faults, then real shell/capability/
selector and browser/backend two-tab proof. Artifact skill installation is
a separate operator/M5 authority boundary. All M0-M11 parent gates remain
unchecked; M3 is partial and startup activation remains false. No deployment,
Git remote push, model call or local application runtime occurred.


M3 standalone artifact/locator checkpoint (2026-10-15): backend #90 RED
missing workspaces capability; #91 GREEN 23 feature API tests (one new), actual
FastAPI startup-state projection, no database gate needed. Frontend #74 RED
reproduced the unbound original standalone renderer; #75 main GREEN first
(47 tests: one new, 46 existing). Only then add two boundary scenarios. #76
passed 75 behaviors/format/target lint but early tsc rejected an unsupported
fixture ByRoleOptions.exact. It was already FAILURE when the stop helper
inspected it; no stop request was sent and it was not aborted. #77 RED in the
same three-case suite proved auth-disabled development incorrectly entered
workspace mode (two passed, one failed). Reuse the native operator predicate
to retain that supported non-tenant path, and fix the test query option.
#78 SUCCESS: 75 tests (three new, 72 existing), nine files, 19-file format/
target lint, early tsc and required full pnpm check. Backend source still
exactly matches #91. Exact source/archive/image/terminal/empty resource
receipts are in frontend_artifact_windows in progress JSON.

The read-only /api/features workspaces block reports isolation requirement
separately from service presence. It cannot activate the runtime. A standalone
page reads server capability with the native cookie, no-store, refused redirects
and a body-spanning timeout. A URL selector is only a locator. Its requested
workspace is pinned before content through the existing catalog/current
handshake, actor/target-keyed provider and per-lifetime ReadyBoundary cache.
The original renderer and styles remain; the scoped AuthProvider is actor-keyed.
Malformed/duplicate selectors, mock+workspace, missing required service, failed
capability or denied current membership cannot fall back to an unscoped read.
Legacy JSON without the optional block remains native, while a scoped locator
on a legacy server is refused. Public allowlisted showcase and supported
auth-disabled/static flows retain native behavior. Workspace locators survive
viewer build/parse and login next; panel/source/download/list/fallback/PDF
top-level URLs now include only the confirmed locator. Entry-stale panel
open/download actions are inert. Existing panel main checks both actual window
open calls and their selectors. No second file/auth service was added.

Positive P/T real renderer/route-function/Context/REST and body-held old actor
replacement, login target preservation, refusal paths and native developer/
legacy compatibility execute against HTTP fixtures. SSR auth/cookies/router/
locale are mocked. This is not compiled Next RSC, actual JWT/session/principal
revocation, real browser/window/download HTTP, physical NAS or model proof.
Native iframe teardown abort/fetch output, expected archive rejection logs and
KaTeX warning remain. Previous actual backend file receipts are independent.

Next: Markdown/message image resolvers, browser/change-panel artifact links,
then nested HTML/CSS relative resources and real browser/cookie/backend
acceptance. Main shell capability/selector, remaining UI-store/title/focus/
sidecar faults and all M4-M11 remain. Every parent gate is unchecked, M3 partial
and startup activation false. No deployment, Git remote push, model call, local
application runtime or new image download occurred.


M3 message/report resource checkpoint: frontend #79 RED reproduced the real
message link's missing workspace locator. Its HTML compiler diagnostic also
failed before browser launch because it lacked the existing pnpm symlink; fix
that fixture prerequisite. #80 main GREEN first: 28 tests (one new, 27 native).
Then add only two boundary scenarios; #81 GREEN: six tests (three new and the
three existing artifact lifetime cases). #82 kept Streamdown's default image
renderer via its native defaultUrlTransform interface: 53 passed, one boundary
failed because native Streamdown omits a rejected image instead of emitting an
empty-src img. Preserve that native behavior and correct the same assertion;
the positive main now requires native image/image-wrapper markup as well.
#83 passed 54 behaviors/format but was actively stopped (ABORTED) after review
found file citation links bypassing scope. #84 RED reproduced this by extending
the same main with /mnt and raw native file citations (two boundaries passed).
Resolve scoped file locators before native citation early returns, retaining
unscoped behavior. #85 SUCCESS: 54 tests (three new, 51 existing), 11 files, 15-file format/
target ESLint, early full tsc and required full pnpm check. Exact source/archive/image/
terminal/empty-resource receipts: frontend_resource_surfaces in progress JSON.

Native /mnt and configured-Gateway raw artifact links, message/upload/report
images, tool/static browser screenshots and file-change links use captured
workspace locators. Preserve query/hash/literal percent names and native safe
link/citation guards. Content-authored duplicate/foreign selectors are replaced,
web references remain unchanged, and scoped relative report paths cannot escape
the source thread file route. Scoped successful write_file preview derives its
source base too. Streamdown's default URL safety and original image renderer/
controls remain, without overriding img. Feedback and file changes share the
whole-decoder fixed REST helper (artifact API aliases preserved). No-options
legacy API calls retain native payload/error semantics; DELETE404 clears local
feedback as before. Same-space route changes cannot publish old feedback or
reset a new pending indicator; obsolete change reads are cancelled and cannot
publish into their old query. Real providers/REST/components use HTTP/router
fixtures; live browser stream is doubled. Native Streamdown paragraph/image
nesting, happy-dom teardown and KaTeX warnings remain; actual browser hydration
is not accepted. These are not actual Gateway/Next/
browser/principal/physical authorization proofs. Live WSS/navigation is open.

The new repeatable scripts/tenant_artifact_html_probe.py transpiles archived
unchanged native preview helpers in the pinned CI image and runs Python
Playwright in the pinned Chromium149 image, network none. Synthetic HttpOnly
SameSite=Lax cookie and strict container-local file/scope fixture only. The
parent image positive control succeeds. Native query-base and fixture-only
path-prefix candidates fail image/CSS/fetch; cookie is absent in the opaque
iframe (query selector is also dropped by native base handling). Parent-made
Blob assets fail too. Parent authorized byte reads transferred into iframe-made
Blobs load image, stylesheet and JSON. #81/#82/#83/#85 retain all four observations;
#80 had the first two candidates. This is a transport experiment, not implemented
product HTML/Gateway acceptance. Keep sandbox allow-scripts allow-forms with
allow-same-origin absent and native Cookie policy unchanged. Production source
validation, nested CSS/dynamic requests, lifecycle cancellation and Blob cleanup
still need implementation and real-browser verification. No production alias
route was added.

Next: bind CitationSourcesPanel native file source links/copied references and
its pending clipboard publication, then implement scoped HTML resource delivery
through captured parent REST and actual shell/selector/browser/backend acceptance.
Remaining UI stores/title/focus, sidecar faults, browser live transport, M4-M11
and physical/principal/revocation gates remain. M3 partial, every parent gate
unchecked, runtime activation false; no deployment, remote push, model call,
local application runtime or new image download.

Staged whitespace check then caught four blank-line spaces inside the diagnostic
script strings. Remove only those spaces; all 15 frontend files still exactly
match #85. The cleaned script's four browser observations were reverified in
pinned Shanghai containers with empty owned resources, directly on Jenkins host
(not a new Jenkins build). Full frontend checks were not repeated. Exact script/
archive hashes and results: frontend_resource_surfaces.post_gate_probe.


M3 source-list references checkpoint: frontend #86 RED extended the existing
main and reproduced a source-list link retaining a foreign content-authored
selector. #87 main GREEN first: eight tests in two files, including five native
source-panel SSR/style/locale regressions. Actual message/report lists link and
copy in P/T through native parsing, reference formatting and clipboard helper;
external web sources keep their original URL/text. No new cases were added.
Then extend the same two existing boundary cases: old same-space copy completion
and an expired workspace/clipboard failure, plus an unbindable native source.
#88 controlled regression omits only the new artifact owner's resourceKey with
locator binding retained: two reports cite the same URL, and the old copy adds
a second toast after a new-view copy (one failed, two passed). Restore the owner
key. #89 SUCCESS: 59 tests/12 files, four-file formatting/target lint, early full
tsc and required full pnpm check. The same three integration cases were extended,
with 56 unchanged regressions; zero additional cases. Source/archive/image/
terminal/empty-resource receipts: frontend_source_references in progress JSON.

Source-list file hrefs and copied Markdown use the confirmed locator; unbindable
native file links are inert with copy disabled. Native layout, counts, locales,
formatter and clipboard fallback stay. Both actual callers pass the owning
thread/message or artifact scrollKey/active identity. Copied feedback, success/
error publication and timers belong to that source/view/workspace incarnation;
old cleanup cannot clear a replacement timer. HTTP/router/clipboard wires are
doubled, and source details are opened in the DOM fixture. This does not prove
OS clipboard cancellation, browser permissions/downloads, compiled Next/hydration,
live backend/principal/two-tab or physical isolation. Already-issued clipboard
operations cannot be undone; guards protect UI publication. Native paragraph/
image nesting and KaTeX warnings remain. Existing HTML helper/probe code is
unchanged and was not rerun; its prior transport evidence is not product HTML
acceptance.

Next: scoped HTML resource delivery through captured parent REST into iframe-
owned bytes, retaining native sandbox/Cookie policy, then source validation,
nested CSS/dynamic requests, disposal and actual browser/backend acceptance.
Main shell/selector, UI stores/title/focus/sidecar faults, live browser transport
and M4-M11 remain open. M3 partial, every parent gate unchecked, activation
false. No deployment, remote push, local application runtime, model call or new
image download.


M3 HTML parent-read foundation: frontend #90 is a missing-feature build RED
(new reader module absent, zero tests executed), not a network failure. #91
main GREEN first: 14 tests (one new byte main, 13 existing URL regressions).
#92 GREEN: 16 tests after only two boundary scenarios. Extend the same refusal
case for encoded structural paths: #93 RED (two passed, one failed) shows literal
prefix validation accepted a path that can normalize outside the thread route.
Inspect structural normalization without rewriting actual filenames; safe literal
percent names remain. #94 passed behaviors/format/target lint, but early tsc rejected an implicit
RstestUtilities return from test afterEach (TS2322). Use an explicit void body;
production code remains unchanged. #95 SUCCESS: 28 tests (three new, 25 existing), four files,
three-file format/target lint, early full tsc and required full pnpm check. Exact
source/archive/image/terminal/empty resources: frontend_html_resource_reader.

The new reader snapshots native source/lifetime scope/rest, reads only that
thread's configured-Gateway files through existing GET/no-store/whole ArrayBuffer
decoding, and returns bytes/MIME/status/locator without response credentials or
headers. Invalid/external/API/foreign-thread and normalized escape targets are
refused before send. Source/client mutation cannot retarget an existing reader.
Per-read abort, report dispose and workspace abort reject held byte decoders;
report disposal leaves other reports and the workspace alive. Native HTTP404
status remains typed. Pure Node HTTP-wire tests do not prove real proxy/backend,
principal revocation, browser rendering, React lifecycle or physical isolation.
This is source identity binding, not an atomic multi-file revision snapshot.

Important: this reader is not yet connected to the production iframe renderer;
HTML resource loading is still unaccepted and retains its previous behavior.
Next wire it through a document/source-bound channel and child-owned byte/Blob
delivery, implementing nested CSS, local scripts/module graphs, dynamic data
requests and disposal. Verify an actual Chromium rich-report main before needed
fault boundaries. Keep sandbox and Cookie policy unchanged. Main shell, actual
backend/two-tab/principal, remaining UI/live-browser and all M4-M11 gates remain.
M3 partial, parent boxes unchecked, activation false. No deployment, remote push,
local application runtime, model call or new image download.


M3 native HTML byte bridge checkpoint (2026-10-16): #96 compiled/mounted the
native React fixture, but a Playwright variable error prevented full assertions;
it is not a clean domain RED. Correct only that predicate: #97 RED shows both
P/T parent controls render while private iframe image/CSS/script/data fail.
#98 GREEN first: actual production preview/parent reader/private channel/child
Blob integration renders both rich-report mains and refreshes local GET data;
16 existing regressions pass. Only then extend the browser fixture with held
read hide/reopen and read-only API/foreign-thread/fetch-POST refusal. #99 SUCCESS:
all browser observations pass, forbidden network hits empty, and 40 existing
Rstest cases/five files pass. Zero new Rstest cases. #100 SUCCESS on formatted
sources: same browser main/boundaries and 40 regressions, seven-file formatting/
target lint, early full tsc and required full pnpm check. A separate temporary
formatter's default 1GiB typecheck exhausted heap; final gate uses the established
1536MiB setting. Exact archive/source/images/terminal/empty-resource receipts:
frontend_html_resource_bridge in progress JSON.

Native scoped ArtifactFilePreview now uses one document/view/lifetime-bound
MessageChannel. Parent captured REST grants only the existing same-thread native
file GET boundary; child gets bytes/MIME/status/locator, never credentials or
raw response headers. parse5 prepares inert HTML; PostCSS/value-parser prepare
nested stylesheet references. Child-owned Blobs keep opaque sandbox isolation
while supporting the tested image/nested CSS/classic script/local fetch main.
Reinstall runtime after document.open clears listeners, before author scripts.
Close/abort/revoke on retirement; hidden/replaced documents cannot own the shown
URL. Scoped scroll keys use a document nonce; legacy behavior stays on its path.
Keep allow-scripts/allow-forms without allow-same-origin, Cookie policy unchanged.

Limits: actual Chromium bundles native React/Auth/Workspace/REST with env/router
build doubles and an HttpOnly Cookie/scope HTTP fixture, not Next/Gateway/SQL/NAS
or live JWT/principal/two-tab/revocation proof. Native Streamdown paragraph/div
and KaTeX DOM warnings remain. General HTML support is unaccepted: next complete
local ESM/import graphs, dynamic elements/srcset/XHR and CSS/media/error fidelity,
including known external-base/fragment, CSS-cycle and malformed-style handling.
Then compiled Next/actual backend acceptance and shell/selector/remaining UI/live
browser gates. All M0-M11 parent gates remain unchecked, M3 partial, activation
false. No deployment, remote push, local application runtime, model call or new
image download.
