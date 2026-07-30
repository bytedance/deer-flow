"""Shared URL safety checks for server-side web tools."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def resolve_host_addresses(hostname: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to all IP addresses for SSRF screening."""
    addresses: list[ipaddress._BaseAddress] = []
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return addresses
    for info in infos:
        sockaddr = info[4]
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return addresses


def is_blocked_address(address: ipaddress._BaseAddress) -> bool:
    """Return True for addresses web tools should not reach by default."""
    return address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified


def validate_public_http_url(
    url: str,
    *,
    allow_private_addresses: bool = False,
    action: str = "fetch",
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> str | None:
    """Validate an http(s) URL before a server-side web tool fetches it.

    Returns an ``"Error: ..."`` string when the URL should be rejected, or
    ``None`` when the caller may proceed.  The check is intentionally conservative
    for self-hosted fetch/render services because those services run inside the
    deployment network and can otherwise reach cloud metadata or private hosts.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Error: Only http:// and https:// URLs are supported"

    if allow_private_addresses:
        return None

    hostname = parsed.hostname
    if not hostname:
        return "Error: URL host could not be parsed"

    normalized_host = hostname.strip().rstrip(".").lower()
    if normalized_host in _BLOCKED_HOSTNAMES:
        return f"Error: Refusing to {action} a private or loopback address"

    try:
        literal_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        candidates = [literal_ip]
    else:
        resolve = resolver or resolve_host_addresses
        candidates = resolve(hostname)
        if not candidates:
            return "Error: URL host could not be resolved"

    if any(is_blocked_address(addr) for addr in candidates):
        return f"Error: Refusing to {action} a private, loopback, or metadata address"
    return None
