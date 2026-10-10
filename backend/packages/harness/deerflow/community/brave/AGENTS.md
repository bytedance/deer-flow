# Brave Search

Web search validates the HTTP-success payload before normalizing results:
`web` must be an object and `results` a list when present and non-null.
Reject wrong container types with the shared structured format error, including
falsy values. Skip non-object entries while preserving valid objects in order;
an entirely malformed non-empty list is a format error, not an empty search.
Missing/null containers and an empty results list keep "No results found".
Preserve existing field defaults, query/count parameters, and image-search behavior.
Log the malformed container's path and type, or that no result objects remain,
before returning a format error. Keep queries, credentials, and payload values
out of these diagnostics; ordinary missing/empty results are not format errors.

`tests/test_brave_response_shapes.py` exercises the real tool and `_brave_get`
through an offline HTTPX transport with synthetic JSON bodies. Do not mock the
normalizer or substitute its final output. Patch the provider's `httpx` reference
with a local client factory and `HTTPStatusError`; never replace the shared
`httpx.Client`. Cover both the unchanged global client and HTTP error handling.
