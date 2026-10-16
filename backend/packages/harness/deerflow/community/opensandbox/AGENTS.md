### Command deadlines

Normalize only `CommandExecError` / `context deadline exceeded` with no numeric
exit to `Exit Code: 124`, preserving output. Transport/missing-code failures and
numeric exits stay unchanged; signal `-1` alone proves no deadline. Test execution
results, not a fake raised `TimeoutError`.

### Lifecycle

Separate closed SDK transports from confirmed termination. Retain failed deletes
by adapter identity; retry only remote-ID management DELETE with a fresh bounded
client bound to the original endpoint/auth. Only success or API 404/410 confirms
termination. Transfer pending ownership atomically with deregistration; stale
callbacks must not retire replacements. Pending remotes count toward capacity.
Reset/shutdown fence admission; started acquire/output-sync workers keep ownership.
Keep shutdown retryable without reopening admission. SDK failures before create
returns a handle and crash recovery remain outside this contract. Details: README.

### Output synchronization

Release mirrors regular outputs to `Paths.sandbox_outputs_dir()` before parking.
Hold the acquire scope serializer and active registry through transfer; never
repool an invalidated/untracked client. Lifecycle tests gate actual downloads.

Base64-encoded NUL frames survive line-oriented SSE. Capture each POSIX pipeline
status. `find` exit 1 permits complete records only after size/framing validation;
failed head/encoder stages and incomplete/oversized listings fail closed. Decode
each filename separately: invalid UTF-8 consumes candidate budget but cannot hide
valid records. Downloads enforce remaining bytes/deadline and close on failure.

Publish an exclusive temporary file atomically; reject traversal and existing
linked destinations. Preflight all accepted records, including beyond transfer
caps, for case-folded/NFC component aliases; skip every ambiguous subtree. Recheck
local aliases before transfer/publication and preserve previous complete copies.
Portable reserved-name checks include superscript COM/LPT digits and console
devices without `PureWindowsPath.is_reserved`. Catch only typed serializer closure
after confirming untracking. Keep sync best effort and retain remotely deleted
files. Test real listing shell and release-to-Gateway reader offline.
