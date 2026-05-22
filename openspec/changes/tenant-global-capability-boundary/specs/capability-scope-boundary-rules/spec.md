## ADDED Requirements

### Requirement: Scope boundary rules are defined
The system SHALL define and enforce clear rules for capability enablement, inheritance, override, and deactivation across global and tenant scopes.

#### Scenario: Tenant inherits global capability by default
- **WHEN** a global capability is published
- **THEN** all tenants SHALL inherit it automatically with the global configuration

#### Scenario: Tenant can override global capability
- **WHEN** a tenant needs custom configuration for a global capability
- **THEN** the tenant SHALL be able to create a TENANT_OVERRIDE that only overrides specified fields

#### Scenario: Global deactivation propagates
- **WHEN** a global capability is deactivated
- **THEN** all tenants inheriting it SHALL also lose access, unless they have an explicit TENANT_OVERRIDE that remains active
