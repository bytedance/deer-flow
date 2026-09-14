"""Trusted-proxy client-IP resolution for per-IP throttling.

Shared by the login rate limiter (``routers/auth.py``) and the public
share-resolution throttle (``routers/shares.py``) so one deployment-level
trust decision — ``AUTH_TRUSTED_PROXIES`` — covers every per-IP limiter
behind the same reverse proxy.
"""

from __future__ import annotations

import logging
import os
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

from starlette.requests import Request

logger = logging.getLogger(__name__)


def trusted_proxies() -> list[IPv4Network | IPv6Network]:
    """Parse ``AUTH_TRUSTED_PROXIES`` env var into a list of ip_network objects.

    Comma-separated CIDR or single-IP entries. Empty / unset = no proxy is
    trusted (direct mode). Invalid entries are skipped with a logger warning.
    Read live so env-var overrides take effect immediately and tests can
    ``monkeypatch.setenv`` without poking a module-level cache.
    """
    raw = os.getenv("AUTH_TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    nets: list[IPv4Network | IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ip_network(entry, strict=False))
        except ValueError:
            logger.warning("AUTH_TRUSTED_PROXIES: ignoring invalid entry %r", entry)
    return nets


def get_client_ip(request: Request) -> str:
    """Extract the real client IP for rate limiting.

    Trust model:

    - The TCP peer (``request.client.host``) is always the baseline. It is
      whatever the kernel reports as the connecting socket — unforgeable
      by the client itself.
    - ``X-Real-IP`` is **only** honored if the TCP peer is in the
      ``AUTH_TRUSTED_PROXIES`` allowlist (set via env var, comma-separated
      CIDR or single IPs). When set, the gateway is assumed to be behind a
      reverse proxy (nginx, Cloudflare, ALB, …) that overwrites
      ``X-Real-IP`` with the original client address.
    - With no ``AUTH_TRUSTED_PROXIES`` set, ``X-Real-IP`` is silently
      ignored — closing the bypass where any client could rotate the
      header to dodge per-IP rate limits in dev / direct-gateway mode.

    ``X-Forwarded-For`` is intentionally NOT used because it is naturally
    client-controlled at the *first* hop and the trust chain is harder to
    audit per-request.

    Deployments that front the Gateway with the shipped nginx without
    setting ``AUTH_TRUSTED_PROXIES`` resolve every request to the proxy's
    address, so per-IP limiters keyed on this value share a single bucket —
    set the variable to the proxy network before relying on per-IP limits.
    """
    peer_host = request.client.host if request.client else None

    trusted = trusted_proxies()
    if trusted and peer_host:
        try:
            peer_ip = ip_address(peer_host)
            if any(peer_ip in net for net in trusted):
                real_ip = request.headers.get("x-real-ip", "").strip()
                if real_ip:
                    return real_ip
        except ValueError:
            # peer_host wasn't a parseable IP (e.g. "unknown") — fall through
            pass

    return peer_host or "unknown"
