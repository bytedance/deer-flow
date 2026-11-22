# Jina web fetch (`deerflow/community/jina_ai/`)

Shared provider rules are in the [community guide](../AGENTS.md). Settings are in
[CONFIGURATION.md](../../../../../docs/CONFIGURATION.md).

```bash
cd backend && python -m pytest tests -q -k "jina"
```

- **Retries are off by default, and one monotonic budget covers attempts and
  waits.** A 429 is retried only with a valid `Retry-After`. Authentication and
  payment errors are terminal. When the server's wait does not fit the budget,
  return the HTTP error.
- **The response limit counts decoded bytes before it keeps a chunk.** A
  response over the limit is closed and returns an error without a body. The
  count resets for each response.
- **`request_admission.py` owns one process-wide policy.** After admission is
  first enabled, every caller reuses the frozen policy until restart. A lease
  covers response stream cleanup. It does not cover retry backoff, idle pool
  close or readability extraction. Cancellation and expiry return the grant.
- **`_CleanupStream` depends on the stream-close ordering of httpx 0.28.** Verify
  it again when HTTPX is upgraded. Cancellation takes precedence over a cleanup
  error.
- **Completion diagnostics classify the code branch, not the error text**, and
  emit enums and numbers only. A logging failure must not change the result or
  swallow a cancellation.
