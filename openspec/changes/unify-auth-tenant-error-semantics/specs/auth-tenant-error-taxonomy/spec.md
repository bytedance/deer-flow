## ADDED Requirements

### Requirement: Error taxonomy distinguishes four categories
The system SHALL classify auth and tenant errors into exactly four user-distinguishable categories: invalid token, insufficient permission, tenant configuration error, and upstream auth unavailable.

#### Scenario: Invalid token is distinct
- **WHEN** a request carries an expired or malformed token
- **THEN** the response SHALL be HTTP 401 with an error code of AUTH_INVALID_TOKEN and a message directing the user to re-authenticate

#### Scenario: Insufficient permission is distinct
- **WHEN** a request carries a valid token but the user lacks required permission
- **THEN** the response SHALL be HTTP 403 with an error code of AUTH_FORBIDDEN and a message indicating which permission is missing

#### Scenario: Tenant configuration error is distinct
- **WHEN** a request fails due to misconfigured tenant settings
- **THEN** the response SHALL be HTTP 400 or 500 with an error code of TENANT_CONFIG_ERROR and a message directing the user to contact their tenant administrator

#### Scenario: Upstream auth unavailable is distinct
- **WHEN** an external auth service (e.g., InS-base RPC) is unreachable
- **THEN** the response SHALL be HTTP 503 with an error code of AUTH_UPSTREAM_UNAVAILABLE and a message asking the user to retry later
