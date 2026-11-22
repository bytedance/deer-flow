# DuckDuckGo search (`deerflow/community/ddg_search/`)

Shared provider rules are in the [community guide](../AGENTS.md).

- **A search that matched nothing differs from a search that never ran.** Only
  the SDK's "No results found." exception maps to the empty response. A rate
  limit, a timeout, blocked HTML, an SDK error and a missing `ddgs` package each
  return a structured error.
- **Keep the exception type and message in the error text.** The tool-result
  classifier reads them. An outage reported as "No results found" tells the model
  to rewrite the query, when the right recovery is a retry or a config fix.
- **Client construction stays inside the same `try`**, so a proxy or setup
  failure returns the same structured error.
- **Tests replace `sys.modules["ddgs"]` with a fake SDK** whose constructor or
  `text()` raises. They do not patch the normalizer or the tool output.
