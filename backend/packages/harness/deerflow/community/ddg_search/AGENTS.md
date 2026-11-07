# DuckDuckGo Search

`web_search` distinguishes a search that matched nothing from one that never
ran. `_search_text` returns `[]` only for a genuinely empty result set, which
`ddgs` reports as `DDGSException("No results found.")`, and raises
`DDGSearchError` for every execution failure: rate limits, timeouts, blocked
HTML (vqd extraction), SDK errors, and the missing `ddgs` dependency. Building
the client is part of the boundary too: keep `DDGS(timeout=30)` inside the
`try` so proxy or client-setup failures surface as the same structured error
instead of escaping raw.
`web_search_tool` answers a failure with
`{"error": "DuckDuckGo search failed: <exception type>: <message>", "query": ...}`
and keeps `{"error": "No results found", "query": ...}` for the empty result.
Keep the exception type and message in the error text: `tool_result_meta`
classifies on it, and an outage downgraded to "No results found" reads as
`no_results` (rewrite the query) instead of transient or config recovery.

`tests/test_ddg_search_tools.py` exercises the real tool by patching
`sys.modules["ddgs"]` with a fake `DDGS` whose `__init__` or `text()` raises -
never the normalizer or the tool's final output. Keep the SDK's "No results
found." sentinel mapped back to the empty-search response.


DDG is a best-effort fallback; prefer Brave/Tavily/Exa or SearXNG as primary.
Text calls share one process-wide lock, including SDK iteration, with monotonic
start spacing (`min_interval_seconds`, default 4, range 0–300) plus 0–1s jitter.
Zero disables spacing. Separate Gateway processes do not share this limiter.
LangChain offloads this synchronous tool's `ainvoke` to a worker; keep config,
lock acquisition, sleeps and SDK calls inside that synchronous boundary.
Do not call `_search_text` directly from async code without offloading it.

Rate-limit/202/429/anomaly/CAPTCHA/challenge/blocked/vqd errors, including chained
causes, retry `max_retries` times (default 2, range 0–5), with 1/2/4/8/16s backoff.
Exhaustion raises `DDGSearchError` containing “DuckDuckGo blocked/challenged this
request”; unknown failures are not retried. Preserve the exact empty sentinel
only when its exception chain carries no challenge evidence. DDGS 9.14.1 can
hide upstream failures behind that sentinel; hidden failures cannot be classified.
Pacing covers text searches only, not the separate image-search adapter.
Offline coverage: `tests/test_ddg_pacing.py`, `tests/test_ddg_search_tools.py`,
and `tests/blocking_io/test_ddg_pacing.py` (fake clock and worker-thread checks).
