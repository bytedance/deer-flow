## ADDED Requirements

### Requirement: CORS method narrowing
The system SHALL restrict CORS `allow_methods` from wildcard `["*"]` to an explicit list: `["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]`.

#### Scenario: Allowed HTTP methods
- **WHEN** a cross-origin request uses methods GET, POST, PUT, DELETE, PATCH, or OPTIONS
- **THEN** the request is allowed (subject to other CORS checks)

#### Scenario: Disallowed HTTP method
- **WHEN** a cross-origin request uses a method not in the allowed list (e.g., TRACE, CONNECT)
- **THEN** the browser blocks the request (CORS preflight fails)

### Requirement: CORS header narrowing
The system SHALL restrict CORS `allow_headers` from wildcard `["*"]` to an explicit list: `["Authorization", "Content-Type", "X-CSRF-Token", "X-DeerFlow-Tenant", "X-EHM-Token"]`.

#### Scenario: Allowed headers
- **WHEN** a cross-origin request includes headers from the allowed list
- **THEN** the request is allowed (subject to other CORS checks)

#### Scenario: Disallowed header
- **WHEN** a cross-origin request includes a header not in the allowed list (e.g., "X-Custom-Header")
- **THEN** the browser blocks the request (CORS preflight fails)
- **AND** the error message indicates which header is not allowed

### Requirement: CORS configuration via environment variable
The system SHALL continue to support CORS origin configuration via `GATEWAY_CORS_ORIGINS` environment variable. Wildcard `*` origin SHALL be rejected when `allow_credentials=True`.

#### Scenario: Valid CORS origins
- **WHEN** `GATEWAY_CORS_ORIGINS=http://localhost:3000,https://app.example.com`
- **THEN** the system configures CORS with these origins
- **AND** credentials are allowed

#### Scenario: Wildcard origin rejected
- **WHEN** `GATEWAY_CORS_ORIGINS=*`
- **AND** `allow_credentials=True`
- **THEN** the system logs an error: "GATEWAY_CORS_ORIGINS contains wildcard '*' with allow_credentials=True. This is a security misconfiguration."
- **AND** the wildcard origin is removed from the list
- **AND** CORS is not configured (no origins remain)
