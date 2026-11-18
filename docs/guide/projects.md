# Projects

Projects group related conversations under a shared name, instructions, and
document shelf.

A conversation joins a project at creation time (when a project is selected) or
later through the move menu. Runs never modify membership: submitting a message
cannot assign or reassign a conversation. Moving a conversation out of a project
keeps it unassigned until it is explicitly moved again.

Moving a conversation refreshes its header affiliation as well as the project
lists, including when an older metadata request is still in flight.

Projects require the current database tables and columns. A database stamped
`0019_thread_incarnations` from the older 0018-based rollout is rejected at
startup if the project schema is missing. Follow the
[offline database recovery procedure](../../docs/database-forward-revision-recovery.md)
before starting this build against that database.

## Project instructions

Each project stores free-form instructions — background, conventions, and
constraints that apply to every conversation in the project — editable on the
project page's Instructions tab with a live byte counter. When a run starts on
a member thread, the Gateway pins the project's current state once and renders
the instructions as a bounded, request-scoped `<project>` block for that run
only: the block never enters the system prompt or persisted history, and every
new run sees the latest saved instructions. Instructions are capped at
`projects.instructions_max_bytes` UTF-8 bytes (default 8192, range 256–262144);
multi-byte characters count as their UTF-8 byte length. Oversized instructions
are rejected with a `422` at write time and are never silently truncated.

## Project memory

With DeerMem automatic memory enabled, project conversations also accumulate
short project facts in a separate pool (up to 30 facts and 2 KiB of rendered
context). The same extraction call classifies user and project facts; personal
facts keep their existing user scope. Unassigned conversations have no project
pool. Project facts are pinned with the instructions at run start and are used
only inside that project. They are background context, subordinate to explicit
instructions and the current request.

An active project pool keeps the shared extraction call enabled for every
eligible batch, even when the user-memory pre-screen would skip it: that
pre-screen does not assess project facts. Existing project facts also add input
tokens. Turn off automatic extraction in the project's Instructions tab to stop
this project-specific work while retaining its stored facts.

Project writes are best-effort after the user pool commits. If the project write
fails, the batch is consumed so later turns do not replay the paid model call or
the committed user writes. The failure is logged and reported separately as
`project_memory_apply_success: false`; `success` still describes the user-pool
commit. A failed project update is not automatically retried.

The Instructions tab shows these facts below the editor. Delete incorrect or
outdated facts, turn automatic extraction off, or move a fact into instructions.
Turning extraction off preserves existing facts and their injection; deleting
one removes it from subsequent runs. Promotion saves the instruction and removes
the fact atomically; save any pending instruction edits first. User edits fence
already-queued extraction so old results cannot undo them. Archived projects
retain their facts for reading and do not collect new ones.

## Document shelf

Each project has a document shelf for files the whole project shares, managed
from the project page's Documents section:

- **Upload** a file (button or drag-drop, one file per request). Shelf size
  limits reuse `uploads.max_file_size` (default 50 MiB); re-uploading identical
  content returns the existing entry instead of creating a duplicate.
  Oversized uploads return `413`; deduplicated uploads return `200`. Staging
  cleanup failures are logged without replacing these outcomes or a missing,
  foreign, or archived project's `404` response.
  Cancelling a shelf upload discards its partial file after any active disk
  operation finishes; waiting for further upload data remains cancellable.
- **List** entries with name, size, modified time, and provenance (uploaded vs.
  saved from a conversation), and preview or download any entry.
- **Save to project** from a thread file: the read-only conversation-files
  browser below the shelf lists member threads' uploads and outputs, each with
  a Save to project action.
- **Attach to thread**: copy a shelf file into a thread's uploads through the
  normal ingestion pipeline, so the conversation can work with it directly.

New shelf names, including explicit upload `name` and promotion `shelf_name`,
follow ordinary upload filename validation. Names containing NUL, Windows
reserved device names (such as `CON.txt`), or trailing dots are rejected with
`400` before bytes are staged.

On native Windows, the document shelf uses extended-length filesystem paths
so deep workspace directories and long filenames can be uploaded, downloaded,
restored, and purged without enabling the system-wide long-path setting.
Filesystem limits on individual path components still apply.

Runs on member threads also receive a bounded `<documents>` index rendered per
run from the pinned snapshot (capped by `projects.shelf_index_max_entries` and
`projects.shelf_index_max_bytes`), and the agent can page the shelf and read
documents with the `list_project_documents` and `read_project_document` tools.

Document character counts use a bounded, thread-safe cache; concurrent reads
do not serialize full file scans behind its cache lock.

Shelf conversion cleanup failures are logged without replacing the read result
or its original error. Cancelled reads wait for their staging cleanup to finish;
files that cannot be removed remain eligible for the existing retention sweep.

Document summaries are enabled by default for newly uploaded or promoted shelf
files (`projects.summaries_enabled: false` disables generation). Each eligible
file uses a separate best-effort summary call; existing files are not backfilled.
The document shelf remains user-curated.

## Archive read semantics

Archiving a project freezes writes but keeps reads. Threads in an archived
project still run and still receive the project's instructions and shelf index,
and the shelf remains fully readable: listing, preview/download, the
conversation-files browser, and attach-to-thread all keep working. Uploads,
save-to-project, and moving individual shelf files to trash require an active
project, and a trashed document cannot be restored into an archived one.
Deleting an archived project remains allowed and moves its whole shelf to
trash.

## Trash

Deleting a shelf document moves it to trash instead of erasing it: the entry
keeps its bytes and a snapshot of its origin project for
`projects.trash_retention_days` (default 30) before the retention sweep may
purge it permanently. The `/workspace/trash` page — reachable from the project
page's Documents section and the sidebar Projects header — lists trashed
documents with their origin project and remaining retention, with per-entry
Restore and Delete permanently actions plus an Empty trash action that
permanently deletes every document in the trash — immediately, not after the
retention window; the window only bounds how long an entry may sit there
before the retention sweep reclaims it. Restore returns the document to its
origin project, or to a project you pick when the origin is gone or archived;
if the target already holds an identical active file, the entries merge.
Deleting a project moves its entire shelf to trash in the same step.

If the retention configuration cannot be read, automatic cleanup is deferred
and the trash listing remains available. Cleanup resumes with the current
configured retention window once the configuration is readable again.

Permanently deleting read-only documents also works on Windows. A file that is
already missing does not block deletion; other filesystem errors keep the entry
in Trash for retry. Permissions on symlink targets are preserved.
