# Security Hardening — Low-Risk Improvements

## Why

Security audit of DeerFlow 2.0 fork identified opportunities to harden the system without breaking existing functionality. These improvements focus on defense-in-depth: tightening CORS policy, preventing brute force attacks, enabling token revocation, improving content safety failover, and adding security response headers.

All changes are configuration-driven or backward compatible — no breaking changes.

## What Changes

- CORS middleware narrows `allow_methods` and `allow_headers` from wildcards to explicit lists
- Login endpoints add per-IP and per-username rate limiting to prevent brute force attacks
- Refresh token revocation mechanism using Redis set (backward compatible with legacy tokens)
- Content safety moderation switches from fail-open to configurable fail-closed with local fallback
- Output guard middleware supports configurable `block_on_harmful` default via config
- Security response headers middleware adds X-Content-Type-Options, X-Frame-Options, CSP, HSTS

## Capabilities

### New Capabilities

- `auth-hardening`: Refresh token revocation, login brute force protection
- `content-safety-hardening`: Moderation fail-closed with fallback, output guard config defaults
- `cors-hardening`: CORS method and header narrowing from wildcards to explicit lists

### Modified Capabilities

- `compliance-essentials`: Security headers added

## Impact

### Backend Code

- `backend/app/gateway/app.py`: CORS narrowing, security headers middleware
- `backend/app/gateway/auth/jwt_handler.py`: refresh token jti claim, revocation API
- New: `backend/app/gateway/auth/login_rate_limit.py`: login-specific rate limiting
- `backend/packages/harness/deerflow/content_safety/builtin.py`: moderation fail-closed
- `backend/packages/harness/deerflow/content_safety/output_guard_middleware.py`: config-driven block_on_harmful

### Configuration

- `config.yaml`: `content_safety.output_block_on_harmful`, `content_safety.moderation_fail_mode`

### Dependencies

- Redis: optional for refresh token revocation (in-memory fallback for single-instance)
- No new external package dependencies

### API Changes

- Login endpoints: rate-limited (20/min per IP, 5/min per username)
- Refresh endpoint: rejects revoked tokens (401 with `token_revoked` error code)
- Legacy refresh tokens (without jti) are still accepted for backward compatibility

### Backward Compatibility

- All changes are configuration-driven or backward compatible
- No breaking changes to existing deployments
- Legacy refresh tokens continue to work
- Content safety defaults remain unchanged unless explicitly configured
