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

Both tools are coroutines and send their request through `httpx.AsyncClient`. A
sync client would run the whole tool on the default executor and hold one of that
pool's threads for the network round-trip, so several providers queried in parallel
queued behind each other. Resolve the config in the same coroutine, but keep the
config file read off the event loop: the tool body now runs on the loop, so a file
read left in it would block it. `backend/tests/blocking_io/test_groundroute_search_async.py`
pins all three — the request is awaited on the loop thread, the config lookup does
not run there, and the request goes out through the async client. That last one
matters because a `MockTransport` runs its handler on the calling thread without
real blocking I/O, so a provider that stayed async but fell back to a sync client
would satisfy the thread assertion; the anchor records which client factory the
provider reached for.

Both tools resolve the key and `max_results` through `_resolve_tool_settings`, one
config read per call. Do not add a second seam around that read: a wrapper with no
production caller can drift from the real call path.

`web_search` returns the structured `{"error": ..., "query": ...}` response; `web_fetch`
returns the `Error: ...` string. Log the malformed container's type, or that no usable
result objects remain, before returning — never the query, URL, credentials, or payload
values.

`tests/test_groundroute_response_shapes.py` exercises the real tools through an offline
HTTPX transport with synthetic JSON bodies. Patch the provider's `httpx` reference with a
local client factory and `HTTPStatusError`; never replace the shared `httpx.Client`.
Cover both the unchanged global client and HTTP error handling.
