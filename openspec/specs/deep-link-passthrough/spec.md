# deep-link-passthrough Specification

## Purpose
TBD - created by archiving change fix-deep-link-passthrough-params. Update Purpose after archive.
## Requirements
### Requirement: Gateway preserves additional_kwargs during message deserialization

The Gateway `normalize_input()` function SHALL preserve `additional_kwargs` fields when converting JSON-serialized messages to LangChain `HumanMessage` objects.

#### Scenario: Message with additional_kwargs is deserialized correctly

- **WHEN** the frontend sends a message with `{"content": "hello", "additional_kwargs": {"device_id": "P-203A", "source": "grafana"}}`
- **THEN** the resulting `HumanMessage` has `additional_kwargs` containing `{"device_id": "P-203A", "source": "grafana"}`

#### Scenario: Message without additional_kwargs is handled gracefully

- **WHEN** the frontend sends a message with only `{"content": "hello"}`
- **THEN** the resulting `HumanMessage` is created with default `additional_kwargs={}` and no error occurs

---

### Requirement: Passthrough params middleware injects deep-link parameters into message content

A `PassthroughParamsMiddleware` SHALL extract non-internal keys from the first HumanMessage's `additional_kwargs` and prepend them to the message content as a structured `<deep_link_params>` block, visible to the LLM.

#### Scenario: Deep-link parameters are injected into content

- **WHEN** the first HumanMessage has `additional_kwargs` containing `{"device_id": "P-203A", "component_id": "Bearing-1", "auto_send": "1"}`
- **THEN** the message content is prefixed with a `<deep_link_params>` block listing `device_id: P-203A` and `component_id: Bearing-1`

#### Scenario: Internal keys are excluded from injection

- **WHEN** the first HumanMessage has `additional_kwargs` containing `{"device_id": "P-203A", "files": [...], "hide_from_ui": true, "element": "task"}`
- **THEN** only `device_id` appears in the `<deep_link_params>` block; `files`, `hide_from_ui`, and `element` are excluded

#### Scenario: No passthrough params — middleware is a no-op

- **WHEN** the first HumanMessage has `additional_kwargs` that contains only internal keys (or is empty/absent)
- **THEN** the message content is NOT modified and the middleware returns no state updates

#### Scenario: Non-first messages are unaffected

- **WHEN** the second HumanMessage in a conversation has `additional_kwargs` with passthrough params
- **THEN** the middleware does NOT inject a `<deep_link_params>` block (only the first message is processed)

#### Scenario: additional_kwargs is preserved on the message

- **WHEN** the middleware injects the `<deep_link_params>` block into content
- **THEN** the original `additional_kwargs` dict remains on the `HumanMessage` unchanged (for frontend stream consumers)

---

### Requirement: Passthrough params middleware is registered in the agent middleware chain

The `PassthroughParamsMiddleware` SHALL be registered in the lead agent's `_build_middlewares()` function, positioned after `ThreadDataMiddleware` and before summarization/other processing middleware.

#### Scenario: Middleware executes in correct position

- **WHEN** an agent run starts with deep-link passthrough parameters
- **THEN** the `<deep_link_params>` block is present in message content before summarization, todo, and other downstream middleware process the message

