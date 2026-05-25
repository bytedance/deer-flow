## ADDED Requirements

### Requirement: Unified list view shows all capability types
The system SHALL provide a unified list view that displays all five capability types (Models, Skills, MCPs, Connectors, Agents) with their key status.

#### Scenario: Configurator browses all capabilities by type
- **WHEN** a platform configurator opens the unified capability view
- **THEN** they SHALL see capabilities organized by type (tab or filter) with each item showing its name, type, scope, status, and owner

#### Scenario: Configurator filters by scope
- **WHEN** a configurator wants to see only tenant-level capabilities
- **THEN** the view SHALL support filtering by scope (GLOBAL, TENANT, TENANT_OVERRIDE)
