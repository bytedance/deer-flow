# Tavily tools

The client helper selects credentials by tool name: search defaults to
`web_search`, fetch passes `web_fetch`, and an omitted key uses the SDK's
`TAVILY_API_KEY` fallback. Keep credential regressions in `backend/tests/test_tavily_tools.py`
on the real helper and SDK constructor, mocking only search/extract calls.
