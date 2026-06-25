## ADDED Requirements

### Requirement: Same `launch_id` restores an existing deep-link thread

When a deep-link to `/workspace/chats/new` or `/workspace/agents/[agent_name]/chats/new` carries a `launch_id`, DeerFlow SHALL reuse the existing thread created by that same launch within the current browser session.

#### Scenario: Refresh reopens the same daily report session

- **GIVEN** the user previously opened a daily report deep-link with `launch_id=L1`
- **AND** DeerFlow already created thread `T1` for that launch in the current browser session
- **WHEN** the browser reloads the same `/chats/new?...&launch_id=L1` URL
- **THEN** DeerFlow SHALL restore thread `T1`
- **AND** SHALL update the browser URL to the concrete thread route
- **AND** SHALL NOT auto-send the deep-link prompt again

#### Scenario: Wrong route does not restore

- **GIVEN** DeerFlow stored `launch_id=L1 -> thread T1` for route key `agent:ai-report--daily`
- **WHEN** the user later opens a different route such as `agent:ai-report--weekly` with the same `launch_id=L1`
- **THEN** DeerFlow SHALL ignore that mapping
- **AND** SHALL treat the visit as a normal new-thread launch

### Requirement: New `launch_id` creates a fresh execution

DeerFlow SHALL use `launch_id` identity, rather than comparing other deep-link params, to decide whether to restore an existing thread or start a new execution.

#### Scenario: Explicit re-open of the same report

- **GIVEN** the user already has a monthly report thread created from deep-link params `A` with `launch_id=L1`
- **WHEN** the caller opens the same deep-link params `A` again but with `launch_id=L2`
- **THEN** DeerFlow SHALL start a new thread instead of restoring the old one
- **AND** SHALL run the normal deep-link auto-send or auto-start flow for `L2`

### Requirement: Thread creation persists launch-session recovery mapping

Whenever a new thread is created from a deep-link carrying `launch_id`, DeerFlow SHALL persist a browser-session mapping from `launch_id` to the created thread and its route key.

#### Scenario: First launch records the mapping

- **WHEN** a defect AI analysis deep-link with `launch_id=L1` creates thread `T1`
- **THEN** DeerFlow SHALL store `L1 -> { threadId: T1, routeKey }` in browser session storage
- **AND** later visits with the same `launch_id` and route key SHALL be able to restore `T1`
