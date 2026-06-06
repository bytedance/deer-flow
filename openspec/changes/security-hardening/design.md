# Security Hardening — Design

## Context

DeerFlow 2.0 fork (EHM AI Workbench) has a multi-layer security architecture: JWT/API Key authentication, CSRF Double Submit Cookie, Input/Output content safety guards, prompt injection detection, tool guardrails, sandbox execution, and rate limiting. A security audit identified hardening opportunities across configuration defaults and missing defense-in-depth layers.

All changes in this proposal are **low-impact, non-breaking** — they are configuration-driven or add new capabilities that do not affect existing workflows. No P0 vulnerability fixes are in scope (those require breaking changes and are deferred).

Constraints: backward compatibility with existing deployments; no new external package dependencies; Redis is already available in production but single-instance deployments need in-memory fallback.

## Goals / Non-Goals

**Goals:**

- Add defense-in-depth layers: security response headers, content safety fail-closed, login brute force protection, refresh token revocation
- Make secure defaults the path of least resistance (explicit CORS lists, fail-closed moderation)
- Maintain full backward compatibility — no breaking changes to existing deployments

**Non-Goals:**

- JWT secret validation (breaking change for deployments with empty secrets — deferred)
- CSRF ehm_token bypass fix (requires frontend code changes — deferred)
- Role-based permissions (current role model uses superadmin/tenant_admin/user — deferred)
- Prompt injection LLM detection (adds latency/cost — deferred)
- Internal token file isolation (affects 4+ scripts — deferred)
- OAuth2/OIDC provider integration
- Full RBAC with custom role creation

## Decisions

### D1: Moderation fail-closed with local keyword fallback

**Choice**: When OpenAI Moderation API is unavailable, behavior depends on `content_safety.moderation_fail_mode`:

- `"closed"`: block all content (safest, but may cause false positives)
- `"fallback"`: use local keyword list (balanced, catches obvious violations)
- `"open"`: allow all content (current behavior, for backward compatibility)

Default is `"fallback"` with a built-in keyword list covering violence, self-harm, and industrial safety terms.

**Alternatives considered**:

- Always fail-closed: may block legitimate content during API outages
- Always fail-open: current vulnerability, allows harmful content during outages
- Retry with exponential backoff: adds latency, doesn't solve permanent outage

**Rationale**: The fallback mode provides a middle ground: local keywords catch obvious violations without relying on external API. The keyword list is configurable, allowing deployments to add domain-specific terms. The `"open"` mode is preserved for backward compatibility but logs a warning.

### D2: Refresh token revocation via Redis set

**Choice**: Store revoked token `jti` (JWT ID) claims in a Redis set keyed by `user_id`. TTL matches refresh token lifetime (7 days). Fallback to in-memory set for single-instance deployments.

**Alternatives considered**:

- Database `token_invalidated_at` column: requires schema migration, slower, doesn't handle per-token revocation
- Token blacklist in database: same issues
- Short-lived refresh tokens (e.g., 1 hour): reduces attack window but increases refresh frequency, degrades UX

**Rationale**: Redis set provides O(1) lookup with automatic TTL expiration. The `jti` claim uniquely identifies each refresh token, allowing granular revocation. The in-memory fallback ensures single-instance deployments don't require Redis setup.

### D3: CORS narrowing with explicit lists

**Choice**: Replace `allow_methods=["*"]` with `["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]` and `allow_headers=["*"]` with explicit list including `Authorization`, `Content-Type`, `X-CSRF-Token`, `X-DeerFlow-Tenant`, `X-EHM-Token`.

**Alternatives considered**:

- Keep wildcards: security issue, allows unexpected methods/headers
- Remove all methods except GET/POST: breaks PUT/DELETE/PATCH routes
- Configure via YAML: adds complexity, most deployments don't need customization

**Rationale**: Explicit lists follow the principle of least privilege. The chosen methods cover all REST operations used by the API. The header list includes all headers currently set by frontend/backend code. This is a one-time change; if new headers are needed, they're added to the list with a code change.

### D4: Login rate limiting with composite key

**Choice**: Rate limit login endpoints with two composite keys:

- `login:{ip}:{username}` → 5/min (prevents brute force against specific account)
- `login:{ip}:*` → 20/min (prevents distributed attack from single IP)

**Alternatives considered**:

- IP-only rate limiting: doesn't prevent slow brute force (1 attempt per minute)
- Username-only rate limiting: doesn't prevent IP-based attacks
- CAPTCHA after N failures: adds frontend complexity, may degrade UX

**Rationale**: Composite keys address both attack vectors: targeted brute force and IP-based attacks. The limits are conservative to avoid blocking legitimate users who mistype passwords. CAPTCHA is deferred to a future sprint if rate limiting proves insufficient.

### D5: Security response headers middleware

**Choice**: Add middleware that sets security response headers on all responses:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy: default-src 'self'`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)
- `Referrer-Policy: strict-origin-when-cross-origin`

**Alternatives considered**:

- No headers: leaves application vulnerable to clickjacking, MIME sniffing, XSS
- Nonce-based CSP: requires backend nonce generation and frontend script tag changes — too complex for initial hardening
- Per-route CSP: adds complexity, most routes share the same policy

**Rationale**: Standard security headers provide defense-in-depth with zero impact on existing functionality. HSTS is only set on HTTPS responses to avoid breaking HTTP development mode. CSP is set to `default-src 'self'` which is safe for an API-only application. Nonce-based CSP is deferred.

### D6: Output guard default config

**Choice**: Change `OutputGuardMiddleware` default `block_on_harmful` from `false` to `true`, read from config (`content_safety.output_block_on_harmful`).

**Alternatives considered**:

- Keep default `false`: harmful content passes through unless explicitly blocked
- Hard-code `true`: no way to override for deployments that don't want blocking
- Make it per-route: too complex, output guard should be global

**Rationale**: Defaulting to `true` follows the principle of fail-safe defaults. The config flag allows deployments to override if needed. This is not a breaking change because the middleware already exists — only the default value changes.

## Risks / Trade-offs

### R1: Moderation fail-closed may block legitimate content during API outages

**Risk**: OpenAI Moderation API outage causes all content to be blocked when mode is `"closed"`.

**Mitigation**:

- Default mode is `"fallback"` (local keyword check), not `"closed"`
- Local keyword list is conservative (only obvious violations)
- Deployments can switch to `"open"` mode if false positives are unacceptable
- Monitoring alerts on Moderation API failure rate

### R2: Refresh token revocation requires Redis (optional)

**Risk**: Single-instance deployments without Redis can't use token revocation.

**Mitigation**:

- In-memory fallback for single-instance (revocation list lost on restart)
- Documentation recommends Redis for production multi-instance deployments
- Warning log when Redis is not configured and revocation is attempted

### R3: CORS narrowing may break frontend integrations using non-standard headers

**Risk**: Frontend code using headers not in the explicit list will get CORS errors.

**Mitigation**:

- Header list includes all headers currently used by frontend/backend code
- Error message clearly indicates which header is blocked
- Adding new headers requires code change (ensures review)

### R4: Login rate limiting may block legitimate users with shared IPs

**Risk**: Corporate NAT / proxy causes multiple users to share one IP, hitting the 20/min limit.

**Mitigation**:

- Per-username limit (5/min) is the primary defense; per-IP limit (20/min) is secondary
- 20/min is generous enough for shared IPs (20 different users can login per minute)
- Rate limit headers (`X-RateLimit-Remaining`) help diagnose issues
- Admin can adjust limits via config if needed

### R5: Output guard default `true` may block legitimate content

**Risk**: Changing default to `block_on_harmful=true` may flag legitimate industrial content as harmful.

**Mitigation**:

- Config flag allows disabling: `content_safety.output_block_on_harmful=false`
- Content safety pipeline already exists — only the default changes
- Monitor blocked content logs for false positives

## Migration Plan

### Single Phase: All hardening changes (1-2 weeks)

All 7 changes are non-breaking and can be deployed together:

1. Deploy to staging environment
2. Run security test suite
3. Enable features one by one with monitoring:
   - Security response headers (immediate, zero risk)
   - CORS narrowing (verify frontend still works)
   - Output guard default `true` (monitor blocked content)
   - Moderation fail-closed with fallback (monitor moderation API failures)
   - Login rate limiting (monitor 429 responses)
   - Refresh token revocation (Redis setup required for multi-instance)
4. Monitor staging for 3-5 days
5. Deploy to production with same gradual enablement

**Rollback**: Each feature is independently configurable — disable via config flags without code deploy.

### Deployment order

1. Deploy to staging environment
2. Run security test suite
3. Monitor staging for 3-5 days
4. Deploy to production with feature flags disabled
5. Enable features one by one with monitoring
6. Full rollout after 1 week of production monitoring

## Open Questions

### Q1: Should we implement token rotation for access tokens (not just refresh tokens)?

**Context**: Access tokens are currently valid until expiration (24h). Rotation would invalidate them after first use.

**Decision needed**: Is the added complexity (token reuse detection, blacklist) worth the security benefit for industrial deployments?

### Q2: Should we implement audit log streaming to external SIEM (e.g., Splunk, ELK)?

**Context**: Audit logs are currently stored in-memory (or database if configured). Security teams often require real-time streaming to SIEM.

**Decision needed**: Is this in scope for security hardening, or is it a separate initiative?

### Q3: Should we implement Content Security Policy (CSP) with nonce-based script loading?

**Context**: Current CSP header is basic (`default-src 'self'`). Nonce-based CSP would prevent XSS but requires backend to generate nonces and frontend to include them in script tags.

**Decision needed**: Is the XSS risk high enough to justify the implementation complexity?
