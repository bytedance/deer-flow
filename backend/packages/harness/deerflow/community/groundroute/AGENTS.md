# GroundRoute

Validate an HTTP-success payload before normalizing it. A top level that is not an
object, a `results` container that is not a list, or a non-empty list whose entries
hold no objects is a format error, not an empty search. Skip non-object entries while
preserving valid objects in order. Missing or null `results` and an empty list keep
"No results found".

`web_fetch` coerces non-string `content` (or its `snippet` fallback) to text before
truncating to the snippet limit, and renders a missing or falsy title as empty, so a
well-formed result object whose leaf fields are not strings still returns text rather
than raising.

`web_search` returns the structured `{"error": ..., "query": ...}` response; `web_fetch`
returns the `Error: ...` string. Log the malformed container's type, or that no usable
result objects remain, before returning — never the query, URL, credentials, or payload
values.

`tests/test_groundroute_response_shapes.py` exercises the real tools through an offline
HTTPX transport with synthetic JSON bodies. Patch the provider's `httpx` reference with a
local client factory and `HTTPStatusError`; never replace the shared `httpx.Client`.
Cover both the unchanged global client and HTTP error handling.
