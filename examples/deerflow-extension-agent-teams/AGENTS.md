# Agent teams extension

Keep team business logic in this independently installable package. Runtime code
imports public `deerflow_extension_api` contracts and its declared LangChain
dependency; do not import host `app.*` or `deerflow.*` internals. Browser code is a
manifest-listed native module with no host React dependency.

Every storage operation is owner-scoped. Native mentions use Gateway's stamped
runtime identity and delegated capability, never an owner from mention content.
Thread sharing is not team sharing. Keep peer content on human-message channels.

Persist run input and idempotency keys before admission. Serialize by thread and
record a terminal result and its follow-up receipt in one SQLite transaction.
Unknown admission outcomes must retain ownership of the pending job. Never
automatically approve interruptions, infer success from a terminal run alone, or
serialize a host capability. Only an authenticated action or native mention
rebinds after restart.

Reconnect ensures every member thread before persisting readiness, serialized
with deletion and task updates. Count only requests toward the 100-request cap;
each request can produce at most one receipt, bounding the ledger to 200 entries.
Browser member labels must remain unique after trimming and truncation to the
backend character/UTF-8 byte limits. Use host theme tokens for action colors.
Validate user-entered team names, goals, tasks and clarification answers against
both backend bounds without truncating the draft. Native mention labels must fit
the host's 120 UTF-16-unit limit; keep routing IDs independent of display labels.

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
