### Model Factory (`packages/harness/deerflow/models/factory.py`)

Request-admission waits follow the next scheduled admission and configured
interval, capped at 50 ms; the cap must not become a minimum poll interval that
limits high-RPM throughput. Local `AdmissionError` is structurally non-retriable
in LLM error handling regardless of its message text.

- `create_chat_model(name, thinking_enabled)` instantiates LLM from config via reflection
- Supports `thinking_enabled` flag with per-model `when_thinking_enabled` overrides
- Supports vLLM-style thinking toggles via `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking` for Qwen reasoning models, while normalizing legacy `thinking` configs for backward compatibility
- A per-request `reasoning_effort` kwarg (the regular, non-bootstrap lead-agent build passes it even when `None`) is popped from `kwargs` and layered like `model_overrides`: a non-`None` value replaces the profile's, and the thinking transforms applied afterwards (`when_thinking_enabled`, `when_thinking_disabled`, the `extra_body.thinking` disable path) still decide the final value. Never let a key reach the constructor through both `kwargs` and the profile settings — Python raises `got multiple values for keyword argument` and the lead agent cannot be built for that model. Codex checks the requested level itself. Pinned by `tests/test_model_factory.py` and `tests/test_lead_agent_model_resolution.py`
- Supports `supports_vision` flag for image understanding models
- Config values starting with `$` resolved as environment variables
- Missing provider modules surface actionable install hints from reflection resolvers (for example `uv add langchain-google-genai`)
- Optional `models[].request_admission` attaches a process-shared `BaseRateLimiter` at the model factory. Identical explicit groups share one FIFO across model instances, threads and event loops; implicit groups use the configured model name. Policies are immutable once registered and conflicting settings fail construction. A monotonic minimum interval spaces requests without idle-time burst credit; bounded waiters poll without occupying executor threads and unregister in `finally`. The factory strips the policy from provider kwargs and sets exposed SDK `max_retries=0` so middleware retries re-enter admission. This limits model invocations, not tokens or a distributed provider account; custom providers bypassing BaseChatModel hooks are outside the contract. Tests: `test_model_request_admission.py`.

### Claude Code Credentials (`packages/harness/deerflow/models/credential_loader.py`)

- `ClaudeChatModel.model_post_init` calls `load_claude_code_credential()` for every instance, and `create_chat_model` builds fresh instances per run (lead agent, title, summarization, subagents)
- `$CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` is a one-shot handoff: a pipe returns EOF and a file keeps its advanced offset. `_read_secret_from_file_descriptor` therefore caches a non-empty secret per `(env_var, fd)` under a lock held across the read. Do not drop the cache or the lock — later instances would get no credential, and the Anthropic SDK raises `TypeError: Could not resolve authentication method` before sending. Empty reads and `OSError` are not cached. The key is the descriptor number on purpose — a closed handoff keeps serving its token, and a secret placed on a recycled number in-process is not re-read unless the cache is cleared. The cache is per process, so a new process (e.g. a uvicorn `--reload` worker) cannot recover a drained descriptor. Pinned by `tests/test_credential_loader.py`, including a two-instance `ClaudeChatModel` test

### vLLM Provider (`packages/harness/deerflow/models/vllm_provider.py`)

- `VllmChatModel` subclasses `langchain_openai:ChatOpenAI` for vLLM 0.19.0 OpenAI-compatible endpoints
- Preserves vLLM's non-standard assistant `reasoning` field on full responses, streaming deltas, and follow-up tool-call turns
- Designed for configs that enable thinking through `extra_body.chat_template_kwargs.enable_thinking` on vLLM 0.19.0 Qwen reasoning models, while accepting the older `thinking` alias
- `cumulative_stream_usage` is an opt-in model setting (default `false`) for endpoints that repeat cumulative token totals on each streaming chunk. The provider converts snapshots to deltas only when a stable completion id is present, isolates interleaved streams by id, and leaves the original usage untouched otherwise. Per-model tracking is lock-protected and cleared on the trailing empty-`choices` frame whether or not that frame carries usage. A soft cap of 1024 ids evicts only entries idle for at least one hour; active streams may temporarily exceed the cap so eviction cannot corrupt their deltas. Regression coverage lives in `tests/test_vllm_provider.py`.
