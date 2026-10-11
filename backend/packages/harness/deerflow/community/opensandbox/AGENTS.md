### OpenSandbox output synchronization

Release mirrors scoped regular output files to `Paths.sandbox_outputs_dir()`
before parking the client. Hold the same scope serializer as acquire and retain
the active entry during transfer so reuse and warm reaping cannot overlap it.
Never repool a client invalidated or untracked during synchronization.

The bounded listing uses base64-encoded NUL frames to survive line-oriented SSE
events. POSIX pipelines must report every stage's exit status explicitly. Native
downloads enforce the remaining byte budget and cooperative deadline and close
the stream on failure. Publish via an exclusively created temporary file and
atomic replacement; reject traversal and existing linked host destinations.
Keep failed synchronization best effort, preserve prior complete copies, and
do not remove remotely deleted files. Cover the real listing shell and release
to Gateway artifact reader with offline transports in
`tests/test_opensandbox_provider.py`.
Decode each NUL-framed filename separately; invalid UTF-8 records consume the
candidate budget but must not prevent valid outputs from being mirrored.
Portable reserved-name checks include COM/LPT superscript digits and console
device names without `PureWindowsPath.is_reserved`. Catch only the serializer's
typed closure exception after verifying the client has been untracked.
