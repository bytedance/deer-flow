## MODIFIED Requirements

### Requirement: Frontend deep-link parsing reserves non-Agent control parameters

DeerFlow frontend SHALL treat transport-level control parameters as reserved keys during deep-link parsing so they do not leak into Agent passthrough params.

#### Scenario: `launch_id` is parsed but not forwarded

- **WHEN** the user opens `/workspace/agents/<agent>/chats/new?...&launch_id=launch-123&device_id=P-203A`
- **THEN** the frontend SHALL parse `launch_id=launch-123` for its own recovery flow
- **AND** SHALL NOT include `launch_id` inside `passthroughParams` or Agent `additional_kwargs`
- **AND** other business params such as `device_id` SHALL remain available for passthrough
