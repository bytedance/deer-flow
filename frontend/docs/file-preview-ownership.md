# File attachments and preview contributions

`workspace/file-type-icon.tsx` and `file-name.tsx` share file identity across selected
uploads, sent attachments and returned artifacts. Keep custom attachment controls
in `workspace/`; generated AI Elements stay unchanged.
`core/uploads/attachment-upload-session.ts` owns per-file state and successful
receipts for one composer, viewer and thread. Retry is upload-only; failed or
cancelled files preserve the draft and prevent sending until resolved or removed.
Keep actionable errors with each failed file. `AttachmentUploadError` carries a
session code and every failed part's original cause; localize session states by
type/code, never by matching diagnostic text. `ArtifactDownloadButton` owns bounded
preparation, duplicate-click prevention, failure feedback and stale-callback fencing.
Browser handoff does not prove a disk write.

Optional `artifactPreviews` contributions use exact lowercase extensions and remain
fenced to enabled registrations for the current viewer. `PluginArtifactPreview` owns
abort/dispose and shadow-root styling; authenticated reads are capped at 25 MiB.
Reload an open preview when the thread run settles. Reading state is bounded JSON in
memory, keyed by viewer, thread, file, renderer and file version (Gateway ETag, or
optional content hash). If neither is available, preview still works without reading
state restoration. Account changes clear it; obsolete mounts cannot write. Built-in
text and media readers retain precedence. The standalone page always owns auth/query
providers, including public Showcase targets; public access is unknown auth, not a
confirmed logout. Office preview works on HTTP LAN origins without Web Crypto.

The Office extension owns a worker per mount. Disposal and the host abort signal
terminate it; a 15-second deadline also terminates stalled preparation. ZIP central
and local records are checked before JSZip, followed by sequential inflation with
actual byte limits, streaming XML complexity checks and raster dimension checks.
ExcelJS, Word XML/model preparation and PPT conversion stay in the worker; the UI
never reopens an Office archive or parses its XML. Word uses docx-preview's public
parseAsync/renderDocument split; a package-local resource facade resolves headers,
footers and validated images, deduplicates Blob URLs and revokes them on abort/dispose.
The pinned XML adapter implements only the namespace/tag selectors the converter
uses and fails explicitly on unsupported selector syntax. Parser output is checked
before structured clone (32 MiB / 100,000 model objects, 512 KiB per PPT slide).
Table rows yield between batches; revision checks fence overlapping sheet changes.
Word's remaining native DOM construction has bounded complexity and no hard timeout;
embedded fonts and alt chunks stay disabled. Worker conversion phases are metadata
only and must never settle a pending request; tests freeze each conversion phase
and verify actual termination on cancellation/deadline.
Build the worker as a self-contained module: Gateway asset CSP sandbox creates an
opaque worker origin, so further authenticated module fetches are unavailable.
`office-preview-resources.spec.ts` exercises real packaged assets with that CSP,
samples process-tree RSS/UI heap, records long tasks/heartbeat gaps, and tests
adversarial XML, stalled conversion phases, cancellation, no main-thread XML parsing,
successful rendering and image/header/footer preservation with Blob URL cleanup.
