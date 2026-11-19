# Frontend performance remediation — design

## Background

A production-oriented audit identified seventeen performance risks across the
default DeerFlow web deployment. The audit was originally performed against an
older `main`, so this design starts from a source re-audit of
`origin/main@17461ee5` rather than treating the old findings as immutable.

Upstream has already improved three parts of the original report:

- render-facing stream messages are coalesced to an 80 ms budget and the main
  history/live/optimistic merge is memoized;
- processing groups build tool-result and browser-view indexes once instead of
  scanning the group for every tool call;
- binary artifacts are served with `FileResponse`, including byte-range support.

Those changes are preserved. The remaining work is one comprehensive PR made
of independently reviewable commits, with a measurement and regression gate
after each slice.

## Goals

1. Fix every still-reproducible item from the seventeen-item audit rather than
   only the easiest P0 subset.
2. Bound network bytes, client bundle bytes, retained DOM, repeated stream
   computation, animation work, browser-frame copies, artifact preview memory,
   and mock-route filesystem work.
3. Preserve chat ordering, streaming semantics, history pagination, anchored
   scrolling, locale behavior, artifact downloads, Browser Live control, and
   the default Docker/local deployment topology.
4. Add deterministic tests or executable measurements for every fix so later
   changes cannot silently restore the same cost.
5. Deliver the work as one PR whose commits can be reviewed and reverted by
   subsystem.

## Non-goals

- Replacing LangGraph, Streamdown, Nextra, CodeMirror, or the existing query
  layer.
- Changing model, sandbox, agent, or scheduler behavior.
- Optimizing third-party hosted deployments that bypass DeerFlow's bundled
  nginx; the default nginx/Next deployment is the delivery contract here.
- Claiming a performance win from source shape alone. Production build output
  and runtime measurements are required.

## Current finding matrix

| # | Audit topic | Current status on `17461ee5` | Planned disposition |
|---|---|---|---|
| 1 | No explicit gzip/Brotli in bundled nginx | Reproduced | Add portable gzip for compressible static/document responses while excluding SSE and already-compressed media; test the generated nginx config and live headers. |
| 2 | Full-history work on every stream chunk | Partially fixed upstream | Keep the 80 ms render coalescer, then make grouping, usage, and human-input derivation reuse an immutable prefix and recompute only the active tail. Compare incremental results with the existing full derivation in tests. |
| 3 | Loaded message history is not virtualized | Reproduced | Add turn-level dynamic-height windowing with anchored prepend and overscan; keep the active streaming turn mounted. |
| 4 | No component-level code splitting | Reproduced | Lazy-load settings, inactive settings sections, Browser Live, artifact preview/editor, and other interaction-only heavy surfaces. |
| 5 | Docs/blog carry excessive shared dependencies | Needs current production measurement; source risk remains | Establish a fresh route asset baseline, remove workspace-only providers/styles from the root layout, and enforce route budgets. |
| 6 | Root locale cookie makes the whole site dynamic | Reproduced | Make the root layout static; move cookie-aware locale providers to auth/workspace and keep public locale resolution route-owned. |
| 7 | Streaming Markdown repeatedly parses growing text | Reproduced | Align reveal updates to the stream render budget, eliminate the per-animation-frame parse loop, and keep cheap streaming code rendering until the block settles. |
| 8 | Focus can refetch every loaded history page | Reproduced | Disable focus refetch for immutable paged history and explicitly invalidate/refetch on run lifecycle events. |
| 9 | Tool lookup and `steps.indexOf` produce quadratic work | Partially fixed upstream | Preserve the new lookup maps; replace remaining repeated `steps.indexOf(...)` calls with indexed conversion metadata. |
| 10 | Code blocks run and retain two Shiki renders | Reproduced | Lazy-load Shiki and produce one dual-theme CSS-variable rendering, with request/result caching and stale-effect protection. |
| 11 | Below-fold landing case-study images load eagerly | Reproduced | Replace CSS backgrounds with optimized lazy images, correct responsive sizes, and retain the card overlay/hover behavior. |
| 12 | Galaxy and Magic Bento do offscreen/unthrottled work | Reproduced | Pause on invisibility/document hide, honor reduced motion, and coalesce pointer work to one animation frame. |
| 13 | Browser Live uses JSON + base64 + React state per frame | Reproduced | Send JPEGs as binary WebSocket messages, use revocable object URLs, and present only the latest frame per paint. Keep JSON for control metadata. |
| 14 | Text artifact preview reads/renders the full file | Partially fixed upstream | Serve text through range-capable responses, request a bounded preview first, show truncation/load-full affordances, and avoid mounting CodeMirror for oversized previews. |
| 15 | Chat lists render every loaded row in two surfaces | Reproduced | Share normalized query data, virtualize the full chats page, and bound the sidebar to a recent/pinned window with explicit older-chat navigation. |
| 16 | Global styles/translations/background queries are too broad | Reproduced | Scope Markdown/KaTeX/Nextra styles by route, avoid shipping both locale payloads where possible, and mount queries only with their visible feature surface. |
| 17 | Mock API uses synchronous IO and dynamic project tracing | Reproduced | Use async cached reads and a deterministic demo-thread manifest so request handling and output tracing do not scan the project tree. |

## Design

### 1. Reproducible performance baseline and budgets

Add a repository script that builds the production frontend and reports, per
representative route, the transitive first-load JavaScript and CSS from Next's
build manifests. The representative routes are:

- `/`
- `/login`
- `/workspace/chats`
- `/workspace/chats/<fixture-id>`
- `/en/docs`
- `/blog/posts`

The script writes no tracked build artifact. It prints stable JSON plus a human
summary and can compare against a checked-in budget file. Budgets are set only
after the fresh `origin/main` baseline is captured; the PR must improve the
audited routes and may not regress an unrelated route beyond a small explicit
tolerance. A second smoke check starts the production stack and records
`Content-Encoding`, `Cache-Control`, and transferred bytes for HTML, JS, CSS,
JSON, and SSE samples.

Long-thread and large-artifact fixtures provide runtime gates:

- a synthetic history with hundreds of heterogeneous turns;
- a continuously growing Markdown answer with code, math, and citations;
- a multi-megabyte UTF-8 artifact;
- a burst of Browser Live JPEG frames.

Unit tests pin bounded derivation and protocol behavior; browser measurements
record DOM node count, rendered turn count, and frame URL cleanup.

### 2. Delivery, static rendering, and route ownership

The bundled nginx enables gzip for HTML, JavaScript, CSS, JSON, XML, and SVG.
It does not gzip `text/event-stream`, fonts, images, video, archives, or other
already-compressed payloads. Proxy buffering remains disabled for streaming
routes. A config test and a live header smoke test prevent an apparently valid
directive from being placed in the wrong nginx context.

The top-level Next layout becomes request-invariant:

- it owns only document structure, the theme provider, and truly global CSS;
- it does not call `cookies()`;
- Streamdown and KaTeX styles move to the layouts that render rich content;
- landing navigation uses the public default locale, docs derive locale from
  their explicit `[lang]` segment, and blog keeps its own locale selection;
- auth and workspace layouts read the locale cookie and mount `I18nProvider`.

The client provider receives only the selected locale from its server layout
and synchronizes `document.documentElement.lang` when the workspace/auth locale
changes. Translation dictionaries include formatter functions and therefore
cannot cross the React Server Component serialization boundary. The
interactive auth/workspace provider deliberately owns both small dictionaries
so switching language remains immediate, while public landing, docs, and blog
routes resolve one route-owned locale without mounting that provider. This
retains the existing language switch behavior without making public routes
dynamically rendered or putting both dictionaries in every route bundle.

### 3. Bundle boundaries

Interaction-only code must not be reachable from the initial workspace chunk.
The workspace root keeps only a small settings-store listener. The settings
dialog is imported after it opens, and each settings page is imported only when
selected. Browser Live, artifact code/preview tooling, and CodeMirror language
packages are loaded only when their panels and modes are used.

Shiki is loaded through an async highlighter boundary instead of a static
top-level import. One Shiki call emits light and dark token variables in one DOM
tree; theme changes are CSS-only. A bounded cache keys on code, language, line
number mode, and highlighter configuration. Effects ignore stale resolutions
when code changes or the component unmounts.

The baseline script verifies that docs/blog no longer inherit workspace-only
chunks and that a closed settings/artifact/browser surface contributes no
interaction-only chunk to initial workspace loading.

### 4. Bounded chat rendering and derivation

Message virtualization happens at the existing `ThreadMessageGroup` boundary,
not individual tool steps. A small headless `@tanstack/react-virtual` adapter
owns dynamic measurements, overscan, and stable identity keys while the
existing conversation component remains the scroll owner. The newest streaming
group is always in the render window. Prepending an older history page
preserves the visual anchor; bottom-follow behavior continues only when the
user was already pinned to the bottom. Selection, edit/regenerate controls,
human-input cards, artifact links, and run-duration anchors remain inside their
current group. A dependency-size comparison is part of the bundle gate; if the
adapter would break the workspace route budget, the same interface is
implemented locally rather than accepting an initial-load regression.

Full derivation remains the reference algorithm. A new incremental adapter
stores the settled group prefix and recomputes only from the earliest message
whose identity/content/run metadata changed. Tests feed append, in-place stream
mutation, tool result, reasoning, history prepend, checkpoint replacement,
summarization bridge, edit/regenerate, and hidden human-input sequences through
both algorithms and require identical groups.

Turn usage, run-duration anchors, workspace-change anchors, and human-input
state use the same stable-prefix boundary or keyed indexes. The active tail may
change every 80 ms, but historical turns are not rescanned. Remaining
`steps.indexOf(...)` calls are removed by attaching the index while steps are
created.

Paged history uses `refetchOnWindowFocus: false` and a nonzero stale window.
Run finish, stop, regenerate, edit-and-regenerate, and explicit refresh remain
authoritative invalidation points.

### 5. Streaming Markdown

The SDK/coalescer's 80 ms snapshot is the upper-frequency source of renderable
content. The current smooth-reveal hook must not turn one snapshot into a new
full Markdown parse on every animation frame. It will reveal at the same bounded
cadence (or render the coalesced snapshot directly when the delta is small),
while Streamdown's visual animation handles appearance without creating extra
source strings.

Incomplete code blocks continue to use the cheap streaming `<pre>/<code>`
components. Shiki, Mermaid, and other expensive settled rendering activates
only after the relevant block/turn is stable. DOM tests cover cancellation,
rapid target replacement, incomplete fences/lists, reduced motion, and the
final exact content.

### 6. Landing visuals

Case-study cards use `next/image` with `fill`, responsive `sizes`, and lazy
loading. Only genuinely above-the-fold media can be priority-loaded. Source
images may be re-encoded if doing so materially lowers bytes without visible
quality loss; generated files remain deterministic and are compared in the
route transfer report.

Galaxy owns a visibility state derived from `IntersectionObserver`, document
visibility, and `prefers-reduced-motion`. Its RAF exists only while rendering is
allowed. Magic Bento listens for pointer movement only while its section is
active and coalesces geometry reads/writes to one RAF. Both components cancel
pending work and animations on cleanup. Tests use mocked RAF/observers to prove
that offscreen, hidden, reduced-motion, and unmounted states perform no frames.

### 7. Browser Live binary frame path

Browser session capture returns JPEG bytes rather than base64 text. The updated
client requests `frame_format=binary` in the WebSocket URL. The gateway keeps
its bounded lossy frame queue and sends frame entries with
`WebSocket.send_bytes`; URL, tab, rejection, and input messages remain JSON
text. Connections without the capability retain the legacy base64 JSON frame
for rolling-deployment compatibility. The new protocol is self-demultiplexing
by WebSocket message type and does not add an extra binary header.

The client treats binary messages as blobs, keeps only the newest pending frame,
and publishes at most one object URL per animation frame. Replaced and unmounted
URLs are revoked. JSON parsing is performed only for text messages. The static
artifact screenshot fallback and all input/control behavior stay unchanged.
Backend tests cover capability negotiation, byte delivery, the legacy fallback,
queue dropping, metadata text frames, auth, and disconnect cleanup; frontend
tests cover coalescing and URL revocation.

### 8. Bounded artifact previews

Active content remains download-only and binary media remains range-streamed.
Regular text artifacts move to a range-capable inline `FileResponse` path. The
frontend initially asks for a fixed byte range and reads response metadata to
distinguish complete from truncated content. It shows file size and a clear
"Load full file" action when truncated; download always returns the original
file.

The 1 MiB preview limit is owned by the frontend, while the shared HTTP Range
contract lets both regular files and bounded archive members honor it. The
preview handles an incomplete UTF-8 tail safely, and tests cover ASCII,
multibyte boundary, empty, exact-limit, oversized, skill-archive, active, and
binary files. Large text opens in the lightweight preview first; CodeMirror is
not instantiated until content is within its safe budget or the user explicitly
loads the full file.

### 9. Conversation lists, queries, and mock data

`useInfiniteThreads` remains the single cache. A shared selector deduplicates
and sorts pages once so the sidebar and chats page do not repeat normalization.
The full chats page uses fixed/dynamic row virtualization. The sidebar renders a
bounded recent window plus all pinned entries, and routes users to the full
page for older conversations instead of silently auto-loading/rendering an
unbounded list.

Channel/provider, scheduler, and other feature queries mount only with their
visible page/panel. Locale payloads are route-scoped: public routes own one
selected locale, while the interactive auth/workspace boundary owns both for
instant switching. Route-scoped CSS is verified in the build manifest rather
than inferred from import location.

Mock route handlers use promise-based filesystem APIs and a cached,
deterministically generated demo-thread manifest. The workspace redirect and
thread search do not call `readdirSync` or dynamically construct project-wide
paths at request time. A manifest consistency test fails if demo fixtures are
added or removed without regeneration.

## Error handling and compatibility

- Performance fallbacks preserve content: a failed lazy import shows the
  existing surface error boundary; a failed bounded preview offers download;
  unsupported binary Browser Live frames fall back to the latest static
  screenshot.
- No user-authored content is moved into `dangerouslySetInnerHTML` beyond the
  existing Shiki output boundary.
- WebSocket auth, origin, and exact thread-owner checks remain before session
  acquisition.
- Range requests do not weaken the active-content download policy or path
  traversal validation.
- Reduced work must not hide persisted history, discard a Browser Live control
  event, or change the final streamed Markdown text.

## Implementation and commit slices

The single PR is implemented in this order:

1. Baseline/budget tooling and failing regression tests.
2. Nginx compression, static root ownership, route CSS/locale split, landing
   image delivery.
3. Lazy bundle boundaries and single-pass Shiki.
4. Incremental chat derivation, history query policy, message/chat
   virtualization, and bounded Markdown cadence.
5. Visibility-aware landing effects and binary Browser Live frames.
6. Range-bounded text artifact previews and async/cached mock data.
7. Documentation, production build comparison, full frontend/backend checks,
   and review fixes.

Each behavior change follows red-green-refactor. Commits remain independently
testable, but the PR description reports the aggregate before/after result and
maps every audit item to its evidence.

## Verification and completion gate

The PR is not complete until all of the following are true:

- every row in the seventeen-item matrix has a code change or current evidence
  proving that no change is required;
- focused unit/DOM/backend tests pass and demonstrate their initial failure;
- `cd frontend && pnpm check`, `pnpm test`, and `pnpm build` pass;
- relevant Playwright suites pass for streaming, history prepend, settings,
  artifacts, and Browser Live;
- backend artifact/browser tests, the blocking-IO gate for changed async code,
  Ruff lint, and format checks pass;
- nginx configuration validation and live compression/SSE smoke checks pass;
- production route asset/transfer budgets pass and the before/after report is
  included in the PR;
- source review, automated review, PR review threads, and CI contain no
  unresolved actionable finding.

An absence of review comments is not sufficient by itself: the final audit must
walk this matrix and attach authoritative evidence for each row.
