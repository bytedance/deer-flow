### Command deadline reporting

Normalize only `CommandExecError` / `context deadline exceeded` with no numeric
exit code to `Exit Code: 124`, preserving partial output. Keep transport errors,
other missing-code errors and numeric exits unchanged. A signal-only `-1` does
not prove a deadline. Tests must use execution results, not a fake-only raised
`TimeoutError`, for the deadline contract.

### OpenSandbox output synchronization

Release mirrors scoped regular output files to `Paths.sandbox_outputs_dir()`
before parking the client. Hold the same scope serializer as acquire and retain
the active entry during transfer so reuse and warm reaping cannot overlap it.
Never repool a client invalidated or untracked during synchronization.

The bounded listing uses base64-encoded NUL frames to survive line-oriented SSE
events. POSIX pipelines must report every stage's exit status explicitly.
`find` exit 1 permits complete records with a warning only after size/framing
validation; failed head/encoder stages and truncated listings still fail closed.
Native downloads enforce the remaining byte budget and cooperative deadline,
closing the stream on failure. Publish via an exclusively created temporary file and
atomic replacement; reject traversal and existing linked host destinations.
Preflight the entire accepted listing for case-folded, NFC-equivalent component
aliases before any download, including records beyond the transfer cap. Skip all
paths under ambiguous components. Reject differently spelled local aliases both
before transfer and before publication; preserve previous complete copies.
Keep failed synchronization best effort, preserve prior complete copies, and
do not remove remotely deleted files. Cover the real listing shell and release
to Gateway artifact reader with offline transports in
`tests/test_opensandbox_provider.py`.
Decode each NUL-framed filename separately; invalid UTF-8 records consume the
candidate budget but must not prevent valid outputs from being mirrored.
Portable reserved-name checks include COM/LPT superscript digits and console
device names without `PureWindowsPath.is_reserved`. Catch only the serializer's
typed closure exception after verifying the client has been untracked.
