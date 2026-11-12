# OpenSandbox provider (`deerflow/community/opensandbox/`)

General sandbox rules are in the [sandbox guide](../../sandbox/AGENTS.md).

```bash
cd backend && python -m pytest tests -q -k "opensandbox"
```

Validate `use_server_proxy` and `secure_access` at provider startup. Accept
booleans, default missing or null values to `false`, and reject strings and
other types before creating an SDK connection.

## Command deadlines

- **Only a `CommandExecError` with `context deadline exceeded` and no numeric
  exit code becomes exit code 124.** Partial output is kept. Transport errors and
  numeric exits stay unchanged, and a signal-only `-1` does not prove a deadline.
- **Deadline tests use execution results.** A `TimeoutError` that only a fake
  raises does not test the contract.

## Output synchronization

- **Release mirrors the output files to the host before it parks the client.**
  It holds the same scope serializer as acquire and keeps the active entry during
  the transfer, so reuse and warm reaping cannot overlap it. A client that was
  invalidated or untracked during synchronization is never returned to the pool.
- **The listing is NUL-framed and base64-encoded**, because the event stream is
  line-oriented. The pipeline reports the exit status of every stage, and a
  truncated listing fails closed. Decode each file name on its own, so one
  invalid name does not block the valid ones.
- **Check the whole listing for alias names before any download.** Two names
  that differ only by case or Unicode normalization collide on some hosts. Skip
  every path below an ambiguous component.
- **Publish through an exclusively created temporary file and an atomic
  replace.** Reject path traversal and an existing linked destination.
- **Synchronization is best effort.** A failure keeps the previous complete
  copy, and a file deleted in the sandbox stays on the host.
