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
