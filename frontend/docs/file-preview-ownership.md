# File attachments and preview contributions

`workspace/file-type-icon.tsx` and `file-name.tsx` share file identity across selected
uploads, sent attachments and returned artifacts. Keep custom attachment controls
in `workspace/`; generated AI Elements stay unchanged.
`core/uploads/attachment-upload-session.ts` owns per-file state and successful
receipts for one composer, viewer and thread. Retry is upload-only; failed or
cancelled files preserve the draft and prevent sending until resolved or removed.
Keep actionable errors with each failed file. `ArtifactDownloadButton` owns bounded
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
