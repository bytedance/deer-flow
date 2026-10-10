# DuckDuckGo Search

`web_search` distinguishes a search that matched nothing from one that never
ran. `_search_text` returns `[]` only for a genuinely empty result set, which
`ddgs` reports as `DDGSException("No results found.")`, and raises
`DDGSearchError` for every execution failure: rate limits, timeouts, blocked
HTML (vqd extraction), SDK errors, and the missing `ddgs` dependency.
`web_search_tool` answers a failure with
`{"error": "DuckDuckGo search failed: <exception type>: <message>", "query": ...}`
and keeps `{"error": "No results found", "query": ...}` for the empty result.
Keep the exception type and message in the error text: `tool_result_meta`
classifies on it, and an outage downgraded to "No results found" reads as
`no_results` (rewrite the query) instead of transient or config recovery.

`tests/test_ddg_search_tools.py` exercises the real tool by patching
`sys.modules["ddgs"]` with a fake `DDGS` whose `text()` raises - never the
normalizer or the tool's final output. Keep the SDK's "No results found."
sentinel mapped back to the empty-search response.
