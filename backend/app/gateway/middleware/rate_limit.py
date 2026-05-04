"""Rate limiting middleware for the Gateway API.

Uses ``slowapi`` with an in-memory backend by default; Redis is supported
for distributed deployments.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from deerflow.config.rate_limit_config import get_rate_limit_config

logger = logging.getLogger(__name__)


def _make_key(request: Request) -> str:
    """Build a composite rate-limit key from client IP and tenant ID."""
    from deerflow.config.tenant import get_current_tenant_id

    ip = get_remote_address(request)
    try:
        tenant_id = get_current_tenant_id()
    except Exception:
        tenant_id = "default"
    return f"{ip}:{tenant_id}"


def create_rate_limit_middleware(app: FastAPI) -> None:
    """Register rate limiting middleware on the FastAPI application.

    When ``rate_limit.enabled`` is False, this is a no-op.
    """
    config = get_rate_limit_config()
    if not config.enabled:
        return

    storage_uri: str | None = None
    if config.backend == "redis" and config.redis_url:
        storage_uri = config.redis_url

    limiter = Limiter(
        key_func=_make_key,
        default_limits=[f"{config.global_per_minute}/minute"],
        storage_uri=storage_uri,
    )

    # Register per-endpoint limits
    for ep in config.endpoints:
        limiter.add_limit(ep.path, ep.limit)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    logger.info(
        "Rate limiting enabled (backend=%s, global=%d/min, tenant=%d/min)",
        config.backend,
        config.global_per_minute,
        config.tenant_per_minute,
    )


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> dict:
    """Return a 429 JSON response with Retry-After and X-RateLimit-* headers."""
    from fastapi.responses import JSONResponse

    retry_after = exc.retry_after if hasattr(exc, "retry_after") else 60
    limit = getattr(exc, "limit", None)
    limit_str = str(limit.limit) if limit and hasattr(limit, "limit") else "unknown"

    headers = {
        "Retry-After": str(retry_after),
        "X-RateLimit-Limit": limit_str,
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(retry_after),
    }
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded", "retry_after_seconds": retry_after},
        headers=headers,
    )
