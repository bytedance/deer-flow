# Browser Automation

### Browser Egress Resolution

SOCKS DNS runs on the private Playwright loop. Use a dedicated bounded executor
so timed-out lookups cannot starve that loop's request guard. Retain permits until
threads exit, including after loop shutdown; reject at capacity and propagate
ContextVars. Keep the Gateway and browser loops separate in starvation tests.
See `backend/tests/test_browser_egress.py`.

