Scheduler main #123, boundaries #125, HTTP create/list/detail #130 history/thread relations #132 and local-session tool list #136 verified; full Scheduler/M4 acceptance remains open.

Implemented for this once/conversation-origin/fresh main:
- Task create captures current live workspace/user context and pins real origin (and fixed reuse parent when present); context is immutable.
- Task get uses current resource context; background get_internal/due claim independently use original SQL context, with private-parent/live predicates before bounds and again under native locks.
- Foreground scheduled dispatch queues only; background scheduled dispatch and private queued attempt each re-resolve SQL and short-bind original context. Scoped manual tool/HTTP dispatch is integrated and its original-identity/paused main passed #149.
- Occurrence creation uses real ThreadMetaRepository create then pins that returned nonce under original task/parent locks. Existing occurrence sequence/active uniqueness and fair FIFO/owner queue are retained.
- Scoped fair candidate predicate checks original task scope plus candidate four-field snapshot and its private execution parent/nonce before LIMIT. Physical/global/per-user executing counts remain global.
- Server-only typed admission receipt fences canonical task/occurrence/lease/attempt and both cached/idempotent/native Run paths. Run association is atomic with native pending Run creation.
- Actual launch_scheduled_thread_run/start_run -> native snapshot/pool/receiver/graph -> actual on_run_completed -> same-transaction finalization/origin event. Existing NoStart/STOP/report capacity release is retained.
- Scoped recovery scans only exact-bound canonical terminal candidates before LIMIT; it rechecks original SQL and finalizes only known outcomes. Native active, absent, revoked or unknown execution is retained. No Run takeover, orphan requeue, or STOP evidence is invented.
- Scoped event writes and reads carry workspace/origin nonce and private parent checks; legacy rows/joins/ID mutations are NULL-isolated.

Withheld / not accepted:
- HTTP create/list/detail are scoped and verified in #130. Local-session tool listing is verified in #136 and original-session remote main in #139; two original credential boundaries passed in #140, while core management mains passed #146 and note/manual/own-stop main passed #149. HTTP history/thread relations are verified in #132. Current resource reads never renew original execution context.
- HTTP task creation response enrichment is verified in #130; complete tool/UI and lifecycle acceptance remains open.
- Page fresh with no origin and reuse branches have identity handling but no runtime acceptance in this single story.
- Scheduled own-stop main passed #149; scheduled native continuation/transfer with the actual dependency_wait_reconciler passed #151 using deterministic remote MCP IO. Complete physical B/host/recovery acceptance remains open.
- Expired scoped queued work is scanned and explicitly rejected for missing native timeout/NoStart control integration. Unknown/unbound launch recovery remains held.
- Scoped IM is suppressed before reading all owner channel bindings; workspace-qualified binding/outbox delivery is still required.
- Scoped event deletion/full tool/UI/lifecycle and withdrawal/recovery fault acceptance remain required; activation stays false.

One PostgreSQL story: RED #122, GREEN #123 (19.61s). Queued withdrawal and pre-insert lease takeover boundaries passed in #125 (two PostgreSQL cases); no dialect matrix. See `native-scheduler-boundaries-125.json`.

Conversation ToolNode create/fresh → due queue main passed #143 with atomic original parent/token/Run checks. List/create/update/pause/resume/delete mains are open and verified in #146; terminal-between-validation-and-write refusal passed #144. Original nonce/token atomic-window refusals are code-reviewed only. Notes/manual/own-stop main passed #149; complete installed runtime/lifecycle remains unaccepted.

HTTP and remote ToolNode complete management mains passed #146 (two PG stories). Unknown queued accounting retention and stale snapshot pause/delete versus rearm boundaries passed #147. Other unknown fields/races are not inferred. Notes/manual/own-stop deterministic native main passed #149. No physical scheduled execution or full installed lifecycle acceptance is inferred.


### 2026-10-18 — Native Scheduler notes/manual trials/own-stop main (#149)

`deerflow-tenant-execution-m4-sql #149 SUCCESS`: one PostgreSQL business story passed (25.61s), Ruff/67-file formatting passed. #148 first reproduced the explicit withheld-note 503. The same story now executes four real native pool/adopt/ToolNode Runs: meaningful verbatim note turn; strict standalone explicit trial turn creates q1; HTTP repeat reuses q1, pause/resume cancels it, HTTP creates q2; control launches q2 and real own-stop completion pauses the task/emits one origin event; HTTP explicitly trials the paused task again as q3 with exact previous q2 thread, preserving pause and event uniqueness. Total manual launches2, automatic use0, original snapshot/note preserved. Each actual no-sandbox STOP/report releases its reservation.

Manual preflight preserves the caller's status/updated-at confirmation; final queue SQL rechecks it and original source target/token/parent/Run authority. Canonical occurrence trigger controls queue/native admission/launch accounting, retaining paused manual semantics and fast-completion protection. HTTP trigger binds current resource scope. Notes reuse the original management writer fences. Scheduled own-stop is a separate narrow capability verified against canonical SQL task/occurrence/normal Run metadata: pending/running identity may be assembled before execution, but the actual request requires live running worker authority and changes only that occurrence's stop-request field. Normal finalization owns pause/events. It grants no Session eligibility or general task-management authority.

Root reviewed the precise seven-file patch, independently checked terminal, SHA-verified archive and byte-matched nine source files; exact fixture resources absent. Evidence: `docs/tenant-workspaces-evidence/native-scheduler-manual-own-stop-149.json`. No provider/model or physical sandbox acceptance. Own-stop management refusal and manual revocation windows are code-reviewed only; no new boundary matrix. Installed scheduled C→B→C, IM/recovery and remaining full M0–M11 gates stay open; activation false, no deployment/push/local runtime.


### M4 step 33 — installed scheduled dependency continuation (in progress)

- [ ] Install the actual controller NativeDispatchHost dependency_wait_reconciler on ScheduledTaskService, matching Gateway bootstrap. Verify one PostgreSQL story: actual due occurrence → C1 native pool/adopt/graph → real MCP durable task and external-wait receipt → source no-sandbox STOP/report → actual control reconciliation protects the original active occurrence → real result notification/continuation admission → C2 → same occurrence/task completion. Deterministic remote MCP IO is not physical B acceptance.
- [ ] Scope dependency_wait_sources to exact normal native Run/task/occurrence metadata, original live context and private incarnation before returning source locators. A returned source ID is not a launch or publication grant. Preserve existing recovery and finite source receipt handling; do not add a limit that permanently masks later waits.
- [ ] Implement original-authority transfer in the native occurrence repository: workspace/actor → sorted task/execution parents → task → occurrence → deterministic source/continuation Run locks. Verify both normal Runs, immutable original context/owner/thread/nonce and exact metadata, successful uncancelled external-wait source, pending live/open uncancelled continuation and canonical idempotency identity. Repeated exact transfer is idempotent. Only occurrence.run_id and eligible task.last_run_id change; no new occurrence/count/accounting/lease or STOP claim.
- [ ] First run the single business story RED, root-review the precise product patch, then GREEN. Verify installed reconciler actually examines C1, delayed C1 completion cannot overwrite C2, original occurrence/count/goal continuity and repeated notification/control do not relaunch. Freeze source/terminal/cleanup evidence and save a local commit.
- [ ] Subsequent complete-M4 requirements remain: superseded/invalid scoped wait control settlement, real B execution wire/physical lifecycle, installed recovery faults and revoked control cleanup. Unknown/unexamined waits stay retained in this slice; no false terminal, authority renewal or physical STOP inference. Keep remaining M0–M11 and activation gate unchanged.


### 2026-10-18 — Installed Scheduler dependency main (#151)

`deerflow-tenant-execution-m4-sql #151 SUCCESS`: one PostgreSQL story passed (21.58s), Ruff/67-file formatting passed. #150 reached real Scheduler→C1 external wait→no-sandbox STOP/report, then reproduced the scoped source-query refusal; the installed reconciler was never invoked. The same story is now green: the actual host reconciler examines/protects C1, real MCP result notification creates C2, native admission transfers the same occurrence and its last Run association, C2 completes the goal/task with one occurrence/automatic launch/count and one origin event. Late C1 completion cannot overwrite C2; repeated notification/control drain does not add Runs. UI-other cannot change original execution ownership.

The sole product file adds original-live/private/exact normal Run/trigger source locators and scoped transfer under workspace/actor→sorted parents→task→occurrence→sorted Run locks. Transfer checks original immutable context, metadata and canonical dependency idempotency, successful waiting C1 with closed native execution lifetime, and pending live/open C2 with no cancellation/STOP. It changes only occurrence.run_id and eligible task.last_run_id. It does not re-admit a schedule, count another occurrence, renew a lease or infer physical STOP.

Root reviewed the exact patch, independently checked terminal and SHA/three archive source bytes plus exact fixture cleanup. Evidence: `docs/tenant-workspaces-evidence/native-scheduler-installed-dependency-151.json`. MCP service/SQL/notification/native launches are real; graph and remote IO are deterministic. No actual B wire/physical/provider/two-host acceptance. Shared helper extraction preserves existing branches; the three non-scheduled selectors were not rerun. Invalid/unexamined waits remain held and need subsequent control settlement; IM/recovery and full M0–M11 remain open, activation false. No deployment/push/local runtime.


### 2026-10-18 — Existing native goal-replacement settlement (#152)

`deerflow-tenant-execution-m4-sql #152 SUCCESS`: exactly one PostgreSQL business boundary passed (21.57s), Ruff/67-file formatting passed. Product code is unchanged from `3119eddf3`; no new control API was needed. After real installed scheduled C1 wait, no-sandbox STOP/report and actual reconciler protection, a real JWT/CSRF PUT replaces the native goal while ambient UI scope remains other. Control reconciliation settles the old occurrence as interrupted/once task cancelled, retires the old wait and preserves canonical C1's complete SQL row, original launch accounting/count1/automatic1, normal Run/C job identities and the complete replacement goal. A repeat retains exact first-terminal rows and the original silent interrupted-once event baseline.

The same story then completes the actual MCP poll/result/notification path with deterministic remote IO. The result remains stored, the superseded notification becomes dead_letter/notified_version0 without a continuation Run, and the replacement goal/source rows stay unchanged. Native checkpoint-write reservations are legitimate control rows and are excluded from normal-model Run counting.

Root reviewed the exact test, independently checked live terminal, SHA/two source bytes and exact cleanup; backend/app and backend/packages have no product diff. Evidence: `docs/tenant-workspaces-evidence/native-scheduler-goal-replacement-152.json`. This verifies the existing live-original-scope path; member-revoked/private-parent-retired/unknown control settlement and full recovery remain open. No actual B wire/physical/provider/two-host acceptance, no other selectors rerun. Full M0–M11 remains open; activation false, no deployment/push/local runtime.


### 2026-10-18 — Revoked closed Scheduler control main (#154)

`deerflow-tenant-execution-m4-sql #154 SUCCESS`: one PostgreSQL business story passed (21.23s), Ruff/67-file formatting passed. #153 first reproduced an already closed initial C1 remaining running after actual native owner transfer and member removal. The same installed control story now settles its original occurrence as interrupted/once task cancelled, retires only the old ledger wait and writes one control audit. Checkpoint/goal/result/business Run entry points are guarded to fail if called; none were called. Canonical C1, normal Run IDs, execution lifetime, original context/count/accounting, event baseline and parent revoke rows stay unchanged. Repeated control adds no audit or job/physical change.

The SQL sweep selects finite control columns and validates canonical workspace_revoke identity, original task/occurrence/native binding and strict captured-version bounds against locked current member/workspace versions. It changes only derived occurrence/task control state and audit, with no business finalizer/observer/publication. Fresh candidates and historical audit replay use separate keyset pages; exact retired source locators go independently through existing host control reauthorization, outside SQL transactions and outside live checked/valid source sets. Parent revoke and scheduler domain remain pending.

Native terminal status plus completed run_execution lifetime proves logical execution closure, not physical STOP. Existing normal completion has the same logical-before-host-STOP ordering. Physical pool reservations remain exclusively stop_owned/report; this sweep never releases capacity or changes native/physical receipts. Initial active/transferred/unknown native rows stay held.

Root reviewed the precise patch (including a required future-version upper fence), independently checked terminal, SHA/four archive files and exact cleanup. Evidence: `docs/tenant-workspaces-evidence/native-scheduler-revoked-control-154.json`. This runtime proof is closed+report C1 only. Queued explicit NoStart, active/transfer/unknown, pending physical STOP, transport-failure replay and large pagination were not separately tested. Complete revoked/private-parent/account/workspace domains, actual B wire/physical, IM/recovery and M0–M11 remain open. Activation false; no deployment/push/local runtime.


#155 SUCCESS: one PG actual queue story (17.49s), product unchanged from `52446f3f9`. Revoked explicit NoStart retires; accounting None retains every task/occurrence field; no native Run, event, executor job or physical action is added. Repeat is idempotent, parent domains pending. Root verified source/terminal/exact cleanup. Evidence: `docs/tenant-workspaces-evidence/native-scheduler-revoked-queued-control-155.json`. This is one representative unknown boundary, not full domain/physical acceptance. Next prioritize actual B wire/physical continuation main.


Step 37: Shanghai physical #16 verifies real single-host B → scheduled native C2 and fixes captured-space publication; #15 preserves the real RED. See `docs/tenant-workspaces-testing.md` and `docs/tenant-workspaces-evidence/native-scheduler-real-b-physical-16.json`. Shared pool/two-host/C physical and complete M0–M11 remain open.


Step 38 shared-pool main verified by physical #18 (2 passed, 28.00s), after real claim RED #17. Actual B/C share one ledger/budget; pending C2 waits for real B STOP. See `docs/tenant-workspaces-evidence/native-shared-bc-pool-18.json` and canonical testing notes. Required withdrawal/control, CLI/restart and two-host/C physical acceptance remain open.
