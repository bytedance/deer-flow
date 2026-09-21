### Thread Uploads (`packages/harness/deerflow/uploads/`)

Thread uploads: the files under `/mnt/user-data/uploads` for one thread, written
by the Gateway route, the project-shelf attach route, the IM channels and the
embedded `DeerFlowClient`. `manager.py` holds the rules they share; the callers
must not restate them.

**The uploads directory is sandbox-writable.**

`LocalSandboxProvider` maps `/mnt/user-data` with `read_only=False` and AIO
sandboxes bind-mount it, so anything in there can be replaced between two
statements by a process the thread's own agent controls. Every access therefore
resolves once and acts on that result:

- Writes go through `open_upload_file_no_symlink` / `write_upload_file_no_symlink`
  / `copy_upload_file_no_symlink` (`O_NOFOLLOW`, single-link regular files only).
  `copy_upload_file_no_symlink` also keeps `shutil.copy2`'s contract — content,
  permission bits, timestamps, and `SameFileError` when source and destination
  are the same file — because uploads must stay readable to a sandbox running as
  another uid.
- `delete_file_safe` deletes the requested entry itself and never resolves it
  first; a symlink is reported as not found, matching `list_files_in_dir`.
- Conversion reads the bytes this request wrote, not the committed name: the
  Gateway converts a private copy taken through the descriptor it staged, and
  the client converts the caller's own source file.

**A companion belongs to the document it is named after.**

`companion_markdown_name()` is the only place that derives a converted
document's `.md` name, and it appends to the whole name: `report.pdf` →
`report.pdf.md`, which is what [docs/FILE_UPLOAD.md](../../../../docs/FILE_UPLOAD.md)
documents. Replacing the suffix instead (`report.md`) makes two documents that
share a stem collide, and the collision is then resolved at upload time by a
`_N` suffix that no other site can reconstruct — which is how deleting `a.pdf`
came to remove `a.docx`'s companion and how `a.pdf` came to show `a.docx`'s
outline.

Four sites depend on that name; all four derive it, none guess:
`upload_ingestion.ingest_chunks` and `DeerFlowClient.upload_files` write it,
`delete_file_safe` removes it, `file_outline.extract_outline_for_file` reads it,
and `list_uploaded_files_tool` hides it from listings. The Gateway claims the
name only after the commit settles the document's final name (a collision retry
moves it) and skips the companion when that name is already taken, rather than
writing one under a name the other three cannot derive. Companions written
before this rule (`report.md`) are left alone — they are not deleted on a guess.
