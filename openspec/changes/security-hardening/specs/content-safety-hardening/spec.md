## ADDED Requirements

### Requirement: Content safety moderation fail-closed with fallback
The system SHALL support configurable fail mode for OpenAI Moderation API failures. Modes: `"closed"` (block all), `"fallback"` (local keyword check), `"open"` (allow all). Default mode SHALL be `"fallback"`.

#### Scenario: Moderation API failure in fallback mode
- **WHEN** `content_safety.moderation_fail_mode="fallback"` (default)
- **AND** OpenAI Moderation API is unavailable
- **AND** the input text contains keywords from the local fallback list
- **THEN** the system blocks the input with reason "Keyword fallback blocked: {keywords}"

#### Scenario: Moderation API failure in closed mode
- **WHEN** `content_safety.moderation_fail_mode="closed"`
- **AND** OpenAI Moderation API is unavailable
- **THEN** the system blocks all input with reason "Moderation API unavailable — fail-closed"

#### Scenario: Moderation API failure in open mode
- **WHEN** `content_safety.moderation_fail_mode="open"`
- **AND** OpenAI Moderation API is unavailable
- **THEN** the system allows the input (backward compatibility)
- **AND** logs a warning: "Moderation API unavailable — allowing content (fail-open mode)"

### Requirement: Output guard default block_on_harmful
The OutputGuardMiddleware SHALL default to `block_on_harmful=true` in production. This can be overridden via `content_safety.output_block_on_harmful` config flag.

#### Scenario: Output guard blocks harmful content by default
- **WHEN** the AI generates output flagged as harmful by content safety provider
- **AND** `content_safety.output_block_on_harmful` is not explicitly set to `false`
- **THEN** the system replaces the output with "[Response blocked by safety policy]"
- **AND** logs a warning with the flagged categories

#### Scenario: Output guard allows harmful content when disabled
- **WHEN** `content_safety.output_block_on_harmful=false`
- **AND** the AI generates output flagged as harmful
- **THEN** the system allows the output to reach the user
- **AND** logs an info message with the flagged categories
