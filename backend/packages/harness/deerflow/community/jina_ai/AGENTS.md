# Jina web fetch

Retries stay provider-local; default `max_retries=0` sends once. One monotonic
budget bounds requests/waits; cancellation propagates. Retry 502/503/504 and
connection-establishment failures; 429 requires valid Retry-After. Parse ASCII
integer seconds or HTTP dates (including obsolete forms); past dates floor at
zero. Wait max(server floor, existing budget-capped jittered 0.5–4s backoff).
Never reduce server floors; unfit waits return the HTTP error. Reset hints each
attempt. Auth/payment errors stay terminal. Tests: `test_jina_retries.py` and
`test_jina_retry_after.py` (offline, not hosted-provider validation).

`max_response_bytes`: null/omitted keeps buffered POST; otherwise positive int
(excluding bool), validated before client creation. Stream `aiter_bytes`, count
content-decoded bytes before text decoding; exact limit passes, excess closes
and returns a body-free terminal Error before extraction, for every status.
Keep one retry loop/deadline and reset the counter per response. Never re-decode
compression or mutate HTTPX internals. Decoder allocations/wire bytes are outside
the cap. Offline transports: `tests/test_jina_response_limit.py`.
