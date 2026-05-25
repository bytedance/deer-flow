## MODIFIED Requirements

### Requirement: Chat result links to reports and artifacts
The system SHALL provide direct navigation from a chat result to related report results and artifacts.

#### Scenario: User navigates from chat to report
- **WHEN** a user views a chat result that has generated a report
- **THEN** the UI SHALL display a clickable link that navigates to the report result

#### Scenario: User navigates from chat to artifact
- **WHEN** a user views a chat result that has generated an artifact
- **THEN** the UI SHALL display a clickable link that navigates to the artifact

## ADDED Requirements

### Requirement: Report run detail identifies triggering conversation
The system SHALL display the specific chat conversation that triggered a report run, allowing users to understand the full context of report generation.

#### Scenario: Run detail shows source chat with clear label
- **WHEN** a user views a report run detail page
- **THEN** the UI SHALL display a labeled "Source Chat" section with a link to the originating thread when `thread_id` is present

#### Scenario: Back navigation from run to chat preserves context
- **WHEN** a user navigates from a report run detail back to the source chat
- **THEN** the cross-page context (if available) SHALL be preserved to highlight the relevant run within the chat view
