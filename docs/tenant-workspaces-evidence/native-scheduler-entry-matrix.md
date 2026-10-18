Scheduler main #123, boundaries #125, HTTP create/list/detail #130 history/thread relations #132 and local-session tool list #136 verified; full Scheduler/M4 acceptance remains open.

Implemented for this once/conversation-origin/fresh main:
- Task create captures current live workspace/user context and pins real origin (and fixed reuse parent when present); context is immutable.
- Task get uses current resource context; background get_internal/due claim independently use original SQL context, with private-parent/live predicates before bounds and again under native locks.
- Foreground scheduled dispatch queues only; background scheduled dispatch and private queued attempt each re-resolve SQL and short-bind original context. Scoped manual dispatch stays rejected.
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
- Scheduled own-stop main passed #149; scheduled C->B->C transfer and installed dependency_wait_reconciler path remain withheld. The main uses no async dependency reconciler and does not represent the complete installed host.
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
