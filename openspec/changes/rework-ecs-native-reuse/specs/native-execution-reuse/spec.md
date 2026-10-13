## ADDED Requirements

### Requirement: Native trusted task submission
The implementation SHALL use native ordinary MCP task tracking and SHALL authenticate submission scope independently of model arguments.

#### Scenario: Submit through native runtime
- **WHEN** the authenticated Agent submits a job through an ordinary MCP task tool
- **THEN** the execution service receives verified owner/thread/run scope bound to the exact arguments, and native task tracking owns polling and notification

#### Scenario: Missing or substituted scope
- **WHEN** submit has no live trusted runtime or the signature, owner, expiry, audience or arguments do not match
- **THEN** submission is rejected without execution

### Requirement: Shared B and C execution
The implementation SHALL support durable program jobs and complete native Agent execution in the same fixed ECS pool with shared resource admission and outbound worker transport.

#### Scenario: Awaited job
- **WHEN** a remote Agent awaits a program job
- **THEN** committed native goal/checkpoint and dependency state permit resources to be freed and one valid continuation after results arrive

#### Scenario: Unknown stop
- **WHEN** physical execution cannot be confirmed stopped
- **THEN** capacity remains reserved and automatic duplicate side effects are not admitted

### Requirement: Preserve native ownership
The implementation SHALL reuse native checkpoint, run ownership, events, cancellation and goal authority and preserve unrelated fork changes.

#### Scenario: Cross-instance cancellation
- **WHEN** cancellation reaches a different Gateway instance
- **THEN** native durable cancellation is applied and executor resource release still requires physical execution reconciliation

### Requirement: Configured native browser capability
The implementation SHALL keep native browser tools and Live on the same verified owner/thread/incarnation session through an explicit operator provider, preserving ordinary startup guards, native authentication and strict physical capacity.

#### Scenario: UI and model share a worker session
- **WHEN** authenticated UI control and native model tools use the same active thread incarnation
- **THEN** fixed-node outbound control reaches the existing native browser session without a second browser runner or worker public listener

#### Scenario: Retired or uncertain browser
- **WHEN** a scoped session closes, resets or has an uncertain physical outcome
- **THEN** old holders cannot recreate an untracked browser, unrelated scoped operations remain active, and replacement waits for confirmed physical closure
