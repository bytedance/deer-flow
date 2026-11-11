# Office file preview

An installable browser contribution for `.xlsx`, `.docx` and `.pptx` files in
DeerFlow's artifact panel and standalone reader. Files stay within the current
authenticated artifact API; no public document viewer or conversion service is used.
Uses the host's optional `artifactPreviews` browser contract. The package is
activated only after operator installation and a Gateway restart.

## Build and install

The package includes its built browser modules. After editing `ui/`, rebuild:

```sh
cd examples/deerflow-extension-office-preview
npm ci --ignore-scripts
npm run build
node notices.mjs
```

From the repository root, check packaging, then install through the extension manager:

```sh
uv run --project backend --no-sync python scripts/check_extension.py examples/deerflow-extension-office-preview
cd backend
uv run deerflow extensions install ../examples/deerflow-extension-office-preview --yes
```

Restart Gateway and refresh the browser. A matching local extension-api and harness
must already be installed in the Gateway environment. The resulting operator-owned
configuration is equivalent to:

```yaml
plugins:
  - use: deerflow_extension_office_preview:install
    enabled: true
    config:
      enabled: true
```

Use `deerflow extensions upgrade SOURCE` after later edits: installs are snapshots.
To disable this contribution, set `config.enabled: false` and restart Gateway.
Other formats retain their built-in preview or download fallback.

## Preview behavior and limits

- Excel: visible worksheet tabs, row/column headers, basic fonts, fills, alignment,
  merged cells, an address jump, a focused cell/formula bar and copying cell values.
  Arrow keys skip hidden rows/columns and merged ranges; sheet tabs support arrow
  keys and Home/End. Selection and scroll restore independently per sheet. Jumping
  inside a visible merged range selects its master cell. At most 500 rows and 50 columns per sheet. Formula results use saved
  workbook caches; formulas are never recalculated. Charts and complex formatting
  are not reproduced. Drawing parts are omitted only from the temporary preview
  copy so workbooks containing charts can still display and search their cells;
  original downloads retain the charts, tables and other workbook content.
- Word: paginated document layout, page navigation and zoom. The page counter follows
  manual scrolling and navigation buttons disable at the first/last page. Advanced Word layout,
  missing fonts and embedded objects can differ from Office.
- PowerPoint: slide navigation with arrows, Page Up/Down and Home/End when the preview
  canvas or its navigation controls are focused, plus zoom and fit width; browser conversion supports
  common text, shapes, images and tables. Paragraph font defaults are materialized
  in a temporary preview copy. Animations, SmartArt and advanced effects can differ
  or be absent. Generated slide HTML uses a sandboxed iframe without scripts or
  external resources.
- All formats: host reads are capped at 25 MiB, including streaming responses without
  a reliable Content-Length. ZIP central/local records, names, member counts, size
  declarations and compression ratios are checked **before** JSZip loads an archive.
  Split/encrypted/ZIP64 archives and inconsistent metadata use the download fallback.
  Limits: 4,000 members, 100 MiB aggregate actual/declared expansion, 16 MiB per member,
  compression ratio 200:1, and 2 MiB per XML part. Sequential streamed inflation also
  checks actual output, so forged size declarations cannot bypass these limits.
- A dedicated Worker validates/prepares each file with a 15-second deadline. Timeout,
  cancellation or disposing the preview terminates the Worker, including synchronous
  parser work. ZIP/XML work, ExcelJS, Word model/outline preparation and PPT conversion
  all run there. The UI receives bounded models rather than Office archives; only display
  data (up to 20 sheets / 100,000 cells in total) reaches the Excel UI. Rows render in
  batches and obsolete sheet renders are discarded. A blocked/unavailable Worker
  fails safely; there is no main-thread parsing fallback.
- XML rejects DTDs, excessive nesting, cyclic/deep Word style inheritance and
  oversized merged ranges. Worker XML budgets are 100,000 elements and 2 MiB text;
  Word/PPT are additionally capped at 20,000 rendered XML elements, 2,000 layout units
  (paragraphs, rows, breaks and shapes), 50 slides and 32 MiB prepared bytes.
  PNG/JPEG images are checked before browser decoding (16 megapixels each, 32 total);
  unsupported media uses the download fallback. Embedded objects are omitted and
  Word does not load embedded fonts. Word parsing uses docx-preview's public API with
  an XML adapter in the Worker; the main thread receives only its plain document model
  and validated image bytes. Headers/footers and images retain their package-relative
  relationships. Image Blob URLs are deduplicated and revoked on abort/disposal.
  PPT receives the same XML adapter through its documented domParserFactory hook.
  Large sparse chart indices and conservative image-reference amplification bounds
  reject small archives that could otherwise produce huge arrays or repeated data URLs.
  Model output is capped at 32 MiB and 100,000 objects before transfer, with 512 KiB
  per converted PPT slide. The UI does not reopen ZIPs or parse Office XML.
  Word's final DOM construction and browser HTML/layout work remain on the main thread.
  These bounded native DOM stages cannot be interrupted by a timer or AbortSignal;
  this is not a hard browser memory
  quota or complete process isolation. Download complex documents for full fidelity.
- Legacy binary `.xls`, `.doc` and `.ppt` files show the download fallback.
- Fit width remains active as the preview panel resizes; manual zoom exits that mode.
  Failed previews offer retry and download. Clipboard failures show a manual-copy hint.
- Find in file offers literal, case-insensitive search, counts, highlighting and
  previous/next matches (Enter / Shift+Enter). Ctrl/Cmd+F focuses it; Escape clears it.
  Excel searches visible cells across visible sheets within the 500-row/50-column
  limit; it searches displayed results rather than formula expressions. Word searches
  rendered text, including styled runs. PPT searches slide text. Images, charts and
  embedded objects are outside the search scope, which the toolbar explains.
  Search counts/navigation/highlights are capped at 2,000 matches to avoid turning
  repetitive text into an unbounded number of DOM nodes or callbacks.
- Word's collapsible outline follows actual OOXML heading levels. Preview bookmarks
  preserve existing names and numeric IDs; a shared allocator indexes reserved IDs
  once and probes each candidate at most once, without Web Crypto or name parsing.
  PowerPoint's
  collapsible thumbnails render only near the navigation viewport and retain the
  same sandbox/CSP restrictions as the main slide.
- Switching files restores worksheet/page, zoom, scroll and navigation visibility
  for unchanged content in the current viewer session. State is in memory, bounded
  by the host, and isolated by account, conversation, renderer and file content hash.

Browser code is trusted deployment code, not an untrusted plugin sandbox. The
shadow root isolates presentation styles. Abort/dispose terminates preparation and
fences obsolete mounts; it cannot preempt the bounded DOM-only conversion stages.
The Worker is bundled without additional module fetches to work with Gateway's
`Content-Security-Policy: sandbox` asset responses, including authenticated deployments.

## Validation

```sh
python -m unittest discover -s examples/deerflow-extension-office-preview/tests
node --test examples/deerflow-extension-office-preview/tests/*.test.mjs
cd frontend
pnpm exec rstest run binary-preview plugin-artifact-preview registry.test catalog.test
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test office-preview-interactions office-preview-navigation --workers=1
PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test word-outline --workers=1
PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test office-preview-resources --workers=1
```

The browser regression serves the actual packaged module graph and synthetic Office
files through mocked Gateway APIs. It does not require an LLM. Run browser tests
with a production frontend on the configured port.
The resource suite uses its own HTTP asset server, needs the extension's locked npm
dependencies (`npm ci --ignore-scripts`) and Chromium, and requires Linux `ps` for
memory measurements. It records sampled process-tree RSS (including Worker/native
allocations), UI heap, long tasks and event-loop gaps in test attachments. Sampled
peaks can miss short-lived allocations and summed RSS includes shared pages; these
are regression measurements, not a proof of an absolute memory bound. Set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to use an installed Chromium executable.

See [third-party notices](THIRD_PARTY_NOTICES.md) for renderer attribution.
