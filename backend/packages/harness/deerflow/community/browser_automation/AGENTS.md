### Browser Progress Screenshots

Hidden per-action browser progress frames use JPEG at quality 80 to keep their
storage and transfer cost bounded relative to lossless PNG. The explicit
`browser_screenshot` tool remains PNG because it creates a user-requested
artifact. New automatic capture entry points must reuse the shared progress
encoding definition in `tools.py` so the byte encoding and `.jpg` suffix cannot
drift. `browser_screenshot` never replaces an `outputs/` file: it hard-links
onto the first free `-N` name.

### Session Lifecycle

Contexts own cookies and origin storage: retain a live context after page
closure; rebuild only when the browser disconnects or the context is gone.
Reset `_request_guard_bound` / `_page_listener_bound` only on context replacement.
Await `bring_to_front()` before `_set_active_page()` during managed-page
recovery; CDP sessions preserve user focus and intentionally skip the request guard.
