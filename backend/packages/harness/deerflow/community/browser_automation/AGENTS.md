# Browser automation (`deerflow/community/browser_automation/`)

```bash
cd backend && python -m pytest tests -q -k "browser"
```

- **SOCKS DNS runs on a dedicated bounded executor.** The lookups belong to the
  private Playwright loop, and a timed-out lookup must not starve that loop's
  request guard. Keep a permit until its thread exits, reject at capacity and
  propagate ContextVars. Starvation tests keep the Gateway loop and the browser
  loop separate.
- **Automatic progress frames are JPEG, and `browser_screenshot` is PNG.**
  Progress frames are hidden and frequent, so their cost is bounded. The
  screenshot tool creates an artifact the user asked for. A new automatic capture
  path reuses the shared progress encoding in `tools.py`, so the bytes and the
  file suffix cannot drift.
- **`browser_screenshot` never replaces a file in `outputs/`.** It takes the
  first free numbered name.
- **A context owns cookies and origin storage.** Keep a live context after its
  page closes. Rebuild only when the browser disconnects or the context is gone,
  and reset the listener flags only then.
- **During managed-page recovery, bring the page to the front before you mark it
  active.** A CDP session keeps the user's focus and skips the request guard on
  purpose.
