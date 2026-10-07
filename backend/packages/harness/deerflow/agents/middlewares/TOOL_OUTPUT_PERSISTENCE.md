# Host tool-output publication

Host and sandbox outputs share a filename helper whose fixed-length SHA-256
suffix hashes the raw call ID and UTF-8 content with an explicit ID-length
boundary. Repeating the same call ID and content reuses one path; changed content
or distinct raw IDs use distinct paths, including missing IDs and IDs that would
collide after sanitization. Provider IDs never appear directly in filenames.

For host storage and non-mounted sandboxes, filename hashing stays inside the
write failure boundary. Invalid UTF-8 text or call IDs return `None` before
file publication, allowing the tool wrappers to use the configured inline fallback.

`_externalize` creates a unique sibling `.tool-output-*.tmp` with exclusive
creation (`open(..., "x")`). Its mode is `0o666 & ~umask`, preserving ordinary
file-creation permissions without reading or changing the process-wide umask.
This matters when a mounted sandbox reads the output under a different UID.
Restrictive operator umasks remain restrictive. It also passes `newline=""`, so
the file holds exactly the bytes of the stamped blob ref on every platform;
Windows text mode would write CRLF, and restore discards a file whose size or
digest does not match.

The writer closes its file before atomically replacing the deterministic final
path. Concurrent publishers of identical output can safely reuse that path;
different output retains its own path. Ownership starts only after exclusive
creation succeeds: a collision or creation failure must not remove another
writer's pending file. An observed `OSError` or `UnicodeEncodeError` cleans only
this invocation's temp and leaves previously published content intact.

When blob storage is enabled, blob publication follows host publication. If the
blob encoding or write fails, that message uses the safety-limited inline fallback and does
not advertise the host path. It also must not unlink the deterministic final
path: a concurrent publisher may already have replaced it and durably
checkpointed that content. Remove published files only as part of inactive
thread-data maintenance.

## Structured tool results

`type=json` payloads count toward the configured text budget, including results
that also carry media or other non-text blocks. Externalization saves the full
text/JSON rendering and replaces that portion with a synopsis; other blocks stay
in the result for providers that support them. Historical results use the same
configured fallback. Disabled budgets, raised limits and tool exemptions apply
before provider normalization. Pure text/media results without JSON retain their
existing pass-through behavior.

## Bash exit marker

The subagent executor reads a bash result's exit status only from its end
(`Exit Code: N`, or a whole-output `Command exited with code N`); with no marker
it falls back to `deerflow_tool_meta`, which reports `success` for a nonzero
exit. A model-visible rewrite of a `bash`/`bash_tool` result must therefore keep
the original trailing marker last: the preview re-appends it after the `Access:`
footer, and the storage-unavailable fallback reserves it from `max_chars` like
sandbox truncation. The local marker regex mirrors
`sandbox.tools._BASH_EXIT_MARKER_TAIL_RE` and a test pins them together. The
persisted output is the original bytes; other tools are not rewritten.

## Unclean shutdown

SIGKILL, OOM termination, and host failure bypass exception cleanup and can leave
unique temporary files. There is no automatic stale-temp sweeper. These internal
files are excluded from workspace-change and delivery scans; `keep_recent_writes`
elides model-visible messages and does not prune files.

Remove `.tool-output-*.tmp` leftovers during thread-data maintenance only when all
Gateway processes writing the shared storage are stopped, or when deleting the
corresponding inactive thread's data. Age alone cannot prove a writer is dead,
especially across workers or shared mounts, so publication must not delete other
writers' files based on a TTL.

## Model-bound write elision

`wrap_model_call` elides successful `write_file` content only in model requests
after a later successful same-path `read_file`, `write_file`, or `str_replace`
(#5328); disk remains the reference. `keep_recent_writes` preserves the newest
writes. Use the shared `tool_call_args` helpers (`pair_tool_call_results` and
argument rewriting). Controls: `elide_superseded_writes` and
`superseded_write_min_chars`.
