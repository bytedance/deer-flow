from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import AgentScalarConfig, get_scalar_api_reference
from starlette.middleware.cors import CORSMiddleware
from store.persistence import create_persistence

from app.gateway.common import lifespan_manager
from app.gateway.router import router as gateway_router
from app.infra.run_events import build_run_event_store
from app.infra.storage import FeedbackStoreAdapter, RunStoreAdapter, ThreadMetaStorage, ThreadMetaStoreAdapter
from app.plugins.auth.authorization.hooks import build_authz_hooks
from app.plugins.auth.injection import install_route_guards, load_route_policy_registry, validate_route_policy_registry
from app.plugins.auth.security import AuthMiddleware, CSRFMiddleware

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
STATIC_MOUNT = "/api/static"
SCALAR_JS_URL = f"{STATIC_MOUNT}/scalar.js"


@lifespan_manager.register
@asynccontextmanager
async def init_persistence(app: FastAPI) -> AsyncGenerator[dict[str, Any], None]:
    """Initialize persistence layer (DB, checkpointer, store)."""
    app_persistence = await create_persistence()

    await app_persistence.setup()
    run_store = RunStoreAdapter(app_persistence.session_factory)
    thread_meta_store = ThreadMetaStoreAdapter(app_persistence.session_factory)
    feedback_store = FeedbackStoreAdapter(app_persistence.session_factory)

    try:
        yield {
            "persistence": app_persistence,
            "checkpointer": app_persistence.checkpointer,
            "store": None,
            "session_factory": app_persistence.session_factory,
            "run_store": run_store,
            "run_read_repo": run_store,
            "run_write_repo": run_store,
            "run_delete_repo": run_store,
            "feedback_repo": feedback_store,
            "thread_meta_repo": thread_meta_store,
            "thread_meta_storage": ThreadMetaStorage(thread_meta_store),
            "run_event_store": build_run_event_store(app_persistence.session_factory),
        }
    finally:
        await app_persistence.aclose()


@lifespan_manager.register
@asynccontextmanager
async def init_runtime(app: FastAPI) -> AsyncGenerator[dict[str, Any], None]:
    """Initialize StreamBridge for LangGraph-compatible runtime endpoints."""
    from app.infra.stream_bridge import build_stream_bridge

    async with build_stream_bridge() as stream_bridge:
        yield {
            "stream_bridge": stream_bridge,
        }


def register_app() -> FastAPI:
    app = FastAPI(
        title="DeerFlow API Gateway",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan_manager.build(),
        openapi_tags=[
            {
                "name": "threads",
                "description": "Endpoints for managing threads, which are conversations between a human and an assistant. A thread can have multiple runs as the conversation progresses."
            }
        ]
    )

    app.state.authz_hooks = build_authz_hooks()

    _register_static(app)
    _register_routes(app)
    _register_scalar(app)
    _register_auth_route_policies(app)
    _register_middlewares(app)

    return app


def _register_static(app: FastAPI) -> None:
    app.mount(STATIC_MOUNT, StaticFiles(directory=STATIC_DIR), name="static")


def _register_routes(app: FastAPI) -> None:
    app.include_router(gateway_router)


def _register_auth_route_policies(app: FastAPI) -> None:
    registry = load_route_policy_registry()
    validate_route_policy_registry(app, registry)
    app.state.auth_route_policy_registry = registry
    install_route_guards(app)


def _register_middlewares(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(AuthMiddleware)


def _register_scalar(app: FastAPI) -> None:
    @app.get("/docs", include_in_schema=False)
    def scalar_docs() -> HTMLResponse:
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title=app.title,
            scalar_js_url=SCALAR_JS_URL,
            agent=AgentScalarConfig(disabled=True),
            hide_client_button=True,
            overrides={"mcp": {"disabled": True}},
        )
