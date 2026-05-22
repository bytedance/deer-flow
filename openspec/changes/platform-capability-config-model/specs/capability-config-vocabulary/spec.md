## ADDED Requirements

### Requirement: Unified configuration vocabulary exists
The system SHALL define a unified configuration and publishing vocabulary covering Models, Skills, MCPs, Connectors, and Agents.

#### Scenario: All five types use the same base terms
- **WHEN** a platform configurator reads the governance documentation
- **THEN** the terms for scope, status, version, owner, and audit SHALL have identical meanings across all five capability types

#### Scenario: Each type has defined extension fields
- **WHEN** a capability type requires type-specific configuration
- **THEN** the extension fields SHALL be defined within the unified model framework rather than as an independent schema
