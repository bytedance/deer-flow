"""Gateway binding tests for app-scoped extension contributions."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from deerflow.extensions.registry import ExtensionRegistry


class _Service:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:
        self.name = name
        self.events = events
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.deps = None

    async def start(self, deps) -> None:
        self.events.append(f"start:{self.name}")
        self.deps = deps
        if self.fail_start:
            raise RuntimeError(f"{self.name} failed")

    async def stop(self) -> None:
        self.events.append(f"stop:{self.name}")
        if self.fail_stop:
            raise RuntimeError(f"{self.name} failed")


@pytest.mark.asyncio
async def test_services_start_in_order_with_narrow_deps_and_fail_open():
    from deerflow.extensions.gateway import start_services

    events: list[str] = []
    first = _Service("first", events, fail_start=True)
    second = _Service("second", events)
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("second:install"):
        registry.service(second)
    extensions = registry.build()
    session_factory = object()
    config = SimpleNamespace(
        token_budget=SimpleNamespace(enabled=False, max_tokens=999),
        subagents=SimpleNamespace(max_total_per_run=4),
    )

    diagnostics = await start_services(extensions, config, session_factory)

    assert events == ["start:first", "start:second"]
    assert first.deps is second.deps
    assert second.deps.app_store is extensions.app_store
    assert second.deps.session_factory is session_factory
    assert second.deps.policy.token_budget_enabled is False
    assert second.deps.policy.max_total_tokens is None
    assert second.deps.policy.max_subagents_per_run == 4
    assert [(diagnostic.source, diagnostic.level) for diagnostic in diagnostics] == [("first:install", "error")]


@pytest.mark.asyncio
async def test_service_originated_cancelled_error_does_not_abort_start_batch():
    from deerflow.extensions.gateway import start_services

    events: list[str] = []

    class _CancelsItself(_Service):
        async def start(self, deps) -> None:
            self.events.append(f"start:{self.name}")
            raise asyncio.CancelledError()

    first = _CancelsItself("first", events)
    second = _Service("second", events)
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("second:install"):
        registry.service(second)

    diagnostics = await start_services(registry.build(), SimpleNamespace(), None)

    assert events == ["start:first", "start:second"]
    assert len(diagnostics) == 1
    assert diagnostics[0].source == "first:install"
    assert "CancelledError" in diagnostics[0].message


@pytest.mark.asyncio
async def test_services_stop_in_reverse_order_and_fail_open():
    from deerflow.extensions.gateway import stop_services

    events: list[str] = []
    first = _Service("first", events)
    second = _Service("second", events, fail_stop=True)
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("second:install"):
        registry.service(second)

    diagnostics = await stop_services(registry.build())

    assert events == ["stop:second", "stop:first"]
    assert [(diagnostic.source, diagnostic.level) for diagnostic in diagnostics] == [("second:install", "error")]


@pytest.mark.asyncio
async def test_service_originated_cancelled_error_does_not_abort_stop_batch():
    from deerflow.extensions.gateway import stop_services

    events: list[str] = []

    class _CancelsItself(_Service):
        async def stop(self) -> None:
            self.events.append(f"stop:{self.name}")
            raise asyncio.CancelledError()

    first = _Service("first", events)
    second = _CancelsItself("second", events)
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("second:install"):
        registry.service(second)

    diagnostics = await stop_services(registry.build())

    assert events == ["stop:second", "stop:first"]
    assert len(diagnostics) == 1
    assert diagnostics[0].source == "second:install"
    assert "CancelledError" in diagnostics[0].message


@pytest.mark.asyncio
async def test_each_service_stop_has_its_own_timeout_budget():
    from deerflow.extensions.gateway import stop_services

    events: list[str] = []

    class _HangingService(_Service):
        async def stop(self) -> None:
            self.events.append(f"stop:{self.name}")
            await asyncio.Event().wait()

    first = _Service("first", events)
    second = _HangingService("second", events)
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("second:install"):
        registry.service(second)

    diagnostics = await stop_services(registry.build(), timeout_seconds=0.01)

    assert events == ["stop:second", "stop:first"]
    assert len(diagnostics) == 1
    assert diagnostics[0].source == "second:install"
    assert "timed out" in diagnostics[0].message


@pytest.mark.asyncio
async def test_service_originated_timeout_error_is_reported_as_failure_not_budget_expiry():
    from deerflow.extensions.gateway import stop_services

    events: list[str] = []

    class _RaisesTimeout(_Service):
        async def stop(self) -> None:
            self.events.append(f"stop:{self.name}")
            raise TimeoutError("extension deadline")

    first = _Service("first", events)
    second = _RaisesTimeout("second", events)
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("second:install"):
        registry.service(second)

    diagnostics = await stop_services(registry.build(), timeout_seconds=1.0)

    assert events == ["stop:second", "stop:first"]
    assert diagnostics[0].source == "second:install"
    assert "failed" in diagnostics[0].message
    assert "timed out" not in diagnostics[0].message


@pytest.mark.parametrize(
    ("owner_path", "owner_protocol", "candidate_path", "candidate_protocol", "rejected"),
    [
        ("/exact", "GET", "/exact", "GET", True),
        ("/items/{item_id}", "GET", "/items/{id}", "GET", True),
        ("/items/{item_id}", "GET", "/items/new", "GET", True),
        ("/items/{item_id}", "GET", "/items/prefix-{id}", "GET", True),
        ("/pre{tenant}", "GET", "/prefoo{id}", "GET", True),
        ("/items/new", "GET", "/items/{id}", "GET", False),
        ("/records/{value}", "GET", "/records/{id:int}", "GET", True),
        ("/records/{value:int}", "GET", "/records/0{id:int}", "GET", True),
        ("/records/{value:int}", "GET", "/records/new", "GET", False),
        ("/files/{rest:path}", "GET", "/files/{id:int}", "GET", True),
        ("/files/{rest:path}", "GET", "/files/{id}", "GET", False),
        ("/x/{rest:path}/tail", "GET", "/x/a/{id}/tail", "GET", False),
        ("/items/{item_id}", "GET", "/items/{id}", "POST", False),
        ("/live/{item_id}", "WS", "/live/{id}", "GET", False),
    ],
    ids=[
        "exact",
        "renamed-parameter",
        "dynamic-shadows-static",
        "dynamic-shadows-compound",
        "compound-trailing-str-shadows-narrower-compound",
        "static-does-not-shadow-dynamic",
        "str-covers-int",
        "int-shadows-digit-compound",
        "int-does-not-cover-static",
        "path-covers-descendant",
        "path-does-not-cover-newline-capable-str",
        "nonterminal-path-does-not-cover-newline-capable-str",
        "disjoint-http-methods",
        "websocket-does-not-shadow-http",
    ],
)
def test_router_conflicts_follow_starlette_dispatch_order(
    owner_path,
    owner_protocol,
    candidate_path,
    candidate_protocol,
    rejected,
):
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    app = FastAPI()
    if owner_protocol == "WS":
        app.add_api_websocket_route(owner_path, endpoint)
    else:
        app.add_api_route(owner_path, endpoint, methods=[owner_protocol])

    router = APIRouter()
    if candidate_protocol == "WS":
        router.add_api_websocket_route(candidate_path, endpoint)
    else:
        router.add_api_route(candidate_path, endpoint, methods=[candidate_protocol])
    registry = ExtensionRegistry()
    with registry.attributed_to("candidate:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert bool(diagnostics) is rejected
    if rejected:
        assert diagnostics[0].source == "candidate:install"
        assert "host" in diagnostics[0].message
        assert candidate_path in diagnostics[0].message
    else:
        assert any(getattr(route, "path", None) == candidate_path for route in app.routes)


@pytest.mark.parametrize("convertor_name", ["flip", "int"])
def test_re_registered_convertor_does_not_create_a_false_shadow(
    monkeypatch,
    convertor_name,
):
    from fastapi import APIRouter, FastAPI
    from starlette.convertors import CONVERTOR_TYPES, Convertor
    from starlette.routing import Match

    from deerflow.extensions.gateway import include_contributed_routers

    class DigitsConvertor(Convertor[str]):
        regex = "[0-9]+"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    class LettersConvertor(Convertor[str]):
        regex = "[A-Z]+"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    async def endpoint(value: str):
        return {"value": value}

    monkeypatch.setitem(CONVERTOR_TYPES, convertor_name, DigitsConvertor())
    route_path = f"/owned/{{value:{convertor_name}}}"
    app = FastAPI()
    app.add_api_route(route_path, endpoint, methods=["GET"])
    owner = app.routes[-1]

    monkeypatch.setitem(CONVERTOR_TYPES, convertor_name, LettersConvertor())
    router = APIRouter()
    router.add_api_route(route_path, endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("candidate:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert diagnostics == []
    candidate = app.routes[-1]
    scope = {
        "type": "http",
        "path": "/owned/A",
        "method": "GET",
        "root_path": "",
    }
    assert owner.matches(scope)[0] is Match.NONE
    assert candidate.matches(scope)[0] is Match.FULL


def test_router_claim_uses_converter_semantics_at_include_time(monkeypatch):
    from fastapi import APIRouter, FastAPI
    from starlette.convertors import CONVERTOR_TYPES, Convertor
    from starlette.routing import Match

    from deerflow.extensions.gateway import include_contributed_routers

    class DigitsConvertor(Convertor[str]):
        regex = "[0-9]+"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    class LettersConvertor(Convertor[str]):
        regex = "[A-Z]+"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    async def endpoint(value: str):
        return {"value": value}

    monkeypatch.setitem(CONVERTOR_TYPES, "flip", DigitsConvertor())
    route_path = "/owned/{value:flip}"
    app = FastAPI()
    app.add_api_route(route_path, endpoint, methods=["GET"])
    owner = app.routes[-1]
    router = APIRouter()
    router.add_api_route(route_path, endpoint, methods=["GET"])

    monkeypatch.setitem(CONVERTOR_TYPES, "flip", LettersConvertor())
    registry = ExtensionRegistry()
    with registry.attributed_to("candidate:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert diagnostics == []
    candidate = app.routes[-1]
    scope = {
        "type": "http",
        "path": "/owned/A",
        "method": "GET",
        "root_path": "",
    }
    assert owner.matches(scope)[0] is Match.NONE
    assert candidate.matches(scope)[0] is Match.FULL


def test_recompiled_converter_cannot_enter_a_public_namespace(monkeypatch):
    from fastapi import APIRouter, FastAPI
    from starlette.convertors import CONVERTOR_TYPES, Convertor

    from deerflow.extensions.gateway import include_contributed_routers

    class PublicPathConvertor(Convertor[str]):
        regex = r"webhooks/.+"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    async def endpoint(value: str):
        return {"value": value}

    router = APIRouter()
    router.add_api_route("/api/{value:int}", endpoint, methods=["GET"])
    monkeypatch.setitem(CONVERTOR_TYPES, "int", PublicPathConvertor())
    registry = ExtensionRegistry()
    with registry.attributed_to("candidate:install"):
        registry.routers((router,))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["candidate:install"]
    assert "public namespace" in diagnostics[0].message
    assert not any(getattr(route, "path", None) == "/api/{value:int}" for route in app.routes)


def test_host_mount_claims_descendant_http_paths():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    app = FastAPI()
    app.mount("/assets", FastAPI())
    router = APIRouter()

    @router.get("/assets/{name:int}")
    async def asset(name: int):
        return {"name": name}

    registry = ExtensionRegistry()
    with registry.attributed_to("assets:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert len(diagnostics) == 1
    assert diagnostics[0].source == "assets:install"
    assert "host" in diagnostics[0].message


def test_dynamic_host_mount_claims_matching_descendants():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    app = FastAPI()
    app.mount("/pre{tenant}", FastAPI())
    router = APIRouter()

    @router.get("/prefoo/{item_id:int}")
    async def item(item_id: int):
        return {"item_id": item_id}

    registry = ExtensionRegistry()
    with registry.attributed_to("mount:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["mount:install"]
    assert "host" in diagnostics[0].message


@pytest.mark.parametrize(
    ("mount_path", "candidate_path", "witness"),
    [
        ("/assets", "/assets/{name}", "/assets/a\nb"),
        ("/pre{tenant}", "/prefoo{id}/{child}", "/prefoo1/a\nb"),
    ],
)
def test_host_mount_does_not_claim_newline_capable_str_descendants(
    mount_path,
    candidate_path,
    witness,
):
    from fastapi import APIRouter, FastAPI
    from starlette.routing import Match, Mount

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    app = FastAPI()
    app.mount(mount_path, FastAPI())
    host_mount = next(route for route in app.routes if isinstance(route, Mount) and route.path == mount_path)
    router = APIRouter()
    router.add_api_route(candidate_path, endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("mount:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert diagnostics == []
    candidate_route = next(route for route in app.routes if getattr(route, "path", None) == candidate_path)
    scope = {
        "type": "http",
        "path": witness,
        "method": "GET",
        "root_path": "",
    }
    assert host_mount.matches(scope)[0] is Match.NONE
    assert candidate_route.matches(scope)[0] is Match.FULL


def test_contributed_websocket_route_is_rejected_until_host_auth_wraps_it():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def websocket_endpoint(websocket):
        await websocket.close()

    router = APIRouter()
    router.add_api_websocket_route("/extension-ws", websocket_endpoint)
    registry = ExtensionRegistry()
    with registry.attributed_to("websocket:install"):
        registry.routers((router,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["websocket:install"]
    assert "WebSocket" in diagnostics[0].message
    assert not any(getattr(route, "path", None) == "/extension-ws" for route in app.routes)


@pytest.mark.parametrize(
    "path",
    [
        "/health-extension",
        "/docs-private",
        "/redoc-private",
        "/api/webhooks/extension",
        "/api/{rest:path}",
        "/api/{section}/extension",
    ],
)
def test_extension_routes_cannot_enter_host_public_namespaces(path):
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    router = APIRouter()
    router.add_api_route(path, endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("public:install"):
        registry.routers((router,))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["public:install"]
    assert "public namespace" in diagnostics[0].message
    assert not any(getattr(route, "path", None) == path for route in app.routes)


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/heal",
        "/api/{item_id:int}",
        "/api/{item_id}",
    ],
)
def test_extension_routes_that_cannot_enter_a_public_namespace_are_allowed(path):
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    router = APIRouter()
    router.add_api_route(path, endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("private:install"):
        registry.routers((router,))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    diagnostics = include_contributed_routers(app, registry.build())

    assert diagnostics == []
    assert any(getattr(route, "path", None) == path for route in app.routes)


def test_unknown_convertor_near_a_public_namespace_fails_closed(monkeypatch):
    from fastapi import APIRouter, FastAPI
    from starlette.convertors import CONVERTOR_TYPES, Convertor

    from deerflow.extensions.gateway import include_contributed_routers

    class UppercaseConvertor(Convertor[str]):
        regex = "[A-Z]+"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    monkeypatch.setitem(CONVERTOR_TYPES, "uppercase", UppercaseConvertor())
    router = APIRouter()
    router.add_api_route(
        "/api/{value:uppercase}",
        lambda: {"ok": True},
        methods=["GET"],
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("custom-public:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(
        FastAPI(docs_url=None, redoc_url=None, openapi_url=None),
        registry.build(),
    )

    assert [diagnostic.source for diagnostic in diagnostics] == ["custom-public:install"]
    assert "public namespace" in diagnostics[0].message


def test_private_custom_convertor_with_named_backreference_is_allowed(monkeypatch):
    from fastapi import APIRouter, FastAPI
    from starlette.convertors import CONVERTOR_TYPES, Convertor

    from deerflow.extensions.gateway import include_contributed_routers

    class DoubledLetterConvertor(Convertor[str]):
        regex = r"(?P<char>[A-Z])(?P=char)"

        def convert(self, value: str) -> str:
            return value

        def to_string(self, value: str) -> str:
            return value

    monkeypatch.setitem(CONVERTOR_TYPES, "doubled", DoubledLetterConvertor())
    router = APIRouter()
    router.add_api_route(
        "/private/{value:doubled}",
        lambda value: {"value": value},
        methods=["GET"],
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("custom-private:install"):
        registry.routers((router,))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    diagnostics = include_contributed_routers(app, registry.build())

    assert diagnostics == []
    assert any(getattr(route, "path", None) == "/private/{value:doubled}" for route in app.routes)


def test_extension_public_paths_track_auth_middleware_public_paths():
    from app.gateway.auth_middleware import (
        _PUBLIC_EXACT_PATHS,
        _PUBLIC_PATH_PREFIXES,
        _is_public,
    )
    from deerflow.extensions.gateway import (
        _HOST_PUBLIC_EXACT_PATHS,
        _HOST_PUBLIC_PATH_PREFIXES,
    )

    assert _HOST_PUBLIC_PATH_PREFIXES == _PUBLIC_PATH_PREFIXES
    assert _HOST_PUBLIC_EXACT_PATHS == _PUBLIC_EXACT_PATHS
    assert all(_is_public(f"{path}//") for path in _HOST_PUBLIC_EXACT_PATHS)


@pytest.mark.parametrize(
    ("host_path", "host_method", "candidate_path", "candidate_method"),
    [
        (
            "/api/v1/auth/login/local",
            "POST",
            "/api/v1/auth/login/local",
            "GET",
        ),
        (
            "/api/v1/auth/login/local",
            "POST",
            "/api/v1/auth/login/local/",
            "GET",
        ),
        (
            "/api/v1/auth/login/local",
            "POST",
            "/api/v1/auth/login/local//",
            "GET",
        ),
        ("/api/v1/auth/me", "GET", "/api/v1/auth/me", "POST"),
        ("/api/v1/auth/me", "GET", "/api/v1/auth/me/", "POST"),
    ],
)
def test_extension_routes_cannot_claim_reserved_exact_paths_with_a_disjoint_method(
    host_path,
    host_method,
    candidate_path,
    candidate_method,
):
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    app = FastAPI()
    app.add_api_route(host_path, endpoint, methods=[host_method])
    router = APIRouter()
    router.add_api_route(candidate_path, endpoint, methods=[candidate_method])
    registry = ExtensionRegistry()
    with registry.attributed_to("public-exact:install"):
        registry.routers((router,))

    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["public-exact:install"]
    assert "reserved" in diagnostics[0].message
    assert not any(getattr(route, "path", None) == candidate_path and getattr(route, "methods", set()) == {candidate_method} for route in app.routes)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/auth/me/",
        "/api/v1/auth/me//",
    ],
)
def test_extension_csrf_reserved_exact_paths_track_csrf_exemption(
    monkeypatch,
    path,
):
    from starlette.requests import Request

    from app.gateway import csrf_middleware
    from deerflow.extensions.gateway import (
        _CSRF_STATE_CHANGING_METHODS,
        _HOST_CSRF_EXEMPT_EXACT_PATHS,
        _HOST_PUBLIC_EXACT_PATHS,
    )

    monkeypatch.setattr(csrf_middleware, "is_auth_disabled", lambda: False)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
        }
    )

    assert path.rstrip("/") in _HOST_CSRF_EXEMPT_EXACT_PATHS
    assert _HOST_CSRF_EXEMPT_EXACT_PATHS == csrf_middleware._CSRF_EXEMPT_EXACT_PATHS
    assert _CSRF_STATE_CHANGING_METHODS == csrf_middleware._CSRF_STATE_CHANGING_METHODS
    assert csrf_middleware._AUTH_EXEMPT_PATHS <= _HOST_PUBLIC_EXACT_PATHS
    assert csrf_middleware.should_check_csrf(request) is False


def test_safe_method_at_csrf_exempt_exact_path_is_not_reserved():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    router = APIRouter()
    router.add_api_route(
        "/api/v1/auth/me",
        lambda: {"ok": True},
        methods=["GET"],
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("safe-csrf:install"):
        registry.routers((router,))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    diagnostics = include_contributed_routers(app, registry.build())

    assert diagnostics == []
    assert any(getattr(route, "path", None) == "/api/v1/auth/me" for route in app.routes)


def test_router_with_one_conflict_is_rejected_atomically_and_names_first_owner():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    first = APIRouter()
    first.add_api_route("/shared", endpoint, methods=["GET"])
    second = APIRouter()
    second.add_api_route("/would-have-been-reachable", endpoint, methods=["GET"])
    second.add_api_route("/shared", endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.routers((first,))
    with registry.attributed_to("second:install"):
        registry.routers((second,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())
    paths = [getattr(route, "path", None) for route in app.routes]

    assert "/shared" in paths
    assert "/would-have-been-reachable" not in paths
    assert len(diagnostics) == 1
    assert diagnostics[0].source == "second:install"
    assert "first:install" in diagnostics[0].message


def test_router_is_rejected_when_its_own_earlier_route_shadows_a_later_one():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    router = APIRouter()
    router.add_api_route("/same/{value}", endpoint, methods=["GET"])
    router.add_api_route("/same/fixed", endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("self-shadow:install"):
        registry.routers((router,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["self-shadow:install"]
    assert "self-shadow:install" in diagnostics[0].message
    assert not any(getattr(route, "path", "").startswith("/same/") for route in app.routes)


def test_contributed_mount_is_rejected_but_does_not_starve_later_router():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    bad = APIRouter()
    bad.mount("/nested", FastAPI())
    good = APIRouter()

    @good.get("/extension-good")
    async def extension_good():
        return {"ok": True}

    registry = ExtensionRegistry()
    with registry.attributed_to("bad:install"):
        registry.routers((bad,))
    with registry.attributed_to("good:install"):
        registry.routers((good,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["bad:install"]
    assert "Mount" in diagnostics[0].message
    assert any(getattr(route, "path", None) == "/extension-good" for route in app.routes)


def test_router_with_unsupported_route_item_is_rejected_atomically():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    router = APIRouter()
    router.add_api_route("/otherwise-valid", endpoint, methods=["GET"])
    router.routes.append(object())
    registry = ExtensionRegistry()
    with registry.attributed_to("unsupported:install"):
        registry.routers((router,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["unsupported:install"]
    assert "unsupported route" in diagnostics[0].message
    assert not any(getattr(route, "path", None) == "/otherwise-valid" for route in app.routes)


def test_include_router_failure_rolls_back_partial_routes_before_continuing():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    broken = APIRouter()
    broken.add_api_route("/partial", endpoint, methods=["GET"])
    broken.add_api_route("/explodes", endpoint, methods=["GET"])
    broken.routes[-1].endpoint = None
    later = APIRouter()
    later.add_api_route("/partial", endpoint, methods=["GET"])

    registry = ExtensionRegistry()
    with registry.attributed_to("broken:install"):
        registry.routers((broken,))
    with registry.attributed_to("later:install"):
        registry.routers((later,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())
    partial_routes = [route for route in app.routes if getattr(route, "path", None) == "/partial"]

    assert [diagnostic.source for diagnostic in diagnostics] == ["broken:install"]
    assert len(partial_routes) == 1


def test_router_lifecycle_hooks_are_rejected_in_favor_of_extension_service():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    async def endpoint():
        return {"ok": True}

    async def startup_hook():
        raise RuntimeError("must never be installed")

    bad = APIRouter()
    bad.add_api_route("/has-lifecycle", endpoint, methods=["GET"])
    bad.add_event_handler("startup", startup_hook)
    good = APIRouter()
    good.add_api_route("/after-lifecycle", endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("lifecycle:install"):
        registry.routers((bad,))
    with registry.attributed_to("good:install"):
        registry.routers((good,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())
    paths = [getattr(route, "path", None) for route in app.routes]

    assert [diagnostic.source for diagnostic in diagnostics] == ["lifecycle:install"]
    assert "ExtensionService" in diagnostics[0].message
    assert "/has-lifecycle" not in paths
    assert "/after-lifecycle" in paths
    assert startup_hook not in app.router.on_startup


def test_router_custom_lifespan_is_rejected_in_favor_of_extension_service():
    from fastapi import APIRouter, FastAPI

    from deerflow.extensions.gateway import include_contributed_routers

    @asynccontextmanager
    async def lifespan(_app):
        yield

    async def endpoint():
        return {"ok": True}

    router = APIRouter(lifespan=lifespan)
    router.add_api_route("/custom-lifespan", endpoint, methods=["GET"])
    registry = ExtensionRegistry()
    with registry.attributed_to("lifespan:install"):
        registry.routers((router,))

    app = FastAPI()
    diagnostics = include_contributed_routers(app, registry.build())

    assert [diagnostic.source for diagnostic in diagnostics] == ["lifespan:install"]
    assert "ExtensionService" in diagnostics[0].message
    assert not any(getattr(route, "path", None) == "/custom-lifespan" for route in app.routes)
