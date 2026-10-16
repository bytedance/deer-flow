"""Real optional SDK DELETE serialization over a strictly offline HTTP transport."""

from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.opensandbox.provider import OpenSandboxProvider


@pytest.mark.parametrize("responses", [[503, 204], [503, 404], [403, 204], ["disconnect", 204], [404], [410]])
@pytest.mark.parametrize("change_environment", [False, True])
@pytest.mark.parametrize("initial_key", ["synthetic-secret", ""])
def test_real_sdk_closed_transport_does_not_erase_pending_remote(monkeypatch, responses, caplog, change_environment, initial_key):
    sdk = pytest.importorskip("opensandbox.sync", reason="optional OpenSandbox SDK serialization tier")

    transports = []
    requests = []
    statuses = list(responses)

    class Transport(httpx.BaseTransport):
        def __init__(self, **kwargs):
            self.closed = False
            transports.append(self)

        def handle_request(self, request):
            assert not self.closed, "a retired SDK transport must never be reused"
            requests.append((request.method, str(request.url), request.headers.get("OPEN-SANDBOX-API-KEY")))
            status = statuses.pop(0)
            if status == "disconnect":
                raise httpx.ConnectError("synthetic management disconnect", request=request)
            return httpx.Response(status, json=None if status == 204 else {"code": "synthetic", "message": "synthetic API response"})

        def close(self):
            self.closed = True

    monkeypatch.setattr(httpx, "HTTPTransport", Transport)
    monkeypatch.setattr("opensandbox.config.client_ip.apply_client_ip", lambda headers: None)
    monkeypatch.setenv("OPEN_SANDBOX_DOMAIN", "synthetic.invalid")
    monkeypatch.setenv("OPEN_SANDBOX_API_KEY", initial_key)
    monkeypatch.setattr("deerflow.community.opensandbox.provider.get_app_config", lambda: SimpleNamespace(sandbox=SimpleNamespace(idle_timeout=0, protocol="https", request_timeout=7)))
    monkeypatch.setattr("deerflow.community.opensandbox.provider.atexit.register", lambda callback: None)

    def create(*args, connection_config, **kwargs):
        manager = sdk.SandboxManagerSync.create(connection_config=connection_config)
        # Provisioning is outside this test. Keep the real SDK lifecycle service,
        # owned transport, destroy/kill implementation and generated HTTP client.
        return sdk.SandboxSync(
            sandbox_id="synthetic-remote",
            sandbox_service=manager._sandbox_service,
            filesystem_service=object(),
            command_service=SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(exit_code=0)),
            health_service=object(),
            metrics_service=object(),
            egress_service=object(),
            connection_config=manager.connection_config,
        )

    monkeypatch.setattr(sdk.SandboxSync, "create", create)
    provider = OpenSandboxProvider()
    try:
        provider.acquire("thread", user_id="owner")
        if responses[0] not in (404, 410):
            with pytest.raises(RuntimeError, match="terminations pending"):
                provider.shutdown()
            assert transports[0].closed
            assert len(requests) == 1
            if change_environment:
                monkeypatch.setenv("OPEN_SANDBOX_DOMAIN", "different.invalid")
                monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "different-secret")
                if not initial_key:
                    with pytest.raises(RuntimeError, match="terminations pending"):
                        provider.shutdown()
                    assert len(requests) == 1
                    monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "")
        provider.shutdown()
        provider.shutdown()
    finally:
        # A failing assertion must not leave an SDK transport open.
        for transport in transports:
            transport.close()
    assert not statuses
    assert len(transports) == len(responses)
    assert requests == [("DELETE", "https://synthetic.invalid/v1/sandboxes/synthetic-remote", initial_key or None)] * len(responses)
    assert all(transport.closed for transport in transports)
    assert "synthetic-secret" not in caplog.text
