# Agent teams extension (`examples/deerflow-extension-agent-teams/`)

An installable extension that runs a team of member agents with shared public
state, queued jobs and retained artifacts. The team logic stays in this package.
Limits and field lists are in the code; this file holds the rules that a local
test run does not show.

## Verify

Run the backend plugin tests and the browser check that
[README.md](README.md) documents. The preview fixture uses synthetic
authentication and stays on loopback; it is never a deployed Gateway.

## Boundaries

- **Import only `deerflow_extension_api` and the declared dependencies.** Host
  `app.*` and `deerflow.*` modules are private. Browser code is a native module
  listed in the manifest and has no dependency on the host's React.
- **The extension API version is declared twice**, in the package dependency and
  in the install marker. Raise both together.
- **Never serialize a host capability**, and never expose frozen inputs or resume
  payloads in a read.

## Ownership and trust

- **Every public read and every mutation is owner-scoped.** The cross-owner
  snapshot exists for scheduling only and is never a public read.
- **Identity comes from the Gateway's stamped runtime identity**, not from mention
  text or message content. History and result tools check the owner and a current
  member thread on every read.
- **Sharing a thread does not share a team.**
- **Public state is task data written by members.** It is not verified consensus
  and not a framework instruction. A registered file is not a verified delivery,
  and file content is untrusted.
- **A stale writer must not overwrite a newer edit.** Compare the entry revision
  and write inside the same owner-scoped transaction.
- **Bound the complete serialized response**, including metadata and escaping,
  and measure in UTF-8 bytes. Anchor a cursor to a record ID, and report an
  expired anchor instead of restarting the pagination.

## Admission and scheduling

- **Persist the run input and the idempotency key before admission.** An unknown
  admission outcome keeps ownership of the pending job and stays charged against
  capacity; it is reconciled, not retried.
- **A terminal run alone is not success**, and an interruption is never approved
  automatically. After a restart, only an authenticated action or a native
  mention rebinds a job.
- **A terminal result and its follow-up receipt commit in one SQLite
  transaction**, and so do team data and the pending-jobs projection.
- **Hold the scheduling lock for bookkeeping only**, never across a host call.
  Execution and control mutations take the team-scoped lock.
- **Order within a thread is first unfinished first.** A job that waits for input
  releases its slot and still holds the head of its thread's queue.
- **Persist `resume.started` before you attempt an answer.** Cancelling an answer
  that has not started never admits it.
- **No new work is admitted over an unresolved input request**, whether it is a
  graph interrupt or an ordinary human-input artifact.
- **Reject malformed Unicode before you change a waiting job or admit a run.**

## Artifacts

- **A declaration belongs to the authenticated member's executing job.** Validate
  the host-stamped run identity and its execution key; a frozen queue input is
  not proof of execution.
- **Capture after a successful execution and before the source thread's queue
  head is released.** A snapshot and its ready status commit together.
- **A retry reuses the exact captured version and path.** Do not read a mutable
  source again, and do not overwrite an older version.
- **A file transfer pauses the worker deadline.** Restore the remaining budget
  afterwards, and drain cancellation before you release a host reservation or a
  sandbox lease.
