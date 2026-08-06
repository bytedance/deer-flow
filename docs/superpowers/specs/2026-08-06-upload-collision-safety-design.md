# Upload Collision Safety Design

**Issue:** #3750
**Status:** Approved
**Scope:** Gateway uploads, embedded client uploads, inbound IM attachments, generated Markdown conversions, outline lookup, and upload deletion

## Problem

Several upload paths avoid duplicate names only within one request or by scanning the
destination directory before writing. The final write is not an atomic no-overwrite
operation. Separate requests or concurrent writers can therefore select the same name
and replace one another.

Generated Markdown conversions are also stored beside user uploads as `<stem>.md`.
This makes ownership ambiguous: converting or deleting `report.pdf` can overwrite or
delete a user-uploaded `report.md`. Outline extraction repeats the same sibling-path
guess.

The fix must provide one collision policy across every ingress path and must never
infer ownership of an existing sibling file from its name.

## Goals

- Preserve every successful upload, including simultaneous uploads with the same name.
- Use the deterministic suffix policy `name.ext`, `name_1.ext`, `name_2.ext`, and so on.
- Publish only fully written files and never replace an existing user upload.
- Give generated conversions a system-owned namespace and deterministic ownership.
- Delete only the primary upload and the conversion owned by that exact upload.
- Return the actual chosen primary and conversion paths from upload APIs.
- Keep legacy ambiguous sibling Markdown files intact.
- Centralize collision, layout, and publication rules so all ingress adapters behave alike.

## Non-goals

- Migrating or deleting legacy `<stem>.md` files whose ownership cannot be proven.
- Adding a persistent database or JSON manifest for upload metadata.
- Changing the public artifact-serving protocol beyond returning the exact generated path.
- Deduplicating files by content.
- Redesigning thread storage or sandbox synchronization.

## Storage Layout

Primary user uploads remain in the existing directory:

```text
<thread>/user-data/uploads/<actual-primary-filename>
```

Generated Markdown is stored outside the primary upload namespace:

```text
<thread>/user-data/.upload-conversions/<actual-primary-filename>.md
```

Examples:

```text
user-data/uploads/report.pdf
user-data/.upload-conversions/report.pdf.md

user-data/uploads/report_1.pdf
user-data/.upload-conversions/report_1.pdf.md

user-data/uploads/report.docx
user-data/.upload-conversions/report.docx.md
```

Including the primary extension in the conversion filename avoids collisions between
`report.pdf` and `report.docx`. Placing conversions outside `uploads/` keeps them out of
the user-upload listing and prevents the upload API from claiming their namespace.

Candidate suffixes are inserted before the final suffix, matching the current naming
behavior: `archive.tar.gz` becomes `archive.tar_1.gz`, a name without an extension becomes
`name_1`, and `.env` becomes `.env_1`.

A small upload-layout module will own construction of physical paths, virtual paths, and
artifact URLs. Callers will not assemble conversion paths or guess sibling names.

## Atomic Publication

All ingress paths use one shared publisher:

1. Normalize and validate the requested basename.
2. Write or copy the complete payload to a hidden staging file in the destination
   directory.
3. Attempt candidates in suffix order: original name, `_1`, `_2`, and so on.
4. Atomically publish the staging inode only if the candidate does not exist.
5. On `EEXIST`, try the next candidate. Other failures are surfaced.
6. Remove the staging file on success or failure.

The publisher uses a same-directory hard link from the completed staging file to the
candidate. Link creation is atomic and cannot replace an existing entry. The staging name
is then unlinked. If the storage backend cannot provide an atomic no-replace primitive,
publication fails explicitly; it must not fall back to scan-then-replace or expose a
partially copied final file. The implementation keeps the primitive behind one helper so
a platform-specific no-replace operation can be added without weakening the contract.

Correctness comes from exclusive atomic publication. Duplicated directory scans and
request-local `seen_filenames` are removed from adapters rather than retained as a second
naming mechanism.

The publisher returns the actual filename chosen. Gateway, embedded client, generic IM,
Feishu, DingTalk, and WeChat download staging all use it instead of implementing their
own scan-then-write flow.

## Conversion Publication and Ownership

After the primary file is published, conversion targets are derived only from its actual
filename. Conversion output is first written to a staging file inside
`.upload-conversions/`, then atomically replaced into the exact system-owned target.

Replacing that target is safe because:

- the target is outside the user-upload namespace;
- each live primary filename is unique;
- the target name contains the full primary filename;
- only the conversion subsystem writes this namespace.

If conversion fails, the primary upload remains successful and the response does not
claim a generated Markdown file. Staging files are cleaned up. A stale generated target
for the same primary may be refreshed, but no user upload is touched.

Outline extraction resolves the generated path through the shared layout module. It does
not fall back to `<stem>.md`, because that would reintroduce ambiguous ownership.

## Deletion

Deleting an upload performs these exact operations:

1. Validate and remove `uploads/<actual-primary-filename>` without following symlinks.
2. Derive and remove `.upload-conversions/<actual-primary-filename>.md`.
3. Do not inspect, infer, or remove `uploads/<stem>.md`.

This policy intentionally preserves legacy sibling Markdown files. They may be user
uploads, and the system has no reliable evidence that they were generated.

## Adapter Behavior

### Gateway API

The multipart stream is written to a staging file and atomically published. The response
uses the chosen primary filename. For convertible files, `markdown_file`,
`markdown_path`, `markdown_virtual_path`, and `markdown_artifact_url` identify the exact
generated file in `.upload-conversions/`.

### Embedded client

Local sources are copied into staging files and use the same publisher and conversion
layout as the Gateway. Repeated calls cannot overwrite an earlier upload.

### Generic IM channels

Downloaded attachment bytes are staged and published by the shared publisher. Correctness
does not depend on a pre-download directory scan, so parallel messages are safe.

### Feishu and DingTalk

Both direct-to-thread adapters use the same publisher and preserve the unresolved upload
directory path so the publisher can reject a planted directory symlink. No process-local
lock or pre-publication directory scan is relied on for correctness.

### WeChat

WeChat first downloads and decrypts inbound media into its channel state directory before
the generic IM ingestion step. This temporary materialization also uses the publisher, so
parallel messages cannot overwrite one another before the thread upload copy occurs.

### Sandbox synchronization

The existing primary upload sync remains unchanged. Generated conversion sync uses its
exact virtual path under `/mnt/user-data/.upload-conversions/`. Mounted providers need no
copy; non-mounted providers sync the exact file explicitly.

## Error Handling

- Invalid or unsafe basenames fail before staging.
- An exhausted or invalid candidate sequence fails without replacing existing files.
- Short writes, interrupted streams, conversion failures, and publication failures clean
  up only staging or reservation files created by that operation.
- A failed cleanup never broadens deletion to guessed sibling paths.
- API results expose only files that were successfully published.

## Compatibility

- Existing primary upload URLs and virtual paths remain unchanged.
- New conversions receive a different virtual path. Responses return the exact path;
  clients must consume it instead of deriving a sibling name. Documentation and tests
  will make this contract explicit.
- Upload listings continue to show only primary uploads.
- Legacy sibling conversions remain readable as ordinary uploads but are not treated as
  generated assets and are never automatically deleted.

## Test Strategy

Tests are written before implementation and cover:

1. Sequential and multi-threaded same-name publication preserves every byte and chooses
   deterministic unique names.
2. Existing files and symlinks are never followed or replaced.
3. Gateway uploads collide safely across separate and concurrent requests.
4. Embedded, generic IM, Feishu, DingTalk, and WeChat ingress paths follow the same naming behavior.
5. Same-stem files with different extensions receive distinct conversion paths.
6. A user-uploaded `report.md` is neither overwritten by converting `report.pdf` nor
   removed when `report.pdf` is deleted.
7. Deletion removes only the exact generated asset; legacy sibling Markdown is preserved.
8. Outline extraction reads the owned generated path and does not guess a sibling.
9. Conversion and publication failures leave no staging files or false response metadata.
10. Existing blocking-I/O and sandbox-sync expectations continue to pass.

Verification includes the focused upload, client, channel, conversion, middleware, and
router suites; concurrent stress cases; the full backend test suite; Ruff lint; and Ruff
format checks.

## Code Boundaries

- A pure upload-layout module owns generated paths and virtual/artifact path mapping.
- The upload manager owns staging, candidate naming, and atomic publication.
- Conversion utilities own conversion content, not upload naming policy.
- Gateway, client, and channel adapters own transport only and consume shared results.
- Deletion and outline lookup consume the same layout helper as creation.

This separation makes collision safety a storage invariant rather than duplicated adapter
behavior.
