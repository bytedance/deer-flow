"""Exercise personal MCP policy through the real HTTP transport and TLS boundary."""

import ipaddress
import socket

import httpcore
import pytest
from httpcore._backends.anyio import AnyIOBackend

from deerflow.mcp.personal_network import personal_httpx_client_factory


class RecordingStream(httpcore.AsyncNetworkStream):
    def __init__(self):
        self.writes = []
        self.tls_hosts = []
        self.closed = False

    async def read(self, max_bytes, timeout=None):
        return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def aclose(self):
        self.closed = True

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        assert ssl_context.check_hostname
        self.tls_hosts.append(server_hostname)
        return self


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_personal_transport_pins_dns_and_preserves_authority(monkeypatch, scheme):
    lookups = []
    connections = []
    streams = []
    real_resolve = socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        if host == "mcp.example":
            address = "8.8.8.8" if not lookups else "127.0.0.1"
            lookups.append(address)
            return real_resolve(address, port, *args, **kwargs)
        return real_resolve(host, port, *args, **kwargs)

    async def connect(self, host, port, **kwargs):
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        connections.append((host, addresses[0][4][0]))
        stream = RecordingStream()
        streams.append(stream)
        return stream

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    async with personal_httpx_client_factory(headers={"Authorization": "Bearer test"}) as client:
        response = await client.post(f"{scheme}://mcp.example:8443/mcp?session=1", content=b"payload")
        assert response.text == "ok"
        assert str(response.request.url) == f"{scheme}://mcp.example:8443/mcp?session=1"
        assert connections == [("8.8.8.8", "8.8.8.8")]
        assert lookups == ["8.8.8.8"]
        wire = b"".join(streams[0].writes)
        assert b"POST /mcp?session=1 HTTP/1.1" in wire
        assert b"Host: mcp.example:8443" in wire
        assert b"Authorization: Bearer test" in wire
        assert b"payload" in wire
        assert streams[0].tls_hosts == (["mcp.example"] if scheme == "https" else [])
        with pytest.raises(ValueError, match="public HTTP"):
            await client.get(f"{scheme}://mcp.example:8443/mcp")
        assert len(connections) == 1
    assert all(stream.closed for stream in streams)


@pytest.mark.asyncio
async def test_personal_transport_does_not_share_tls_across_hostnames(monkeypatch):
    streams = []
    real_resolve = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *args, **kwargs: real_resolve("8.8.8.8", port, *args, **kwargs))

    async def connect(self, host, port, **kwargs):
        stream = RecordingStream()
        streams.append(stream)
        return stream

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    async with personal_httpx_client_factory() as client:
        for host in ("first.example", "second.example"):
            assert (await client.get(f"https://{host}/mcp")).status_code == 200
    assert [stream.tls_hosts for stream in streams] == [["first.example"], ["second.example"]]
    assert all(stream.closed for stream in streams)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
async def test_personal_transport_blocks_private_addresses_before_connect(monkeypatch, address):
    real_resolve = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *args, **kwargs: real_resolve(address, port, *args, **kwargs))

    async def connect(*args, **kwargs):
        pytest.fail("Private address reached TCP connect")

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    async with personal_httpx_client_factory() as client:
        with pytest.raises(ValueError, match="public HTTP"):
            await client.get("https://mcp.example/mcp")


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [[], ["8.8.8.8", "127.0.0.1"], ["2606:4700:4700::1111", "::1"]])
async def test_personal_transport_rejects_empty_or_mixed_dns_answers(monkeypatch, addresses):
    monkeypatch.setattr("deerflow.mcp.personal_network.resolve_host_addresses", lambda host: [ipaddress.ip_address(address) for address in addresses])

    async def connect(*args, **kwargs):
        pytest.fail("Rejected DNS answers reached TCP connect")

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    async with personal_httpx_client_factory() as client:
        with pytest.raises(ValueError, match="public HTTP"):
            await client.get("https://mcp.example/mcp")


@pytest.mark.asyncio
async def test_personal_transport_tries_only_vetted_addresses(monkeypatch):
    addresses = ["2606:4700:4700::1111", "8.8.8.8"]
    monkeypatch.setattr("deerflow.mcp.personal_network.resolve_host_addresses", lambda host: [ipaddress.ip_address(address) for address in addresses])
    attempts = []

    async def connect(self, host, port, **kwargs):
        attempts.append(host)
        if host == addresses[0]:
            raise httpcore.ConnectError("IPv6 unavailable")
        return RecordingStream()

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    async with personal_httpx_client_factory() as client:
        assert (await client.get("https://mcp.example/mcp")).status_code == 200
    assert attempts == addresses


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["8.8.8.8", "[2606:4700:4700::1111]"])
async def test_personal_transport_accepts_public_literal_ips(monkeypatch, address):
    attempts = []

    async def connect(self, host, port, **kwargs):
        attempts.append(host)
        return RecordingStream()

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", connect)
    async with personal_httpx_client_factory() as client:
        assert (await client.get(f"http://{address}/mcp")).status_code == 200
    assert attempts == [address.strip("[]")]
