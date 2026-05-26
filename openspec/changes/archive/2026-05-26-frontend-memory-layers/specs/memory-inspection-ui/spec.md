## ADDED Requirements

### Requirement: Memory inspection panel
The frontend SHALL provide a Memory Panel accessible from the thread view and settings page. The panel SHALL display facts from User Memory, Session Memory, and Domain Memory in separate tabs or sections.

#### Scenario: User opens memory panel from thread view
- **WHEN** user clicks "Memory" icon in thread view
- **THEN** Memory Panel opens showing Session Memory facts for current thread, with tabs for User Memory and Domain Memory

#### Scenario: User opens memory panel from settings
- **WHEN** user navigates to Settings → Memory
- **THEN** Memory Panel opens showing User Memory facts, with tabs for Session Memory (select thread) and Domain Memory (select domain)

#### Scenario: Empty memory layer shows helpful message
- **WHEN** selected memory layer has no facts
- **THEN** panel displays "No facts stored yet" with explanation of how memory is collected

### Requirement: Memory fact search and filtering
The Memory Panel SHALL support searching facts by keyword and filtering by metadata (confidence, date range, domain, entity).

#### Scenario: User searches for keyword
- **WHEN** user types "budget" in search bar
- **THEN** panel filters facts containing "budget" across all visible memory layers

#### Scenario: User filters by confidence threshold
- **WHEN** user sets confidence filter to "≥ 0.8"
- **THEN** only facts with confidence ≥ 0.8 are displayed

#### Scenario: User filters by date range
- **WHEN** user selects date range "Last 30 days"
- **THEN** only facts created within last 30 days are displayed

### Requirement: Memory fact metadata display
Each fact card SHALL display metadata: content, confidence score, creation timestamp, source thread (if applicable), domain/entity (for Domain Memory), and decay status.

#### Scenario: User views User Memory fact
- **WHEN** User Memory fact is displayed
- **THEN** card shows: content, confidence (e.g., "0.85"), created date (e.g., "2026-05-20"), source (e.g., "thread_abc123")

#### Scenario: User views Domain Memory fact with decay
- **WHEN** Domain Memory fact with linear decay is displayed
- **THEN** card shows: content, confidence, created date, domain/entity, decay status (e.g., "Decayed: 75% relevance")

#### Scenario: User hovers over source thread link
- **WHEN** user hovers over source thread ID
- **THEN** tooltip shows thread title and date, clicking navigates to thread

### Requirement: Real-time memory update notifications
The frontend SHALL receive WebSocket notifications when memory is updated during conversations. The Memory Panel SHALL auto-refresh when relevant memory changes.

#### Scenario: Memory updated while panel is open
- **WHEN** agent extracts new fact during conversation and user has Memory Panel open
- **THEN** panel receives WebSocket event `memory_updated` and displays new fact with "New" badge

#### Scenario: Memory updated while panel is closed
- **WHEN** memory is updated but panel is closed
- **THEN** no notification shown, panel loads updated data when opened

### Requirement: Memory layer visibility toggles
The Memory Panel SHALL allow users to toggle visibility of each memory layer (User/Session/Domain) to focus on specific context.

#### Scenario: User hides Domain Memory
- **WHEN** user toggles off Domain Memory visibility
- **THEN** Domain Memory section is hidden, only User and Session Memory are displayed

#### Scenario: User shows only Session Memory
- **WHEN** user toggles off User and Domain Memory
- **THEN** only Session Memory facts are displayed
