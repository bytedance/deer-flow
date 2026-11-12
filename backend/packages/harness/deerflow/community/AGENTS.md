# Community providers (`deerflow/community/`)

Optional search, fetch, knowledge and sandbox providers. The rules here apply to
every provider. A provider directory has its own guide only when it has a trap of
its own.

## Verify

```bash
cd backend
python -m pytest tests -q -k "<provider name>"
make test-blocking-io
```

## Rules for every search and fetch provider

- **Validate a successful response before you normalize it.** A container of the
  wrong type, or a non-empty list that holds no objects, is a format error. A
  missing, null or empty result list is an empty search. Skip non-object entries
  and keep the valid ones in order.
- **Never return the raw payload as a fallback.** It bypasses result-URL
  screening.
- **Screen result URLs with `url_safety.safe_public_result_url`.** Providers
  share this one copy. It is a string check without DNS, so a later downloader
  still enforces the address policy at connection time. Normalize the Unicode dot
  separators of IDNA before the check, and return the original URL for an
  allowed result.
- **A diagnostic names the malformed container and its type.** Queries, URLs,
  credentials and payload values stay out of logs.
- **Resolve API keys through `provider_credentials.resolve_api_key`.**
- **Build the HTTPX client off the event loop.** TLS setup is synchronous.
  Requests and cleanup stay on the loop.
- **Test the real tool through an offline HTTPX transport.** Patch the
  provider's own `httpx` reference and leave the shared `httpx.Client` unchanged.
  A test that mocks the normalizer or the tool's final output proves nothing
  about the boundary.
