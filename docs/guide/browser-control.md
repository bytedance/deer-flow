# Agentic Browser Control

Browser screenshots and Browserless captures publish complete content atomically.
New files use the host's normal creation permissions (typically `0644`), and
replacements preserve existing permissions, so sandbox code can read captures
when those permissions allow it.
If saving fails, the original error is preserved even when temporary-file
cleanup also fails; the previous output remains intact.
Cleanup failures are logged with the temporary-file path for troubleshooting.
Logging-handler errors cannot replace the save error or skip remaining cleanup.

Browserless reserves capture names with empty placeholders to prevent concurrent
captures from overwriting one another. Failed publication releases the placeholder;
if cleanup fails, Gateway logs a warning with its path and preserves the original
publication error or interruption.

`browser_screenshot` never replaces an existing `outputs/` file: a taken name
moves to the next free one, such as `report-1.png`.

Browser dependency auto-detection accepts `name`, `group`, and `use` in any
order within a tool entry, with either indented or indentless YAML lists.

Reading a page is not the same as *using* one. Alongside the read-only `web_fetch` and `web_capture` tools, DeerFlow ships an optional agentic browser tool group that keeps a live, per-conversation browser session so the agent can actually operate a page — navigate, read the interactive elements, click, type, submit forms, and follow multi-step flows on JavaScript-heavy sites.

Each action returns a fresh snapshot of the page's interactive elements, each addressed by a stable `[ref]` number, so the agent acts on what it just observed instead of guessing selectors. Outbound URLs are SSRF-screened by default, and the browser's TCP connections go through a local proxy that pins each one to the screened addresses, so a DNS answer that changes after the check cannot redirect them to a private host (WebRTC UDP is not covered). It is powered by Playwright and shipped as an optional extra so the core install stays lean:

```bash
cd backend
uv sync --extra browser
uv run playwright install chromium
```

Then uncomment the `group: browser` tool entries in `config.yaml` (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_back`, `browser_screenshot`, `browser_close`). `make dev` / Docker startup detects an enabled `browser_navigate` tool and preserves the `browser` extra on dependency syncs. The Gateway fails startup if browser control is configured but Playwright is missing, and `/api/features` hides the Browser UI unless the backend can actually serve it. Keep `headless: true` and `allow_private_addresses: false` for anything but local, trusted debugging. Attaching to an existing Chrome with `cdp_url` cannot enforce DeerFlow's subresource/redirect SSRF guard and therefore fails closed unless `allow_unguarded_cdp: true` explicitly acknowledges that risk; use it only with a trusted local browser. Browser sessions are process-local; keep the Gateway to a single worker process while this tool group is enabled because ordinary uvicorn worker dispatch does not provide thread affinity. That means `GATEWAY_WORKERS=1`, and on the launches that pass uvicorn no worker count at all (`backend/Dockerfile`, `scripts/serve.sh`) also `WEB_CONCURRENCY` unset or `1`, since uvicorn takes the process count from it.

Existing, non-mock Custom Agent chats expose the same Browser Live controls when browser control is available and the agent either leaves `tool_groups` unrestricted or includes the `browser` group. An explicit tool-group allowlist without `browser` keeps those controls hidden.

Closing a login popup returns browser control to a surviving tab in the same session, preserving cookies and site storage. If every tab closes, the next browser action opens a tab in that same session. Recovered tabs are brought to the front in DeerFlow-managed browsers; CDP-attached Chrome keeps the user's current tab focus.

The workspace Browser Live client negotiates binary JPEG WebSocket frames,
keeps only the newest pending frame per display refresh, and revokes replaced
object URLs. Gateway control messages remain JSON, and clients that do not
request the binary capability retain the legacy JSON/base64 frame protocol.
Opening a Live connection has a 10-second handshake deadline. A stalled
handshake enters the existing capped backoff, with up to six reconnects;
successful connections reset that retry budget. The panel distinguishes connection
timeouts from other connection failures and shows recovery guidance, including
when retries are exhausted. Turn Live off and on to start a fresh retry budget.
