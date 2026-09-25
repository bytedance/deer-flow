### Model Factory (`packages/harness/deerflow/models/factory.py`)

Request-admission waits follow the next scheduled admission and configured
interval, capped at 50 ms; the cap must not become a minimum poll interval that
limits high-RPM throughput. Local `AdmissionError` is structurally non-retriable
in LLM error handling regardless of its message text. Immediate admission and
joining the blocking FIFO are one lock-protected decision: do not split the
fast-path permit check from queue insertion, or an older caller can be overtaken
while handing off to the wait queue.

- `create_chat_model(name, thinking_enabled)` instantiates LLM from config via reflection
- Supports `thinking_enabled` flag with per-model `when_thinking_enabled` overrides
- Supports vLLM-style thinking toggles via `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking` for Qwen reasoning models, while normalizing legacy `thinking` configs for backward compatibility
- A per-request `reasoning_effort` kwarg (the regular, non-bootstrap lead-agent build passes it even when `None`) is popped from `kwargs` and layered like `model_overrides`: a non-`None` value replaces the profile's, and the thinking transforms applied afterwards (`when_thinking_enabled`, `when_thinking_disabled`, the `extra_body.thinking` disable path) still decide the final value. Never let a key reach the constructor through both `kwargs` and the profile settings — Python raises `got multiple values for keyword argument` and the lead agent cannot be built for that model. Codex checks the requested level itself. Pinned by `tests/test_model_factory.py` and `tests/test_lead_agent_model_resolution.py`
- Supports `supports_vision` flag for image understanding models
- Config values starting with `$` resolved as environment variables
- Missing provider modules surface actionable install hints from reflection resolvers (for example `uv add langchain-google-genai`)
- Optional `models[].request_admission` attaches a process-shared `BaseRateLimiter` at the model factory. Identical explicit groups share one FIFO across model instances, threads and event loops; implicit groups use the configured model name. Policies are immutable once registered and conflicting settings fail construction. A monotonic minimum interval spaces requests without idle-time burst credit; bounded waiters poll without occupying executor threads and unregister in `finally`. The factory strips the policy from provider kwargs and sets exposed SDK `max_retries=0` so middleware retries re-enter admission. This limits model invocations, not tokens or a distributed provider account; custom providers bypassing BaseChatModel hooks are outside the contract. Tests: `test_model_request_admission.py` and `test_model_request_admission_fifo_atomic.py`.

### Reasoning Capability Contract (`packages/harness/deerflow/models/reasoning.py`)

Mapping-valued `ModelConfig.reasoning` (issue #5073) is an optional declarative contract beside
the legacy `supports_thinking` / `supports_reasoning_effort` booleans: thinking
`unsupported | optional | required`, `on_disable_request` (`keep_enabled` or
`reject`, required-thinking only), the payload `dialect` (`auto` infers it from
`when_thinking_enabled`), the reasoning `history` requirement, and an `effort`
vocabulary with `default`, generic-value `aliases`, and a serialization `path`.
A boolean or level-string `reasoning` (`true` / `false`, or `low|medium|high` for
gpt-oss style models) remains a native ChatOllama provider setting; the factory
forwards it on the legacy path, and the assembly descriptor keeps it — like a
declared contract's `dialect` / `history` — inside `model_parameters` so
request-affecting reasoning settings move the fingerprint. When the block is
present the booleans are derived from it and contradictory
profiles fail at config load (`required` + `when_thinking_disabled`, `unsupported`
+ an enable template, a `default` outside `values`, an explicit boolean that
disagrees, an effort value at `effort.path` in the profile or in the
`when_thinking_*` / `thinking` templates that the contract rejects, a `path` that
is not a dotted identifier or would overwrite a whole mapping, or a stale
`reasoning_effort` key beside a custom effort path). The factory strips a
generic effort key from runtime overrides for custom-path contracts. `default` also
governs callers that never choose an effort (summarization, title, subagents), so
shipped profiles keep it below the provider's deepest level.

`resolve_reasoning_contract` turns any profile (legacy or declared) into an
immutable `ReasoningContract`, `resolve_reasoning_request` applies a caller's
generic `thinking_enabled` / `reasoning_effort` to it, and
`reasoning_capabilities_payload` projects it for `/api/models` and
`DeerFlowClient` (`reasoning` object, `source: legacy|contract`).
`create_chat_model` is the single enforcement point for every caller (lead agent,
subagents, summarization, title, one-shot utilities): a required-thinking model
never enters the disable branch, effort is mapped through aliases or the default
and otherwise dropped, and `dialect` synthesizes the on/off payload when no
template exists. Legacy profiles (no mapping-valued `reasoning:` contract) keep the historical path
byte-for-byte, including the synthesized `reasoning_effort=minimal` on the
OpenAI-compatible disable path. The lead agent and the subagent descriptor resolve
the same policy first so run metadata reports the effective values. Design note:
`docs/plans/2026-09-23-reasoning-capability-contract.md`; tests:
`tests/test_reasoning_contract.py`, the contract section of
`tests/test_model_factory.py`, `tests/test_models_router_reasoning.py`.

### Claude Code Credentials (`packages/harness/deerflow/models/credential_loader.py`)

- `ClaudeChatModel.model_post_init` calls `load_claude_code_credential()` for every instance, and `create_chat_model` builds fresh instances per run (lead agent, title, summarization, subagents)
- `$CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` is a one-shot handoff: a pipe returns EOF and a file keeps its advanced offset. `_read_secret_from_file_descriptor` therefore caches a non-empty secret per `(env_var, fd)` under a lock held across the read. Do not drop the cache or the lock — later instances would get no credential, and the Anthropic SDK raises `TypeError: Could not resolve authentication method` before sending. Empty reads and `OSError` are not cached. The key is the descriptor number on purpose — a closed handoff keeps serving its token, and a secret placed on a recycled number in-process is not re-read unless the cache is cleared. The cache is per process, so a new process (e.g. a uvicorn `--reload` worker) cannot recover a drained descriptor. Pinned by `tests/test_credential_loader.py`, including a two-instance `ClaudeChatModel` test

### vLLM Provider (`packages/harness/deerflow/models/vllm_provider.py`)

- `VllmChatModel` subclasses `langchain_openai:ChatOpenAI` for vLLM 0.19.0 OpenAI-compatible endpoints
- Preserves vLLM's non-standard assistant `reasoning` field on full responses, streaming deltas, and follow-up tool-call turns
- Designed for configs that enable thinking through `extra_body.chat_template_kwargs.enable_thinking` on vLLM 0.19.0 Qwen reasoning models, while accepting the older `thinking` alias
- `cumulative_stream_usage` is an opt-in model setting (default `false`) for endpoints that repeat cumulative token totals on each streaming chunk. The provider converts snapshots to deltas only when a stable completion id is present, isolates interleaved streams by id, and leaves the original usage untouched otherwise. Per-model tracking is lock-protected and cleared on the trailing empty-`choices` frame whether or not that frame carries usage. A soft cap of 1024 ids evicts only entries idle for at least one hour; active streams may temporarily exceed the cap so eviction cannot corrupt their deltas. Regression coverage lives in `tests/test_vllm_provider.py`.

### Managed shared models (`config/managed_models.py`)

`ManagedModelStore` persists a Fernet-encrypted catalog plus its generated local key
under `runtime_home()/managed-models`. Files are atomically replaced with temporary
file permissions; complete read/modify/write transactions hold the process lock and
cross-process sidecar lock. Missing keys and invalid catalogs fail closed. Backups
and shared deployments must include both files. SQL storage does not replicate this
catalog. Admin-supplied endpoints can address local providers; only trusted admins
may create or probe them.

`get_app_config()` and `reload_app_config()` merge enabled managed models after YAML
profiles, with YAML names winning conflicts. A cached effective snapshot uses the
base config identity and content signatures of both files. Never mutate a previously
returned AppConfig: runtime-scoped and explicitly injected configurations remain
authoritative. `_managed_model_names` is private source metadata, not provider kwargs.
Direct `AppConfig.from_file()` continues to read only operator configuration.

`config/managed_model_providers.py` owns endpoint detection and provider defaults.
Managed profiles normally use `langchain_openai:ChatOpenAI`. Official HTTPS
`api.deepseek.com` endpoints (default port, root or `/v1` path) instead resolve to
`PatchedChatDeepSeek` with explicit thinking on/off settings and reasoning-effort
support. Resolve from the parsed endpoint, never a model-name substring; proxies,
lookalike hosts and other paths retain the generic contract. This is derived runtime
configuration: no catalog migration or new API fields. The native `api_base` field
preserves the administrator's endpoint; the adapter preserves `reasoning_content`
and sends `max_tokens` rather than OpenAI's `max_completion_tokens`.

Full updates require the current revision; omission means create, an omitted API
key retains the saved key and an empty string clears it. Never serialize SecretStr
masking as a saved key. Read APIs return `has_api_key`, never a credential.
The Gateway probe constructs the resolved class off-loop and applies the profile's
`when_thinking_disabled` settings to its bounded forced-tool request. It does not
repeat provider selection or persist the probe override.
Tests: `test_managed_models.py`, `test_managed_deepseek.py` (real SDK serialization
with an HTTP double), opt-in `test_managed_deepseek_live.py`, and
`tests/blocking_io/test_managed_models.py`.
