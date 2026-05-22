## ADDED Requirements

### Requirement: Auth error scenarios have regression coverage
The system SHALL maintain regression tests or an acceptance checklist for common 401, 403, and 503 auth scenarios.

#### Scenario: Invalid token test exists
- **WHEN** the regression test suite runs
- **THEN** at least one test SHALL verify that an expired or invalid token returns 401 with the correct error code

#### Scenario: Forbidden test exists
- **WHEN** the regression test suite runs
- **THEN** at least one test SHALL verify that insufficient permissions return 403 with the correct error code

#### Scenario: Upstream unavailable test exists
- **WHEN** the regression test suite runs
- **THEN** at least one test SHALL verify that upstream auth unavailability returns 503 with the correct error code
