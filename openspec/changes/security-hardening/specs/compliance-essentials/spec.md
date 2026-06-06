## MODIFIED Requirements

### Requirement: Security response headers
The application SHALL include security-focused HTTP response headers on all responses to prevent common web vulnerabilities.

#### Scenario: Security headers on all responses
- **WHEN** any HTTP response is sent
- **THEN** the response includes the following headers:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `X-XSS-Protection: 1; mode=block`
  - `Content-Security-Policy: default-src 'self'`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)
  - `Referrer-Policy: strict-origin-when-cross-origin`

#### Scenario: HSTS header only on HTTPS
- **WHEN** the response is sent over HTTPS
- **THEN** the `Strict-Transport-Security` header is included

#### Scenario: HSTS header omitted on HTTP
- **WHEN** the response is sent over HTTP (development mode)
- **THEN** the `Strict-Transport-Security` header is NOT included
