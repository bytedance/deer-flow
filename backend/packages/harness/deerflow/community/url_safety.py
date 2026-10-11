"""Shared URL safety checks for server-side web tools."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def resolve_host_addresses(hostname: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to all IP addresses for SSRF screening.

    Blocking: this is a synchronous DNS lookup, so async callers must run it
    (or :func:`validate_public_http_url`) via ``asyncio.to_thread``.
    """
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
    """Return True for addresses web tools should not reach by default.

    ``not is_global`` catches special-purpose ranges the individual flags miss,
    notably the 100.64.0.0/10 shared address space (CGNAT, Tailscale, and
    Alibaba Cloud's ``100.100.100.200`` instance metadata endpoint). The flags
    stay because some non-public forms still report ``is_global``, such as the
    NAT64 spelling of a metadata address (``64:ff9b::a9fe:a9fe``).
    """
    return not address.is_global or address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified


def resolve_public_addresses(
    hostname: str,
    *,
    action: str = "connect to",
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> list[ipaddress._BaseAddress]:
    """Resolve *hostname* once and return the addresses a connection may use.

    Raises ``ValueError`` carrying the same ``"Error: ..."`` message
    :func:`validate_public_http_url` returns when the host must be refused. A
    caller that connects to exactly these addresses, instead of resolving the
    name again at connect time, closes the DNS-rebinding window a check-only
    screen leaves open. Blocking like :func:`resolve_host_addresses`.
    """
    normalized_host = hostname.strip().rstrip(".").lower()
    if normalized_host in _BLOCKED_HOSTNAMES:
        raise ValueError(f"Error: Refusing to {action} a private or loopback address")

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
            raise ValueError("Error: URL host could not be resolved")

    if any(is_blocked_address(addr) for addr in candidates):
        raise ValueError(f"Error: Refusing to {action} a private, loopback, or metadata address")
    return candidates


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

    A hostname URL is resolved synchronously; from a coroutine, call this via
    ``asyncio.to_thread`` so a slow DNS answer cannot stall the event loop.

    The check runs at validation time only. A caller that connects later
    resolves the name again, so a rebinding DNS server can still hand that
    connect a private address unless the connection is pinned to the vetted
    IPs (:func:`resolve_public_addresses`), as ``deerflow.mcp.personal_network``
    and the browser egress proxy do. Delegated fetch services (Browserless,
    crawl4ai, fastcrw, firecrawl) resolve on their own side and cannot be pinned
    from here.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Error: Only http:// and https:// URLs are supported"

    if allow_private_addresses:
        return None

    hostname = parsed.hostname
    if not hostname:
        return "Error: URL host could not be parsed"

    try:
        resolve_public_addresses(hostname, action=action, resolver=resolver)
    except ValueError as exc:
        return str(exc)
    return None


def validate_delegated_backend_url(
    base_url: str,
    *,
    network_isolation_confirmed: bool = False,
    resolver: Callable[[str], list[ipaddress._BaseAddress]] | None = None,
) -> str | None:
    """Validate a delegated fetch backend's base URL before delegating navigation.

    Browserless, Crawl4AI, fastCRW, and Firecrawl resolve the target URL, follow
    redirects, and load subresources in the backend's own network namespace, so
    the target-URL screen in :func:`validate_public_http_url` cannot be enforced
    end-to-end. The only safe way to delegate is to ensure the backend's outbound
    network is isolated from the deployment's private and metadata networks.

    A backend reachable at a public address (for example Browserless Cloud) runs
    outside the deployment network, so delegation needs no extra confirmation. A
    backend at a loopback, private, or unverifiable address is self-hosted inside
    the deployment network, so this fails closed unless the operator confirms the
    backend's egress is isolated via ``network_isolation_confirmed=True``.

    The check resolves the backend hostname once, at validation time only. A
    backend client built afterwards connects by hostname and resolves the name
    again, so a DNS name that answers with a public address during screening and
    a private one at connect time still passes. Pin the connection to the vetted
    addresses (:func:`resolve_public_addresses`) to close that rebinding window.

    Returns an ``"Error: ..."`` string when delegation must be refused, or
    ``None`` when the caller may proceed. Blocking like
    :func:`resolve_public_addresses`; from a coroutine, call it via
    ``asyncio.to_thread``.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Error: Only http:// and https:// backend URLs are supported"

    if network_isolation_confirmed:
        return None

    hostname = parsed.hostname
    if not hostname:
        return "Error: Backend URL host could not be parsed"

    try:
        resolve_public_addresses(hostname, action="delegate to", resolver=resolver)
    except ValueError as exc:
        return f"{exc}. To delegate to a self-hosted backend, set network_isolation_confirmed: true."
    return None
