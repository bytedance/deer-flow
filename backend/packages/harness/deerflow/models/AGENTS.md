# Models (`deerflow/models/`)

The model factory, the reasoning capability contract, request admission, and the
provider adapters (Claude, Codex, vLLM, MindIE, OpenAI-compatible). The managed
shared-model catalog lives in `config/managed_models.py`. Model fields and their
defaults are in the config models and `config.example.yaml`; see
[the config guide](../config/AGENTS.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "model or provider or codex or claude or mindie or vllm or reasoning or admission"
make test-blocking-io
```

Provider tests drive the public sync and async calls through an offline HTTP
transport, so they check the payload that DeerFlow sends.

## Factory and reasoning

- **`create_chat_model` is the one place a model is built.** The lead agent,
  titles, summarization, subagents and the Gateway probe all call it, so the
  reasoning contract and request admission apply to every caller. A second
  construction path would skip both.
- **A declared `reasoning.effort.path` is the only way effort is serialized.** A
  leftover `reasoning_effort` key on such a profile is rejected, because two
  serializations of one setting can disagree on the wire.
- **Thinking templates add or override keys and never remove one.** The disable
  path treats a null template value as absent, so the native and vLLM fallbacks
  still apply.
- **`aliases` is presentation metadata.** It is stripped before provider kwargs
  are built. An explicit user model choice is authorized as given and is not
  replaced by the default when it is denied.
- **A missing provider module raises an install hint**, not a bare import error.

## Request admission and retries

- **Admission is first-in, first-out across model instances, threads and event
  loops.** Taking a free permit and joining the wait queue are one decision under
  one lock. If they are split, a new caller overtakes an older one.
- **The wait cap is an upper bound.** It must not become a minimum poll interval,
  which would limit throughput at a high request rate.
- **A local `AdmissionError` is never retried**, whatever its message says.
- **A paced model retries in one layer only.** With request admission, the Claude
  and Codex wrappers and the SDK make a single attempt, and middleware retries
  re-enter admission. Log a warning when this lowers a configured attempt count.
  Unpaced models keep their own retry policy.
- **`Retry-After` goes through `utils.retry_after`.** HTTP dates are read as UTC,
  a past date means zero, and the delay is bounded.

## Provider wire rules

- **A non-blank tool-call ID is sent unchanged, byte for byte.** Calls and results
  are paired by that ID. A warning about a repaired ID never includes result
  content.
- **An empty `choices` list becomes `EmptyModelResponseError`** before LangChain
  indexes it. Every OpenAI-compatible adapter keeps `OpenAIEmptyChoicesMixin`.
- **A completed response with null or empty usage keeps its text.**
- **A terminal stream error returns no partial output.** The caller must not take
  a truncated answer for a finished one.
- **Cancelling a Codex async call closes its HTTP stream.** Async generation owns
  an HTTPX async stream, not an executor-backed sync request. Load TLS trust
  off-loop, keep retry sleeps cancellable, and drain the client close across
  repeated cancellation. `test_codex_cancellation.py` observes real loopback EOF
  before fixture release.
- **MindIE requests `stream=False` and simulates streaming**, and its XML tool
  calls and numeric arguments are parsed in the adapter.
- **Claude prompt caching copies before it marks.** The request payload shares
  blocks and tool dicts with the caller, and a `cache_control` marker written in
  place is checkpointed with the thread. Strip stored markers on every request,
  with caching on or off.
- **`thinking` and `redacted_thinking` blocks take no cache marker.** Anthropic
  rejects one there. Keep their content, signature and order, so a later
  breakpoint still covers them.
- **Claude OAuth betas lead any request `betas` and any `anthropic-beta` in
  `extra_headers`.** They sit in the client's default header, but request
  `betas` replace that header and `extra_headers` replace both, and Anthropic
  rejects the Bearer token without `oauth-2025-04-20`. Build a new list and a
  new header dict, because the payload can hold the model's own `betas` and
  `model_kwargs`.

## Credentials

- **CLI credential files are read per model instance**, and models are built
  fresh for each run, so a refreshed login applies to the next run. Read the JSON
  with or without a BOM.

## Managed shared models

- **The catalog is two files**: the encrypted catalog and its generated key, under
  `runtime_home()/managed-models`. A backup or a shared deployment needs both. SQL
  storage does not replicate them. A missing key or an invalid catalog fails
  closed.
- **Managed models are merged after the YAML profiles, and a YAML name wins.** The
  merge happens in `get_app_config()` and `reload_app_config()` only. Runtime-scoped
  and explicitly injected configurations are left as given, and an `AppConfig`
  that was already returned is never mutated.
- **`config/managed_model_providers.py` is the only provider registry.** Do not
  infer an adapter from a substring of the model name.
- **A full update needs the current revision**, and a response reports
  `has_api_key`, never the credential.
- **Only trusted admins create or probe a managed model.** An admin-supplied
  endpoint can address a host on the local network.
