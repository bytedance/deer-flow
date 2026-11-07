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

Public state is plugin-owned, member-authored task data, not verified consensus
or framework instructions. Stamp creator/editor and source from the authenticated
member thread. Publish with a stable per-member request ID. Compare entry revisions
and write state inside the same owner-scoped transaction; stale writers must not
overwrite newer edits. Preserve the original publication fingerprint after edits.
Project explicit public fields, never internal retry fingerprints. Keep at most
20 current entries (archived entries count), within 16,000 UTF-8 JSON bytes.
Inject active state independently of recent-message retention; bound the complete
shared context to 24,000 bytes, dropping recent messages first. Do not rewrite a
job's frozen input on state changes. Old teams read as empty without writes.

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

The artifact contract requires extension API 0.2.11 in both the package dependency
and install marker; 0.2.10 hosts lack executing Run identity and artifact methods.
Artifact declarations belong to the authenticated member's executing team job.
Use host-stamped run identity and validate its execution key/status before new
registrations; frozen queue input is not execution proof. Persist the active
execution key with the Run, including after resume
acknowledgement clears its pending response. Each bounded file transfer pauses
the ordinary worker deadline; restore its remaining budget afterward and drain
cancellation before releasing host reservations or sandbox leases.
Retried registrations remain readable after completion. Capture checks the previously inspected
checkpoint under the host reservation. Persist import receipts with frozen
input and pass them to first admission; reconcile existing keys before validation.
Stable request IDs deduplicate publication; append numeric versions without
overwriting older snapshots. Capture only after successful execution through
AgentRuns.read_artifact, before releasing the source conversation's queue head.
Keep captured bytes in owner/team-scoped SQLite rows; project explicit metadata,
never registration fingerprints or file bytes in ordinary team reads. Bound
versions to 20/team, four/task, 2 MiB/file and 64 MiB/owner. Snapshots and their
ready status commit together; delete them with their team. Pending attachments
hold conversation order but not an active slot. Import ready retained versions
through AgentRuns.import_artifact before freezing input/admission, using per-job
filenames. Preserve exact versions/paths on retries; never reread mutable sources.
Do not interpret a registered file as verified delivery. File contents remain
untrusted task data. Reads require the owner and a current member; browser
downloads use the owner's authenticated action. Bound list/chunk JSON to 24,000
bytes; offsets follow append-only registration order or immutable file bytes.
