### Shared TypeSafe client

`typesafe/` is the transport layer for every TypeSafe (Jev) call site: the
guardrail risk gate (`guardrails/typesafe.py`), and — once enabled — memory
pre-screening and signal classification. It owns exactly transport and lifecycle,
authentication, retry and backoff, the deadline budget, response parsing and the
error taxonomy, UTF-8 wire-size counting, and the request skeleton. Clients live
for one evaluation: no cache, no connection pool, and `transport_factory` is
always a factory because httpx closes the transport it was handed.

**It must not gain, and no consumer may move into it:** state content, the
questions/criteria/thresholds and which way they decide, the failure policy (the
gate denies on error, the memory paths carry on), cache semantics, or business
audit. Two consumers with different thresholds are expected to share one request,
so policy parameters can never reach this layer — they belong to each consumer's
`release_policy_parameters()`, while `sharing_key()` carries only the credential
fingerprint, the connection settings, the consumer's input limit and the transport
identity. Keeping that split is the whole point: contaminating either identity
either merges requests that must stay apart or breaks assembly fingerprinting.

Two-layer responses are load-bearing. A request-level failure (transport,
deadline, non-200, missing envelope) raises `TypeSafeError` with a `cause`, and
the consumer decides deny / fall back. A question-level failure is **data**
(`AnswerSet.errors_by_question`), never an exception, so one bad answer cannot
discard the other valid answers in the same response; the tool gate maps its own
question's error back to `TypeSafeGuardrailError` because it has no verdict
without it.

Limits and secrets must not move. `max_state_chars` stays a character count in
every consumer — `wire_size` reports bytes and replaces no limit, and one CJK
character is three of them. A credential never reaches a log, an error message, a
policy identity, a reason message or `repr()` (`TypeSafeConnection` hides both the
key and its environment-variable name); only `sha256` fingerprints are compared.
Two rules keep that promise true at the edges: a credential that could not travel
as a header value (surrounding whitespace, a non-printable character) is refused
when the connection resolves, and a transport failure is raised without chaining
the original exception, whose message can contain the request it refused.
Credential resolution is per *layer* too — the first layer that sets `api_key` or
`api_key_env` decides it, and inside one layer the literal key wins — so a
consumer naming an environment variable is never silently switched to another
layer's key. Likewise `base_url` must be an `http(s)` URL with no query, fragment
or embedded credentials, checked at construction rather than on every request.
