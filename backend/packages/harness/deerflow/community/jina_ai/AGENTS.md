# Jina web fetch

Jina opt-in retries stay provider-local: `max_retries=0` preserves one attempt;
`retry_budget_seconds` bounds enabled request sequences and asynchronous backoff
with one asyncio deadline. Only 502/503/504 and connection-establishment failures
retry; cancellation propagates. Backoff ceilings double from 0.5 to 4 seconds.
Each wait caps the ceiling by the remaining budget, then multiplies it by a fresh
uniform random factor from 0.5 to 1.0 to avoid synchronized retries.
Offline coverage: `tests/test_jina_retries.py`.
