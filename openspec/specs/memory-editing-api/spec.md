## ADDED Requirements

### Requirement: REST API for memory fact CRUD
The system SHALL provide REST endpoints for creating, reading, updating, and deleting memory facts across User, Session, and Domain layers. All endpoints SHALL require authentication and enforce tenant isolation.

#### Scenario: Create new User Memory fact
- **WHEN** authenticated user sends `POST /api/v1/memory/user/facts` with `{content: "Prefers concise responses", category: "preference", confidence: 0.9}`
- **THEN** system creates fact, returns `{id: "fact_abc123", content: "...", confidence: 0.9, createdAt: "2026-05-26T10:00:00Z"}`

#### Scenario: Read Session Memory facts for thread
- **WHEN** authenticated user sends `GET /api/v1/memory/session?thread_id=thread_xyz`
- **THEN** system returns list of session facts for that thread, ordered by createdAt desc

#### Scenario: Update Domain Memory fact
- **WHEN** authenticated user sends `PUT /api/v1/memory/domain/facts/fact_def456` with `{content: "Pump A flow rate: 600 GPM (updated)", confidence: 0.95}`
- **THEN** system updates fact content and confidence, returns updated fact

#### Scenario: Delete memory fact
- **WHEN** authenticated user sends `DELETE /api/v1/memory/user/facts/fact_abc123`
- **THEN** system deletes fact, returns `204 No Content`

#### Scenario: Unauthorized access is rejected
- **WHEN** unauthenticated user sends `GET /api/v1/memory/user`
- **THEN** system returns `401 Unauthorized`

#### Scenario: Cross-tenant access is rejected
- **WHEN** tenant A user tries to access tenant B's memory
- **THEN** system returns `403 Forbidden`

### Requirement: Memory fact validation
The API SHALL validate fact content and metadata before persistence. Invalid requests SHALL return `400 Bad Request` with descriptive error messages.

#### Scenario: Empty content is rejected
- **WHEN** user sends `POST /api/v1/memory/user/facts` with `{content: ""}`
- **THEN** system returns `400 Bad Request` with error "content must be non-empty"

#### Scenario: Invalid confidence is rejected
- **WHEN** user sends `POST /api/v1/memory/user/facts` with `{confidence: 1.5}`
- **THEN** system returns `400 Bad Request` with error "confidence must be between 0.0 and 1.0"

#### Scenario: Content length limit is enforced
- **WHEN** user sends fact with content exceeding 1000 characters
- **THEN** system returns `400 Bad Request` with error "content exceeds maximum length of 1000 characters"

### Requirement: Audit logging for memory edits
The system SHALL log all memory create/update/delete operations with user identity, timestamp, and before/after state. Audit logs SHALL be queryable by admin users.

#### Scenario: Fact creation is logged
- **WHEN** user creates a new memory fact
- **THEN** system logs: `{action: "create", user_id: "alice", timestamp: "...", layer: "user", fact_id: "fact_abc123", after: {...}}`

#### Scenario: Fact update is logged with diff
- **WHEN** user updates a memory fact
- **THEN** system logs: `{action: "update", user_id: "alice", timestamp: "...", layer: "user", fact_id: "fact_abc123", before: {...}, after: {...}}`

#### Scenario: Fact deletion is logged
- **WHEN** user deletes a memory fact
- **THEN** system logs: `{action: "delete", user_id: "alice", timestamp: "...", layer: "user", fact_id: "fact_abc123", before: {...}}`

#### Scenario: Admin queries audit logs
- **WHEN** admin user sends `GET /api/v1/memory/audit?user_id=alice&action=delete&from=2026-05-01`
- **THEN** system returns list of audit entries matching filters

### Requirement: Memory export and import
The API SHALL support exporting memory as JSON and importing corrected versions. Export SHALL include all facts across User/Session/Domain layers (filtered by user/thread/domain). Import SHALL validate JSON schema and reject invalid data.

#### Scenario: Export User Memory as JSON
- **WHEN** user sends `GET /api/v1/memory/user/export`
- **THEN** system returns JSON file with all User Memory facts: `{version: "1.0", facts: [...], exportedAt: "..."}`

#### Scenario: Export Session Memory for thread
- **WHEN** user sends `GET /api/v1/memory/session/export?thread_id=thread_xyz`
- **THEN** system returns JSON file with session facts for that thread

#### Scenario: Import corrected memory
- **WHEN** user sends `POST /api/v1/memory/user/import` with valid JSON payload
- **THEN** system validates schema, replaces existing User Memory with imported data, returns `{imported: 15, skipped: 0}`

#### Scenario: Import with invalid schema is rejected
- **WHEN** user sends `POST /api/v1/memory/user/import` with malformed JSON
- **THEN** system returns `400 Bad Request` with error "invalid memory schema"

### Requirement: WebSocket event for memory updates
The system SHALL emit WebSocket event `memory_updated` when memory is created/updated/deleted. Event payload SHALL include layer, action, fact_id, and user_id.

#### Scenario: Memory update triggers WebSocket event
- **WHEN** agent extracts new fact during conversation
- **THEN** system emits WebSocket event: `{type: "memory_updated", layer: "session", action: "create", fact_id: "fact_abc123", user_id: "alice", thread_id: "thread_xyz"}`

#### Scenario: Manual edit triggers WebSocket event
- **WHEN** user edits a fact via REST API
- **THEN** system emits WebSocket event: `{type: "memory_updated", layer: "user", action: "update", fact_id: "fact_def456", user_id: "alice"}`

#### Scenario: WebSocket event includes tenant isolation
- **WHEN** tenant A's memory is updated
- **THEN** only WebSocket connections for tenant A receive the event, tenant B connections do not
