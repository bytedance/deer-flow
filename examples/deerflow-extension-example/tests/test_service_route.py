"""The eager router and its 503 window, tested without a host.

Only this extension's router is mounted -- no Gateway, no auth middleware, no
harness. That is the whole point of building routers eagerly and resolving host
capabilities through ``Depends()``: the dependency graph is testable in isolation.
"""

from __future__ import annotations

from deerflow_extension_api import ExtensionData, ExtensionRuntimeDeps, HostPolicySnapshot
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deerflow_extension_example.service import ROUTE_PREFIX, ExampleService, build_router
from deerflow_extension_example.stats import StatsAccess

STATS_URL = f"{ROUTE_PREFIX}/stats"


def _client() -> tuple[TestClient, ExampleService]:
    access = StatsAccess()
    service = ExampleService(access)
    app = FastAPI()
    app.include_router(build_router(service, access))
    return TestClient(app), service


def _deps() -> ExtensionRuntimeDeps:
    return ExtensionRuntimeDeps(
        app_store=ExtensionData("app"),
        policy=HostPolicySnapshot(token_budget_enabled=True, max_total_tokens=1_000_000, max_subagents_per_run=6),
        session_factory=object(),
    )


def test_unavailable_before_the_service_starts() -> None:
    client, _service = _client()

    assert client.get(STATS_URL).status_code == 503


async def test_available_once_the_host_binds_runtime_dependencies() -> None:
    client, service = _client()

    await service.start(_deps())
    response = client.get(STATS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["scope_id"] == "app"
    assert body["session_factory_available"] is True
    # The narrow projection the host hands over, echoed back verbatim.
    assert body["host_policy"]["max_total_tokens"] == 1_000_000
    assert body["host_policy"]["max_subagents_per_run"] == 6
    assert body["tasks"] == {"started": 0, "by_outcome": {}, "by_kind": {}}


async def test_unavailable_again_after_stop() -> None:
    """The router stays mounted through shutdown; it must stop answering."""
    client, service = _client()
    await service.start(_deps())
    assert client.get(STATS_URL).status_code == 200

    await service.stop()

    assert client.get(STATS_URL).status_code == 503


async def test_unavailable_when_the_host_bound_no_app_store() -> None:
    # ExtensionRuntimeDeps fields all default, so a host that fail-opened past a
    # partial startup can hand over a deps object with nothing in it.
    client, service = _client()

    await service.start(ExtensionRuntimeDeps())

    assert client.get(STATS_URL).status_code == 503
