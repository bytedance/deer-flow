# Jina web fetch

Retries default to zero; one monotonic budget covers attempts/waits. Retry 502/503/504 and connect failures; 429 requires valid Retry-After.
Accept ASCII seconds or HTTP dates (also obsolete); past dates floor at zero. Wait max(server floor, budget-capped jittered 0.5–4s backoff); unfit floors
return HTTP errors. Reset hints each attempt; auth/payment errors stay terminal.

`max_response_bytes`: null keeps buffered POST unless admission is enabled.
Positive int, not bool; validate before client creation. Count decoded
`aiter_bytes` before retaining chunks; exact limit passes. Excess closes and
returns a body-free terminal Error before extraction. Reset per
response; never re-decode compression. Decoder/wire bytes are uncapped.

`request_admission.py` owns one immutable process policy. Locked FIFO reserves before loop-safe wakeup. Cancellation/expiry return grants;
leases cover response stream cleanup, never retry backoff, idle client-pool close, or readability. Reuse one client across retries.

`_CleanupStream` wraps every response via an async response hook, before HTTPX reads/closes redirects. It depends on httpx 0.28
stream-close ordering; re-verify on upgrades. Drain stream/client close on cancellation, with cancellation taking precedence over cleanup errors. Null bypasses only before first enablement; afterward all callers reuse the frozen policy until restart.
Config: `backend/docs/CONFIGURATION.md`. Tests:
`tests/test_jina_{client,retries,retry_after,response_limit,request_admission}.py`.
