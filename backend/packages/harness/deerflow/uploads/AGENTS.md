# Uploads (`deerflow/uploads/`)

Saves uploaded files into the thread's upload directory, converts documents to
Markdown companions, and lists files for the agent. The route, the directory
layout and the limits: [file upload](../../../../docs/FILE_UPLOAD.md). Atomic
write helpers are in the [utils guide](../utils/AGENTS.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "upload"
make test-blocking-io
```

## Publication

- **A new name never replaces an existing upload.** The atomic no-replace link is
  the concurrency boundary. After a lost claim, retry with the next suffix. A
  name that already existed in the first directory snapshot takes a suffix too.
- **A final name exposes a complete copy.** Stage first, then publish.
- **Capture the opened source once, before the retries.** Every attempt reads that
  private capture. Do not reopen the caller's path or the sandbox path, which can
  have changed.
- **Do not copy the permission bits of a snapshot onto the saved upload.**
- **Apply the source timestamps after publication**, so cleanup cannot sweep an
  in-flight copy of an old source.
- **Bind the checks before and after the link to the open staging descriptor.**
  Use a no-follow hard link where the platform supports one. The fallback
  identity check narrows the link-time race and does not remove it.
- **Validate the requested destination before you derive suffixes** from a
  directory snapshot, so an unsafe link still fails.
- **Finish conversion workers before you remove a capture.**
- **A staged `.part` file with more than one link is a published alias** and is
  removed at any age. A lone young `.part` file can be in flight on another
  replica and is kept.

## Companions

- **An existing file name does not prove companion ownership.** Ownership is the
  recorded identity of the source and of the Markdown file.
- **A legacy identity record fails closed.** Do not backfill missing timestamps on
  read; a new upload or conversion registers a new association.
- **The identity check detects ordinary edits only.** A sandbox writer can restore
  timestamps, so it is not a content-integrity guarantee.
- **Publish the ownership record with `cleanup_failed_atomic_write`.** A bare
  `os.unlink` in `finally` replaces the primary error when the unlink fails.

## Listing and cleanup

- **A listing is a best-effort snapshot under concurrent cleanup.** Skip an entry
  that vanished during the scan, and let permission and other operational errors
  propagate.
- **Staging cleanup continues after a scan error**, with a warning. A directory
  that vanished is not an error.
- **Filesystem work in handlers goes through `utils.file_io.run_file_io`**, which
  keeps the request context.
- **Scan a heading's closing markers linearly.** Do not run an unanchored
  whitespace regex on a heading of unbounded length.
