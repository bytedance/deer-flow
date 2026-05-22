## ADDED Requirements

### Requirement: Error codes are consistent across entry points
The system SHALL return consistent HTTP status codes and error codes across all API entry points for the same error condition.

#### Scenario: Same error returns same codes from any entry
- **WHEN** an auth or tenant error occurs
- **THEN** the HTTP status code and error code SHALL be identical regardless of which API endpoint or service was called

### Requirement: Logs reflect root cause
The system SHALL log the root cause of auth and tenant errors, not just the surface HTTP status.

#### Scenario: Log includes root cause detail
- **WHEN** an upstream auth service is unavailable
- **THEN** the log entry SHALL include the upstream service name, the raw error, and the translated error code, enabling operators to distinguish it from other 503 scenarios
