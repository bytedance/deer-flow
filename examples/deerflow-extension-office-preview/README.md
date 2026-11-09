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
  a reliable Content-Length. OOXML archives are rejected above 4,000 members or
  100 MiB declared expanded size. Parsing runs in the browser; large or complex
  documents can still be expensive. Download the original for full fidelity.
- Legacy binary `.xls`, `.doc` and `.ppt` files show the download fallback.
- Fit width remains active as the preview panel resizes; manual zoom exits that mode.
  Failed previews offer retry and download. Clipboard failures show a manual-copy hint.
- Find in file offers literal, case-insensitive search, counts, highlighting and
  previous/next matches (Enter / Shift+Enter). Ctrl/Cmd+F focuses it; Escape clears it.
  Excel searches visible cells across visible sheets within the 500-row/50-column
  limit; it searches displayed results rather than formula expressions. Word searches
  rendered text, including styled runs. PPT searches slide text. Images, charts and
  embedded objects are outside the search scope, which the toolbar explains.
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
shadow root isolates presentation styles. Abort/dispose isolates obsolete mounts;
it cannot preempt synchronous third-party parsing.

## Validation

```sh
python -m unittest discover -s examples/deerflow-extension-office-preview/tests
node --test examples/deerflow-extension-office-preview/tests/identifiers.test.mjs
cd frontend
pnpm exec rstest run binary-preview plugin-artifact-preview registry.test catalog.test
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test office-preview-interactions office-preview-navigation --workers=1
PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test word-outline --workers=1
```

The browser regression serves the actual packaged module graph and synthetic Office
files through mocked Gateway APIs. It does not require an LLM. Run browser tests
with a production frontend on the configured port.

See [third-party notices](THIRD_PARTY_NOTICES.md) for renderer attribution.
