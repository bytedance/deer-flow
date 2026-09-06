# Community Browserless Web Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for code changes. Commit and push steps are intentionally deferred because this local branch must stay uncommitted until user review.

**Goal:** Add an opt-in community `web_capture` tool backed by Browserless `/screenshot` that renders a URL in headless Chrome, saves a PNG/JPEG/WebP screenshot into the current thread outputs directory, and exposes the file as a DeerFlow artifact path.

**Architecture:** Keep the integration inside the existing `deerflow.community.browserless` package. `BrowserlessClient` owns HTTP request construction and binary response handling; `tools.py` owns DeerFlow runtime/config resolution, output filename generation, file persistence, and artifact-state updates. The feature uses existing thread-data outputs semantics rather than inventing a new artifact channel.

**Tech Stack:** Python 3.12, LangChain tool decorators, LangGraph `Command`, `httpx.AsyncClient`, Browserless REST `/screenshot`, pytest.

---

## Technical Design

### User-Facing Tool Contract

Add a new configured tool:

```yaml
tools:
  - name: web_capture
    group: web
    use: deerflow.community.browserless.tools:web_capture_tool
    base_url: http://localhost:3032
    timeout_s: 30
    output_format: png
    full_page: true
    viewport_width: 1280
    viewport_height: 720
    # token: $BROWSERLESS_TOKEN
    # wait_for_selector: main
    # wait_for_selector_timeout_ms: 5000
    # wait_for_timeout_ms: 1000
    # best_attempt: true
```

The model-callable arguments should stay narrow:

```python
async def web_capture_tool(
    runtime: Runtime,
    url: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    filename: str | None = None,
    full_page: bool | None = None,
    output_format: str | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
) -> Command:
```

Behavior:
- Accept only explicit `http://` or `https://` URLs.
- Save the screenshot under `runtime.state["thread_data"]["outputs_path"]`.
- Return a `Command` that appends the virtual artifact path `/mnt/user-data/outputs/<filename>` and a short `ToolMessage`.
- Use tool config defaults when optional callable args are omitted.
- Read Browserless credentials from the configured `token` value or the `BROWSERLESS_TOKEN` environment variable.

### Browserless API Mapping

Official Browserless docs describe `POST /screenshot` with JSON body:

```json
{
  "url": "https://example.com/",
  "options": {
    "fullPage": true,
    "type": "png"
  }
}
```

Browserless returns binary image content with `Content-Type: image/png`, `image/jpeg`, or `image/webp` depending on `options.type`. Shared request fields such as `waitForSelector`, `waitForTimeout`, `bestAttempt`, `gotoOptions`, `rejectResourceTypes`, and `rejectRequestPattern` are top-level fields.

This PR supports:
- `url`
- `options.fullPage`
- `options.type`
- `options.quality` for JPEG/WebP only when configured
- `viewport` from config/callable width and height
- `waitForSelector` from config
- `waitForTimeout` from config
- `bestAttempt` from config

This PR intentionally does not support:
- inline `html`
- `addScriptTag`
- `addStyleTag`
- authenticated profiles
- arbitrary launch parameters
- proxy parameters

Those omitted fields are useful, but exposing them directly to an agent increases the chance of unexpected side effects or credential/session leakage. They can be added later behind explicit config if maintainers want them.

### File and Artifact Boundary

The tool writes to the host-side outputs path that `ThreadDataMiddleware` provides, with filesystem writes offloaded through `asyncio.to_thread`:

```python
thread_data = runtime.state.get("thread_data") or {}
outputs_path = thread_data.get("outputs_path")
```

The final user-facing artifact path is always:

```text
/mnt/user-data/outputs/<safe-filename>.<ext>
```

Filename handling:
- If `filename` is provided, strip directories and normalize it to a safe stem.
- If omitted, derive a readable stem from the URL host/path and append a UTC timestamp.
- Enforce extension from `output_format`.
- Use only ASCII letters, digits, dot, dash, and underscore in the final basename.

### Error Handling

`BrowserlessClient.capture_screenshot()` sends `token` as a query parameter, matching the current Browserless `/screenshot` documentation, and returns a small result object instead of raising expected API/network errors:

```python
@dataclass(frozen=True)
class BrowserlessScreenshotResult:
    content: bytes
    content_type: str
    target_status_code: str
    target_status: str
    final_url: str
```

Expected failures return strings beginning with `Error:` from the client, matching existing `fetch_html()` behavior:
- non-200 Browserless response
- empty image response
- timeout
- request error

The tool converts any error string into a `ToolMessage` and does not mutate artifacts. Unexpected exceptions are logged and returned as `Error: ...`.

### Tests

Use TDD with `backend/tests/test_browserless_client.py`.

Client tests:
- `capture_screenshot` posts to `/screenshot` with `url`, `options.fullPage`, `options.type`, `viewport`, and wait fields.
- Token is sent as the Browserless `token` query parameter.
- Non-200 status returns an error string with status and response snippet.
- Empty binary content returns a clear error.

Tool tests:
- Successful `web_capture_tool` writes bytes to `outputs_path` and returns artifact path in `Command.update["artifacts"]`.
- Tool reads `web_capture` config block, not `web_fetch`.
- Invalid URL is rejected before calling Browserless.
- Missing runtime thread outputs returns a clear error and writes no file.
- Unsafe filename is sanitized to a basename under outputs.

### Documentation Updates

Update:
- `config.example.yaml`: add commented `web_capture` Browserless block.
- `backend/docs/CONFIGURATION.md`: include `web_capture` in tool list and mention Browserless.
- `frontend/src/content/en/harness/tools.mdx`: add Browserless tab for web fetch and a web capture section.
- `frontend/src/content/zh/harness/tools.mdx`: mirror the English documentation.
- `scripts/doctor.py`: recognize `web_capture` and `browserless` token/config status.
- `backend/packages/harness/deerflow/community/browserless/__init__.py`: export `web_capture_tool`.

No `README.md` update is planned because this is a provider-specific opt-in community tool, and existing provider additions in this area document through config/docs pages.

## Execution Tasks

### Task 1: Write Failing Client Tests

**Files:**
- Modify: `backend/tests/test_browserless_client.py`

Steps:
- Add tests for `BrowserlessClient.capture_screenshot()`.
- Run `cd backend && uv run pytest tests/test_browserless_client.py::TestBrowserlessClient -q`.
- Expected red state: `AttributeError: 'BrowserlessClient' object has no attribute 'capture_screenshot'`.

### Task 2: Implement Browserless Screenshot Client

**Files:**
- Modify: `backend/packages/harness/deerflow/community/browserless/browserless_client.py`
- Modify: `backend/tests/test_browserless_client.py`

Steps:
- Add `BrowserlessScreenshotResult`.
- Add `capture_screenshot()` using `httpx.AsyncClient.post(f"{base_url}/screenshot", ...)`.
- Preserve existing `fetch_html()` behavior.
- Run client tests until green.

### Task 3: Write Failing Tool Tests

**Files:**
- Modify: `backend/tests/test_browserless_client.py`

Steps:
- Add tests for `web_capture_tool`.
- Use a fake runtime with `state={"thread_data": {"outputs_path": str(tmp_path)}}`.
- Patch `_get_browserless_client()` and `_get_tool_config()`.
- Run the new tool tests.
- Expected red state: `AttributeError` or missing `web_capture_tool`.

### Task 4: Implement `web_capture_tool`

**Files:**
- Modify: `backend/packages/harness/deerflow/community/browserless/tools.py`
- Modify: `backend/packages/harness/deerflow/community/browserless/__init__.py`

Steps:
- Add helpers for config lookup, URL validation, format validation, filename sanitization, and virtual artifact path generation.
- Add `@tool("web_capture", parse_docstring=True)`.
- Write the screenshot bytes to outputs.
- Return `Command(update={"artifacts": [virtual_path], "messages": [ToolMessage(...)]})`.
- Run Browserless tests until green.

### Task 5: Update Config, Doctor, and Docs

**Files:**
- Modify: `config.example.yaml`
- Modify: `scripts/doctor.py`
- Modify: `backend/docs/CONFIGURATION.md`
- Modify: `frontend/src/content/en/harness/tools.mdx`
- Modify: `frontend/src/content/zh/harness/tools.mdx`

Steps:
- Add commented config block for `web_capture`.
- Extend doctor provider map.
- Update docs with concise config snippets.
- Run targeted tests and lint/format checks.

### Task 6: Verification and Self-Review

Run:

```bash
cd backend && uv run pytest tests/test_browserless_client.py -q
cd backend && uv run ruff check packages/harness/deerflow/community/browserless tests/test_browserless_client.py
cd backend && uv run ruff format --check packages/harness/deerflow/community/browserless tests/test_browserless_client.py
```

Manual review checklist:
- No tracked changes outside the scoped files above.
- No commit created.
- `web_capture` reads the `web_capture` config block.
- Tool does not expose inline HTML, script injection, style injection, or Browserless profile.
- Tool writes only under current thread outputs path.
- Errors do not mutate artifacts.
