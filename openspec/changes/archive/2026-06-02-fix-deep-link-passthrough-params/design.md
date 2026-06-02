## Context

Deep-link parameters flow through a multi-layer pipeline:
`URL query → useDeepLinkChat (frontend) → sendMessage additional_kwargs → LangGraph SDK HTTP → Gateway normalize_input() → HumanMessage → middleware chain → LLM`

Two layers break this flow:

1. **Gateway `normalize_input()`** ([services.py:82-101](backend/app/gateway/services.py#L82-L101)) — deserializes JSON messages to `HumanMessage` but only copies `content`, discarding `additional_kwargs`
2. **LangChain provider serializers** — when sending messages to LLM providers (OpenAI, DeepSeek, etc.), LangChain only includes known keys (`tool_calls`, `name`, `function_call`) in the API request. Custom keys in `additional_kwargs` are invisible.

The existing `UploadsMiddleware` already demonstrates the correct pattern: middleware reads `additional_kwargs.files` in `before_agent()` and prepends a `<uploaded_files>` block to message content. This change applies the same pattern to deep-link passthrough parameters.

## Goals / Non-Goals

**Goals:**
- Make deep-link passthrough parameters (`device_id`, `component_id`, `diagnosis_date`, `diagnosis_hour`, `template_id`, etc.) visible to the LLM
- Preserve `additional_kwargs` on messages for frontend stream consumers
- Follow the existing `UploadsMiddleware` middleware injection pattern
- Zero behavior change when no passthrough parameters are present
- Backward compatible with existing agent SOUL.md instructions

**Non-Goals:**
- Frontend changes — the parameter flow from URL to `additional_kwargs` stays as-is
- Agent-specific parameter validation — validation remains in SOUL.md instructions
- New API endpoints or protocol changes

## Decisions

### Decision 1: Middleware injection into message content (not SystemMessage)

**Chosen**: Prepend a `<deep_link_params>` block to the first HumanMessage content, following the same approach as `UploadsMiddleware`'s `<uploaded_files>` block.

**Alternatives considered**:
- *Inject as SystemMessage*: Would require inserting before the first HumanMessage in the `messages` list. This complicates state mutation (LangGraph's `AgentState.messages` is append-only in practice) and the SystemMessage could be truncated by summarization before the LLM reads the corresponding HumanMessage.
- *Modify system prompt template*: Would couple passthrough params to the prompt rendering layer, making it impossible to add new agent-specific params without changing generic infrastructure.

**Rationale**: Prepending to HumanMessage content keeps the instruction adjacent to the user's text, survives summarization naturally (it's part of the preserved message), and follows the established `UploadsMiddleware` precedent.

### Decision 2: Generic middleware (not agent-specific)

**Chosen**: A single `PassthroughParamsMiddleware` registered for all agents. The middleware passes all non-internal `additional_kwargs` keys through without filtering.

**Alternatives considered**:
- *Agent-specific parameter whitelist*: Would require middleware to know which params each agent expects. Violates the architecture principle that agents own their parameter contracts.

**Rationale**: The middleware treats all passthrough params uniformly. Agent SOUL.md instructions are responsible for parsing and validating the specific fields they care about. Unknown fields are harmless — the LLM simply ignores them.

### Decision 3: Fixed internal key exclusion set

**Chosen**: Exclude a known set of internal keys from injection (`files`, `hide_from_ui`, `element`).

**Rationale**: `files` is handled by `UploadsMiddleware`, `hide_from_ui` and `element` are frontend-only signaling keys. This list is small and stable.

## Risks / Trade-offs

- **[Risk] LLM misinterprets raw parameter values** → **Mitigation**: Agent SOUL.md instructions include explicit validation requirements (regex, date format, etc.). The `<deep_link_params>` block is in a consistent, structured text format that instructions can reference precisely.
- **[Risk] Parameter values contain sensitive data** → **Mitigation**: Deep-link params are already visible in the URL (or transmitted via the LangGraph SDK HTTP stream). No additional exposure beyond what already exists. If this becomes a concern in future, a `sensitive_params` exclusion list can be added.
- **[Risk] `normalize_input()` change affects non-deep-link flows** → **Mitigation**: The change only preserves fields that already exist in the wire format. If `additional_kwargs` is absent, behavior is identical to today.
