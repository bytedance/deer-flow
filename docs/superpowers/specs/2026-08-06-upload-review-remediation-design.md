# Upload Review Remediation Design

**Issue:** #3750
**PR:** #4704
**Status:** Approved in conversation; awaiting written-spec confirmation
**Scope:** Findings from the independent review of the collision-safe upload implementation

## Problem

The first implementation prevents two writers from replacing the same destination, but
the filename is still the only identity carried after publication. A delete can therefore
remove a primary while its conversion is running, and a later upload can reuse the same
name before the old conversion publishes. The old conversion then becomes associated with
the new primary.

The review also found six boundary defects: conversion lifecycle I/O can block the event
loop; AIO sandboxes do not mount the generated-conversion namespace; user filenames can
claim the internal staging pattern; staging-link cleanup can report success after a partial
publication; maximum-length primary names overflow the conversion filename component; and
WeChat does not translate every invalid platform filename into its normal attachment
failure path.

## Goals

- Keep one upload generation stable from atomic publication through conversion, chmod,
  sandbox synchronization, response construction, or rollback.
- Coordinate publication and deletion across threads and processes without a database.
- Ensure stale work cannot operate on a later upload that reused the same pathname.
- Keep locks scoped by actual filename so unrelated uploads remain concurrent.
- Make the generated-conversion namespace readable but not writable from mounted sandboxes.
- Keep every synchronous filesystem operation off async event loops.
- Reject internal names and handle cleanup and filename-length boundaries explicitly.

## Non-goals

- Adding a database table or durable upload manifest.
- Serializing every upload in a thread behind one directory-wide lock.
- Changing the public primary-upload listing schema.
- Making conversion failure fail an otherwise successful primary upload.

## Name Lease and Publication Identity

The upload manager introduces two internal values:

- `UploadIdentity`: the published file's device and inode captured immediately after the
  no-replace link succeeds.
- `PublishedUpload`: the actual `Path`, its `UploadIdentity`, and an exclusive name lease.

Name leases use advisory file locks under the system-owned namespace:

```text
user-data/.upload-conversions/.locks/<sha256(actual-filename)>.lock
```

Lock files are stable and are not deleted during normal operation; retaining the same lock
inode avoids split-brain locking between processes. A bounded set of in-process striped
locks complements the OS file lock so threads and processes use the same exclusion rule.
The lock filename is a digest, so platform filenames cannot escape the lock namespace or
exceed a component limit.

### Leased publication

For each candidate name, the publisher performs these operations:

1. Validate the user basename before creating a staging file.
2. Acquire the candidate's name lease.
3. Attempt the existing atomic hard-link no-replace publication.
4. On `EEXIST`, release that candidate lease and try the next suffix.
5. On success, capture the final inode identity and remove the staging link.
6. Return `PublishedUpload` while retaining the final candidate lease.

If staging unlink fails after link creation, the publisher removes only the candidate whose
identity it just created and returns a publication failure. It never reports a half-cleaned
publication as successful. Cleanup closes handles with `try/finally` so an exceptional
close cannot suppress staging unlink.

Compatibility helpers that only need an immediately stable path release the lease before
returning the `Path`. Ingress adapters with post-publication work use the leased form.

### Lifecycle ownership

- Gateway holds each lease through conversion, permission adjustment, remote sandbox sync,
  response assembly, or identity-safe rollback.
- Embedded client holds the lease through conversion and metadata construction.
- Feishu and DingTalk hold it through remote sandbox synchronization.
- Generic IM ingestion and WeChat download staging have no later pathname-dependent side
  effect, so they release immediately after publication.
- Deletion acquires the same actual-name lease before inspecting or unlinking the primary
  and its generated conversion.

Rollback receives `PublishedUpload`, verifies that the current path still has the captured
identity, and removes only that generation. It cannot unlink a later file that reused the
name.

## Conversion and Delete Coordination

The conversion wrapper accepts the active `PublishedUpload`. When no publication is
supplied for a standalone internal caller, it acquires the actual-name lease and treats the
currently locked regular file as the generation to convert.

Conversion runs while the name lease is held. Deletion of that exact primary waits for the
conversion lifecycle to finish, then removes both the primary and its exact generated
asset. Publication of other filenames remains concurrent. This prevents all three unsafe
orders:

- delete during conversion;
- delete followed by same-name re-upload before old conversion publication;
- rollback, chmod, or sandbox sync operating on a later same-name generation.

Conversion remains non-fatal to primary upload success. A conversion exception cleans its
own stage, emits no Markdown metadata, and leaves the primary intact.

## Async Filesystem Boundary

`convert_uploaded_file_to_markdown()` offloads all synchronous lifecycle work: conversion
directory creation and validation, lease acquisition/release, staging creation/close,
identity checks, publication, and cleanup. The underlying converter also offloads file
stat, parsing, and Markdown writes regardless of input size. A strict Blockbuster test
executes the real wrapper with only the document parser substituted.

## Sandbox Visibility

Both Local and AIO providers add an explicit mapping for:

```text
<host user-data>/.upload-conversions -> /mnt/user-data/.upload-conversions
```

The mapping is read-only. AIO creates and validates the source before building the mount.
The nested mapping also overrides Local's writable aggregate `/mnt/user-data` mapping, so
only host conversion code can mutate generated files and lock state.

## Reserved Names and Filename Lengths

Basenames matching `.upload-*.part` are reserved and rejected before staging. This keeps
primary listings and startup cleanup unambiguous.

Normal conversion targets remain `<actual-primary-filename>.md`. If that component would
exceed 255 UTF-8 bytes, the layout helper uses:

```text
<utf8-safe-truncated-primary>.<sha256-prefix>.md
```

The digest makes the shortened mapping deterministic and collision-resistant; all response,
outline, deletion, and virtual-path helpers use the same function rather than appending
`.md` independently.

## WeChat Failure Translation

WeChat validates platform filenames with the shared normalizer before staging. Invalid or
reserved names fall back to its generated safe media name. Any remaining validation error
from the shared publisher is caught and becomes the adapter's existing `None` result, so a
hostile attachment does not abort the whole polling update.

## Tests

Tests are added before implementation and must demonstrate:

1. A paused old conversion cannot publish after delete and same-name re-upload.
2. Delete waits for the leased conversion and removes its exact generated asset.
3. Identity-safe rollback cannot remove a later same-name generation.
4. The real async conversion wrapper passes the strict blocking-I/O gate.
5. Local and AIO mount specifications expose `.upload-conversions` read-only.
6. `.upload-*.part` is rejected before any staging file is created.
7. Injected staging unlink and handle-close failures never report successful publication
   and leave no unintended final entry.
8. Convertible primary names at the 252-255 byte boundary produce valid deterministic
   conversion paths.
9. WeChat overlong, backslash, and reserved filenames use a safe fallback or normal failure
   result without escaping the inbound handler.
10. Existing concurrency, symlink, Gateway, embedded-client, IM, conversion, outline,
    deletion, and sandbox-sync suites remain green.

Final verification is the focused upload/sandbox/channel suite, the full backend test
suite, Ruff lint and format checks, a static ingress audit, and a fresh independent review.
