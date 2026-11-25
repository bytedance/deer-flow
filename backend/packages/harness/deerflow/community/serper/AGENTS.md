# Serper (`deerflow/community/serper/`)

Shared provider rules are in the [community guide](../AGENTS.md). The operator
contract for domain filters is in
[CONFIGURATION.md](../../../../../docs/CONFIGURATION.md#serper-source-filters).

```bash
cd backend && python -m pytest tests -q -k "serper"
```

Tests mock HTTP. The behavior of the live Serper API is not verified by them.

- **Domain filters select sources. They are not a fetch policy or a factuality
  check.** Google `site:` operators are best-effort, so the local filter on the
  result URL host always runs. A deny entry wins over an allow entry. Do not
  truncate the restrictions, refill filtered results or relax the scope, and
  report the count that remains, including zero.
- **Reject an invalid filter or endpoint before any HTTP call**, and log the
  failure without the configured value or the query.
- **Resolve the endpoint and read the tool config once per call.** Every retry
  reuses the same endpoint, key and payload, also when config or environment
  changes during backoff. This keeps the endpoint and its key paired through a
  hot reload.
- **Send the key only in `X-API-KEY`.** Endpoint diagnostics omit URL
  credentials, query and fragment. The result-URL guard does not restrict the
  operator's API host.
- **Retries are off by default and share one monotonic budget.** The budget
  schedules attempts. It does not cancel synchronous I/O. Retry connect
  failures, 502, 503, 504 and a 429 that carries a hint. Hint parsing is local to
  this provider, so it does not couple to Jina.
