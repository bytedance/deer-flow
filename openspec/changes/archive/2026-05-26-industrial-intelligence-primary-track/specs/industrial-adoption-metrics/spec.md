## ADDED Requirements

### Requirement: Industrial workflow completion tracking
The system SHALL track completion of industrial workflows (device diagnosis, monitoring analysis, trend report generation) with metrics: workflow type, duration, success/failure status, and user ID.

#### Scenario: Track diagnosis workflow completion
- **WHEN** a user completes a device diagnosis workflow (receives diagnosis report)
- **THEN** the system emits a telemetry event: `industrial_workflow_completed` with `workflow_type=diagnosis`, `duration_seconds`, `success=true`, `user_id`

#### Scenario: Track monitoring analysis completion
- **WHEN** a user completes a monitoring analysis workflow (receives analysis report)
- **THEN** the system emits a telemetry event: `industrial_workflow_completed` with `workflow_type=monitoring`, `duration_seconds`, `success=true`, `user_id`

#### Scenario: Track workflow failure
- **WHEN** a user's industrial workflow fails (error during execution)
- **THEN** the system emits a telemetry event: `industrial_workflow_completed` with `success=false` and `error_code`

### Requirement: Industrial template usage tracking
The system SHALL track industrial template usage with metrics: template ID, report run ID, user ID, tenant ID, duration, and completion status.

#### Scenario: Track template usage
- **WHEN** a user runs a report using an industrial template (category=industrial)
- **THEN** the system emits a telemetry event: `industrial_template_used` with `template_id`, `report_run_id`, `user_id`, `tenant_id`, `duration_seconds`, `completed=true`

#### Scenario: Track template abandonment
- **WHEN** a user starts a template run but abandons it (no completion after 30 minutes)
- **THEN** the system emits a telemetry event: `industrial_template_used` with `completed=false`

### Requirement: Industrial agent creation tracking
The system SHALL track creation of agents with industrial skills enabled. Metrics: agent name, number of industrial skills enabled, user ID, tenant ID.

#### Scenario: Track industrial agent creation
- **WHEN** a user creates a new agent with at least one industrial skill enabled
- **THEN** the system emits a telemetry event: `industrial_agent_created` with `agent_name`, `skills_enabled_count`, `user_id`, `tenant_id`

#### Scenario: Track agent fork with industrial skills
- **WHEN** a user forks an agent and the forked agent has industrial skills enabled
- **THEN** the system emits a telemetry event: `industrial_agent_created` with `agent_name`, `skills_enabled_count`, `forked_from=source_agent_name`

### Requirement: Industrial adoption funnel metrics
The system SHALL compute an industrial adoption funnel with stages: 1. Onboarding completed, 2. First industrial skill used, 3. First industrial template used, 4. First industrial agent created, 5. Repeat usage (3+ industrial workflows in 7 days).

#### Scenario: Compute adoption funnel
- **WHEN** an admin queries `GET /api/telemetry/industrial-skills/adoption-funnel`
- **THEN** the system returns funnel metrics: count of users at each stage, conversion rates between stages

#### Scenario: Funnel stage tracking
- **WHEN** a user progresses through adoption stages (e.g., uses first industrial skill)
- **THEN** the system updates the user's current stage in the adoption funnel

### Requirement: Industrial time-to-value metric
The system SHALL compute time-to-value for industrial workflows: time from user creation to first successful industrial workflow completion.

#### Scenario: Compute time-to-value
- **WHEN** an admin queries `GET /api/telemetry/industrial-skills/time-to-value`
- **THEN** the system returns: median time-to-value (hours), 25th percentile, 75th percentile, for users who completed first industrial workflow

#### Scenario: Time-to-value tracking
- **WHEN** a new user completes their first industrial workflow
- **THEN** the system records the time difference between user creation and workflow completion for time-to-value calculation

### Requirement: Replace balance metrics with adoption depth
The system SHALL remove "industrial vs foundation balance" metrics from the telemetry summary. The summary SHALL focus on adoption depth metrics (workflow completion, template usage, agent creation) instead of usage balance.

#### Scenario: Telemetry summary without balance metrics
- **WHEN** an admin queries `GET /api/telemetry/industrial-skills/summary`
- **THEN** the response does NOT include `industrial_percentage`, `by_tier` breakdown, or balance-related fields

#### Scenario: Telemetry summary with adoption metrics
- **WHEN** an admin queries `GET /api/telemetry/industrial-skills/summary`
- **THEN** the response includes: `workflow_completions`, `template_usage_count`, `agent_creation_count`, `adoption_funnel`, `time_to_value`

## REMOVED Requirements

### Requirement: Industrial vs foundation balance tracking
**Reason**: Industrial-first is no longer an experiment requiring balance tracking. The platform has transitioned to permanent industrial-first positioning.
**Migration**: Balance metrics (`industrial_percentage`, `by_tier`) are removed from telemetry summary. Use adoption depth metrics instead.

### Requirement: Balance-based alerting thresholds
**Reason**: Alerting on "industrial percentage < 50%" is no longer relevant. Industrial-first is the default, not a target to achieve.
**Migration**: Replace balance alerts with adoption alerts (e.g., "workflow completion rate < 60%", "time-to-value > 48 hours").
