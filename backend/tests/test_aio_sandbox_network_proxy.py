from __future__ import annotations

import asyncio
import json
import socket
import ssl
from unittest.mock import MagicMock

import pytest

from deerflow.community.aio_sandbox import network_proxy


def test_domain_matches_exact_and_leading_wildcard_only() -> None:
    assert network_proxy.domain_matches("pypi.org", "pypi.org")
    assert not network_proxy.domain_matches("evilpypi.org", "pypi.org")
    assert network_proxy.domain_matches("files.pythonhosted.org", "*.pythonhosted.org")
    assert not network_proxy.domain_matches("pythonhosted.org", "*.pythonhosted.org")


def test_address_is_public_rejects_host_private_link_local_and_metadata() -> None:
    for address in (
        "127.0.0.1",
        "10.0.0.2",
        "172.16.0.2",
        "192.168.1.2",
        "169.254.169.254",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fec0::1",
        "fe80::1",
        "ff0e::1",
    ):
        assert not network_proxy.address_is_public(address)
    assert network_proxy.address_is_public("8.8.8.8")
    assert not network_proxy.address_is_public("198.18.1.5")
    assert network_proxy.address_is_public("198.18.1.5", allow_synthetic_dns=True)


def test_policy_denial_and_temporary_or_sandbox_grants(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", "allowlist")
    monkeypatch.setenv("DEERFLOW_ALLOW_DOMAINS_JSON", json.dumps(["pypi.org"]))

    assert network_proxy.policy_allows("pypi.org", 443, now=100)
    assert not network_proxy.policy_allows("example.com", 443, now=100)

    temporary = network_proxy.record_denial("example.com", 443, "CONNECT")
    assert network_proxy.decide(temporary, "allow_temporary", ttl=60)
    assert network_proxy.policy_allows("example.com", 443)

    sandbox = network_proxy.record_denial("files.example.net", 443, "CONNECT")
    assert network_proxy.decide(sandbox, "allow_sandbox", ttl=60)
    assert network_proxy.policy_allows("files.example.net", 443, now=10**12)


def test_pending_events_are_consumed_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    request_id = network_proxy.record_denial("example.com", 443, "CONNECT")

    events = network_proxy.pending_events()

    assert events == [
        {
            "request_id": request_id,
            "host": "example.com",
            "port": 443,
            "method": "CONNECT",
            "created_at": events[0]["created_at"],
        }
    ]
    assert network_proxy.pending_events() == []


def test_pending_events_surface_only_one_destination_per_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    first = network_proxy.record_denial("one.example", 443, "CONNECT")
    network_proxy.record_denial("two.example", 443, "CONNECT")

    assert [event["request_id"] for event in network_proxy.pending_events()] == [first]
    # The sibling is superseded so a retry can create a fresh approvable event.
    assert network_proxy.pending_events() == []
    fresh = network_proxy.record_denial("two.example", 443, "CONNECT")
    assert [event["request_id"] for event in network_proxy.pending_events()] == [fresh]


def test_pending_events_supersede_every_sibling_without_a_batch_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    request_ids = [network_proxy.record_denial(f"host-{index}.example", 443, "CONNECT") for index in range(17)]

    assert [event["request_id"] for event in network_proxy.pending_events()] == [request_ids[0]]
    assert network_proxy.pending_events() == []


def test_deny_pending_events_atomically_denies_every_unsurfaced_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    for index in range(17):
        network_proxy.record_denial(f"host-{index}.example", 443, "CONNECT")

    assert network_proxy.deny_pending_events() == 17
    assert network_proxy.pending_events() == []

    with network_proxy._connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE decision = 'deny'").fetchone() == (17,)


def test_deny_pending_events_preserves_an_already_surfaced_user_decision(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    surfaced = network_proxy.record_denial("interactive.example", 443, "CONNECT")
    assert [event["request_id"] for event in network_proxy.pending_events()] == [surfaced]
    unsurfaced = network_proxy.record_denial("scheduled.example", 443, "CONNECT")

    assert network_proxy.deny_pending_events() == 1
    assert network_proxy.decide(surfaced, "allow_temporary", ttl=60)
    assert network_proxy.decide(unsurfaced, "deny", ttl=60)


def test_pending_events_claims_old_unsurfaced_denial_on_retry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    now = [100.0]
    monkeypatch.setattr(network_proxy.time, "time", lambda: now[0])
    request_id = network_proxy.record_denial("late.example", 443, "CONNECT")

    now[0] = 105.0
    assert network_proxy.record_denial("late.example", 443, "CONNECT") == request_id
    assert [event["request_id"] for event in network_proxy.pending_events()] == [request_id]


@pytest.mark.anyio
async def test_resolve_public_fails_closed_when_dns_contains_private_answer(monkeypatch) -> None:
    loop = __import__("asyncio").get_running_loop()

    async def fake_getaddrinfo(*_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    assert await network_proxy.resolve_public("example.com", 443) is None


@pytest.mark.anyio
async def test_resolve_public_returns_every_validated_answer_and_open_retries(monkeypatch) -> None:
    loop = asyncio.get_running_loop()
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
    ]

    async def fake_getaddrinfo(*_args, **_kwargs):
        return answers

    attempts: list[str] = []
    connected = (MagicMock(), MagicMock())

    async def fake_open_connection(host: str, _port: int, *, family: int):
        attempts.append(host)
        assert family == socket.AF_INET
        if host == "8.8.8.8":
            raise OSError("first address unavailable")
        return connected

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(network_proxy.asyncio, "open_connection", fake_open_connection)

    resolved = await network_proxy.resolve_public("example.com", 443)

    assert resolved == (
        (socket.AF_INET, ("8.8.8.8", 443)),
        (socket.AF_INET, ("1.1.1.1", 443)),
    )
    assert await network_proxy._open_public(resolved, 443) is connected
    assert attempts == ["8.8.8.8", "1.1.1.1"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["isolated", "allowlist"])
async def test_denied_destination_is_rejected_without_dns_resolution(tmp_path, monkeypatch, mode: str) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", mode)
    monkeypatch.setenv("DEERFLOW_ALLOW_DOMAINS_JSON", json.dumps(["allowed.example"]))
    monkeypatch.delenv("DEERFLOW_RECORD_DENIALS", raising=False)
    resolutions: list[tuple[str, int]] = []

    async def fake_resolve_public(host: str, port: int):
        resolutions.append((host, port))
        return None

    monkeypatch.setattr(network_proxy, "resolve_public", fake_resolve_public)

    proxy = await asyncio.start_server(network_proxy.handle_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"CONNECT denied.example:443 HTTP/1.1\r\nHost: denied.example:443\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert b"403 Forbidden" in response
        assert resolutions == []
    finally:
        proxy.close()
        await proxy.wait_closed()


@pytest.mark.anyio
async def test_tls_client_hello_sni_is_extracted_for_connect_enforcement() -> None:
    incoming = ssl.MemoryBIO()
    outgoing = ssl.MemoryBIO()
    context = ssl.create_default_context()
    tls = context.wrap_bio(incoming, outgoing, server_side=False, server_hostname="pypi.org")
    with pytest.raises(ssl.SSLWantReadError):
        tls.do_handshake()

    reader = __import__("asyncio").StreamReader()
    wire = outgoing.read()
    reader.feed_data(wire)
    reader.feed_eof()

    parsed = await network_proxy._read_tls_client_hello(reader)

    assert parsed == ("pypi.org", wire)


def test_http_request_framing_rejects_ambiguous_or_duplicate_lengths() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        fields = network_proxy._parse_http_header_fields(["Content-Length: 4", "Transfer-Encoding: chunked"])
        network_proxy._http_request_body_framing(fields)
    with pytest.raises(ValueError, match="one non-negative"):
        fields = network_proxy._parse_http_header_fields(["Content-Length: 4", "Content-Length: 4"])
        network_proxy._http_request_body_framing(fields)


@pytest.mark.anyio
async def test_chunked_request_body_rejects_non_hex_size() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"+1\r\na\r\n0\r\n\r\n")
    reader.feed_eof()
    writer = MagicMock()

    with pytest.raises(ValueError, match="Invalid chunk size"):
        await network_proxy._copy_chunked_request_body(reader, writer)


@pytest.mark.anyio
async def test_http_proxy_relays_exactly_one_request_per_connection(monkeypatch) -> None:
    received: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()

    async def upstream_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header = await reader.readuntil(b"\r\n\r\n")
        body = await reader.readexactly(4)
        received.set_result(header + body)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(upstream_handler, "127.0.0.1", 0)
    upstream_port = upstream.sockets[0].getsockname()[1]

    async def fake_resolve_public(_host: str, _port: int):
        return (socket.AF_INET, ("127.0.0.1", upstream_port))

    async def fake_open_public(_resolved, _port: int):
        return await asyncio.open_connection("127.0.0.1", upstream_port)

    monkeypatch.setattr(network_proxy, "resolve_public", fake_resolve_public)
    monkeypatch.setattr(network_proxy, "_open_public", fake_open_public)
    monkeypatch.setattr(network_proxy, "policy_allows", lambda host, port: (host, port) == ("allowed.example", 80))

    proxy = await asyncio.start_server(network_proxy.handle_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"POST http://allowed.example/first HTTP/1.1\r\nHost: allowed.example\r\nContent-Length: 4\r\nConnection: keep-alive\r\n\r\ndataGET http://denied.example/second HTTP/1.1\r\nHost: denied.example\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        upstream_request = await asyncio.wait_for(received, timeout=2)
        assert b"POST /first HTTP/1.1" in upstream_request
        assert b"Connection: close" in upstream_request
        assert b"Connection: keep-alive" not in upstream_request
        assert upstream_request.endswith(b"data")
        assert b"denied.example" not in upstream_request
        assert b"200 OK" in response
    finally:
        proxy.close()
        upstream.close()
        await proxy.wait_closed()
        await upstream.wait_closed()


@pytest.mark.anyio
async def test_sandbox_api_relay_requires_per_sandbox_token(monkeypatch) -> None:
    received: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()

    async def upstream_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header = await reader.readuntil(b"\r\n\r\n")
        received.set_result(header)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(upstream_handler, "127.0.0.1", 0)
    upstream_port = upstream.sockets[0].getsockname()[1]
    monkeypatch.setenv(network_proxy.RELAY_TOKEN_ENV, "test-relay-token")
    monkeypatch.setenv("DEERFLOW_SANDBOX_TARGET", f"127.0.0.1:{upstream_port}")
    relay = await asyncio.start_server(network_proxy.handle_relay, "127.0.0.1", 0)
    relay_port = relay.sockets[0].getsockname()[1]
    try:
        denied_reader, denied_writer = await asyncio.open_connection("127.0.0.1", relay_port)
        denied_writer.write(b"GET /v1/sandbox HTTP/1.1\r\nHost: sandbox\r\n\r\n")
        await denied_writer.drain()
        denied_response = await asyncio.wait_for(denied_reader.read(), timeout=2)
        denied_writer.close()
        await denied_writer.wait_closed()

        assert b"403 Forbidden" in denied_response
        assert not received.done()

        reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
        writer.write(b"GET /v1/sandbox HTTP/1.1\r\nHost: sandbox\r\n" + f"{network_proxy.RELAY_AUTH_HEADER}: test-relay-token\r\n\r\n".encode())
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert b"200 OK" in response
        assert network_proxy.RELAY_AUTH_HEADER.encode() in await asyncio.wait_for(received, timeout=2)
    finally:
        relay.close()
        upstream.close()
        await relay.wait_closed()
        await upstream.wait_closed()


@pytest.mark.anyio
async def test_sandbox_api_relay_rejects_non_ascii_token(monkeypatch) -> None:
    monkeypatch.setenv(network_proxy.RELAY_TOKEN_ENV, "test-relay-token")
    relay = await asyncio.start_server(network_proxy.handle_relay, "127.0.0.1", 0)
    relay_port = relay.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
        writer.write(b"GET /v1/sandbox HTTP/1.1\r\nHost: sandbox\r\n" + network_proxy.RELAY_AUTH_HEADER.encode() + b": \xff\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert b"403 Forbidden" in response
    finally:
        relay.close()
        await relay.wait_closed()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "malformed_header",
    [
        b"Host : denied.example",
        b"Transfer-Encoding : chunked",
        b"Bad(Header): value",
    ],
)
async def test_http_proxy_rejects_ambiguous_field_names_before_policy_check(monkeypatch, malformed_header: bytes) -> None:
    policy_checks: list[tuple[str, int]] = []

    def fake_policy_allows(host: str, port: int) -> bool:
        policy_checks.append((host, port))
        return False

    monkeypatch.setattr(network_proxy, "policy_allows", fake_policy_allows)

    proxy = await asyncio.start_server(network_proxy.handle_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"GET http://allowed.example/ HTTP/1.1\r\nHost: allowed.example\r\n" + malformed_header + b"\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert b"400 Bad Request" in response
        assert policy_checks == []
    finally:
        proxy.close()
        await proxy.wait_closed()
