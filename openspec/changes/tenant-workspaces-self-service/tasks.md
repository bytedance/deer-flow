# Implementation tasks

Status: partial M0/M1/M2/M3 foundations verified, including member controls, credential-reset/ownership-transfer serialization, production router registration, startup fencing and actual private-project CRUD SQL scoping and private project upload/list/download/trash with before-send revocation, explicit shared project/document ACLs and private-default legacy migration; no complete work-package acceptance yet. See docs/tenant-workspaces-progress.json for exact scope and Jenkins evidence.

- [ ] 1. M0 — 冻结入口清单与空间合同。验收：缺少/伪造空间上下文被拒绝；单用户模式保持原有行为；入口清单无未指定处理方式的运行路径。
- [ ] 2. M1 — 租户与成员模型、增量迁移及个人空间回填。验收：空库及0035/e0001隔离副本升级成功；8 runs/4 mcp_tasks/12 execution jobs等既有实际记录按清单校验保留而非硬编码业务数量；重复回填幂等，冲突记录不开放。
- [ ] 3. M2 — 统一空间授权、成员与管理员开通API。验收：管理员开通空间后指定owner可登录使用；owner/admin/member遵循权限表；并发转让/退出不会失去owner；跨空间ID请求404。
- [ ] 4. M3 — 原生资源、文件及客户端空间切换贯通。验收：同一用户在个人空间和团队空间各上传/提问/下载一份文件成功；切换后无旧数据闪现；未授权空间无法列举或直接读取。
- [ ] 5. M4 — B/C、Scheduler、通知和撤权贯通。验收：一个空间的一次确定性C→B→C仍使用原生任务权威；切换UI空间不改变运行归属；移除成员阻止queued启动与后续发布，物理STOP未确认不释放容量。
- [ ] 6. M5 — 记忆、知识检索与工具凭据隔离。验收：A/B各含唯一哨兵文本，直接读取、检索、prompt构建及跨线程引用均不串用；成员可用空间连接但无法读密钥；全局插件安装仍拒绝租户admin。
- [ ] 7. M6 — 自助注册、邮箱验证、邀请接受和密码恢复。验收：用户真实收信验证后获得个人空间，接受团队邀请；重复/过期/错邮箱拒绝；GET预取不消费；重置后旧session/PAT失效；正常管理员开通仍可用。
- [ ] 8. M7 — 团队管理、注册与共享资料界面。验收：浏览器完成管理员开通和客户自注册两条主干，各可建立团队邀请成员；第二标签页切换不会改写第一标签页运行归属；错误不暴露内部堆栈。
- [ ] 9. M8 — 配额、用量、审计和空间生命周期。验收：A达到并发/任务/存储额度不影响B；同一结果重复回报不重计；停用无新启动、恢复无自动重放；最后owner无法直接销号；保留期与清理回执可查。
- [ ] 10. M9 — 个人研究与定期跟进业务主干。验收：报告来源指向该空间真实文档及版本；更新说明新增信息；用户可以暂停；另一空间无法访问来源、报告或定时结果。
- [ ] 11. M10 — 隔离副本迁移、恢复与Jenkins交付。验收：断在metadata升级后仍不放行，重入读取回执并安全继续；成套备份能恢复原镜像与数据；跨schema仅镜像回滚被拒绝；新源码/镜像/数据库版本一致。
- [ ] 12. M11 — 集中边界验收、文档与发布结论。验收：两种开户入口及同一业务能力均通过，没有未覆盖的租户入口；失败历史保留；具备邮件配置、隔离和迁移证据后才允许公开注册。

Detailed steps: `../../../docs/superpowers/plans/2026-10-13-tenant-workspaces.md`.

M3 thread repository checkpoint: #25 RED (NULL scope, both databases), #26 GREEN (7 passed, 29.58s). Owner-private thread SQL and shared-project association are verified. HTTP admission, checkpoint/run/files and frontend remain incomplete; parent M3 stays unchecked.

M3 metadata HTTP checkpoint: #27 RED (missing trusted HTTP scope), #28 GREEN (7 passed, 30.21s). Actual authenticated creation/search/PATCH/move and own-only project thread listing now use the scoped SQL repository. Full state/lifecycle/files, Run/background and frontend remain requirements; M3 stays unchecked.

M3 thread file checkpoint: #31 passed real scoped upload, source-preserving copy/promotion, member shared-source attachment, SQL thread main and two legacy transfer checks (6 passed, 30.99s). #29/#30 failure history retained. Before-send artifacts, deletion/withdrawal, lifecycle/client and physical mounts remain unaccepted; parent M3 stays unchecked.

M3 artifact GET checkpoint: #32 RED missing upload link locator; #33 GREEN (5 passed, 27.51s) real SQLite/PostgreSQL downloads, ZIP preview, Range, conflicting/default selector and private-owner denial, plus prepared-response policy revocation. Native Range/download regressions retained. Deletion/withdrawal, continuous-stream/token reset, PUT, lifecycle/client and physical mounts remain required; M3 stays unchecked.

M3 upload DELETE checkpoint: #34 RED proved denied request had already removed file; #35 GREEN (4 passed, 26.75s) actual persisted SQL withdrawal preserves original bytes and later valid deletion succeeds, with companion preservation/symlink regressions. Full lifecycle/client, controlled transfer/cancellation faults and physical mounts remain; M3 stays unchecked.

M3 persistent checkpoint reads: #36 RED missing state scope; #37 RED stale incarnation despite otherwise valid compiled-graph reads; #38 GREEN (6 passed, 30.28s). Actual durable SQLite reopen with both metadata dialects, native detail/state/history/goal, foreign-space denial and in-read incarnation rotation are verified. No full/delta recovery, write/read-clock/lifecycle, background backfill or browser acceptance implied; M3 stays unchecked.

M3 read-clock checkpoint: #39 RED SQL/HTTP/schema gaps; #40 GREEN (12 passed, 54.07s), actual SQLite/PostgreSQL independent clocks, private parent filtering, withdrawal, repeat reads, old-data preservation and current paired CLI. #41 GREEN (2 passed, 30.34s) validates final async HTTP drain; other runtime/test bytes identical to #40. Native head 0038/e0002, immutable old receipts. Lifecycle cleanup, full Run/activity/client and cancellation/physical proof remain; M3 stays unchecked.

M3 native Run reads: #42 RED reproduced foreign-space disclosure in SQLite/PostgreSQL; #43 GREEN (8 passed, 21.74s). Native reads/cursors/keyset/source/batch/token reduction use matching private Run/thread workspace and live policy; required scope is captured at bootstrap. Actual withdrawal and four legacy read behaviors verified. Admission/reservations, HTTP feeds/streams, background recovery and frontend remain incomplete; M3 stays unchecked.

M3 non-run reservation checkpoint: #44 RED NULL workspace; #45 GREEN (7 passed, 21.58s). Actual SQLite/PostgreSQL native RunManager reservations persist private scope and exclude peer admission. Captured user/space/worker release survives policy withdrawal and selection changes, refuses wrong-worker and normal Run deletion, and hides foreign idempotency payloads. Three native compatibility tests retained. HTTP goal/state/new-thread behavior, cancellation/leases/recovery and normal-run M4 remain required; M3 stays unchecked.

M3 native goal/state writes: #46 RED missing scope; #47 RED new-chat allocation ordering; #48 HTTP fixture version mismatch (6 native regressions passed); #49 GREEN actual HTTP mains (2 passed, 33.24s). New goal allocation, state/title update, clear, foreign denial and SQL policy/incarnation changes preserving checkpoint IDs are verified. #48→#49 differs only in the native saver version fixture. Graph preparation stays outside final live SQL commit fencing. PostgreSQL checkpoint, cancellation/crash, full lifecycle/feed/client and M4 remain incomplete; M3 stays unchecked.

M3 write identity follow-up: #50 RED actual owner-check incarnation replacement still admitted goal write; #51 GREEN (8 passed, 34.31s), all three goal/state/clear replacement windows refused with unchanged checkpoint IDs plus both HTTP mains and six native regressions. Final source bytes match the #51 archive. Original request identity is preserved before owner-check and through final live commit; M3 full lifecycle/feed/client acceptance remains pending.

M3 checkpoint-only admission: #52 RED actual legacy checkpoint ID claimed by scoped POST thread; #53 GREEN (8 passed, 35.22s), root-only IDs refused for POST thread/new goal, subgraph-only IDs refused, no metadata or checkpoint mutation, and a real native goal committed between allocation and initialization remains intact. Six affected native creation/goal regressions passed. Durable SQLite checkpoint with both metadata dialects; mixed-version/physical inventory/restore and remaining branch/delete/compact/feed/client acceptance stay pending. M3 remains unchecked.

M3 native branches: #54 RED missing scope; #55 GREEN (8 passed, 35.34s). Actual SQLite/PostgreSQL metadata with native SQLite graph checkpoints proves private child/project ownership, exact source/child file bytes, own-only history, shared peer denial and source-incarnation replacement refusing new metadata. Six native full/delta/history/file/project regressions passed. Prepared checkpoints publish under source SQL fencing after file staging; cross-store faults and unpublished-stage reconciliation remain M4/M8/M10/M11 requirements. Delete/compact/feed/client and full M3 remain unchecked.

M3 manual compaction: #56 RED missing scope; #57 GREEN (8 passed, 36.66s). Actual native middleware/graph/SQL with deterministic model output persists summary and latest-message retention, refuses generation-span policy/incarnation changes without checkpoint writes, and refuses snapshot replacement/foreign/peer access before model calls. Six native mutation/schema/noop/failure/binding/busy regressions passed. Scoped memory/archive disabled; live model/M5 effects, delete/feed/client, fault recovery and full M3 remain pending.

M3 private deletion: #58 RED scope; #59 test API mismatch; #60 actual stale
request cleanup removes recreated file; #61 HTTP mains repaired but old native
cancellation entry failed; #62 GREEN (10 passed, 39.38s), including both metadata
dialects and native drain regression. Tombstones and opaque internal receipts
protect local cleanup, and file operations compare original incarnation.
Remote STOP/recovery, retained task disposition, Run cache/history, physical
NAS/PostgreSQL checkpoint and client acceptance remain; M3 stays unchecked.

M3 activity HTTP: #63 RED missing scope; #64 GREEN (7 passed, 39.36s). Two real
SQL/JWT mains and five native pagination/clock regressions prove independent
workspace heads/read versions and pre-limit private filtering/withdrawal denial.
Run cache, HTTP/SSE and client scope lifecycle remain; M3 stays unchecked.

M3 resident Run reads: #65 RED actual foreign-space cache hit; #66 independent
native collection exposed eager path/authz cycle; #67 GREEN (9 passed, 43.47s).
Both SQL/cache mains, both HTTP mains and five native cache/pagination cases
pass. Durable read faults cannot fall back to cache. Run HTTP/event/SSE/client
and M4 worker identity remain incomplete, so M3 stays unchecked.

M3 event SQL reads: #68 RED foreign-space disclosure; #69 GREEN (9 passed,
44.47s), both metadata dialects plus existing HTTP/native read regressions.
Filter event and private parent before limits/reductions, preserve synthetic
branch IDs, and reject required unbound position queries. HTTP/SSE, event
writes/factory/background integration and client acceptance remain unchecked.

M3 thread Run/message/event HTTP: #70 RED scope; #71 GREEN (6 passed, 40.62s),
actual authenticated SQL events/feedback and four native read regressions.
Seven read routes bind private scope, specific Run paths verify durable
ownership, and entry incarnation is retained until response. SSE/global/other
entrypoints and producer/client acceptance remain unchecked; M3 stays open.

M3 read-only SSE: #72 RED missing scope; #73 initial seven checks pass; #74
RED slow close delays creator cancel; #75 GREEN (8 passed, 41.02s). Native
HTTP/JWT/SQL memory-bridge mains prove entry, delivery-time withdrawal/replay
and subscriber drain without cancelling Run. Native creator cancel precedes
blocked teardown. Redis/physical/load, full credential workflows, producer
paths and remaining M3-M11 integration still gate activation.

M3 global Run reads checkpoint: #76 RED missing scope; #77 GREEN (27 passed,
43.96s) covers two actual SQL/JWT HTTP mains and native global API regressions.
Same-space messages/feedback, foreign/peer refusal and materialization-span
parent replacement are verified. Feedback mutation fences, remaining APIs,
client and M4-M11 remain pending; M3 unchecked, activation closed. Native UI
styling reuse confirmed by user on 2026-10-14, not yet implemented/accepted.

M3 native usage/file-change reads: #78 missing-scope RED, #79 fixture-count
failure, #80 GREEN (13 passed, 45.12s) on actual two-dialect HTTP mains and eleven
native regressions. Distinct usage/diffs and native options, foreign/peer denial
and changed entry/materialization nonce refusal verified. Exact child retention
checks preserved after new event fixture. Feedback/files/client and M4-M11
remain pending; M3 unchecked and activation closed.

M3 feedback checkpoint: #81 RED real cross-space disclosure/missing HTTP scope;
#82 GREEN (38 passed, 57.61s), four SQLite/PostgreSQL SQL/JWT mains plus native
feedback compatibility. Scoped reads filter parent/Run/live versions before
pagination/reduction; writes require original incarnation and parent-first SQL
locks. Actual withdrawal/replacement preserves data. Generic scoped bulk cleanup
refuses bypass of canonical deletion receipt. Exact resources empty, archive
bytes match. Files/client, full factories/producers and M4–M11 remain pending;
M3 stays unchecked and activation closed.

M3 native archive checkpoint: #83 RED missing scope/owned-file close;
#84 GREEN (9 passed, 47.55s), both real SQL/JWT/ZIP mains plus native selection,
manifest/busy/wrong-thread/cancellation checks. Prepared archive closes on
post-materialization or pre-header refusal and cancellation. Source bytes match,
exact resources empty. Artifact GET entry identity/PUT/client and M4-M11 remain;
M3 unchecked and activation closed.

M3 artifact GET entry identity: #85 RED real owner-admission replacement returned
200; #86 GREEN (6 passed, 47.62s) on both SQL/JWT HTTP mains and four native
text/Range/ETag regressions. Capture before owner check, recheck before file
preparation; old request 404 and fresh request valid. Exact resources empty,
source/archive bytes match. PUT/remote/filesystem/client and M4-M11 still required;
M3 remains unchecked, activation closed.

M3 mounted artifact edit checkpoint: #87 missing-scope RED; #88 fixture config
failure (eight native regressions passed); #89 GREEN (10 passed, 51.07s). Both
SQL/JWT mains verify actual space bytes, CAS/nonce/policy refusal and parent
symlink replacement preserving protected bytes. Bound publication is drained
under original-thread SQL fencing with descriptor-relative atomic replacement;
unbound native remote/rollback/cancellation remains passing. Scoped remote hosts
and non-mounted providers still need M4/M5 protocol (currently 503); unsupported
platform and uncertain filesystem outcomes do not bypass gates. Physical/NAS/
distributed fault/unknown-outcome reconciliation and client/M4-M11 remain required.
Exact resources empty, sources match archive; M3 unchecked and activation closed.

M3 frontend Request foundation: frontend #2 RED header/signal loss; #1 setup,
#3/#4 DOM Headers-double diagnostic and #5 formatting history retained. #6 GREEN
passes 16 checks (two new/fourteen native), Prettier and full pnpm check. Runtime/
test bytes match archive, exact resources empty; existing Node22 CI image and
frozen pnpm10 cache reused. This preserves explicit Request scope/method/body/
signal only: automatic scope, SDK/reconnect, per-space cache/provider/UI and real
two-tab backend acceptance remain mandatory. M3 unchecked, activation closed.


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


M3 query-cache checkpoint: frontend #16 RED reproduced the actual shared
module-global QueryClient, cache reuse after a workspace lifetime key change
and retained query data after unmount. #17 passed three mains and eighteen
related native regressions, then was explicitly stopped to correct the new
cleanup-ref lint warning; no test failed. #18 SUCCESS passes the same 21,
modified-file formatting, targeted ESLint with zero warnings and full frontend
pnpm check. Runtime/test bytes match its archive; exact #16-#18 and formatter
owned resource inventories are independently empty.

The actual QueryClientProvider now owns a lazy client per page tree and keys
its child tree by optional native AuthProvider actor plus explicit workspace
lifetime cacheKey. Existing authenticated pages reset on account/null changes;
public pages require no AuthProvider. Changing cacheKey renders an empty client
before the new subtree can show old cache data, and real unmount clears the
old queries/mutations and cancels queries. A captured generation object and
microtask preserve live StrictMode effect replay. This is cache ownership, not
authorization or physical Run/mutation cancellation. Native-style workspace
selector/context, real validated lifetime keys, shared REST/SDK wiring, response
publication and React reconnect storage remain next; real authenticated two-tab
backend acceptance and M4-M11 remain required. M3 unchecked, activation closed;
no deployment/push/local runtime or model calls.


M3 bound REST checkpoint: frontend #19 only established absent factory API;
it is not business RED. #20 used a native-transport-only scaffold and reproduced
missing selectors, foreign dispatch and accepted late JSON results; a late 401
entered native login handling. #21 passed 22 checks/format/target lint, then was
explicitly stopped to correct a source-inspected relative-URL destination issue.
#22 reproduced that actual /workspace/chats/api/threads dispatch instead of the
validated /api/threads target. #23 SUCCESS passes the same three mains plus 19
related Request/static/scoped SDK checks, modified-file formatting, zero-warning
target lint and full pnpm check. Runtime/test bytes match its archive; exact
#19-#23 and formatter owned resource inventories independently empty.

The REST factory freezes scope metadata and API root, preserves native Request
body/method and credential/CSRF behavior, and checks the exact combined signal
after real JSON decoding before returning a value/error. Shared scoped fetch
sends its resolved/validated URL or the original native Request. Explicit null
removes only the inherited Request signal; workspace cancellation stays bound.
Native unscoped/static behavior remains; no scope client is activated in demos.

Next implement typed workspace list/current adapters and the tab-local Context
using the actual server current-context actor/workspace/version tuple. Then wire
the validated lifetime into cacheKey, REST/SDK consumers, native selector and
React reconnect storage. Raw body/Blob readers and caller publication after
further awaits still need fences. A changed shared HttpOnly cookie can change
the native principal while another tab has old display metadata: M6/M11 must
prove session/account synchronization and expected-principal consistency, also
when both actors belong to the same workspace. Never grant authority to an actor
header. Full real backend/browser acceptance and M4-M11 remain; M3 unchecked,
activation closed, no deployment/push/local runtime/model calls.


M3 confirmed Context checkpoint: frontend #24 RED used a legacy-passthrough
contract scaffold and reproduced absent confirmed context and resource mounting
before validation. #25 SUCCESS passes three real React/StrictMode mains plus
nine cache/REST/SDK regressions, four-file formatting, zero-warning target lint
and full frontend pnpm check. Runtime/test bytes match its archive; exact
#24-#25 and formatter owned inventories independently empty.

The typed fixed-GET metadata adapter validates active list shape, unique own
personal membership and current actor/selector/membership/policy tuple before
publishing a newly fetched list. Its native cookie, no-store, no-redirect reads
are cancelled around headers/JSON. Per-actor WorkspaceSession owns local epochs,
aborts the old lifetime immediately, ignores late selections and creates fixed
REST/SDK clients plus a fresh cacheKey only after confirmation. Context controls
remain available while pending; WorkspaceReadyBoundary gates resources and
query cache. Nested disabled wrappers preserve the parent; genuine unmount
closes the store, while StrictMode replay retains its lease.

Evidence is two mounted trees and network doubles, not actual browser/server
authorization. WorkspaceContent does not mount the new Context yet and no
server capability bootstrap/selector exists. Next integrate those and every
real resource consumer. Include native artifact panel sessionStorage bootstrap,
thread UI stores and React reconnect metadata in the scope/reset inventory;
a QueryClient remount alone is insufficient. Selection/manual refresh only:
active revocation/session watchers and native principal consistency after
promotion remain M4/M6/M11. Same-workspace cookie actor change between metadata
reads is covered; post-promotion cross-tab credential proof still is not.
M3 and M4-M11 remain open; activation closed, no deployment/push/local runtime
or model calls. Preserve original DeerFlow style in the coming selector UI.


M3 actual upload consumer checkpoint: frontend #26 RED reproduced the existing
hooks' missing selector and accepted late JSON upload. #27 SUCCESS passes two
real React/StrictMode upload mains plus 19 upload/REST/Context regressions,
modified-file formatting, zero-warning target lint and full pnpm check.
Runtime/test files match the archived source; exact #26-#27 and formatter owned
resources independently empty.

Native upload/list/limits/delete hooks now capture the confirmed lifetime REST
client. Scoped read queries consume TanStack cancellation; the REST client owns
native Response objects in a private WeakMap and consume() checks the captured
combined signal around whole domain decoders, preserving multipart/native
structured errors. Switching aborts a delayed decoded upload and retained old
mutation callback; a new workspace starts an empty observer/cache. Submit helper
also checks lifetime before/after its await. Native unscoped callers retain their
signatures and behavior.

This is actual hook integration, still DOM/network doubles. useThreadStream's
separate direct uploadFiles path and actual SDK/thread reads/submission are next;
app-shell bootstrap/selector, storage/reconnect reset and actual browser/backend
acceptance remain. No real business upload is claimed from this test. M3 and
M4-M11 remain open, activation closed, no deployment/push/local runtime/model.


M3 native chat consumer checkpoint: frontend #28 RED reproduced actual missing
thread selectors, stale decoded upload continuing to submit, and shared SDK
reconnect storage. #29 passed two mains but exposed a test-only return-shape
mistake (chat.thread.messages); #30 passed all three mains and 35 regressions,
then exposed two existing isolated options tests' incomplete React substitute.
Their explicit native/no-workspace fixture now supplies null; no production
workaround. #31 passed all 40 tests but target lint refused two test fixture String()
conversions; explicit type narrowing fixed those. #32 SUCCESS passes three mains plus all 37 native/SDK regressions,
five-file formatting, zero-warning target lint and full pnpm check. Runtime/test
bytes match the archive; exact #28-#32 and formatter/SDK-probe resources empty.

Ordinary useThreadStream now captures the confirmed SDK for streaming and agent
metadata. Native per-thread history, metadata, Runs and token-usage reads bind
the matching client; materialized responses are fenced after decode. File
conversion and direct chat upload are checked before/after await, at onSent and
before submit/cache effects. Old stream callbacks cannot notify/update new
content. The native SDK's documented reconnectOnMount storage factory is used
instead of modifying global storage or replacing its runtime. The adapter maps
SDK keys to the existing actor/workspace/thread namespace, refuses stale
lifetime reads/writes/removal and preserves native unscoped markers. Explicit
server admission must still verify current resource/Run identity; markers grant
no authority. Ordinary selection never requests Run cancellation.

New mains use real React/StrictMode, Context, native domain hooks, REST/SDK
clients and the SDK stream parser with network doubles. The external React SDK
useStream adapter is doubled, so actual automatic rejoin/stop/render lifecycle
and browser/backend authorization are not proven. Search/archive/branch/move/
delete/rename and replay/compact still need client/publication binding, along
with project-thread creation, artifacts, remaining resources and storage.
App-shell/bootstrap/native selector and real two-tab acceptance remain next.
M3 and M4-M11 stay open; tenant activation closed, no deployment/push/local
application runtime/model calls. Continue reusing native DeerFlow styling.


2026-10-15 用户暂停：保存本地 WIP，详见 `docs/tenant-workspaces-resume-2026-10-15.md`。前端 #33 三条 RED；#34 的 50 项行为测试、格式和 ESLint 通过，但完整 pnpm check 在 workspace-actions.dom.test.tsx:275 的 nullable metadata 访问报 TS2533，构建 FAILURE。未补跑、未宣称完成。#33/#34 专属容器和网络、actions-format 探针资源均为空。下次先修复该测试类型并完成上海完整检查，然后继续其余客户端/页面调用方/存储/空间入口；全部父验收仍未完成，activation 关闭。用户恢复前不要继续构建、部署或推送。


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


2026-10-16 user pause: full plan remains incomplete and paused. Last fully
verified frontend checkpoint is #100 / commit 3fb8ed75. Module loading is WIP:
#101 actual relative-module RED; #102 initial browser networkidle timeout before
main assertions, no diagnostic JSON. Neither is module acceptance. Both builds
are terminal with exact owned resources empty. Resume instructions and source/
archive evidence: docs/tenant-workspaces-resume-2026-10-16.md and progress JSON.
No new builds until user resumes; all parent gates unchecked, activation false.


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


M4 model service lifetime checkpoint (2026-10-17): #72 fixture-only signature error is not a business RED; corrected #73 reproduced four premature native exits; #74 additionally reproduced six swallowed STOP signals. #75 main twelve passed before #76 fourteen boundary checks; #77 fixed eighty-five passed plus twenty-six-file cloud Ruff. Native model-service tasks are held by their original private Run guard; drain actual construction/provider threads, keep legitimate completion model calls, then seal/drain before actual native closure. Same-thread replacement remains fenced while shared-service work in another space finishes independently. Service/title/summary preserve GraphBubbleUp; ordinary errors retain normalization/fallback. Exact archives, source hashes, logs and resource receipts: native_model_service_lifetime. Direct lead/system-model lifetimes, goal fallback, arbitrary transports, other revocation domains, dispatcher/recovery and full M0-M11 remain pending. No activation/deployment/local runtime; all parent tasks remain open.


M4 named direct-model lifetime and goal STOP checkpoint (2026-10-17): #78 actual lead/title cancellation RED (four failed/four passed), #79 real goal preparation STOP normalization RED (two failed/six passed). #80 main eight passed, #82 focused thirty-six passed, #83 fixed 114 passed plus twenty-seven-file cloud Ruff. Private host guard retains/drains named native model calls; goal usage remains inside actual work and goal read/evaluation/persistence/re-read preserves permission refusal/STOP. Existing real thread/SQL/heartbeat/conflict/independent-workspace checks reused, with only necessary revocation/direct-retained-task-cancel boundaries. Exact evidence: native_direct_model_lifetime. Tool/external effects, real SDK/stream/cache, full scoped goal persistence, remaining revocation domains, dispatcher/recovery and all M0-M11 acceptance remain open. No tenant activation, push or deployment.


M4 native sandbox dispatch checkpoint (2026-10-18): resumed the same pending #88,
no rebuild. #84 actual late report RED (2 failed/2 passed); #85 main four passed;
#86 read-before-write STOP fail-open RED (2 failed/6 passed); #87 twelve passed;
#88 fixed 134 passed in 250.07s plus thirty-file cloud Ruff. Native readiness,
reuse and sync thread dispatch recheck the private Run guard; preserve STOP in
sandbox normalization/read-before-write; reuse existing drain and native lease
cleanup. Real SQL/Run/LocalSandbox report and full shared SDK chain, deterministic
model only. Source/archive/log/exact resource evidence: native_sandbox_dispatch_fence.
Provider cache workspace/incarnation reuse remains next; no host/process/network
isolation, remote C physical STOP or complete product acceptance claimed.
All M0-M11 parent tasks remain open, activation false, schema fence unchanged.
No deployment/push or local application runtime.


M4 native Local deletion/recreation main checkpoint (2026-10-18): #89 failed
before business execution because the new fixture omitted mandatory ownership
heartbeats; not a product RED. Corrected #90 four passed (23.64s), thirty-file
cloud Ruff. Actual SQL/Run/LocalSandbox report, same-incarnation continuation,
then actual delete_private_thread reservation/cleanup/receipt and same-ID new
incarnation. A restored old sandbox ID cannot recover the removed report.
Existing native cleanup suffices for this main; no production namespace rewrite.
Exact evidence: native_sandbox_recreation_main. Original twelve dispatch cases
unchanged; retain #88 fixed 134-item evidence rather than repeat it. Internal
entry proof only; HTTP/JWT/browser, AIO/provider namespace, crash/revocation during
cleanup, scoped dispatcher/remote C, other revocation domains and all M0-M11
parents remain open. Activation/schema fences unchanged; no deployment or push.
