# Agent teams extension

Keep team business logic in this independently installable package. Runtime code
imports public `deerflow_extension_api` contracts and its declared LangChain
dependency; do not import host `app.*` or `deerflow.*` internals. Browser code is a
manifest-listed native module with no host React dependency.

Public reads and all team mutations are owner-scoped. The service-only snapshot
spans owners for scheduling bookkeeping and is never exposed as a public read.
Native mentions use Gateway's stamped
runtime identity and delegated capability, never an owner from mention content.
Thread sharing is not team sharing. Keep peer content on human-message channels.
History/result tools require the owner and a current member thread on every read.
Project retained records explicitly; never expose frozen inputs, resume payloads
or host capabilities. Bind cursors to the tool, team and filters, and anchor them
to record IDs, not shifting offsets. Report expired anchors instead of silently
resetting pagination. Bound the complete serialized JSON response, including
metadata and escaping, to 24,000 UTF-8 bytes. Preserve result-truncation provenance;
legacy unknown flags stay null. Queries never reconnect or admit Agent runs.
Hash cursor anchors independently of job-ID syntax. Cancelled jobs have no
available answer; their cancellation notices remain shared history events.

Persist run input and idempotency keys before admission. Serialize by thread and
record a terminal result and its follow-up receipt in one SQLite transaction.
Unknown admission outcomes must retain ownership of the pending job. Never
automatically approve interruptions, infer success from a terminal run alone, or
serialize a host capability. Only an authenticated action or native mention
rebinds after restart.
Use team-scoped locks for every execution/control mutation, including native
mentions; hold the scheduling lock only for snapshot/slot bookkeeping, never for
host calls. Background ticks launch independent team workers and shutdown drains
all workers. Preserve first-unfinished order within each thread, including source
receipts shared across teams; legacy timestamps must not reorder a team's queue.
Rotate new admission attempts by owner, carrying the cursor between passes.
Reserve before dispatch and count in-flight reservations against eight slots.
Terminal jobs and waiting_input jobs release their slots, even if the original
input remains frozen; waiting_input still retains its thread's queue head.
Unfrozen conversation waits also release their temporary reservation. Pending
answers with resume.started=false wait for capacity. Other unfinished frozen
jobs remain charged through disconnection/startup without a capability.
Persist resume.started before attempting an answer,
and keep uncertain admissions charged. Legacy resumes without the marker are
conservatively charged. Cancelling an unstarted answer never admits it.
Maintain the indexed has_pending_jobs projection in the same transaction as team
data, including receipt creation. It tracks all unfinished jobs, not only charged
jobs. Each planning pass uses one batch query; terminal history must not be
parsed and missing keys must not remain in a separate scheduling registry.

Reconnect ensures every member thread before persisting readiness, serialized
with deletion and task updates. Count only requests toward the 100-request cap;
each request can produce at most one receipt, bounding the ledger to 200 entries.
Browser member labels must remain unique after trimming and truncation to the
backend character/UTF-8 byte limits. Use host theme tokens for action colors.
Validate user-entered team names, goals, tasks and clarification answers against
both backend bounds without truncating the draft. Native mention labels must fit
the host's 120 UTF-16-unit limit; keep routing IDs independent of display labels.
Measure string responses as raw UTF-8 and structured interrupt responses as UTF-8
JSON. Reject malformed Unicode before changing a waiting job or admitting a run.

Ordinary human-input artifacts end runs successfully without a graph interrupt.
Keep unanswered requests waiting; persist text-response inputs and idempotency
keys before ordinary admission, and retain their message/run IDs for result
attribution. Graph interrupts still use explicit resume. Do not admit new work
over either unresolved input path. Peer handoffs inherit the first unfinished
source-thread occupant only when it has begun admission and is not waiting for
input; later queued jobs never supply the parent or chain budget.

Run the backend plugin tests and the browser check documented in README.md after
changes. The preview fixture has synthetic authentication and must remain
loopback-only; never use it as a deployed Gateway.
