# Jina web fetch

Jina opt-in retries stay provider-local: `max_retries=0` preserves one attempt;
`retry_budget_seconds` bounds enabled request sequences and asynchronous backoff
with one asyncio deadline. Only 502/503/504 and connection-establishment failures
retry; cancellation propagates. Offline coverage: `tests/test_jina_retries.py`.
