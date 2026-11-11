"""Proxy policy shared by every control-plane HTTP client.

DeerFlow reaches its own Gateway, provisioner and sandboxes over the deployment
network, not the public internet. When operators export ``HTTP_PROXY`` for
outbound model/tool traffic, those hops must not be sent through the proxy: the
proxy answers with its own 502/504 while the target is perfectly healthy
(#3441, #7876).

This module is deliberately dependency-free (no ``httpx``, no sandbox imports)
so that ``app.channels.manager``, ``app.gateway.health`` and the sandbox
backends can all import the policy without dragging in the sandbox provider
stack.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def control_plane_trust_env(url: str) -> bool:
    """Whether HTTP clients for *url* should inherit environment proxy settings.

    Local Docker, DooD, Kubernetes and co-located Gateway endpoints are
    control-plane connections, not internet traffic. External fully-qualified
    hosts retain normal environment proxy behavior.
    """
    try:
        hostname = (urlparse(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return True
    if not hostname:
        return True
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".docker.internal") or hostname.endswith(".containers.internal"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return "." in hostname
    return not (address.is_loopback or address.is_private or address.is_link_local)
