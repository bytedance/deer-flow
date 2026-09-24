# Model Provider Reasoning Capability Contract

## Status

Implemented in the `feat-model-provider-reasoning-capability-contract` worktree
for issue #5073, following option 1 from the issue discussion: an optional
structured, mapping-valued `reasoning:` block lives beside the legacy `supports_thinking` /
`supports_reasoning_effort` booleans, both shapes normalize to one contract,
and the normalized result is projected through the existing `/api/models`
response during a deprecation window.

This is an implementation document. It describes the contract the code
delivers, the compatibility boundary, and the validation rules.

## Problem

DeerFlow modeled reasoning support with two independent booleans and then
applied generic runtime values (`thinking_enabled`, `reasoning_effort`)
uniformly across providers. Three things could not be expressed:

- **Required thinking.** GLM-5.3-Flash rejects `thinking.type=disabled`, yet
  summarization, title generation, subagents, and the flash chat mode all
  request `thinking_enabled=False`. PR #5074 worked around this at the profile
  level by pinning the thinking block into the base `extra_body` and switching
  effort forwarding off entirely.
- **Restricted effort vocabularies.** The UI emits `minimal/low/medium/high`;
  GLM-5.3-Flash accepts `low/high/max`, DeepSeek accepts
  `low/medium/high/xhigh/max` (issue #4514). The factory also hard-coded
  `reasoning_effort=minimal` on the OpenAI-compatible disable path.
- **Payload dialects and reasoning history.** The factory guessed the disable
  payload from the shape of `when_thinking_enabled`, and whether reasoning
  history is preserved (`clear_thinking`) was buried in provider-specific
  `extra_body` blocks.

## Contract

### Configuration shape

```yaml
models:
  - name: glm-5.3-flash
    use: deerflow.models.patched_deepseek:PatchedChatDeepSeek
    model: glm-5.3-flash
    api_base: https://api.z.ai/api/paas/v4
    api_key: $ZAI_API_KEY
    reasoning:
      thinking: required            # unsupported | optional | required
      on_disable_request: keep_enabled   # keep_enabled | reject (required only)
      dialect: openai_extra_body    # auto | openai_extra_body | anthropic | vllm_chat_template | ollama | none
      history: clear                # preserve | clear | omitted (provider default)
      effort:
        values: [low, high, max]    # provider vocabulary, in display order
        default: high               # used when the caller does not choose (also background calls)
        aliases:                    # DeerFlow generic value -> provider value
          minimal: low
          medium: high
        path: reasoning_effort      # where the value is serialized (dotted identifier path)
```

Every key under `reasoning` except `thinking` is optional. `effort` omitted
means the model exposes no effort control.

### Normalized contract

`deerflow.models.reasoning.resolve_reasoning_contract(model_config)` returns a
frozen `ReasoningContract`:

| Field | Legacy derivation | Contract |
| --- | --- | --- |
| `thinking` | `optional` if `supports_thinking` else `unsupported` | as declared |
| `effort` | generic `minimal/low/medium/high`, non-strict, when `supports_reasoning_effort` | declared values, strict |
| `on_disable_request` | `keep_enabled` | as declared |
| `dialect` | `auto` | as declared |
| `history` | `None` | as declared |
| `source` | `legacy` | `contract` |

`strict=False` on the legacy effort contract means values are forwarded
verbatim, exactly as before. `strict=True` means unknown values never reach the
provider. The chat UI still drops a remembered contract-only value when the
selected legacy model does not advertise it; direct legacy backend requests
retain their historical non-strict behavior.

### Request resolution

`resolve_reasoning_request(contract, thinking_enabled=..., reasoning_effort=...)`
is the single policy every model creation path goes through. It returns the
effective `thinking_enabled`, the effective provider effort value, and a tuple
of adjustment codes for logging.

| Thinking | Request | Result |
| --- | --- | --- |
| `unsupported` | any | `False` |
| `optional` | `x` | `x` |
| `required` | `True` | `True` |
| `required` | `False`, `keep_enabled` | `True` (adjustment `thinking_forced_on`) |
| `required` | `False`, `reject` | `ReasoningPolicyError` |

| Effort contract | Request | Result |
| --- | --- | --- |
| none | any | `None` (adjustment `effort_unsupported` when a value was requested) |
| legacy (non-strict) | `x` | `x` |
| strict | `None` | `default` |
| strict | value in `values` | value |
| strict | key in `aliases` | `aliases[key]` |
| strict | anything else | `default` (adjustment `effort_unsupported_value`) |

### Factory behavior

`create_chat_model` resolves the contract, resolves the request, and then
branches on `contract.source`:

- **legacy** keeps the pre-existing code path byte-for-byte: the
  `when_thinking_enabled` guard, the inferred disable payloads, the hard-coded
  `reasoning_effort=minimal` on the OpenAI-compatible disable path, and the
  `supports_reasoning_effort=False` strip. Existing profiles therefore behave
  exactly as before.
- **contract** applies `when_thinking_enabled` / `thinking` / `when_thinking_disabled`
  when present and otherwise synthesizes the on/off payload from the dialect.
  `dialect: auto` infers the dialect from `when_thinking_enabled` the same way
  the legacy path does. `history` is serialized as
  `extra_body.thinking.clear_thinking` for the `openai_extra_body` dialect and
  is otherwise informational. The resolved effort is written to `effort.path`
  after the templates, so a validated request always wins over a template
  value; a `None` result leaves the profile value in place. A model without an
  effort contract never forwards `reasoning_effort`.

Required thinking short-circuits the disable branch entirely, which is what
makes the synthesized `thinking.type=disabled` + `reasoning_effort=minimal`
pair impossible for those models.

### Validation

`ModelConfig` rejects impossible combinations at load time when `reasoning`
is present:

- `effort.default` not in `effort.values`; an alias key that is already a
  value; an alias target outside `values`; empty or duplicate values.
- `effort.path` that is not a dotted identifier, or a single segment that would
  replace a whole mapping (`extra_body`, `thinking`, `model_kwargs`,
  `default_headers`, `default_query`).
- `thinking: required` together with `when_thinking_disabled`.
- `thinking: unsupported` together with `when_thinking_enabled` or `thinking`.
- `on_disable_request: reject` on a model whose thinking is not `required`.
- A legacy boolean explicitly set to a value that contradicts the contract.
- An effort value at `effort.path` in the profile, in `when_thinking_enabled`
  / `when_thinking_disabled`, or in the `thinking` shortcut that the effort
  contract does not accept, or any such value on a model that declares no
  effort control. These operator-supplied values are forwarded when the caller
  chooses nothing, so they must satisfy the contract too.
- A stale `reasoning_effort` key in the profile or a thinking template when
  `effort.path` points elsewhere. The factory also removes a generic key from
  runtime overrides before forwarding a custom-path contract to the provider.

When the contract is present the legacy booleans are projected from it, so
`ModelConfig.supports_thinking` and `supports_reasoning_effort` stay correct
for every reader that has not migrated yet.

### API projection

`GET /api/models` and `DeerFlowClient.list_models()` / `get_model()` keep the
legacy booleans and add a `reasoning` object for every model:

```json
{
  "reasoning": {
    "thinking": "required",
    "effort": {"values": ["low", "high", "max"], "default": "high", "aliases": {"minimal": "low", "medium": "high"}},
    "history": "clear",
    "source": "contract"
  }
}
```

Legacy models report `source: "legacy"`, the generic effort vocabulary, and no
default, which is exactly what the UI used to assume.

### Frontend

`core/models/reasoning.ts` normalizes a `Model` (falling back to the booleans
when an older Gateway omits `reasoning`) and owns the mode/effort decisions:

- `getResolvedMode` never yields `flash` for a required-thinking model and
  never yields a thinking mode for an unsupported one.
- The effort menu renders the contract's `values`; generic values keep their
  localized labels and descriptions, provider-specific values (`max`,
  `xhigh`) get their own labels.
- Mode presets (`thinking → low`, `pro → medium`, `ultra → high`) are mapped
  through `resolveReasoningEffort`, so a preset that the model does not accept
  becomes the alias or the default instead of an invalid request.
- When a remembered provider-specific effort is used with a legacy model,
  `resolveReasoningEffort` keeps only the legacy model's advertised generic
  values and drops the rest.
- The custom-agent dialog hides the "off" thinking option for required models
  and offers only the effort values both the model and the per-agent schema
  accept.

User preferences accept any lowercase effort token so a provider-specific
default such as `max` can be persisted.

## Compatibility

- No existing `config.yaml` changes meaning. A model without a mapping-valued
  `reasoning:` contract is `source: legacy` and follows the pre-existing factory
  path. In particular, a boolean or level-string `reasoning` (`true` /
  `false`, or `low|medium|high` for gpt-oss style models) remains a native
  ChatOllama constructor setting and is forwarded on that path. The assembly
  descriptor keeps that native value — and a declared contract — in
  `model_parameters`, so request-affecting reasoning settings move the
  fingerprint.
- `supports_thinking` / `supports_reasoning_effort` remain in the config
  schema, the API, and the frontend types. They are derived when a contract is
  present and are the deprecation-window projection.
- Per-agent `reasoning_effort` keeps its `low/medium/high` schema; the factory
  maps it through the model's aliases at run time.
- The wizard's Z.AI profile and `config.example.yaml` migrate GLM-5.3-Flash to
  the contract, restoring its `low/high/max` effort control. Its `default` is
  `high` rather than the provider-recommended `max` because the default also
  governs summarization, title generation, and subagent calls, which never
  choose an effort.

## Validation contract

- `backend/tests/test_reasoning_contract.py` — normalization, validation
  failures, request resolution for optional / required / unsupported /
  restricted-effort models, API projection.
- `backend/tests/test_model_factory.py` — required-thinking models never
  receive a disable payload, restricted effort mapping, dialect synthesis,
  history serialization, legacy behavior unchanged.
- `backend/tests/test_models_authorization.py` and `test_client.py` — API
  projection shape.
- `backend/tests/test_setup_wizard.py` — Z.AI profile uses the contract.
- `frontend/tests/unit/core/models/reasoning.test.ts` — mode resolution,
  effort options, alias mapping, legacy fallback.

## Follow-ups

- Widen `AgentConfig.reasoning_effort` once the UI can express per-agent
  provider-specific values.
- Teach the summarization middleware to honor `history: preserve` by replaying
  reasoning blocks; today the contract only serializes the provider flag.
- Retire the legacy booleans from the API after a deprecation window.
