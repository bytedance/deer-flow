# Tavily tools

The client helper selects credentials by tool name: search defaults to
`web_search`, fetch passes `web_fetch`, and an omitted key uses the SDK's
`TAVILY_API_KEY` fallback. Keep credential regressions in `backend/tests/test_tavily_tools.py`
on the real helper and SDK constructor, mocking only search/extract calls.

Search forwards `include_domains` and `exclude_domains` only when present in
the `web_search` tool config's `model_extra`, alongside `max_results` and optional
`time_range`. Preserve explicit empty lists (no restriction of that kind) and
omit absent keys. These are deployment-only search-source settings; keep the
model-visible signature limited to `query` and `time_range`. Offline regressions
in `backend/tests/test_tavily_tools.py` pin SDK arguments and the tool schema.
For non-empty `include_domains`, explicitly send `include_domains_mode="filter"`
through the SDK's keyword arguments; inclusion must restrict sources rather than
boost them. Omit the mode when the include list is absent or empty.
