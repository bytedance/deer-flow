"""Canonical thread ID contract: every HTTP route and embedded-client entry
point that takes a ``thread_id`` must enforce ``ThreadId`` validation.

Two complementary guards:

1. A static sweep (AST over ``app/gateway/routers/*.py``) asserting every
   route handler that declares a ``thread_id`` parameter annotates it
   ``ThreadId`` — this is what prevents new routes from silently landing
   with a raw ``str`` again (the suggestions/thread_runs/threads gaps).
2. A runtime sweep hitting every ``{thread_id}`` route with a non-canonical
   ID and asserting a 422 whose error location names ``thread_id``.

Deliberate exceptions (RFC #4588):
- ``DELETE /api/threads/{thread_id}`` keeps ``thread_id: str`` as the
  legacy-cleanup escape hatch.
- The browser websocket stream validates on upgrade; covered separately.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "app" / "gateway" / "routers"

# (handler name) route handlers deliberately allowed to keep ``thread_id: str``.
STATIC_WHITELIST = {"delete_thread_data"}

# (method, path) routes deliberately excluded from the runtime 422 sweep.
RUNTIME_WHITELIST = {
    ("DELETE", "/api/threads/{thread_id}"),  # legacy-cleanup escape hatch
}

BAD_THREAD_ID = "bad.thread.id"

_ROUTE_DECORATOR_RE = re.compile(r"router\.(get|post|delete|put|patch|websocket)")


def _iter_route_handlers(path: Path):
    """Yield (handler_name, has_thread_id_param, annotation) for route handlers."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name) and _ROUTE_DECORATOR_RE.fullmatch(f"{dec.func.value.id}.{dec.func.attr}") for dec in node.decorator_list):
            continue
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.arg == "thread_id":
                annotation = ast.unparse(arg.annotation) if arg.annotation else None
                yield node.name, annotation


def test_every_thread_id_route_handler_uses_canonical_type():
    """Static guard: no route handler may declare a bare ``str`` thread_id."""
    violations = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        for handler, annotation in _iter_route_handlers(path):
            if handler in STATIC_WHITELIST:
                continue
            if annotation != "ThreadId":
                violations.append(f"{path.name}:{handler} -> {annotation!r}")
    assert not violations, "route handlers with non-canonical thread_id:\n" + "\n".join(violations)


def _collect_thread_id_routes():
    """Import every gateway router and collect (method, full_path) with {thread_id}."""
    from app.gateway.routers import (
        artifacts,
        browser,
        feedback,
        runs,
        scheduled_tasks,
        skills,
        suggestions,
        thread_runs,
        threads,
        uploads,
    )

    routers = [artifacts, browser, feedback, runs, scheduled_tasks, skills, suggestions, thread_runs, threads, uploads]
    cases = []
    for module in routers:
        for route in module.router.routes:
            path = getattr(route, "path", "")
            if "{thread_id}" not in path:
                continue
            methods = getattr(route, "methods", None)
            if methods is None:
                continue  # websocket routes — covered by the dedicated test below
            for method in sorted(methods):
                if (method, path) in RUNTIME_WHITELIST:
                    continue
                cases.append((module.__name__.rsplit(".", 1)[-1], method, path))
    return cases


_THREAD_ID_ROUTES = _collect_thread_id_routes()


def test_browser_websocket_rejects_noncanonical_thread_id():
    """The browser stream websocket validates thread_id on upgrade."""
    from starlette.websockets import WebSocketDisconnect

    from app.gateway.routers import browser

    app = make_authed_test_app()
    app.include_router(browser.router)

    with TestClient(app, raise_server_exceptions=False) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/threads/{BAD_THREAD_ID}/browser/stream"):
                pass


def test_sweep_covers_expected_surface():
    """Sanity: the sweep must actually see the known thread_id routes."""
    assert len(_THREAD_ID_ROUTES) >= 30
    assert any("suggestions" in name for name, _, _ in _THREAD_ID_ROUTES)


@pytest.mark.parametrize(
    ("router_name", "method", "path"),
    _THREAD_ID_ROUTES,
    ids=[f"{name}:{method}:{path}" for name, method, path in _THREAD_ID_ROUTES],
)
def test_noncanonical_thread_id_gets_422(router_name, method, path):
    """Runtime guard: a non-canonical thread_id yields 422 naming thread_id."""
    import importlib
    from unittest.mock import MagicMock

    from app.gateway.deps import get_config

    module = importlib.import_module(f"app.gateway.routers.{router_name}")
    app = make_authed_test_app()
    app.include_router(module.router)
    # get_config 503s when no config.yaml exists (CI), and dependency solving
    # precedes path-param validation — override it so the 422 contract is
    # exercised regardless of the environment.
    app.dependency_overrides[get_config] = MagicMock()

    url = path.replace("{thread_id}", BAD_THREAD_ID)
    # Other path params get a harmless canonical placeholder.
    url = re.sub(r"\{(\w+)(?::path)?\}", "x", url)

    with TestClient(app, raise_server_exceptions=False) as client:
        if method == "GET":
            response = client.get(url)
        elif method == "DELETE":
            response = client.delete(url)
        elif method in {"POST", "PUT", "PATCH"}:
            response = client.request(method, url, json={})
        else:  # WEBSOCKET etc. — not expected in the sweep
            pytest.skip(f"unsupported method {method}")

    assert response.status_code == 422, f"{method} {path} -> {response.status_code}: {response.text[:300]}"
    detail = response.json()["detail"]
    assert any("thread_id" in str(err.get("loc", ())) for err in detail), f"422 did not name thread_id: {detail}"
