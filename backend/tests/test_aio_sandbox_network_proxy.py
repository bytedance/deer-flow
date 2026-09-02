from __future__ import annotations

import json
import socket
import ssl

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

    events = network_proxy.pending_events(0)

    assert events == [
        {
            "request_id": request_id,
            "host": "example.com",
            "port": 443,
            "method": "CONNECT",
            "created_at": events[0]["created_at"],
        }
    ]
    assert network_proxy.pending_events(0) == []


def test_pending_events_surface_only_one_destination_per_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network_proxy, "POLICY_DB", tmp_path / "policy.sqlite3")
    first = network_proxy.record_denial("one.example", 443, "CONNECT")
    network_proxy.record_denial("two.example", 443, "CONNECT")

    assert [event["request_id"] for event in network_proxy.pending_events(0)] == [first]
    # The sibling is superseded so a retry can create a fresh approvable event.
    assert network_proxy.pending_events(0) == []
    fresh = network_proxy.record_denial("two.example", 443, "CONNECT")
    assert [event["request_id"] for event in network_proxy.pending_events(0)] == [fresh]


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
