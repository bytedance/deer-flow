## ADDED Requirements

### Requirement: Refresh token revocation mechanism
The system SHALL support revoking refresh tokens before their natural expiration. Revoked tokens SHALL be stored in a Redis set (or in-memory fallback) and checked during token refresh operations.

#### Scenario: Revoke refresh token on password change
- **WHEN** a user changes their password
- **THEN** all refresh tokens for that user are revoked
- **AND** subsequent refresh attempts with revoked tokens are rejected with error code `token_revoked`

#### Scenario: Revoke specific refresh token
- **WHEN** an administrator revokes a specific refresh token (by `jti` claim)
- **THEN** that refresh token is added to the revocation list
- **AND** subsequent refresh attempts with that token are rejected

#### Scenario: Refresh with revoked token
- **WHEN** a user attempts to refresh their access token
- **AND** the refresh token's `jti` claim is in the revocation list
- **THEN** the system rejects the refresh request with error code `token_revoked`
- **AND** returns HTTP 401

#### Scenario: Revocation list cleanup
- **WHEN** a revoked token's TTL (7 days) expires
- **THEN** the token is automatically removed from the revocation list (via Redis TTL)

### Requirement: Login brute force protection
The system SHALL rate-limit login attempts to prevent brute force attacks. Limits SHALL be enforced per-IP and per-username using composite keys.

#### Scenario: Per-username rate limit
- **WHEN** a user attempts to login
- **AND** the same username has had 5 or more failed login attempts in the last minute from any IP
- **THEN** the system rejects the login attempt with HTTP 429 (Too Many Requests)
- **AND** returns `Retry-After` header with remaining wait time

#### Scenario: Per-IP rate limit
- **WHEN** a user attempts to login
- **AND** the same IP address has had 20 or more login attempts (success or failure) in the last minute
- **THEN** the system rejects the login attempt with HTTP 429
- **AND** returns `Retry-After` header

#### Scenario: Successful login resets counter
- **WHEN** a user successfully logs in
- **THEN** the failed login counter for that username is reset

#### Scenario: Rate limit headers
- **WHEN** a login attempt is made
- **THEN** the response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers
