# Jina web fetch

Retries stay opt-in (`max_retries=0` means one attempt), under one asyncio deadline; cancellation propagates. Retry 502/504 and connection-establishment errors. Retry 503 with a valid `Retry-After` floor or local backoff; retry 429 only with a valid integer-seconds or HTTP-date hint. Never shorten a provider floor. If an HTTP retry wait cannot fit the remaining budget, return that HTTP error without another request. Local backoff ceilings double from 0.5 to 4 seconds with fresh 0.5–1.0 jitter. Tests: `tests/test_jina_retries.py`.
