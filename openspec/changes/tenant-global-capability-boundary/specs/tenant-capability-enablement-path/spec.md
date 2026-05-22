## ADDED Requirements

### Requirement: Tenant capability enablement path is verified
The system SHALL have at least one end-to-end verification path demonstrating a tenant enabling a capability.

#### Scenario: Tenant enables a capability end-to-end
- **WHEN** the verification test runs
- **THEN** it SHALL demonstrate the complete path: global capability exists → tenant inherits it → tenant creates an override → tenant uses the overridden capability → tenant disables the override → falls back to global configuration
