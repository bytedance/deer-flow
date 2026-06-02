## ADDED Requirements

### Requirement: Reserved URL parameters for deep-link

The system SHALL recognize four reserved URL query parameters on new chat pages with defined behavior. All other query parameters SHALL be passed through to `additionalKwargs` automatically.

Reserved parameters and their behavior:

- `prompt`: Message text (string, max 2000 chars, trimmed). When present without `auto_send=1`, pre-fills the input box. When present with `auto_send=1`, used as the auto-sent message text.
- `auto_send`: If exactly `"1"`, triggers immediate message send on page load (new threads only).
- `source`: External system identifier (string, max 100 chars), passed in `additionalKwargs` and logged to console.
- `context`: Opaque context key (string, max 500 chars), passed in `additionalKwargs`.

All parameters SHALL be validated and sanitized at the boundary. Invalid values SHALL be silently ignored for that parameter only.

#### Scenario: Pre-fill prompt on new general chat

- **WHEN** a user navigates to `/workspace/chats/new?prompt=analyze+equipment+V-203`
- **THEN** the chat input SHALL be pre-filled with "analyze equipment V-203"
- **AND** no message SHALL be sent automatically

#### Scenario: Auto-send prompt on new general chat

- **WHEN** a user navigates to `/workspace/chats/new?prompt=analyze+equipment+V-203&auto_send=1`
- **THEN** a new thread SHALL be created
- **AND** a message with text "analyze equipment V-203" SHALL be sent immediately

#### Scenario: Source and context in additionalKwargs

- **WHEN** a user navigates to `/workspace/chats/new?prompt=hello&source=grafana-alerting&context=alert-12345&auto_send=1`
- **THEN** `additionalKwargs` SHALL contain `{ source: "grafana-alerting", context: "alert-12345" }`

### Requirement: Passthrough parameters

All query parameters that are NOT in the reserved set (`prompt`, `auto_send`, `source`, `context`) SHALL be collected and passed through to `sendMessage`'s `additionalKwargs`.

Each passthrough value SHALL be validated with generic rules: trim whitespace, max 500 chars, strip control characters, skip if empty after trimming.

#### Scenario: Diagnosis agent receives structured params

- **WHEN** a user navigates to `/workspace/agents/fault-diagnosis--pump/chats/new?device_id=P-203A&component_id=Bearing-1&diagnosis_date=2026-06-01&diagnosis_hour=8&auto_send=1&source=grafana-alerting`
- **THEN** `additionalKwargs` SHALL contain `{ source: "grafana-alerting", device_id: "P-203A", component_id: "Bearing-1", diagnosis_date: "2026-06-01", diagnosis_hour: "8" }`
- **AND** the prompt SHALL be the agent's first `auto_start` starter prompt

#### Scenario: Monitoring analysis receives custom params

- **WHEN** a user navigates to `/workspace/agents/monitoring-analysis/chats/new?device_id=V-401&analysis_type=trend&start_time=2026-05-25T00:00:00&end_time=2026-06-01T23:59:59&auto_send=1`
- **THEN** `additionalKwargs` SHALL contain `{ device_id: "V-401", analysis_type: "trend", start_time: "2026-05-25T00:00:00", end_time: "2026-06-01T23:59:59" }`

#### Scenario: Defect closure receives ticket params

- **WHEN** a user navigates to `/workspace/agents/defect-closure/chats/new?ticket_id=TCKT-0042&action=view&auto_send=1`
- **THEN** `additionalKwargs` SHALL contain `{ ticket_id: "TCKT-0042", action: "view" }`

#### Scenario: CRM analyst receives query params

- **WHEN** a user navigates to `/workspace/agents/crm-analyst/chats/new?query_type=service_events&date_range=last_30d&auto_send=1&prompt=查询服务事件并检测异常`
- **THEN** `additionalKwargs` SHALL contain `{ query_type: "service_events", date_range: "last_30d" }`
- **AND** the message text SHALL be "查询服务事件并检测异常"

#### Scenario: Unknown params on general chat are still passed through

- **WHEN** a user navigates to `/workspace/chats/new?custom_field=hello&auto_send=1&prompt=test`
- **THEN** `additionalKwargs` SHALL contain `{ custom_field: "hello" }`

#### Scenario: Passthrough param with control characters

- **WHEN** a user navigates to `/workspace/chats/new?device_id=P-203%00A&auto_send=1&prompt=test`
- **THEN** the null byte in `device_id` SHALL be stripped
- **AND** `additionalKwargs.device_id` SHALL be `"P-203A"`

#### Scenario: Empty passthrough param after trimming

- **WHEN** a user navigates to `/workspace/chats/new?device_id=+++&auto_send=1&prompt=test`
- **THEN** `device_id` SHALL be omitted from `additionalKwargs`

### Requirement: Deep-link parameters only on new threads

Deep-link parameters SHALL only take effect when `thread_id` is `"new"`. On existing thread URLs, all parameters SHALL be silently ignored.

#### Scenario: Existing thread ignores all params

- **WHEN** a user navigates to `/workspace/chats/abc123?prompt=hello&device_id=P-203A`
- **WHERE** `abc123` is an existing thread ID
- **THEN** all parameters SHALL be ignored
- **AND** the existing thread SHALL load normally

### Requirement: Parameter validation at the boundary

The system SHALL validate all reserved parameters and apply generic validation to all passthrough parameters.

#### Scenario: Prompt exceeds max length

- **WHEN** a user navigates to `/workspace/chats/new?prompt=<text longer than 2000 characters>`
- **THEN** the prompt SHALL be truncated to 2000 characters

#### Scenario: auto_send has invalid value

- **WHEN** a user navigates to `/workspace/chats/new?prompt=hello&auto_send=true`
- **THEN** `auto_send` SHALL be treated as `false` (only exactly `"1"` triggers auto-send)

#### Scenario: Empty prompt after trimming

- **WHEN** a user navigates to `/workspace/chats/new?prompt=+++`
- **THEN** the prompt SHALL be ignored (nothing to pre-fill or send)

#### Scenario: Passthrough value exceeds max length

- **WHEN** a user navigates to `/workspace/chats/new?device_id=<value longer than 500 characters>&auto_send=1&prompt=test`
- **THEN** the `device_id` SHALL be truncated to 500 characters

### Requirement: auto_send takes precedence over agent auto_start

When deep-link `auto_send=1` is present, it SHALL supersede any agent-configured `auto_start` starter.

#### Scenario: Deep-link prompt overrides agent auto_start

- **WHEN** a user navigates to `/workspace/agents/fault-diagnosis--pump/chats/new?prompt=diagnose+bearing+wear&auto_send=1`
- **AND** the agent has a configured `auto_start` starter with prompt "诊断机泵故障"
- **THEN** the deep-link prompt "diagnose bearing wear" SHALL be sent
- **AND** the agent-configured auto_start SHALL be skipped

#### Scenario: Passthrough-only deep-link uses agent starter prompt

- **WHEN** a user navigates to `/workspace/agents/fault-diagnosis--pump/chats/new?device_id=P-203A&component_id=Bearing-1&diagnosis_date=2026-06-01&diagnosis_hour=8&auto_send=1`
- **WHERE** no `prompt` parameter is present
- **THEN** the agent's first `auto_start` starter prompt SHALL be used as message text
- **AND** passthrough params SHALL be included in `additionalKwargs`

#### Scenario: Agent auto_start fires when no deep-link present

- **WHEN** a user navigates to `/workspace/agents/fault-diagnosis--pump/chats/new`
- **WHERE** no deep-link parameters are present
- **THEN** the agent's configured `auto_start` starter SHALL fire as normal

### Requirement: Passthrough params on agent chat pages

The agent chat page at `/workspace/agents/[agent_name]/chats/[thread_id]` SHALL support the same reserved + passthrough parameter convention as general chat.

#### Scenario: Passthrough-only with auto_send on agent page

- **WHEN** a user navigates to `/workspace/agents/monitoring-analysis/chats/new?device_id=V-401&analysis_type=spectrum&auto_send=1`
- **THEN** the agent SHALL be `monitoring-analysis`
- **AND** the agent's first `auto_start` starter prompt SHALL be sent
- **AND** `additionalKwargs` SHALL contain `{ device_id: "V-401", analysis_type: "spectrum" }`
