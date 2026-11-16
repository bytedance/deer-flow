# Tavily (`deerflow/community/tavily/`)

Shared provider rules are in the [community guide](../AGENTS.md).

```bash
cd backend && python -m pytest tests -q -k "tavily"
```

- **When no key resolves, pass an empty string to the SDK.** The SDK then never
  reads the raw `TAVILY_API_KEY` variable on its own.
- **Each tool owns its client for one call and closes it in `finally`**, also on
  a request failure and on cancellation.
- **Domain filters are deployment settings from the `web_search` tool config.**
  The model-visible signature stays `query` and `time_range`. An explicit empty
  list means no restriction of that kind and is preserved. An absent key is
  omitted.
- **A non-empty include list sends `include_domains_mode="filter"`**, so that
  inclusion restricts the sources and does not only boost them.
- **Search returns a structured error object and fetch returns an `Error: ...`
  string.**
- **Tests drive the real tools and the real SDK client through an offline
  transport.** A non-object top-level payload needs a stubbed client, because the
  SDK rejects that shape before the tool sees it.
