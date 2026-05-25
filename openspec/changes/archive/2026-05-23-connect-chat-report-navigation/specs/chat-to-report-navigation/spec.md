## ADDED Requirements

### Requirement: Report run list shows source chat link
The system SHALL display the source chat for each report run in the runs list view, allowing users to navigate directly from the run list to the originating thread without going through the run detail page.

#### Scenario: Run list shows source thread column
- **WHEN** a user views the report runs list (Runs tab)
- **THEN** each row SHALL include a "来源对话" column showing a clickable link to the source thread when `thread_id` is present

#### Scenario: Missing thread_id is handled gracefully
- **WHEN** a report run record has no `thread_id`
- **THEN** the source chat column SHALL display "—" (dash) without causing an error

### Requirement: Chat provides direct artifact access
The system SHALL provide direct download links to report artifacts (Markdown, PDF) from the chat header's report dropdown, without requiring navigation through the report run detail page.

#### Scenario: Chat header dropdown shows artifact links
- **WHEN** a user opens the report dropdown in the chat header and a report run has completed with available artifacts
- **THEN** each dropdown item SHALL show artifact download links (Markdown and/or PDF) alongside the report run status

#### Scenario: Artifact link carries cross-page context for traceability
- **WHEN** a user clicks an artifact download link from the chat header
- **THEN** the click SHALL be logged via `logCrossPageNavigation` with `sourceType: "chat"` and the relevant context

### Requirement: Navigation jumps produce structured trace logs
The system SHALL produce structured trace identifiers for every cross-page jump, consumable by browser developer tools and RUM (Real User Monitoring) systems.

#### Scenario: Outbound navigation produces structured log
- **WHEN** a user navigates from chat to report or artifact
- **THEN** the system SHALL emit a structured log object containing `traceId`, `direction` ("outbound"), `sourceType`, `sourceId`, `threadId`, `runId` (if available), and `timestamp`

#### Scenario: Inbound navigation produces structured log
- **WHEN** a destination page detects CrossPageContext from URL params
- **THEN** the system SHALL emit a structured log object containing `traceId`, `direction` ("inbound"), and the same context fields

## MODIFIED Requirements

### Requirement: Chat result links to reports and artifacts
The system SHALL provide direct navigation from a chat result to related report results and artifacts.

#### Scenario: User navigates from chat to report
- **WHEN** a user views a chat result that has generated a report
- **THEN** the UI SHALL display a clickable link that navigates to the report result

#### Scenario: User navigates from chat to artifact
- **WHEN** a user views a chat result that has generated an artifact
- **THEN** the UI SHALL display a clickable link that navigates to or downloads the artifact directly

#### Scenario: Artifact download from chat header
- **WHEN** a user opens the report dropdown in the chat header and clicks an artifact download link
- **THEN** the artifact SHALL be downloaded immediately without requiring intermediate page navigation
