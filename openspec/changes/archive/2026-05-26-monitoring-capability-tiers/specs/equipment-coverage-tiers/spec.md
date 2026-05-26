## ADDED Requirements

### Requirement: Basic equipment coverage
At Basic tier, the system SHALL allow selecting up to 5 devices in a single monitoring analysis session via `device-selector-multi` with `maxSelect: 5`.

#### Scenario: User selects 3 devices at Basic tier
- **WHEN** Agent has only `monitoring:basic` in tool_groups and user selects 3 devices
- **THEN** the system SHALL proceed with analysis for all 3 devices

#### Scenario: User attempts to select more than 5 at Basic tier
- **WHEN** Agent has only `monitoring:basic` and `device-selector-multi` is configured with `maxSelect: 5`
- **THEN** the tree picker SHALL cap selection at 5 devices

### Requirement: Pro equipment coverage
At Pro tier, the system SHALL allow selecting up to 50 devices and SHALL support grouping by equipment type for batch analysis.

#### Scenario: User selects 30 devices at Pro tier
- **WHEN** Agent has `monitoring:pro` and user selects 30 devices across 3 equipment types
- **THEN** the system SHALL group devices by type and render per-type analysis sections in the report

### Requirement: Ultra equipment coverage
At Ultra tier, the system SHALL allow unlimited device selection and SHALL support cross-organization queries via `queryParams.orgId` configuration.

#### Scenario: Ultra tier with cross-org query
- **WHEN** Agent has `monitoring:ultra` and `queryParams.orgId` is set to `0` (all orgs)
- **THEN** the system SHALL fetch devices across all organizations the tenant has access to
