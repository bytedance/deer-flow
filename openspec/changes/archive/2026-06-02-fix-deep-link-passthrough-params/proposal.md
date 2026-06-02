## Why

Deep-link URL parameters (device_id, component_id, diagnosis_date, etc.) are passed from the frontend to the backend via LangChain `HumanMessage.additional_kwargs`, but they are **never visible to the LLM** — the Gateway drops them during message deserialization, and LangChain provider serializers exclude custom keys from LLM-visible context. This renders all 6 agent deep-link integration features non-functional.

## What Changes

- Fix Gateway message deserialization to preserve `additional_kwargs` from the wire format into `HumanMessage` objects
- Add a new `PassthroughParamsMiddleware` that extracts deep-link passthrough parameters from the first HumanMessage's `additional_kwargs` and injects them into the message content as a structured block visible to the LLM
- Register the middleware in the lead agent's middleware chain
- Update 6 agent SOUL.md files to reference the injected content block instead of the (now-proven-inaccessible) `additional_kwargs` metadata

## Capabilities

### New Capabilities

- `deep-link-passthrough`: Structured deep-link parameter passthrough from frontend URL query parameters through the backend middleware chain into LLM-visible message content

### Modified Capabilities

<!-- None — this is a new capability that does not change existing spec requirements. -->

## Impact

- **Backend Gateway** (`app/gateway/services.py`): `normalize_input()` must preserve `additional_kwargs` when converting JSON messages to `HumanMessage` — minimal change, no downstream effect
- **Backend Middleware** (`packages/harness/deerflow/agents/middlewares/`): New `passthrough_params_middleware.py`, ~80 lines following the existing `UploadsMiddleware` pattern
- **Backend Agent Factory** (`agents/lead_agent/agent.py`): One-line middleware registration in `_build_middlewares()`
- **Agent SOUL.md** (6 files): Update deep-link parameter handling instructions to reference the injected `<deep_link_params>` block instead of `additional_kwargs`
- **Frontend**: No changes — parameter flow remains unchanged (URL → `useDeepLinkChat` → `sendMessage` → `additional_kwargs`)
