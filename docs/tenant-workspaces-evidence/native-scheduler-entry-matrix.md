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
- HTTP create/list/detail are scoped and verified in #130. Local-session tool listing is verified in #136; remote eligibility, management and manual trigger remain withheld. HTTP history/thread relations are verified in #132. Current resource reads never renew original execution context.
- HTTP task creation response enrichment is verified in #130; complete tool/UI and lifecycle acceptance remains open.
- Page fresh with no origin and reuse branches have identity handling but no runtime acceptance in this single story.
- Scheduled C->B->C transfer/own-stop and installed dependency_wait_reconciler path are explicitly withheld. The main uses no async dependency reconciler and does not represent the complete installed host.
- Expired scoped queued work is scanned and explicitly rejected for missing native timeout/NoStart control integration. Unknown/unbound launch recovery remains held.
- Scoped IM is suppressed before reading all owner channel bindings; workspace-qualified binding/outbox delivery is still required.
- Scoped event deletion/full tool/UI/lifecycle and withdrawal/recovery fault acceptance remain required; activation stays false.

One PostgreSQL story: RED #122, GREEN #123 (19.61s). Queued withdrawal and pre-insert lease takeover boundaries passed in #125 (two PostgreSQL cases); no dialect matrix. See `native-scheduler-boundaries-125.json`.
