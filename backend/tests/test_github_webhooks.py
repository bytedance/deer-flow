"""Tests for the GitHub webhook receiver.

Covers HMAC signature verification (positive + negative paths), event
recognition, JSON parsing failures, and the unset-secret dev-mode escape
hatch. Also exercises the CSRF middleware exemption so the route stays
reachable without an X-CSRF-Token header.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.channels.message_bus import MessageBus
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import github_webhooks

SECRET = "test-secret-do-not-use-in-production"
DELIVERY_ID = "12345678-1234-1234-1234-123456789abc"


def _signature(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _make_app() -> FastAPI:
    app = FastAPI()
    # Include CSRF middleware so we also prove /api/webhooks/ is exempt.
    app.add_middleware(CSRFMiddleware)
    app.include_router(github_webhooks.router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to: secret configured, dev opt-in cleared.

    Tests that exercise the unset-secret / opt-in paths override these
    explicitly with their own ``monkeypatch.delenv`` /
    ``monkeypatch.setenv``.
    """
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)


@pytest.fixture(autouse=True)
def _stub_channel_service(monkeypatch: pytest.MonkeyPatch):
    """Provide a stub channel service so the route can publish to a bus.

    The real ChannelService is started by the gateway lifespan; here we
    only need something with a `.bus` attribute the route can use. Tests
    that want to check what was published can read from the bus.

    Defaults ``is_channel_enabled("github")`` to True so the route's
    R7 kill-switch doesn't skip dispatch. The test that pins the
    disabled-channel branch overrides this via a different stub.
    ``get_channel_config("github")`` returns ``None`` so the operator
    default mention threading is exercised in the no-config branch by
    default; the test that pins the live-config path stubs this in.
    """
    bus = MessageBus()

    class _StubService:
        def __init__(self) -> None:
            self.bus = bus

        def is_channel_enabled(self, name: str) -> bool:
            return True

        def get_channel_config(self, name: str) -> dict | None:
            return None

    stub = _StubService()
    # Patch in the channel-service module so the import inside the route
    # picks up the stub.
    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: stub)
    return stub


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_ping_event_returns_200(client: TestClient) -> None:
    body = json.dumps({"zen": "Practicality beats purity.", "hook": {"id": 42}}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # The dispatch key is populated even when no agents match — its value
    # is a small summary dict, here empty because no agents are registered.
    assert payload["ok"] is True
    assert payload["event"] == "ping"
    assert payload["delivery"] == DELIVERY_ID
    assert payload["handled"] is True
    assert "dispatch" in payload


def test_pull_request_opened_returns_200(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {
                "number": 7,
                "title": "Add webhook receiver",
                "html_url": "https://github.com/org/repo/pull/7",
            },
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_issue_comment_returns_200(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "created",
            "issue": {"number": 3, "pull_request": {"url": "..."}},
            "comment": {"user": {"login": "octocat"}},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_issues_event_returns_200(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "opened",
            "issue": {
                "number": 12,
                "title": "Bug: things are broken",
                "html_url": "https://github.com/org/repo/issues/12",
            },
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_pull_request_review_returns_200(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "submitted",
            "pull_request": {"number": 5},
            "review": {"state": "approved", "user": {"login": "reviewer"}},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request_review",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["handled"] is True


def test_plain_issue_comment_is_not_pr(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    """An issue_comment on a plain issue (not a PR) should log is_pr=False."""
    body = json.dumps(
        {
            "action": "created",
            "issue": {"number": 7},  # No "pull_request" key
            "comment": {"user": {"login": "octocat"}},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()
    with caplog.at_level("INFO", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issue_comment",
                "X-GitHub-Delivery": DELIVERY_ID,
                "X-Hub-Signature-256": _signature(body),
            },
        )

    assert response.status_code == 200
    assert any("is_pr=False" in rec.message for rec in caplog.records)


def test_unknown_event_returns_200_but_unhandled(client: TestClient) -> None:
    body = json.dumps({"action": "started"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    body_json = response.json()
    assert body_json["ok"] is True
    assert body_json["handled"] is False
    assert body_json["event"] == "workflow_run"


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_missing_signature_returns_401(client: TestClient) -> None:
    body = b'{"zen": "x"}'
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
        },
    )

    assert response.status_code == 401
    assert "X-Hub-Signature-256" in response.json()["detail"]


def test_malformed_signature_returns_401(client: TestClient) -> None:
    body = b'{"zen": "x"}'
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": "not-a-valid-format",
        },
    )

    assert response.status_code == 401


def test_signature_mismatch_returns_401(client: TestClient) -> None:
    body = b'{"zen": "x"}'
    # Sign with a different secret.
    bad_sig = _signature(body, secret="wrong-secret")
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": bad_sig,
        },
    )

    assert response.status_code == 401


def test_signature_verified_against_exact_bytes(client: TestClient) -> None:
    """Signature must be computed over the request body bytes, not
    re-serialised JSON. Whitespace and key ordering matter."""
    body = b'{"zen":"x","other":1}'  # no spaces
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Unset-secret dev mode
# ---------------------------------------------------------------------------


def test_unset_secret_rejects_with_503_by_default(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Fail-closed contract: unset secret + no dev opt-in => the runtime
    handler rejects the delivery with 503 even though the route is
    mounted in this test app. Production fail-closed depends on
    ``is_route_enabled`` gating the include in :mod:`app.gateway.app`;
    this is the defense-in-depth fallback path inside the handler itself
    (e.g. for a runtime env-var rotation that cleared the secret without
    a restart).
    """
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    body = json.dumps({"zen": "ok"}).encode()

    with caplog.at_level("ERROR", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
        )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "GITHUB_WEBHOOK_SECRET" in detail
    assert "DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS" in detail
    assert any("rejecting delivery" in rec.message for rec in caplog.records)


def test_unset_secret_with_dev_optin_accepts_unverified(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Explicit dev/loopback opt-in: ``DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS=1``
    causes the handler to accept unverified deliveries with a loud WARNING.
    """
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", "1")
    body = json.dumps({"zen": "ok"}).encode()

    with caplog.at_level("WARNING", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
        )

    assert response.status_code == 200
    assert any("UNVERIFIED delivery" in rec.message and "dev/loopback mode ONLY" in rec.message for rec in caplog.records)


def test_empty_string_secret_rejects_without_optin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty/whitespace-only secret is treated as unset by
    :func:`_get_webhook_secret`, so the fail-closed path applies (503) unless
    the explicit unverified opt-in is set.
    """
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "   ")
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
    )

    assert response.status_code == 503


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "   ", "anything-else"])
def test_unverified_optin_falsy_values_reject(client: TestClient, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Only the documented truthy strings flip the unverified opt-in. Anything
    else — including 0/false/empty — keeps the fail-closed posture.
    """
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", value)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
    )

    assert response.status_code == 503


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "ON"])
def test_unverified_optin_truthy_values_accept(client: TestClient, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Case-insensitive accepted truthy values for the dev opt-in."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", value)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": DELIVERY_ID},
    )

    assert response.status_code == 200


def test_is_route_enabled_requires_secret_or_optin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup-time gate that :mod:`app.gateway.app` consults before
    mounting the router. Fail-closed: neither var set => route NOT mounted.
    """
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    assert github_webhooks.is_route_enabled() is False

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "anything")
    assert github_webhooks.is_route_enabled() is True

    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", "1")
    assert github_webhooks.is_route_enabled() is True

    # Empty / whitespace-only secret is treated as unset, so the opt-in
    # alone decides.
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "  ")
    monkeypatch.delenv("DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS", raising=False)
    assert github_webhooks.is_route_enabled() is False


# ---------------------------------------------------------------------------
# Header / body edge cases
# ---------------------------------------------------------------------------


def test_missing_event_header_returns_400(client: TestClient) -> None:
    body = b'{"zen": "x"}'
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 400
    assert "X-GitHub-Event" in response.json()["detail"]


def test_invalid_json_body_returns_400(client: TestClient) -> None:
    body = b"this-is-not-json"
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]


# ---------------------------------------------------------------------------
# CSRF middleware exemption
# ---------------------------------------------------------------------------


def test_csrf_middleware_does_not_block_webhook(client: TestClient) -> None:
    """The route is mounted behind CSRFMiddleware in _make_app(). GitHub
    sends neither csrf_token cookie nor X-CSRF-Token header, so the
    middleware must allow this path through without those credentials.
    """
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    # If CSRF middleware blocked the route, we'd see 403 with a
    # "CSRF token missing" detail. We must get 200 instead.
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


def test_dispatch_result_included_in_response(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fan-out helper's summary dict should appear in the response payload."""

    fake = AsyncMock(return_value={"matched_agents": ["x"], "fired_agents": ["x"], "skipped": []})
    monkeypatch.setattr(github_webhooks, "fanout_event", fake)

    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["dispatch"] == {"matched_agents": ["x"], "fired_agents": ["x"], "skipped": []}
    assert fake.await_count == 1


def test_dispatch_failure_returns_503_not_200(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """A crashing fan-out helper must return 503, not 200.

    The earlier behaviour swallowed every fan-out exception into a 200 OK
    response (``dispatch={"error": "fanout failed"}``). GitHub treats 200
    as final success and does not automatically retry any failure,
    including 5xx (see
    https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries)
    — so a 200 ack permanently drops the delivery. The route now lets
    runtime failures propagate as 503 so the delivery is correctly
    recorded as failed, recoverable via a manual "Redeliver", the REST
    API, or an operator's own recovery script. The startup-time
    ``is_route_enabled`` check still handles *configuration* failures
    fail-closed (route absent → 404); 503 is reserved for runtime
    failures worth making recoverable this way.
    """

    async def fake_fanout(*args, **kwargs) -> dict:
        raise RuntimeError("transient registry hiccup")

    monkeypatch.setattr(github_webhooks, "fanout_event", fake_fanout)

    body = json.dumps({"zen": "ok"}).encode()
    with caplog.at_level("ERROR", logger="app.gateway.routers.github_webhooks"):
        response = client.post(
            "/api/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": DELIVERY_ID,
                "X-Hub-Signature-256": _signature(body),
            },
        )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "fan-out failed" in detail
    assert DELIVERY_ID in detail
    assert "transient registry hiccup" in detail
    # Operator-visible log: stack trace + delivery id so the redelivery
    # page entry can be correlated.
    assert any("fanout failed" in rec.message for rec in caplog.records)


def test_dispatch_failure_503_lets_github_redeliver_successfully(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retried delivery (after the transient error resolves) lands on 200.

    Regression: confirm the 503 response is a real signal — once the
    underlying failure is gone, the same delivery (re-sent by GitHub)
    succeeds normally. If we ever cache "failed delivery" state on the
    route, this test would catch it.
    """
    calls: list[int] = []

    async def flaky_fanout(*args, **kwargs) -> dict:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"matched_agents": [], "fired_agents": [], "skipped": []}

    monkeypatch.setattr(github_webhooks, "fanout_event", flaky_fanout)

    body = json.dumps({"zen": "ok"}).encode()
    first = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert first.status_code == 503

    # A redelivery — same payload, same signature (e.g. a manual
    # "Redeliver" click, since GitHub does not resend this automatically).
    second = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert second.status_code == 200
    assert second.json()["dispatch"] == {"matched_agents": [], "fired_agents": [], "skipped": []}


def test_unknown_event_skips_dispatcher(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fan-out helper is not invoked for events not in _KNOWN_EVENTS."""
    fake = AsyncMock(return_value={})
    monkeypatch.setattr(github_webhooks, "fanout_event", fake)

    body = json.dumps({"action": "x"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["dispatch"] is None
    assert fake.await_count == 0


def test_missing_channel_service_does_not_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the channel service is not running, the route must still 200."""
    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: None)
    body = json.dumps({"zen": "ok"}).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["dispatch"]["error"] == "channel_service_not_available"


def test_channel_disabled_skips_fanout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """``channels.github.enabled: false`` is the documented operator kill-switch.

    With the channel disabled, the route must NOT call ``fanout_event`` —
    publishing inbound onto the bus would let the ChannelManager consumer
    pick it up and run agents that then post back to GitHub via ``gh``,
    contradicting the documented off-switch. Returns 200 (permanent
    state, not transient) rather than mark the delivery failed and invite
    a pointless redelivery; ``dispatch.skipped`` surfaces the reason in
    the Recent Deliveries panel.
    """
    bus = MessageBus()

    class _DisabledService:
        def __init__(self) -> None:
            self.bus = bus

        def is_channel_enabled(self, name: str) -> bool:
            return False  # the kill-switch

        def get_channel_config(self, name: str) -> dict | None:
            return None

    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: _DisabledService())

    # Belt-and-braces: also pin that fanout_event is never invoked even if
    # is_channel_enabled is bypassed by a future regression.
    fake_fanout = AsyncMock(return_value={"matched": ["should-not-run"]})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["handled"] is True
    assert payload["dispatch"] == {"skipped": "channel_disabled"}
    assert fake_fanout.await_count == 0


def test_channel_enabled_dispatches_normally(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity counterpart to the kill-switch test: enabled → fan-out runs.

    Pins the positive branch so a future regression that inverts
    ``is_channel_enabled`` semantics fails loudly here too.
    """
    fake_fanout = AsyncMock(return_value={"matched": ["agent-a"]})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert response.json()["dispatch"] == {"matched": ["agent-a"]}
    assert fake_fanout.await_count == 1


def test_operator_default_mention_login_is_threaded_to_fanout(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression pin for willem-bd's R8 on PR #3754.

    The webhook route must read ``channels.github.default_mention_login``
    from the live channel-service config and pass it through as
    ``operator_default_mention_login`` to ``fanout_event``. Without this,
    the documented operator default is never honoured: an agent named
    ``coder`` with ``require_mention: true`` silently requires ``@coder``
    mentions instead of the configured ``@deerflow-bot``.
    """
    bus = MessageBus()

    class _ConfiguredService:
        def __init__(self) -> None:
            self.bus = bus

        def is_channel_enabled(self, name: str) -> bool:
            return True

        def get_channel_config(self, name: str) -> dict | None:
            if name == "github":
                return {"enabled": True, "default_mention_login": "deerflow-bot"}
            return None

    import app.channels.service as service_module

    monkeypatch.setattr(service_module, "get_channel_service", lambda: _ConfiguredService())

    fake_fanout = AsyncMock(return_value={"matched_agents": [], "fired_agents": [], "skipped": []})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    assert fake_fanout.await_count == 1
    # The kwarg must have been passed through with the configured value.
    _, kwargs = fake_fanout.await_args
    assert kwargs["operator_default_mention_login"] == "deerflow-bot"


def test_operator_default_mention_login_absent_passes_none(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``channels.github.default_mention_login`` is unset, the kwarg is None.

    A deployment that never opted into the operator default must NOT have
    a phantom value silently substituted. The dispatcher's existing
    ``bot_login → agent.name`` chain remains the source of truth.
    """
    fake_fanout = AsyncMock(return_value={"matched_agents": [], "fired_agents": [], "skipped": []})
    import app.gateway.routers.github_webhooks as router_module

    monkeypatch.setattr(router_module, "fanout_event", fake_fanout)

    body = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "pull_request": {"number": 7, "title": "PR", "html_url": "https://github.com/o/r/pull/7"},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY_ID,
            "X-Hub-Signature-256": _signature(body),
        },
    )

    assert response.status_code == 200
    _, kwargs = fake_fanout.await_args
    assert kwargs["operator_default_mention_login"] is None


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_verify_signature_helper_constant_time_equal() -> None:
    body = b'{"x": 1}'
    sig = _signature(body)
    assert github_webhooks._verify_signature(SECRET, body, sig) is True


def test_verify_signature_rejects_none() -> None:
    assert github_webhooks._verify_signature(SECRET, b"x", None) is False


def test_verify_signature_rejects_missing_prefix() -> None:
    assert github_webhooks._verify_signature(SECRET, b"x", "abcdef0123") is False


def test_summarise_event_handles_missing_fields() -> None:
    # No KeyError even on a near-empty payload.
    result = github_webhooks._summarise_event("pull_request", {})
    assert "pull_request" in result


def test_summarise_event_unknown_event_falls_back() -> None:
    result = github_webhooks._summarise_event("deployment_status", {"action": "success", "repository": {"full_name": "a/b"}})
    assert "deployment_status" in result
    assert "success" in result
