## 1. Security Response Headers

- [ ] 1.1 Add SecurityHeadersMiddleware with X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, CSP, Referrer-Policy
- [ ] 1.2 Add Strict-Transport-Security header only on HTTPS responses
- [ ] 1.3 Write integration test for security headers on all responses

## 2. Content Safety Hardening

- [ ] 2.1 Add fail_mode parameter to OpenAIModerationProvider: "closed", "fallback", "open" (default "fallback")
- [ ] 2.2 Implement local keyword fallback check for moderation API failures
- [ ] 2.3 Add configurable fallback keyword list with violence, self-harm, industrial safety terms
- [ ] 2.4 Write unit tests for moderation fail modes (closed, fallback with keywords, fallback without keywords, open)
- [ ] 2.5 Change OutputGuardMiddleware default block_on_harmful to true (read from config if not explicitly set)
- [ ] 2.6 Add config flag content_safety.output_block_on_harmful (default true)
- [ ] 2.7 Write unit tests for output guard default behavior (blocks by default, allows when disabled)

## 3. Refresh Token Revocation

- [ ] 3.1 Add jti (JWT ID) claim to refresh tokens using secrets.token_urlsafe(16)
- [ ] 3.2 Implement refresh token revocation API using Redis set (key: revoked_refresh_tokens:{user_id}, TTL: 7 days)
- [ ] 3.3 Add in-memory fallback for refresh token revocation when Redis is not available
- [ ] 3.4 Update refresh endpoint to check if token jti is in revocation list before issuing new access token
- [ ] 3.5 Implement revoke_all_refresh_tokens(user_id) called on password change
- [ ] 3.6 Write unit tests for refresh token revocation (revoke on password change, reject revoked token, TTL cleanup)

## 4. CORS Hardening

- [ ] 4.1 Narrow CORS allow_methods from ["*"] to ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
- [ ] 4.2 Narrow CORS allow_headers from ["*"] to ["Authorization", "Content-Type", "X-CSRF-Token", "X-DeerFlow-Tenant", "X-EHM-Token"]
- [ ] 4.3 Write integration test for CORS narrowing (allowed methods/headers, disallowed methods/headers)

## 5. Login Rate Limiting

- [ ] 5.1 Implement login rate limiting with composite key: login:{ip}:{username} → 5/min
- [ ] 5.2 Implement login rate limiting with composite key: login:{ip}:* → 20/min
- [ ] 5.3 Add rate limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset) to login responses
- [ ] 5.4 Reset failed login counter on successful login
- [ ] 5.5 Write unit tests for login rate limiting (per-username limit, per-IP limit, successful login resets counter)

## 6. Configuration and Documentation

- [ ] 6.1 Add content_safety.output_block_on_harmful to config.yaml with default true
- [ ] 6.2 Add content_safety.moderation_fail_mode to config.yaml with default "fallback"
- [ ] 6.3 Update config.example.yaml with all new security config flags and comments
- [ ] 6.4 Update API documentation with new login rate limiting behavior
- [ ] 6.5 Update API documentation with refresh token revocation error code (token_revoked)
- [ ] 6.6 Write security hardening release notes with all changes and migration steps

## 7. Testing and Validation

- [ ] 7.1 Run full security test suite against staging environment
- [ ] 7.2 Test moderation fail-closed behavior during simulated API outage
- [ ] 7.3 Test refresh token revocation flow (password change, admin revocation, token reuse)
- [ ] 7.4 Validate CORS narrowing doesn't break frontend integrations
- [ ] 7.5 Test login rate limiting with simulated brute force attacks
- [ ] 7.6 Monitor staging environment for 1 week after deployment
- [ ] 7.7 Deploy to production with feature flags disabled
- [ ] 7.8 Enable features one by one with monitoring
- [ ] 7.9 Full production rollout after 2 weeks of monitoring

## 8. Rollback and Recovery

- [ ] 8.1 Document rollback procedure for each feature (config-based disable)
- [ ] 8.2 Test rollback procedure in staging environment
- [ ] 8.3 Prepare config flags for gradual feature rollout (enable/disable without code deploy)
- [ ] 8.4 Create monitoring alerts for security-related errors (auth failures, rate limits, moderation blocks)
- [ ] 8.5 Prepare incident response plan for security hardening issues
