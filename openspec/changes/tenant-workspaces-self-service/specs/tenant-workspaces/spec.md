## ADDED Requirements

### Requirement: Unified tenant identity
The system SHALL preserve global user identity and use personal/team workspaces with explicit active memberships as tenant boundaries. Server-resolved workspace context SHALL intersect native permissions and resource ACLs; platform administration SHALL NOT bypass content access.

#### Scenario: Same user selects another space
- **WHEN** a user selects workspace B and requests a private artifact belonging to workspace A
- **THEN** the request SHALL return 404 even when the user belongs to both spaces; the original request in A SHALL succeed if its ACL permits

### Requirement: Managed and self-service onboarding
The system SHALL deliver operator provisioning and verified self-registration through the same idempotent native account/workspace provisioning service. Unverified users SHALL NOT execute tasks.

#### Scenario: Verified signup provisions once
- **WHEN** a valid email-verification action is completed and its callback is repeated
- **THEN** exactly one personal workspace SHALL exist and the token SHALL not authorize a second action

### Requirement: Account recovery and public enrollment controls
The system SHALL hash single-use purpose-bound tokens, encrypt retryable mail payloads, apply shared rate limits, avoid public account enumeration, and invalidate old credentials after password reset.

#### Scenario: Reset token replay
- **WHEN** a password reset token is consumed and presented again
- **THEN** the second consumption SHALL fail and pre-reset sessions and PATs SHALL not authorize requests

### Requirement: Team ownership and invitations
The system SHALL enforce owner/admin/member permissions, verified-email-bound invitations and exactly one active team owner using serialized mutations.

#### Scenario: Concurrent last owner removal
- **WHEN** ownership transfer and owner exit compete
- **THEN** the transaction outcomes SHALL preserve one owner or reject the conflicting operation without broadening membership

### Requirement: Resource and context source isolation
The system SHALL scope queries before pagination and isolate file paths, retrieval sources, memory, connections, caches and explicit shared materials. Private conversations and personal memory SHALL remain private.

#### Scenario: Foreign retrieval source
- **WHEN** a client supplies a dataset identifier or connection from another workspace
- **THEN** the server SHALL reject it before provider access and SHALL not include foreign facts in model context

#### Scenario: Explicit team project publication
- **WHEN** a team owner or admin explicitly publishes a project with workspace visibility
- **THEN** live members with native read permission SHALL read its documents; ordinary members SHALL NOT modify shared materials, and other workspaces SHALL NOT authorize those IDs
- **AND** document authors SHALL retain their native user identity while their access inherits the parent project's current ACL; sharing SHALL NOT grant private conversation access

### Requirement: Durable execution and revocation
The system SHALL persist and authenticate workspace scope across native Run, MCP, Scheduler, B/C assignments, browser sessions, output publication, continuations and notifications. Current authorization SHALL be revalidated and unknown physical work SHALL retain reservations.

#### Scenario: Member removed during a dependency wait
- **WHEN** a member is removed while C waits for B
- **THEN** new claims and continuation SHALL be denied, cancellation SHALL use native lifecycle, and results SHALL not be delivered to the revoked member

#### Scenario: Native caller exits before its host model provider
- **WHEN** a native Run caller is cancelled or revoked while its host model service still has actual provider work in flight
- **THEN** the Run SHALL retain its execution lifetime and reject same-thread replacement until that work has stopped, including when the provider task itself is cancelled
- **AND** a different authorized workspace using the shared service SHALL be able to finish independently within the existing service budget

#### Scenario: Native execution stop reaches a system model boundary
- **WHEN** native execution authority is denied at the extension model service, title generation or summary generation boundary
- **THEN** the owning worker SHALL receive the native stop signal without converting it into an ordinary provider failure, local title or summary skip that continues execution

#### Scenario: Legitimate completion model work
- **WHEN** an authorized native Run completes its body and invokes the host model service from its completion hook
- **THEN** that work SHALL remain allowed before final sealing, and actual work left by the hook SHALL finish before execution cleanup is confirmed

### Requirement: Workspace aware user experience
The interface SHALL support workspace selection, managed and self-service onboarding, membership management and explicit sharing while preserving backend authorization and isolating subscriptions and caches.

#### Scenario: Workspace switch during execution
- **WHEN** the user changes the visible workspace while a run continues
- **THEN** the run SHALL retain its original workspace and the new view SHALL not render cached private content from the previous workspace

### Requirement: Quotas and audit
The system SHALL atomically reserve workspace concurrency and storage, deduplicate usage events and retain minimal tenant-scoped audit metadata without credential values.

#### Scenario: Duplicate completion under quota
- **WHEN** the same usage event is received twice for workspace A while B has available quota
- **THEN** A SHALL be charged once and B SHALL retain its independent allowance

### Requirement: Tenant and account lifecycle
The system SHALL fence new admission before suspension or closure, revoke access, await physical cleanup, apply documented retention and require ownership resolution before account closure. Restoring a tenant SHALL NOT replay old work automatically.

#### Scenario: Unconfirmed physical stop
- **WHEN** workspace closure cannot confirm a running task has stopped
- **THEN** closure SHALL remain pending with resources accounted for and SHALL not claim completed cleanup

### Requirement: Native research and follow up
The system SHALL reuse native project files, skills, artifact delivery and Scheduler for a sourced research report and a subsequent update in the same authorized workspace.

#### Scenario: New source material arrives
- **WHEN** a user approves follow-up and new authorized material is added
- **THEN** the next occurrence SHALL produce an attributable update without including another workspace’s sources or private memory

### Requirement: Schema migration and rollback
The system SHALL use additive native/executor migrations, deterministic owner backfill, quarantined ambiguous records, verified NAS mappings and paired backup recovery. Mixed protocol versions SHALL fail admission.

#### Scenario: Partial cross database migration
- **WHEN** metadata migration succeeds while executor migration fails
- **THEN** admission SHALL stay fenced and recovery SHALL use phase receipts without deleting existing history or relabelling foreign resources

### Requirement: Evidence before public registration
The release SHALL keep public registration disabled until tenant entrypoint coverage, mail delivery, managed/self-service mains, isolation, revocation and restore evidence pass on the selected cloud release.

#### Scenario: Only happy path passes
- **WHEN** onboarding succeeds but a required isolation or migration proof is missing
- **THEN** the release SHALL remain incomplete and public registration SHALL remain disabled

### Requirement: Isolation cannot be disabled after activation
After multi-tenant data activation, the system SHALL refuse legacy unscoped binaries or configuration that bypasses workspace authorization. Disabling self-registration SHALL NOT disable isolation for existing tenants.

#### Scenario: Registration is turned off
- **WHEN** an operator disables public registration after team resources exist
- **THEN** existing workspace authorization SHALL remain enforced and a fallback to anonymous or unscoped access SHALL be rejected
