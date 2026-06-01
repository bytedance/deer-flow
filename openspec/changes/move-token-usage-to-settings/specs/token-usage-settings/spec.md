## ADDED Requirements

### Requirement: Token usage displayed in settings

The system SHALL provide a "Token 用量" section within the workspace settings dialog that displays cumulative token usage for the current chat session.

#### Scenario: User opens token usage settings

- **WHEN** user opens the settings dialog and navigates to the "Token 用量" section
- **THEN** the system displays a read-only summary of input tokens, output tokens, and total tokens consumed in the current thread

#### Scenario: No token data available

- **WHEN** the current thread has no token usage metadata (model provider did not return `usage_metadata`)
- **THEN** the section displays a message indicating that token data is not yet available for this session

### Requirement: Token usage inline mode removed

The system SHALL NOT display per-message token badges within the message list.

#### Scenario: Message list renders without token badges

- **WHEN** any message list is rendered in a chat thread
- **THEN** no per-message token usage information is displayed alongside message bubbles

### Requirement: Token usage header indicator removed

The system SHALL NOT display a token usage indicator in the chat page header.

#### Scenario: Chat page header renders without token indicator

- **WHEN** a chat page renders its top header bar
- **THEN** no token usage button or indicator is present in the header controls
