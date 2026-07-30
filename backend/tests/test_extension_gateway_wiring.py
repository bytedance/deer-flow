"""Tests for Gateway-side extension wiring: routers, services, policy."""

from __future__ import annotations

import asyncio

import pytest
from deerflow_extension_api import ExtensionRuntimeDeps, HostPolicySnapshot
from fastapi import WebSocket

from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.extensions.gateway import include_contributed_routers, project_host_policy, start_services, stop_services
from deerflow.extensions.registry import ExtensionRegistry


@pytest.fixture(autouse=True)
def _isolate_runtime_diagnostics():
    from deerflow.extensions import reset_runtime_diagnostics

    reset_runtime_diagnostics()
    yield
    reset_runtime_diagnostics()


def _app_config() -> AppConfig:
    # AppConfig.sandbox has no default (`use` is required), so a bare
    # AppConfig() always fails pydantic validation in this repo — the same
    # deviation Tasks 5 and 9 hit.
    return AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))


class _Service:
    def __init__(self, *, fail_start: bool = False, fail_stop: bool = False) -> None:
        self.started = False
        self.stopped = False
        self.deps: ExtensionRuntimeDeps | None = None
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    async def start(self, deps):
        if self._fail_start:
            raise ValueError("start exploded")
        self.started = True
        self.deps = deps

    async def stop(self):
        if self._fail_stop:
            raise ValueError("stop exploded")
        self.stopped = True


def _extensions(*services):
    registry = ExtensionRegistry()
    for index, service in enumerate(services):
        with registry.attributed_to(f"ext{index}:install"):
            registry.service(service)
    return registry.build()


def test_policy_projection_reads_only_the_declared_fields():
    """AppConfig must not leak into the extension API — extensions see a narrow,
    additive projection instead."""
    policy = project_host_policy(_app_config())
    assert isinstance(policy, HostPolicySnapshot)
    assert policy.token_budget_enabled in (True, False)


def test_policy_projection_survives_a_config_without_the_sections():
    """The projection is read with getattr defaults on purpose: a host that has
    not configured token_budget/subagents must not crash extension startup."""
    policy = project_host_policy(object())
    assert policy.token_budget_enabled is False
    assert policy.max_total_tokens is None


def test_services_start_with_deps():
    service = _Service()
    extensions = _extensions(service)
    asyncio.run(start_services(extensions, _app_config(), session_factory=None))
    assert service.started is True
    assert service.deps.app_store is extensions.app_store


def test_start_failure_is_fail_open():
    """A failed observability service must not stop the Gateway from starting."""
    bad, good = _Service(fail_start=True), _Service()
    extensions = _extensions(bad, good)
    diagnostics = asyncio.run(start_services(extensions, _app_config(), session_factory=None))
    assert good.started is True
    assert any(d.level == "error" for d in diagnostics)


def test_services_stop_in_reverse_order():
    order: list[str] = []

    class _Ordered(_Service):
        def __init__(self, tag: str) -> None:
            super().__init__()
            self.tag = tag

        async def stop(self):
            order.append(self.tag)

    extensions = _extensions(_Ordered("first"), _Ordered("second"))
    asyncio.run(stop_services(extensions))
    assert order == ["second", "first"]


def test_stop_failure_does_not_block_shutdown():
    """A Gateway that cannot shut down is worse than a lost observation."""
    bad, good = _Service(fail_stop=True), _Service()
    extensions = _extensions(bad, good)
    diagnostics = asyncio.run(stop_services(extensions))
    assert good.stopped is True
    assert any(d.level == "error" for d in diagnostics)


def test_stop_timeout_is_bounded():
    class _Hangs(_Service):
        async def stop(self):
            await asyncio.sleep(60)

    extensions = _extensions(_Hangs())
    diagnostics = asyncio.run(stop_services(extensions, timeout_seconds=0.05))
    assert any("timed out" in d.message for d in diagnostics)


def test_stop_timeout_does_not_starve_later_services():
    """The budget is per service, not shared: one hung service must not stop the
    rest from getting their stop() called."""
    hung_calls: list[str] = []

    class _Hangs(_Service):
        async def stop(self):
            hung_calls.append("hung")
            await asyncio.sleep(60)

    good = _Service()
    extensions = _extensions(good, _Hangs())
    diagnostics = asyncio.run(stop_services(extensions, timeout_seconds=0.05))

    assert hung_calls == ["hung"], "premise: the hung service really was reached first"
    assert good.stopped is True, "a service after a hung one must still be stopped"
    assert any("timed out" in d.message for d in diagnostics)


def test_zero_services_is_a_no_op():
    extensions = ExtensionRegistry().build()
    assert asyncio.run(start_services(extensions, _app_config(), session_factory=None)) == []
    assert asyncio.run(stop_services(extensions)) == []


# --- router contribution ----------------------------------------------------


def _router(prefix: str):
    from fastapi import APIRouter

    router = APIRouter(prefix=prefix)

    @router.get("/ping")
    def _ping():
        return {"ok": True}

    return router


def _with_routers(*pairs):
    registry = ExtensionRegistry()
    for source, routers in pairs:
        with registry.attributed_to(source):
            registry.routers(routers)
    return registry.build()


def test_contributed_routers_are_mounted():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    extensions = _with_routers(("ext0:install", [_router("/ext0")]))
    diagnostics = include_contributed_routers(app, extensions)

    assert diagnostics == []
    assert TestClient(app).get("/ext0/ping").json() == {"ok": True}


def test_mounted_router_paths_are_reported_with_attribution(caplog):
    """Which URLs the Gateway just handed to third-party code is operational
    information, not something an operator should have to read /openapi.json for."""
    from fastapi import FastAPI

    app = FastAPI()
    extensions = _with_routers(("ext0:install", [_router("/ext0")]), ("ext1:install", [_router("/ext1")]))

    with caplog.at_level("INFO", logger="deerflow.extensions.gateway"):
        assert include_contributed_routers(app, extensions) == []

    assert "ext0:install -> /ext0/ping" in caplog.text
    assert "ext1:install -> /ext1/ping" in caplog.text


def test_a_rejected_router_is_not_reported_as_mounted(caplog):
    from fastapi import FastAPI

    app = FastAPI()
    # Same path twice: the second router loses conflict detection.
    extensions = _with_routers(("ext0:install", [_router("/ext0")]), ("ext1:install", [_router("/ext0")]))

    with caplog.at_level("INFO", logger="deerflow.extensions.gateway"):
        diagnostics = include_contributed_routers(app, extensions)

    assert [diagnostic.source for diagnostic in diagnostics] == ["ext1:install"]
    assert "ext0:install -> /ext0/ping" in caplog.text
    assert "ext1:install ->" not in caplog.text


def test_zero_contributed_routers_stays_off_the_info_log(caplog):
    from fastapi import FastAPI

    with caplog.at_level("INFO", logger="deerflow.extensions.gateway"):
        assert include_contributed_routers(FastAPI(), _with_routers()) == []

    assert "Extension routers mounted" not in caplog.text


def test_eager_router_resolves_runtime_deps_per_request():
    """Routes exist before binding; request-time Depends reads live deps.

    The extension owns the fail-closed readiness check because service startup
    is intentionally fail-open. No route or dependency graph is rebuilt in the
    Gateway lifespan.
    """
    from fastapi import APIRouter, Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient

    session_factory = object()

    class _RoutedService(_Service):
        def __init__(self) -> None:
            super().__init__()
            self.router = APIRouter(prefix="/runtime-bound")

            @self.router.get("/status")
            def _status(
                deps: ExtensionRuntimeDeps = Depends(self.require_runtime),
            ):
                return {
                    "scope_id": deps.app_store.scope_id,
                    "same_deps": deps is self.deps,
                    "same_session_factory": deps.session_factory is session_factory,
                }

        def require_runtime(self) -> ExtensionRuntimeDeps:
            if self.deps is None:
                raise HTTPException(status_code=503, detail="extension is not ready")
            return self.deps

        async def stop(self) -> None:
            self.stopped = True
            self.deps = None

    service = _RoutedService()
    registry = ExtensionRegistry()
    with registry.attributed_to("routed:install"):
        registry.service(service)
        registry.routers([service.router])
    extensions = registry.build()

    app = FastAPI()
    assert include_contributed_routers(app, extensions) == []
    assert any(getattr(route, "path", None) == "/runtime-bound/status" for route in app.routes)

    client = TestClient(app)
    assert client.get("/runtime-bound/status").status_code == 503

    assert asyncio.run(start_services(extensions, _app_config(), session_factory)) == []
    assert client.get("/runtime-bound/status").json() == {
        "scope_id": "app",
        "same_deps": True,
        "same_session_factory": True,
    }

    assert asyncio.run(stop_services(extensions)) == []
    assert client.get("/runtime-bound/status").status_code == 503


def test_a_prefix_conflict_names_the_responsible_extension():
    """Router source attribution exists precisely so this diagnostic can name
    who collided; without it an operator sees a duplicate path and no owner."""
    from fastapi import FastAPI

    app = FastAPI()
    extensions = _with_routers(
        ("first:install", [_router("/shared")]),
        ("second:install", [_router("/shared")]),
    )
    diagnostics = include_contributed_routers(app, extensions)

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "second:install"
    assert "first:install" in diagnostics[0].message, "the diagnostic must name both sides"
    assert "/shared/ping" in diagnostics[0].message


def test_dynamic_routes_with_different_parameter_names_conflict_for_the_same_method():
    """Starlette matches parameter values, not parameter names, so the earlier
    route would shadow the later route for every request."""
    from fastapi import APIRouter, FastAPI

    first = APIRouter()
    second = APIRouter()

    @first.get("/items/{item_id}")
    def _first(item_id: str):
        return {"source": "first", "item_id": item_id}

    @second.get("/items/{id}")
    def _second(id: str):
        return {"source": "second", "item_id": id}

    app = FastAPI()
    extensions = _with_routers(
        ("first:install", [first]),
        ("second:install", [second]),
    )
    diagnostics = include_contributed_routers(app, extensions)

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "second:install"
    assert "first:install" in diagnostics[0].message
    assert "/items/{id}" in diagnostics[0].message


def test_contributed_dynamic_route_conflicts_with_equivalent_host_route():
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/items/{item_id}")
    def _host(item_id: str):
        return {"item_id": item_id}

    contributed = APIRouter()

    @contributed.get("/items/{id}")
    def _extension(id: str):
        return {"item_id": id}

    extensions = _with_routers(("extension:install", [contributed]))
    diagnostics = include_contributed_routers(app, extensions)

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/items/{id}" in diagnostics[0].message


def test_contributed_dynamic_route_conflicts_with_equivalent_host_converter_route():
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/records/{record_id:int}")
    def _host(record_id: int):
        return {"record_id": record_id}

    contributed = APIRouter()

    @contributed.get("/records/{id:int}")
    def _extension(id: int):
        return {"record_id": id}

    extensions = _with_routers(("extension:install", [contributed]))
    diagnostics = include_contributed_routers(app, extensions)

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/records/{id:int}" in diagnostics[0].message


def test_host_dynamic_route_conflicts_with_shadowed_contributed_static_route():
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/items/{item_id}")
    def _host(item_id: str):
        return {"source": "host", "item_id": item_id}

    contributed = APIRouter()

    @contributed.get("/items/new")
    def _extension():
        return {"source": "extension"}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/items/new" in diagnostics[0].message


def test_host_path_route_conflicts_with_shadowed_contributed_converter_route():
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/records/{rest:path}")
    def _host(rest: str):
        return {"source": "host", "rest": rest}

    contributed = APIRouter()

    @contributed.get("/records/{id:int}")
    def _extension(id: int):
        return {"source": "extension", "id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/records/{id:int}" in diagnostics[0].message


def test_host_mount_conflicts_with_a_route_below_its_prefix():
    """A preceding Mount consumes every descendant before later routes."""
    from fastapi import APIRouter, FastAPI
    from starlette.applications import Starlette

    app = FastAPI()
    app.mount("/assets", Starlette())

    contributed = APIRouter()

    @contributed.get("/assets/{name}")
    def _extension(name: str):
        return {"name": name}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/assets/{name}" in diagnostics[0].message


def test_host_root_mount_conflicts_with_every_contributed_route():
    """Starlette normalizes Mount('/') to an empty route.path."""
    from fastapi import APIRouter, FastAPI
    from starlette.applications import Starlette

    app = FastAPI()
    app.mount("/", Starlette())

    contributed = APIRouter()

    @contributed.get("/extension")
    def _extension():
        return {"source": "extension"}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/extension" in diagnostics[0].message


def test_host_dynamic_mount_conflicts_with_a_narrower_descendant_route():
    from fastapi import APIRouter, FastAPI
    from starlette.applications import Starlette

    app = FastAPI()
    app.mount("/users/{tenant}", Starlette())

    contributed = APIRouter()

    @contributed.get("/users/fixed/{id:int}")
    def _extension(id: int):
        return {"id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/users/fixed/{id:int}" in diagnostics[0].message


def test_host_embedded_parameter_mount_conflicts_with_static_descendant():
    from fastapi import APIRouter, FastAPI
    from starlette.applications import Starlette

    app = FastAPI()
    app.mount("/pre{tenant}", Starlette())

    contributed = APIRouter()

    @contributed.get("/prefoo/bar")
    def _extension():
        return {"source": "extension"}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/prefoo/bar" in diagnostics[0].message


def test_terminal_path_route_with_dynamic_prefix_shadows_narrower_route():
    """A terminal :path converter consumes the candidate's remaining segments."""
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/{tenant}/{rest:path}")
    def _host(tenant: str, rest: str):
        return {"tenant": tenant, "rest": rest}

    contributed = APIRouter()

    @contributed.get("/fixed/{id:int}")
    def _extension(id: int):
        return {"id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/fixed/{id:int}" in diagnostics[0].message


def test_terminal_path_route_does_not_shadow_a_candidate_without_a_remainder():
    """The slash before Starlette's terminal :path parameter is required."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/org/{tenant}/{rest:path}")
    def _host(tenant: str, rest: str):
        return {"source": "host", "tenant": tenant, "rest": rest}

    contributed = APIRouter()

    @contributed.get("/org/{id:int}")
    def _extension(id: int):
        return {"source": "extension", "id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert diagnostics == []
    assert TestClient(app).get("/org/123").json() == {
        "source": "extension",
        "id": 123,
    }


def test_terminal_path_route_shadows_an_embedded_parameter_remainder():
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/{tenant}/{rest:path}")
    def _host(tenant: str, rest: str):
        return {"tenant": tenant, "rest": rest}

    contributed = APIRouter()

    @contributed.get("/fixed/pre{id:int}")
    def _extension(id: int):
        return {"id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/fixed/pre{id:int}" in diagnostics[0].message


def test_broad_dynamic_segments_shadow_static_and_narrower_segments():
    from fastapi import APIRouter, FastAPI

    app = FastAPI()

    @app.get("/{first}/{second}")
    def _host(first: str, second: str):
        return {"first": first, "second": second}

    contributed = APIRouter()

    @contributed.get("/fixed/{id:int}")
    def _extension(id: int):
        return {"id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "extension:install"
    assert "host" in diagnostics[0].message
    assert "/fixed/{id:int}" in diagnostics[0].message


def test_contributed_router_mount_is_rejected_instead_of_silently_ignored():
    """FastAPI.include_router() does not copy Starlette Mount entries."""
    from fastapi import APIRouter, FastAPI
    from starlette.applications import Starlette

    mounted = APIRouter()
    mounted.mount("/assets", Starlette())

    ordinary = APIRouter()

    @ordinary.get("/assets/{name}")
    def _ordinary(name: str):
        return {"name": name}

    app = FastAPI()
    diagnostics = include_contributed_routers(
        app,
        _with_routers(
            ("mounted:install", [mounted]),
            ("ordinary:install", [ordinary]),
        ),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "mounted:install"
    assert "Mount" in diagnostics[0].message
    assert any(getattr(route, "path", "") == "/assets/{name}" for route in app.routes), "a rejected Mount must not claim a route FastAPI never installed"


def test_dynamic_routes_with_different_methods_do_not_conflict():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    reads = APIRouter()
    writes = APIRouter()

    @reads.get("/items/{item_id}")
    def _read(item_id: str):
        return {"method": "GET", "item_id": item_id}

    @writes.post("/items/{id}")
    def _write(id: str):
        return {"method": "POST", "item_id": id}

    app = FastAPI()
    extensions = _with_routers(
        ("reads:install", [reads]),
        ("writes:install", [writes]),
    )
    diagnostics = include_contributed_routers(app, extensions)

    assert diagnostics == []
    client = TestClient(app)
    assert client.get("/items/42").json()["method"] == "GET"
    assert client.post("/items/42").json()["method"] == "POST"


def test_equivalent_websocket_and_http_routes_do_not_conflict():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.websocket("/live/{item_id}")
    async def _live(websocket: WebSocket, item_id: str):
        await websocket.accept()
        await websocket.send_text(item_id)
        await websocket.close()

    contributed = APIRouter()

    @contributed.get("/live/{id}")
    def _read(id: str):
        return {"item_id": id}

    diagnostics = include_contributed_routers(
        app,
        _with_routers(("extension:install", [contributed])),
    )

    assert diagnostics == []
    client = TestClient(app)
    assert client.get("/live/http").json() == {"item_id": "http"}
    with client.websocket_connect("/live/socket") as websocket:
        assert websocket.receive_text() == "socket"


def test_a_conflicting_router_is_not_mounted():
    """First writer wins: silently shadowing an already-mounted path would make
    which extension answers depend on load order."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    winner = _router("/shared")

    loser = _router("/shared")
    for route in loser.routes:
        route.endpoint = lambda: {"ok": False}

    extensions = _with_routers(("first:install", [winner]), ("second:install", [loser]))
    include_contributed_routers(app, extensions)

    assert TestClient(app).get("/shared/ping").json() == {"ok": True}


def test_a_router_that_fails_to_mount_is_fail_open():
    from fastapi import FastAPI

    app = FastAPI()
    extensions = _with_routers(("bad:install", ["not-a-router"]), ("good:install", [_router("/good")]))
    diagnostics = include_contributed_routers(app, extensions)

    assert any(d.source == "bad:install" and d.level == "error" for d in diagnostics)
    assert any(getattr(r, "path", "") == "/good/ping" for r in app.routes), "a later router still mounts"


def test_zero_routers_is_a_no_op():
    from fastapi import FastAPI

    app = FastAPI()
    before = len(app.routes)
    assert include_contributed_routers(app, ExtensionRegistry().build()) == []
    assert len(app.routes) == before


@pytest.mark.parametrize("bad", [None, object()])
def test_router_mounting_tolerates_junk(bad):
    from fastapi import FastAPI

    app = FastAPI()
    extensions = _with_routers(("bad:install", [bad]))
    diagnostics = include_contributed_routers(app, extensions)
    assert len(diagnostics) == 1
    assert diagnostics[0].level == "error"


# --- the real create_app wiring ---------------------------------------------
#
# Everything above tests the helpers in isolation, which passes even if
# create_app never calls them. These drive the real app builder.


def test_create_app_mounts_contributed_routers_and_records_diagnostics(monkeypatch):
    import deerflow.extensions as extensions_module
    from deerflow.extensions import reset_loaded_extensions

    built = _with_routers(("ext0:install", [_router("/ext-e2e")]))
    monkeypatch.setattr(extensions_module, "load_extensions", lambda plugins: (built, []))

    reset_loaded_extensions()
    try:
        from fastapi.testclient import TestClient

        from app.gateway.app import create_app

        app = create_app()

        assert app.state.extensions is built
        assert app.state.extension_diagnostics == []
        assert any(getattr(r, "path", "") == "/ext-e2e/ping" for r in app.routes), "the contributed route was not mounted"
        # Not a 200: contributed routers sit behind the Gateway's auth
        # middleware like every other route, which is the intended posture.
        assert TestClient(app).get("/ext-e2e/ping").status_code != 404
        assert extensions_module.get_loaded_extensions() is built, "the process-wide singleton must be set too"
    finally:
        reset_loaded_extensions()


def test_create_app_exposes_runtime_diagnostics_through_its_live_state(monkeypatch):
    import deerflow.extensions as extensions_module
    from deerflow.extensions import (
        Diagnostic,
        record_runtime_diagnostic,
        reset_loaded_extensions,
    )

    built = ExtensionRegistry().build()
    monkeypatch.setattr(extensions_module, "load_extensions", lambda plugins: (built, []))

    reset_loaded_extensions()
    try:
        from app.gateway.app import create_app

        app = create_app()
        diagnostic = Diagnostic.error("runtime:install", "middleware failed")

        record_runtime_diagnostic(diagnostic)

        assert app.state.extension_diagnostics == [diagnostic]
    finally:
        reset_loaded_extensions()


def test_recreating_the_app_keeps_one_canonical_diagnostic_list(monkeypatch):
    import deerflow.extensions as extensions_module
    from deerflow.extensions import (
        Diagnostic,
        record_runtime_diagnostic,
        reset_loaded_extensions,
    )

    built = ExtensionRegistry().build()
    monkeypatch.setattr(extensions_module, "load_extensions", lambda plugins: (built, []))

    reset_loaded_extensions()
    try:
        from app.gateway.app import create_app

        first_app = create_app()
        second_app = create_app()
        diagnostic = Diagnostic.error("runtime:install", "middleware failed")

        record_runtime_diagnostic(diagnostic)

        assert first_app.state.extension_diagnostics is second_app.state.extension_diagnostics
        assert first_app.state.extension_diagnostics == [diagnostic]
    finally:
        reset_loaded_extensions()


def test_create_app_refuses_to_let_an_extension_shadow_a_host_route(monkeypatch):
    """Contributed routers mount last, so a host path is always already claimed
    and the extension is told it collided instead of silently winning."""
    from fastapi import APIRouter

    import deerflow.extensions as extensions_module
    from deerflow.extensions import reset_loaded_extensions

    hijack = APIRouter()

    @hijack.get("/health")
    def _hijacked():
        return {"status": "hijacked"}

    built = _with_routers(("evil:install", [hijack]))
    monkeypatch.setattr(extensions_module, "load_extensions", lambda plugins: (built, []))

    reset_loaded_extensions()
    try:
        from fastapi.testclient import TestClient

        from app.gateway.app import create_app

        app = create_app()

        assert TestClient(app).get("/health").json()["service"] == "deer-flow-gateway"
        assert any(d.source == "evil:install" and "/health" in d.message for d in app.state.extension_diagnostics)
    finally:
        reset_loaded_extensions()


def test_create_app_survives_a_loader_that_raises(monkeypatch):
    """A malformed plugins block must not stop the Gateway from booting."""
    import deerflow.extensions as extensions_module
    from deerflow.extensions import reset_loaded_extensions

    def _boom(plugins):
        raise RuntimeError("bad plugins config")

    monkeypatch.setattr(extensions_module, "load_extensions", _boom)

    reset_loaded_extensions()
    try:
        from app.gateway.app import create_app

        app = create_app()
        assert app.state.extensions is not None
        assert app.state.extension_diagnostics == []
    finally:
        reset_loaded_extensions()


def test_create_app_aborts_when_a_required_extension_fails(monkeypatch):
    """`required: true` is fail-closed: the loader signals it with
    ExtensionLoadError, and create_app must let that abort startup instead of
    booting with zero extensions — silently dropping every other successfully
    loaded extension along with the failed one would be worse than fail-open.
    """
    import deerflow.extensions as extensions_module
    from deerflow.extensions import ExtensionLoadError, reset_loaded_extensions

    def _required_boom(plugins):
        raise ExtensionLoadError("required extension acme_policy:install failed to install")

    monkeypatch.setattr(extensions_module, "load_extensions", _required_boom)

    reset_loaded_extensions()
    try:
        from app.gateway.app import create_app

        with pytest.raises(ExtensionLoadError):
            create_app()
    finally:
        reset_loaded_extensions()
