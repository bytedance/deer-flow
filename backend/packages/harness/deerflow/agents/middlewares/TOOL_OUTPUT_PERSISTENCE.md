# Host tool-output publication

`_externalize` creates a unique sibling `.tool-output-*.tmp` with exclusive
creation (`open(..., "x")`). Its mode is `0o666 & ~umask`, preserving ordinary
file-creation permissions without reading or changing the process-wide umask.
This matters when a mounted sandbox reads the output under a different UID.
Restrictive operator umasks remain restrictive.

The writer closes its file before atomically replacing the deterministic final
path. The last successful publisher wins. Ownership starts only after exclusive
creation succeeds: a collision or creation failure must not remove another
writer's pending file. An observed `OSError` cleans only this invocation's temp
and leaves previously published content intact.

When blob storage is enabled, blob publication follows host publication. If the
blob write fails, that message uses the safety-limited inline fallback and does
not advertise the host path. It also must not unlink the deterministic final
path: a concurrent publisher may already have replaced it and durably
checkpointed that content. Remove published files only as part of inactive
thread-data maintenance.

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
