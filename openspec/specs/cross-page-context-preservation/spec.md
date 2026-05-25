## ADDED Requirements

### Requirement: Cross-page context preservation
The system SHALL preserve source context when navigating between main chain pages, ensuring no page is a dead-end without traceable origin.

#### Scenario: Every page has visible origin
- **WHEN** a user lands on any main chain page (chat, report, artifact)
- **THEN** the page SHALL display a visible identifier of where the user came from (source type and source ID)

#### Scenario: Navigation links are observable
- **WHEN** a cross-page navigation occurs
- **THEN** the jump SHALL carry a trace identifier that is logged and available for troubleshooting broken navigation chains
