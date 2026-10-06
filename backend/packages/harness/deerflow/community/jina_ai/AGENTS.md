# Jina web fetch

Jina opt-in retries stay provider-local: `max_retries=0` preserves one attempt;
`retry_budget_seconds` bounds enabled request sequences and asynchronous backoff
with one asyncio deadline. Only 502/503/504 and connection-establishment failures
retry; cancellation propagates. Backoff ceilings double from 0.5 to 4 seconds.
Each wait caps the ceiling by the remaining budget, then multiplies it by a fresh
uniform random factor from 0.5 to 1.0 to avoid synchronized retries.
Offline coverage: `tests/test_jina_retries.py`.

`max_response_bytes`: null/omitted keeps buffered POST; otherwise positive int
(excluding bool), validated before client creation. Stream `aiter_bytes`, count
content-decoded bytes before text decoding; exact limit passes, excess closes
and returns a body-free terminal Error before extraction, for every status.
Keep one retry loop/deadline and reset the counter per response. Never re-decode
compression or mutate HTTPX internals. Decoder allocations/wire bytes are outside
the cap. Offline transports: `tests/test_jina_response_limit.py`.
