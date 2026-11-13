# File attachments and previews

## Attachments and downloads

Attachments show individual ready, uploading, uploaded, failed and cancelled states.
Failed uploads retain per-file error details; session-state messages remain localized.
Retry a failed file or remove it before sending again; successful uploads and the
message draft are retained. File cards share format icons and preserve extensions
in long filenames. Sent attachments open in the right-hand artifact panel.
Single-file downloads show preparation and retry feedback while preventing duplicate
requests. Unsupported formats offer the original file for download.
Public Showcase files keep their standalone viewer and download controls available
without requiring sign-in.

Deployments can add binary readers through the optional `artifactPreviews` browser
contribution; see the [plugin contract](../full-stack-plugins.md#artifact-previews).

## Office artifact preview extension

The optional [Office preview package](../../examples/deerflow-extension-office-preview/README.md)
adds read-only XLSX, DOCX and PPTX readers with search, worksheet/page navigation,
Word outlines, PowerPoint thumbnails and per-file reading preferences. It requires
the artifact-preview host contribution and operator installation; it is not enabled
by a catalog entry alone. Legacy binary Office files retain the download fallback.
Previews also work over LAN HTTP. Reading preferences use the file's ETag when
available, with an optional content hash on secure origins; without either, files
still open but reading preferences are not restored.
Office preview validates ZIP metadata before loading, prepares files in a cancellable
Worker with a deadline, and limits XML/layout and image sizes before DOM rendering.
Word XML/model preparation and PPT conversion run in that Worker; the UI receives
bounded models with images and document relationships preserved.
Files exceeding preview budgets retain the original-file download fallback.

See the [Office package guide](../../examples/deerflow-extension-office-preview/README.md)
for installation, supported formats, resource limits and validation commands.
