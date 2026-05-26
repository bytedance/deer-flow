## ADDED Requirements

### Requirement: Extract resolution data from audit event payloads on verify-close
When a closure ticket transitions to `closed` via the `verify_close` action, the system SHALL query `ClosureTicketEventRow` for events with `action` in (`submit_verification`, `verify_close`) associated with the ticket, extract `verification_summary` and evidence pointers from the event `payload` JSON field, and generate a knowledge base document candidate.

#### Scenario: KB candidate generated from event payloads on successful closure
- **WHEN** an admin calls verify_close on ticket T-001, and the ticket has a prior `submit_verification` event with payload `{"verification_summary": "Replaced faulty sensor on channel 3", "evidence": ["sensor_calibration_report.pdf"]}` and a `verify_close` event with payload `{"verification_summary": "Confirmed sensor replacement resolved the issue"}`
- **THEN** the system creates a KB candidate document with body assembled from both event payloads' `verification_summary` fields, evidence references from the `submit_verification` event's `evidence` array, and ticket metadata (title, device_id, extra_metadata)

#### Scenario: Closure rejected does not generate KB candidate
- **WHEN** a closure ticket transitions to `rejected` or `verify_close` is rejected via `reject_verification` action
- **THEN** no KB candidate is generated

#### Scenario: Ticket with no verification events produces minimal candidate
- **WHEN** a ticket transitions to `closed` via `verify_close` but has no `submit_verification` event (verifier closed directly)
- **THEN** the KB candidate is generated using only the ticket's `title`, `description`, `device_id`, and the `verify_close` event's payload

### Requirement: KB candidate review gate
Generated KB candidates SHALL be stored in a "pending_review" state. An administrator MUST explicitly promote a candidate via API before it enters the KB indexing pipeline. Unpromoted candidates SHALL NOT appear in retrieval results.

#### Scenario: Admin promotes a KB candidate
- **WHEN** an admin calls `POST /api/insights/closure-knowledge/{ticket_id}/promote` with `target_kb_id`
- **THEN** the candidate status changes to "approved" and the document is submitted to the KB indexing pipeline via `IndexingDispatcher.submit(IndexJobRequest(document=..., knowledge_base=...))`

#### Scenario: Admin dismisses a KB candidate
- **WHEN** an admin calls `POST /api/insights/closure-knowledge/{ticket_id}/dismiss` with a reason
- **THEN** the candidate status changes to "dismissed" with the reason recorded, and it is never indexed

#### Scenario: Pending candidate not retrievable
- **WHEN** a KB retrieval query matches content similar to a pending_review candidate
- **THEN** the pending candidate is excluded from retrieval results

### Requirement: KB candidate content structure
Each generated KB candidate SHALL include: title (from ticket `title`), body (assembled verification summaries from event payloads), metadata tags (device_id, device_name, source_ticket_id, closed_at, verifier_id from event actor_id), fault_category (from ticket `extra_metadata` if present), and provenance fields (source_type="closure_resolution", confidence derived from verification quality).

#### Scenario: Candidate includes full provenance
- **WHEN** a KB candidate is generated from a verified closure ticket
- **THEN** the candidate document contains source_type="closure_resolution", source_ticket_id referencing the original ticket, verifier_id from the `verify_close` event's `actor_id`, and closed_at timestamp

#### Scenario: Candidate extracts fault_category from metadata
- **WHEN** the ticket's `extra_metadata` contains `{"fault_category": "sensor_failure", "findings": ["channel 3 drift"]}`
- **THEN** the KB candidate is tagged with fault_category="sensor_failure" and findings are included in the document body

### Requirement: Tenant isolation for closure knowledge
KB candidates SHALL inherit the tenant_id of the source closure ticket. Candidates from one tenant SHALL NOT be promoted into another tenant's knowledge base.

#### Scenario: Cross-tenant promotion rejected
- **WHEN** an admin of Tenant A attempts to promote a KB candidate that belongs to Tenant B
- **THEN** the system rejects the request with a 403 permission_denied error
