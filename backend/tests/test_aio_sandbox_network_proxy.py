from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import sqlite3
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


def test_address_is_public_rejects_non_public_ipv4_inside_ipv6_spellings() -> None:
    # NAT64 (64:ff9b::/96) and IPv4-compatible (::a.b.c.d) spellings report
    # is_global even when the embedded IPv4 is loopback, private or metadata.
    for address in (
        "64:ff9b::a9fe:a9fe",  # 169.254.169.254
        "64:ff9b::a9fe:a9fe%eth0",  # the same spelling with a zone id
        "64:ff9b::7f00:1",  # 127.0.0.1
        "64:ff9b::a00:1",  # 10.0.0.1
        "64:ff9b::c0a8:102",  # 192.168.1.2
        "64:ff9b::6464:64c8",  # 100.100.100.200, CGNAT cloud metadata
        "::169.254.169.254",
        "::127.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:0:a9fe:a9fe",  # IPv4-translated (SIIT) metadata spelling
        "2002:a9fe:a9fe::1",
        "::2",  # IPv4-compatible this-network block, not a unicast target
        # RFC 8215 local-use translation prefix: rejected explicitly, without
        # relying on the interpreter classification that changed in 3.12.4.
        "64:ff9b:1::1",
        "64:ff9b:1::a9fe:a9fe",
        "64:ff9b:1:42::a9fe:a9fe",
        "64:ff9b:1::808:808",  # even a public IPv4 spelling must not egress
    ):
        assert not network_proxy.address_is_public(address)
    # 6to4 carrying a public IPv4 target follows the interpreter's outer
    # classification: CPython marks 2002::/16 private from 3.12.4 (gh-113171),
    # so it is rejected there and allowed on earlier 3.12 patch releases.
    sixtofour_public = "2002:808:808::1"
    assert network_proxy.address_is_public(sixtofour_public) == ipaddress.ip_address(sixtofour_public).is_global
    # A NAT64 spelling of a public IPv4 target stays allowed; the prefix
    # reports is_reserved, so a blanket reserved check would wrongly reject it.
    assert network_proxy.address_is_public("64:ff9b::808:808")  # 8.8.8.8
    assert network_proxy.address_is_public("64:ff9b::101:101")  # 1.1.1.1
    assert network_proxy.address_is_public("::ffff:8.8.8.8")
    assert network_proxy.address_is_public("::ffff:0:808:808")
    assert network_proxy.address_is_public("2606:4700:4700::1111")
    # The Docker Desktop synthetic-DNS exception passes through the embedded
    # check: 64:ff9b::c612:105 carries 198.18.1.5.
    assert not network_proxy.address_is_public("64:ff9b::c612:105")
    assert network_proxy.address_is_public("64:ff9b::c612:105", allow_synthetic_dns=True)


def test_local_use_nat64_prefix_rejected_independent_of_interpreter_flags(monkeypatch) -> None:
    # Simulate a pre-3.12.4 interpreter (gh-113171) that reports the RFC 8215
    # local-use range as global; the explicit rejection must still hold.
    monkeypatch.setattr(ipaddress.IPv6Address, "is_global", property(lambda self: True))
    for address in ("64:ff9b:1::1", "64:ff9b:1::a9fe:a9fe", "64:ff9b:1::808:808"):
        assert not network_proxy.address_is_public(address)


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
async def test_resolve_public_fails_closed_on_nat64_metadata_answer(monkeypatch) -> None:
    loop = asyncio.get_running_loop()

    async def fake_getaddrinfo(*_args, **_kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("64:ff9b::a9fe:a9fe", 443, 0, 0)),
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


@pytest.mark.anyio
async def test_denied_destination_still_gets_403_when_the_policy_database_fails(tmp_path, monkeypatch) -> None:
    """A full policy database must degrade to a clean denial, not a bare reset.

    The proxy container's only writable space is a 16 MiB /tmp tmpfs, so the
    policy database can fill up. An exception escaping ``handle_proxy`` closes
    the connection with no response at all, which a sandbox cannot distinguish
    from a network failure. The failure is injected at ``_connect_db`` so that
    both database touch points are exercised: the policy lookup reads grants
    (and may rewrite an expired one), and recording the denial writes a row.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", "allowlist")
    monkeypatch.setenv("DEERFLOW_ALLOW_DOMAINS_JSON", json.dumps(["allowed.example"]))
    monkeypatch.setenv("DEERFLOW_RECORD_DENIALS", "1")

    def full_database() -> None:
        # sqlite3 errors are not OSError subclasses, so this is not caught by the
        # handler's surrounding OSError handling.
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(network_proxy, "_connect_db", full_database)

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
        assert b"Sandbox network policy denied denied.example:443" in response
        # The request_id is unavailable, so it is omitted rather than invented.
        assert b"(request " not in response
    finally:
        proxy.close()
        await proxy.wait_closed()


def test_events_are_bounded_under_a_flood_of_unique_hosts(tmp_path, monkeypatch) -> None:
    """Unique hosts each insert a row, so the cap is what bounds the table.

    The 30 second deduplication in ``record_denial`` only matches a repeated
    host and port, and the policy check runs before DNS resolution, so a sandbox
    needs no real network egress to produce unbounded undecided rows.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 50)

    for index in range(500):
        network_proxy.record_denial(f"host-{index}.example", 443, "CONNECT")

    with network_proxy._connect_db() as db:
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # One row above the cap is the row the triggering insert just added.
    assert total <= 51


def test_pruning_keeps_decided_history_bounded_and_approvals_usable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 5)
    for index in range(30):
        network_proxy.record_denial(f"host-{index}.example", 443, "CONNECT")

    denied = network_proxy.deny_pending_events()
    assert denied > 0
    fresh = network_proxy.record_denial("fresh.example", 443, "CONNECT")

    with network_proxy._connect_db() as db:
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        decided = db.execute("SELECT COUNT(*) FROM events WHERE decision IS NOT NULL").fetchone()[0]

    # One row above the cap is the row the triggering insert just added.
    assert total <= 6
    assert decided <= 5
    # The newest decided rows survive, and approvals still work after the flood.
    assert [event["request_id"] for event in network_proxy.pending_events()] == [fresh]


def test_pruning_never_removes_a_card_a_user_is_currently_viewing(tmp_path, monkeypatch) -> None:
    """A surfaced, undecided row is a live approval card and must survive pruning.

    Deleting it would leave the user's decision pointing at a request_id that no
    longer resolves, so ``decide`` would silently return False on their click.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", "allowlist")
    surfaced = network_proxy.record_denial("card.example", 443, "CONNECT")
    assert [event["request_id"] for event in network_proxy.pending_events()] == [surfaced]

    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 5)
    for index in range(50):
        network_proxy.record_denial(f"host-{index}.example", 443, "CONNECT")

    with network_proxy._connect_db() as db:
        row = db.execute("SELECT surfaced, decision FROM events WHERE request_id = ?", (surfaced,)).fetchone()

    assert row == (1, None)
    assert network_proxy.decide(surfaced, "allow_temporary", ttl=60)
    assert network_proxy.policy_allows("card.example", 443)


def test_flood_does_not_evict_fresh_denials_or_break_deduplication(tmp_path, monkeypatch) -> None:
    """Superseded flood rows must be pruned before real, undecided denials.

    ``pending_events`` supersedes every unsurfaced row it does not surface, so a
    flood leaves a batch of superseded rows behind. If pruning instead dropped
    the oldest undecided rows, a real denial recorded after the flood would be
    deleted before ``pending_events`` could surface it, and the 30 second
    deduplication would stop matching.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 100)
    for index in range(300):
        network_proxy.record_denial(f"noise-{index}.example", 443, "CONNECT")
    network_proxy.pending_events()

    first = network_proxy.record_denial("pypi.org", 443, "CONNECT")
    again = network_proxy.record_denial("pypi.org", 443, "CONNECT")

    assert again == first
    assert [event["request_id"] for event in network_proxy.pending_events()] == [first]


@pytest.mark.anyio
async def test_oversized_method_is_truncated_in_storage_and_denials_stay_bounded(tmp_path, monkeypatch) -> None:
    """The row cap only bounds bytes if persisted fields are bounded too.

    The request line has no token-length limit of its own, so a method can be
    nearly MAX_HEADER_BYTES long. Stored verbatim, a few hundred such rows
    would fill the 16 MiB tmpfs long before MAX_EVENTS is reached. The method
    is truncated for storage; the denial response is unchanged.
    """
    db_path = tmp_path / "policy.sqlite3"
    monkeypatch.setattr(network_proxy, "POLICY_DB", db_path)
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", "allowlist")
    monkeypatch.setenv("DEERFLOW_ALLOW_DOMAINS_JSON", json.dumps(["allowed.example"]))
    monkeypatch.setenv("DEERFLOW_RECORD_DENIALS", "1")

    oversized_method = b"X" * 60_000
    proxy = await asyncio.start_server(network_proxy.handle_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(oversized_method + b" http://denied.example/ HTTP/1.1\r\nHost: denied.example\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert b"403 Forbidden" in response
        assert b"Sandbox network policy denied denied.example:80" in response
    finally:
        proxy.close()
        await proxy.wait_closed()

    with network_proxy._connect_db() as db:
        stored = db.execute("SELECT method FROM events").fetchone()[0]
    assert stored == "X" * network_proxy.MAX_METHOD_CHARS

    # A burst of oversized-method denials stays small on disk: the row cap and
    # the field truncation together bound the bytes, not just the row count.
    for index in range(300):
        network_proxy.record_denial(f"host-{index}.example", 80, "X" * 60_000)
    assert db_path.stat().st_size < 1_000_000


def test_recently_answered_old_card_survives_history_pruning(tmp_path, monkeypatch) -> None:
    """Resolved history must be ordered by when the decision was applied.

    An old card can be answered after newer cards. Ordering retention by the
    denial timestamp would delete the just-applied decision on the next prune,
    and a resumed run re-applying it would get False from decide() and raise.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 5)
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", "allowlist")

    old = network_proxy.record_denial("old.example", 443, "CONNECT")
    assert [event["request_id"] for event in network_proxy.pending_events()] == [old]
    for index in range(10):
        network_proxy.record_denial(f"newer-{index}.example", 443, "CONNECT")
    network_proxy.deny_pending_events()

    # The old card is answered last, after all the newer decisions exist.
    assert network_proxy.decide(old, "allow_temporary", ttl=60)

    pending = network_proxy.record_denial("pending.example", 443, "CONNECT")
    assert [event["request_id"] for event in network_proxy.pending_events()] == [pending]

    # Exercise pruning with both a recent decision and an open approval card.
    for index in range(20):
        network_proxy.record_denial(f"flood-{index}.example", 443, "CONNECT")

    with network_proxy._connect_db() as db:
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total <= network_proxy.MAX_EVENTS + 1

    # The latest decision can still replay, and the open card is still decidable.
    assert network_proxy.decide(old, "allow_temporary", ttl=60)
    assert network_proxy.policy_allows("old.example", 443)
    assert network_proxy.decide(pending, "deny", ttl=0)


def test_full_history_trims_itself_instead_of_evicting_pending_denials(tmp_path, monkeypatch) -> None:
    """Pending approvals reserve capacity once resolved history fills the cap.

    With the cap full of decided rows, two denials arriving before the next
    poll must both survive: evicting the older one would reverse the
    oldest-first order pending_events() surfaces cards in.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 5)

    for index in range(10):
        network_proxy.record_denial(f"history-{index}.example", 443, "CONNECT")
    network_proxy.deny_pending_events()

    first = network_proxy.record_denial("first.example", 443, "CONNECT")
    second = network_proxy.record_denial("second.example", 443, "CONNECT")

    # The oldest denial is surfaced first, and the newer one is superseded
    # rather than silently deleted by pruning.
    assert [event["request_id"] for event in network_proxy.pending_events()] == [first]
    with network_proxy._connect_db() as db:
        row = db.execute("SELECT decision FROM events WHERE request_id = ?", (second,)).fetchone()
    assert row == ("superseded",)


def test_pre_decided_at_database_migrates_and_keeps_old_decisions(tmp_path, monkeypatch) -> None:
    """A database created before decided_at existed must migrate on connect.

    CREATE TABLE IF NOT EXISTS does not add columns to an existing table, so
    the sidecar adds decided_at explicitly. Old decided rows have no decision
    timestamp; retention falls back to created_at for them and their replay
    still resolves.
    """
    db_path = tmp_path / "old.sqlite3"
    legacy = sqlite3.connect(db_path)
    legacy.execute("CREATE TABLE events (request_id TEXT PRIMARY KEY, host TEXT NOT NULL, port INTEGER NOT NULL, method TEXT NOT NULL, created_at REAL NOT NULL, surfaced INTEGER NOT NULL DEFAULT 0, decision TEXT)")
    legacy.execute("INSERT INTO events VALUES ('r1', 'old.example', 443, 'CONNECT', 1.0, 1, 'allow_temporary')")
    legacy.commit()
    legacy.close()

    monkeypatch.setattr(network_proxy, "POLICY_DB", db_path)
    monkeypatch.setattr(network_proxy, "MAX_EVENTS", 5)
    for index in range(20):
        network_proxy.record_denial(f"flood-{index}.example", 443, "CONNECT")

    with network_proxy._connect_db() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
        row = db.execute("SELECT decision, decided_at FROM events WHERE request_id = 'r1'").fetchone()
    assert "decided_at" in columns
    assert row == ("allow_temporary", None)
    assert network_proxy.decide("r1", "allow_temporary", ttl=60)


@pytest.mark.anyio
async def test_lookup_failure_does_not_create_an_approval_card(tmp_path, monkeypatch) -> None:
    """A transient lookup failure must not record a denial.

    Recording can succeed on a fresh connection after the lookup failed. The
    destination may already hold a sandbox-lifetime grant, and answering the
    spurious card with "Allow temporarily" would replace that grant with an
    expiring one. Lookup errors fail closed without creating an event.
    """
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    monkeypatch.setenv("DEERFLOW_NETWORK_MODE", "allowlist")
    monkeypatch.setenv("DEERFLOW_ALLOW_DOMAINS_JSON", json.dumps([]))
    monkeypatch.setenv("DEERFLOW_RECORD_DENIALS", "1")

    def failing_lookup(host: str, port: int) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(network_proxy, "policy_allows", failing_lookup)

    proxy = await asyncio.start_server(network_proxy.handle_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"CONNECT granted.example:443 HTTP/1.1\r\nHost: granted.example:443\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert b"403 Forbidden" in response
        assert b"Sandbox network policy denied granted.example:443" in response
        assert b"(request " not in response
    finally:
        proxy.close()
        await proxy.wait_closed()

    with network_proxy._connect_db() as db:
        total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total == 0
