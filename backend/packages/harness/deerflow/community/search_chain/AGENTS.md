# Search chain

`web_search` that tries the bundled Brave, Tavily, Exa, SearXNG and DDG
providers in the configured `providers` order (default
`brave, tavily, exa, searxng, ddg`) and returns the first answer, tagged with
`provider` plus any earlier `attempts`.

- Reuse each provider module's network boundary (`brave._brave_get`,
  `tavily._get_tavily_client`, `exa._build_exa_client`, `SearxngClient`,
  `ddg._search_text`); never copy their HTTP or SDK code here. The adapters
  only map payloads to `{title, url, content}` through `safe_public_result_url`.
- Per-provider settings sit under the provider's name in the tool entry; keys
  fall back to `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`. SearXNG
  needs an explicit `base_url`. Missing credentials are `skipped`, not failures.
- Exceptions, HTTP errors (429 included), `DDGSearchError` and malformed
  payloads are `failed` and fail over. Error text passes through
  `redact_secret` with the provider's configured key.
- A genuine empty result returns "No results found" from that provider unless
  `fallback_on_empty: true`. When nothing answers, the error starts with
  "All web search providers failed" and lists each attempt; it must never read
  "No results found".
- Exa has no `time_range` support and is skipped for recency searches rather
  than returning undated results.
- `max_results` uses `search_max_results.coerce_max_results`; Brave's 20 cap is
  read from the Brave module.

Tests: `tests/test_search_chain_tools.py` (offline; patches only the provider
boundaries above).
