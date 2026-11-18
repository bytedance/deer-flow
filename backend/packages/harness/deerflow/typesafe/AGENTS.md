# TypeSafe client (`deerflow/typesafe/`)

The transport layer for every TypeSafe call: the guardrail risk gate, memory
pre-screening and signal classification. It owns transport, authentication,
retry, the deadline, response parsing and the error taxonomy.
`deerflow/openai_decisions/` reaches a second endpoint through this same client.

## Verify

```bash
cd backend
python -m pytest tests -q -k "typesafe or openai_decisions"
make test-blocking-io
```

## What stays out of this layer

- **Policy belongs to each consumer**: the questions, criteria and thresholds, the
  failure policy, caching and audit. Two consumers with different thresholds
  share one request, so a policy parameter that reaches this layer either merges
  requests that must stay apart or breaks assembly fingerprinting.
- **`sharing_key()` carries the credential fingerprint, the connection settings,
  the input limit and the transport identity.** Policy parameters go in the
  consumer's `release_policy_parameters()`.
- **A client lives for one evaluation.** It has no cache and no pool, and
  `transport_factory` is a factory because httpx closes the transport it was
  given.

## Responses

- **A request-level failure raises `TypeSafeError`, and the consumer decides
  whether to deny or to continue.** A question-level failure is data in
  `AnswerSet.errors_by_question`, so one bad answer does not discard the others.
- **The reply is read with a byte bound and without decoding.** A body with a
  non-identity `Content-Encoding` is refused. An endpoint that returns something
  else cannot be expanded into memory or accepted as a verdict.
- **Deep nesting raises `RecursionError`, not `ValueError`.** Map it into the
  taxonomy.
- **The deadline covers the body read**, not only the headers. The sync path
  checks the budget before each transport read.
- **Build the HTTPX client off the event loop.** On cancellation during setup,
  close the late client on the loop before the cancellation propagates.

## Limits and secrets

- **`max_state_chars` counts characters in every consumer.** `wire_size` reports
  bytes and replaces no limit.
- **A credential never reaches a log, an error message, a policy identity or
  `repr()`.** Only SHA-256 fingerprints are compared.
- **A transport failure is raised without chaining the original exception**, whose
  message can contain the request.
- **A credential that cannot travel as a header value is refused** when the
  connection resolves.
- **The first config layer that sets `api_key` or `api_key_env` decides the
  credential.** A consumer that names an environment variable is not switched to
  another layer's key.

## Dialects

- **A dialect changes two things only**: `TypeSafeClient.provider_label` and
  `TypeSafeConnection.endpoint_path`. An error message then names the service
  that the operator configured.
- **The endpoint path is part of the sharing key and the policy identity**, so two
  dialects behind one gateway never share a request.
- **A dialect adds no threshold, no rubric and no failure policy.** A second copy
  of this client would let the security rules above drift.
