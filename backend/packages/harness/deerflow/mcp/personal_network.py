"""Public-network policy for non-operator personal HTTP MCP connections."""

import asyncio
import ipaddress

import httpx

from deerflow.community.url_safety import resolve_host_addresses, validate_public_http_url


def _public_addresses(url: httpx.URL) -> list[str]:
    addresses = []

    def resolve(host):
        candidates = resolve_host_addresses(host)
        addresses.extend(str(address) for address in candidates)
        return candidates

    if validate_public_http_url(str(url), action="connect to", resolver=resolve):
        raise ValueError("Personal MCP connections require a public HTTP(S) endpoint")
    # Literal IP URLs are validated without calling the resolver.
    return list(dict.fromkeys(addresses)) if addresses else [str(ipaddress.ip_address(url.host))]


class _PersonalTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self._ssl_context = httpx.create_ssl_context(trust_env=False)
        self._transports: dict[tuple[bytes, bytes, int | None], httpx.AsyncHTTPTransport] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        addresses = await asyncio.to_thread(_public_addresses, request.url)
        origin = (request.url.raw_scheme, request.url.raw_host, request.url.port)
        # Pin TCP to the vetted IP, but isolate pools by original origin so two
        # names sharing an IP cannot reuse a connection authenticated for one.
        if origin not in self._transports:
            self._transports[origin] = httpx.AsyncHTTPTransport(verify=self._ssl_context, trust_env=False)
        transport = self._transports[origin]
        for index, address in enumerate(addresses):
            pinned = httpx.Request(
                request.method,
                request.url.copy_with(host=address),
                headers=request.headers,
                stream=request.stream,
                extensions={**request.extensions, "sni_hostname": request.url.raw_host.decode("ascii")},
            )
            try:
                return await transport.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if index == len(addresses) - 1:
                    raise
        raise AssertionError("Public address validation returned no addresses")

    async def aclose(self):
        for transport in self._transports.values():
            await transport.aclose()


def personal_httpx_client_factory(headers=None, timeout=None, auth=None):
    kwargs = {"headers": headers, "auth": auth, "follow_redirects": False, "trust_env": False, "transport": _PersonalTransport()}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return httpx.AsyncClient(**kwargs)
