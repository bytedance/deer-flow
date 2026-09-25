"""Opt-in, local-only checks of the exact companion revision in the example.

Set RESEARCH_AUDIT_SOURCE to a trusted checkout at the configured SHA. No test
downloads or installs code. Synthetic public addresses are redirected at the
socket boundary to a local fixture; a separate private trap must stay untouched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_IP = "93.184.216.34"
HOST = "source.audit.test"
OTHER_HOST = "redirect.audit.test"


@pytest.fixture
def companion(monkeypatch):
    source = os.environ.get("RESEARCH_AUDIT_SOURCE")
    if not source:
        pytest.skip("set RESEARCH_AUDIT_SOURCE to a trusted checkout of the configured audit-server pin")
    source = Path(source).resolve()
    server = json.loads((ROOT / "extensions_config.example.json").read_text(encoding="utf-8"))["mcpServers"]["research_audit"]
    revision = server["args"][1].rsplit("@", 1)[1]
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    assert actual == revision, "transport checks must exercise the configured revision"
    modules = {}
    for name in ("verify", "audit", "mcp_server"):
        path = source / f"{name}.py"
        expected = subprocess.check_output(["git", "-C", str(source), "show", f"{revision}:{name}.py"])
        assert path.read_bytes() == expected, f"{name}.py differs from the pinned source"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    return SimpleNamespace(**modules)


@pytest.fixture
def network(companion, monkeypatch):
    public_requests, private_requests, dials = [], [], []
    resolutions = Counter()
    scenario = SimpleNamespace(head_status=200, redirect=None, private_first=False)

    class Trap(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.respond()

        def do_GET(self):
            self.respond()

        def respond(self):
            private_requests.append(self.command)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    class Public(Trap):
        def respond(self):
            public_requests.append((self.command, self.path, self.headers["Host"]))
            redirect_now = self.path == "/source" and scenario.redirect and (scenario.redirect != "get-private" or self.command == "GET")
            if redirect_now:
                target = {
                    "same": f"http://{HOST}/final",
                    "cross": f"http://{OTHER_HOST}/final",
                    "private": "http://127.0.0.1/private",
                    "get-private": "http://127.0.0.1/private",
                }[scenario.redirect]
                self.send_response(302)
                self.send_header("Location", target)
            else:
                self.send_response(scenario.head_status if self.command == "HEAD" else 200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    public = ThreadingHTTPServer(("127.0.0.1", 0), Public)
    trap = ThreadingHTTPServer(("127.0.0.1", 0), Trap)
    threads = [threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}) for server in (public, trap)]
    for thread in threads:
        thread.start()
    real_connect = socket.socket.connect

    def resolve(host, port, *args, **kwargs):
        if host in (HOST, OTHER_HOST):
            resolutions[host] += 1
            address = "127.0.0.1" if scenario.private_first or resolutions[host] > 1 else PUBLIC_IP
        elif host in (PUBLIC_IP, "127.0.0.1"):
            address = host
        else:
            raise AssertionError(f"unexpected DNS lookup: {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]

    def connect(sock, address):
        dials.append(address[0])
        if address[0] == PUBLIC_IP:
            return real_connect(sock, public.server_address)
        if address[0] == "127.0.0.1":
            return real_connect(sock, trap.server_address)
        raise AssertionError(f"unexpected connection: {address}")

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ADVERSARIAL_RESEARCH_AUDIT_ALLOW_PRIVATE_NETWORKS", "false")
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    try:
        yield SimpleNamespace(scenario=scenario, public=public_requests, private=private_requests, dials=dials, resolutions=resolutions)
    finally:
        for server in (public, trap):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()


def _call(companion, entrypoint):
    url = f"http://{HOST}/source"
    if entrypoint == "verifier":
        verifier = companion.verify.SourceVerifier(allow_private_networks=False)
        result = verifier.verify(url)
        summary = verifier.summary([result])
        assert summary["dead"] == 0
        return summary["degraded"]
    report = {
        "title": "Synthetic transport regression",
        "source_of_set": {"method": "script", "description": "One synthetic item"},
        "coverage": {"examined": 1, "total": 1},
        "claims": [{"id": "c1", "count": 1, "text": "Fixture", "sources": [{"url": url}]}],
        "unjudged": [],
    }
    result = companion.mcp_server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "audit_report", "arguments": {"report": report, "verify_sources": True}}},
        {"initialized": True},
    )["result"]
    assert result["isError"] is False
    envelope = result["structuredContent"]
    assert envelope["outputs"]["verdict"] == "PASS"
    assert len(envelope["outputs"]["gates"]) == 6
    return envelope["degraded"]


@pytest.mark.parametrize("entrypoint", ["verifier", "mcp"])
@pytest.mark.parametrize("head_status", [200, 403, 405, 501])
def test_rebinding_never_reaches_private_service(companion, network, entrypoint, head_status):
    network.scenario.head_status = head_status
    degraded = _call(companion, entrypoint)
    assert network.private == [], "DNS rebinding reached the private HTTP service"
    assert network.dials == [PUBLIC_IP, PUBLIC_IP]
    assert network.resolutions[HOST] == 1
    assert network.public == [("HEAD", "/source", HOST), ("GET", "/source", HOST)]
    assert degraded is False


@pytest.mark.parametrize("entrypoint", ["verifier", "mcp"])
@pytest.mark.parametrize("redirect", ["same", "cross", "private", "get-private"])
def test_redirects_keep_the_validated_address_boundary(companion, network, entrypoint, redirect):
    network.scenario.redirect = redirect
    degraded = _call(companion, entrypoint)
    assert network.private == []
    assert set(network.dials) == {PUBLIC_IP}
    assert degraded is (redirect in {"private", "get-private"})
    if redirect in {"same", "cross"}:
        target = HOST if redirect == "same" else OTHER_HOST
        # urllib follows a 302 from HEAD with GET. Every hop must dial only
        # the validated address; on a cross-host hop, the Host header is
        # the redirect target's host.
        assert network.public == [("HEAD", "/source", HOST), ("GET", "/final", target), ("GET", "/source", HOST), ("GET", "/final", target)]
        assert all(count == 1 for count in network.resolutions.values())


@pytest.mark.parametrize("entrypoint", ["verifier", "mcp"])
def test_initial_private_dns_is_degraded_without_a_request(companion, network, entrypoint):
    network.scenario.private_first = True
    degraded = _call(companion, entrypoint)
    assert network.private == network.public == network.dials == []
    assert degraded is True


@pytest.mark.parametrize("entrypoint", ["verifier", "mcp"])
def test_environment_proxy_fails_closed(companion, network, monkeypatch, entrypoint):
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": "http://127.0.0.1:8080"})
    degraded = _call(companion, entrypoint)
    assert network.private == network.public == network.dials == []
    assert degraded is True


def test_explicit_proxy_fails_closed(companion, network):
    result = companion.verify.SourceVerifier(allow_private_networks=False, proxy="http://127.0.0.1:8080").verify(f"http://{HOST}/source")
    assert network.private == network.public == network.dials == []
    assert result["ok"] is None
    assert "proxy-policy-unsupported" in result["error"]


@pytest.mark.parametrize("entrypoint", ["verifier", "mcp"])
def test_get_timeout_after_successful_head_is_degraded(companion, network, monkeypatch, entrypoint):
    from http.client import HTTPResponse

    original_read = HTTPResponse.read

    def read(response, *args, **kwargs):
        if response._method == "GET":
            raise TimeoutError("synthetic body-read timeout")
        return original_read(response, *args, **kwargs)

    monkeypatch.setattr(HTTPResponse, "read", read)
    degraded = _call(companion, entrypoint)
    assert network.private == []
    assert network.public == [("HEAD", "/source", HOST), ("GET", "/source", HOST)]
    assert degraded is True


def test_https_preserves_hostname_for_tls(companion, monkeypatch):
    from unittest.mock import MagicMock

    context = MagicMock()
    sock = MagicMock()
    dial = MagicMock(return_value=sock)
    monkeypatch.setattr(socket, "create_connection", dial)
    connection = companion.verify._PinnedHTTPSConnection(HOST, validated_ip=PUBLIC_IP, context=context)
    try:
        connection.connect()
        assert dial.call_args.args[0] == (PUBLIC_IP, 443)
        context.wrap_socket.assert_called_once_with(sock, server_hostname=HOST)
    finally:
        connection.close()
