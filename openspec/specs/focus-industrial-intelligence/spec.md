# focus-industrial-intelligence Specification

## Purpose
TBD - created by archiving change industrial-intelligence-primary-track. Update Purpose after archive.
## Requirements
### Requirement: Permanent industrial-first configuration
The system SHALL treat industrial-first as the permanent, non-configurable platform identity. There is no configuration option, environment variable, or admin setting to disable industrial-first positioning.

#### Scenario: No industrial-first configuration
- **WHEN** an admin views platform configuration options
- **THEN** there is no setting for "industrial mode", "industrial-first toggle", or "platform positioning"

#### Scenario: Industrial-first is hardcoded
- **WHEN** frontend code determines whether to show industrial-first UI
- **THEN** the decision is hardcoded to `true` (not configurable)

### Requirement: Feature flag removal
The system SHALL NOT provide a feature flag for industrial-first positioning. Industrial intelligence is the permanent platform identity, not an experiment. The `NEXT_PUBLIC_INDUSTRIAL_FIRST` environment variable is removed. All conditional logic checking this flag is deleted, and the industrial-first branch is inlined as the only code path.

#### Scenario: Feature flag removal from environment
- **WHEN** the frontend application starts
- **THEN** the `NEXT_PUBLIC_INDUSTRIAL_FIRST` environment variable is not read, not validated, and not present in `src/env.js`

#### Scenario: Feature flag removal from conditional logic
- **WHEN** frontend code previously checked `isIndustrialFirst()`
- **THEN** the check is removed, and the industrial-first code path is the only path (no fallback to general-first mode)

#### Scenario: Feature flag removal from documentation
- **WHEN** a user reads the admin documentation
- **THEN** there is no mention of "industrial_first feature flag", "rollback to general-first", or "A/B testing industrial vs foundation"

### Requirement: Rollback capability removed
Industrial-first is no longer an experiment. The system SHALL NOT provide rollback capability to general-first mode. All rollback documentation, configuration options, and conditional logic are removed.

#### Scenario: No rollback option
- **WHEN** an admin looks for rollback options
- **THEN** there is no "disable industrial-first" or "rollback to general-first" option available

### Requirement: A/B testing infrastructure removed
The system SHALL NOT provide A/B testing infrastructure for comparing industrial-first vs general-first modes.

#### Scenario: No A/B testing for platform mode
- **WHEN** the platform evaluates user experience
- **THEN** there is no A/B test group assignment, test group tracking, or mode-comparison telemetry

### Requirement: General-first fallback mode removed
The system SHALL NOT provide a general-first fallback mode. Users can still access general tools via the "Tools" menu, but cannot switch the entire platform to general-first mode.

#### Scenario: No fallback navigation
- **WHEN** a user navigates the platform
- **THEN** the industrial-first navigation hierarchy is always active (no alphabetical skill sorting, no generic onboarding, no general-first navigation)

### Requirement: Migration from feature flag to permanent state
The system SHALL provide a one-time migration for existing tenants. Migration enables all industrial skills and updates tenant preferences to industrial-first.

#### Scenario: Migration prompt for existing tenants
- **WHEN** a tenant has not completed migration
- **THEN** on login, the system displays migration prompt: "Industrial intelligence is now the default. Enable recommended industrial skills?"

#### Scenario: Migration acceptance
- **WHEN** a tenant admin accepts the migration prompt
- **THEN** the system enables all `core-industrial` skills for the tenant and sets migration as completed

#### Scenario: Migration decline
- **WHEN** a tenant admin declines the migration prompt
- **THEN** the system keeps current skill configuration but marks migration as completed (no further prompts)

