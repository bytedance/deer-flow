# Jina web fetch

Retries stay provider-local; default `max_retries=0` sends once. One monotonic
budget bounds requests/waits; cancellation propagates. Retry 502/503/504 and
connection-establishment failures; 429 requires valid Retry-After. Parse ASCII
integer seconds or HTTP dates (including obsolete forms); past dates floor at
zero. Wait max(server floor, existing budget-capped jittered 0.5–4s backoff).
Never reduce server floors; unfit waits return the HTTP error. Reset hints each
attempt. Auth/payment errors stay terminal. Tests: `test_jina_retries.py` and
`test_jina_retry_after.py` (offline, not hosted-provider validation).
