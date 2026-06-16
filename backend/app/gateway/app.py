import asyncio
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # uvicorn's asyncio_loop_factory on Windows unconditionally returns
    # ProactorEventLoop, which is incompatible with psycopg's async pool.
    # Patch it to return SelectorEventLoop (already requested by the policy).
    import uvicorn.loops.asyncio as _uv_asyncio

    _uv_asyncio.asyncio_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.gateway.auth.middleware import create_auth_middleware
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.config import get_gateway_config
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.deps import langgraph_runtime
from app.gateway.middleware.rate_limit import create_rate_limit_middleware
from app.gateway.routers import (
    abnormal,
    admin,
    agents,
    artifacts,
    assistants_compat,
    audio,
    auth,
    auth_router,
    blueprints,
    capabilities,
    channels,
    closure_tickets,
    config,
    cost,
    feedback,
    genui,
    genui_telemetry,
    greetings,
    ins_base_auth,
    insights,
    knowledge_bases,
    machine,
    marketplace,
    mcp,
    memory,
    models,
    organize,
    point,
    rag,
    report_runs,
    report_template_telemetry,
    report_templates,
    runs,
    skills,
    suggestions,
    system,
    tenant_agents,
    tenant_connectors,
    tenant_industrial_migration,
    tenant_mcp_servers,
    tenant_status,
    thread_runs,
    threads,
    uploads,
    workbench,
)
from deerflow.config import app_config as deerflow_app_config
from deerflow.config.app_config import apply_logging_level

AppConfig = deerflow_app_config.AppConfig
get_app_config = deerflow_app_config.get_app_config

# Default logging; lifespan overrides from config.yaml log_level.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(worker_id)s] %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from deerflow.config.worker_id import apply_worker_id_filter  # noqa: E402

apply_worker_id_filter()

logger = logging.getLogger(__name__)

# Upper bound (seconds) each lifespan shutdown hook is allowed to run.
# Bounds worker exit time so uvicorn's reload supervisor does not keep
# firing signals into a worker that is stuck waiting for shutdown cleanup.
_SHUTDOWN_HOOK_TIMEOUT_SECONDS = 5.0


async def _ensure_admin_user(app: FastAPI) -> None:
    """Startup hook: handle first boot and migrate orphan threads otherwise.

    After admin creation, migrate orphan threads from the LangGraph
    store (metadata.user_id unset) to the admin account. This is the
    "no-auth → with-auth" upgrade path: users who ran DeerFlow without
    authentication have existing LangGraph thread data that needs an
    owner assigned.
        First boot (no admin exists):
            - Does NOT create any user accounts automatically.
            - The operator must visit ``/setup`` to create the first admin.

    Subsequent boots (admin already exists):
      - Runs the one-time "no-auth → with-auth" orphan thread migration for
        existing LangGraph thread metadata that has no owner_id.

    No SQL persistence migration is needed: the four user_id columns
    (threads_meta, runs, run_events, feedback) only come into existence
    alongside the auth module via create_all, so freshly created tables
    never contain NULL-owner rows.
    """
    from sqlalchemy import select, text

    from deerflow.persistence.engine import get_engine, get_session_factory
    from deerflow.persistence.user.model import UserRow

    # ── Schema migration: add tenant_id column to existing databases ──
    # create_all only creates tables, not columns. Run ALTER TABLE for
    # databases created before tenant_id was added to the UserRow model.
    engine = get_engine()
    if engine is not None and engine.url.get_backend_name() == "sqlite":
        async with engine.begin() as conn:
            # Check if the column already exists
            result = await conn.execute(
                text("PRAGMA table_info('users')")
            )
            columns = {row[1] for row in result.fetchall()}
            if "tenant_id" not in columns:
                logger.info("Migrating users table: adding tenant_id column")
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'")
                )
                logger.info("Migration complete: tenant_id column added")
            # Always clean up legacy email-only unique index so the
            # composite (email, tenant_id) index is the sole uniqueness
            # constraint. Safe to run on every boot (DROP IF EXISTS).
            try:
                await conn.execute(text("DROP INDEX IF EXISTS ix_users_email"))
            except Exception:
                pass
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_tenant ON users (email, tenant_id)")
            )

            # ── Schema migration: add tenant_id column to threads_meta ──
            result = await conn.execute(
                text("PRAGMA table_info('threads_meta')")
            )
            tm_columns = {row[1] for row in result.fetchall()}
            if "tenant_id" not in tm_columns:
                logger.info("Migrating threads_meta table: adding tenant_id column")
                await conn.execute(
                    text("ALTER TABLE threads_meta ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'")
                )
                await conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_threads_meta_tenant_id ON threads_meta (tenant_id)")
                )
                # Backfill tenant_id from the owning user's tenant
                await conn.execute(
                    text("""
                        UPDATE threads_meta
                        SET tenant_id = COALESCE(
                            (SELECT u.tenant_id FROM users u WHERE u.id = threads_meta.user_id),
                            'default'
                        )
                    """)
                )
                logger.info("Migration complete: threads_meta.tenant_id column added and backfilled")

            # ── Schema migration: create tenants table ──
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(256) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    daily_quota_usd FLOAT NOT NULL DEFAULT 50.0,
                    monthly_quota_usd FLOAT NOT NULL DEFAULT 1000.0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # One-time import from tenants.json if the table is empty
            row_count = await conn.execute(text("SELECT COUNT(*) FROM tenants"))
            if row_count.scalar() == 0:
                import json
                from datetime import UTC, datetime
                from pathlib import Path

                from deerflow.config.paths import get_paths

                json_path = Path(get_paths().base_dir) / "tenants.json"
                if json_path.exists():
                    try:
                        data = json.loads(json_path.read_text(encoding="utf-8"))
                        tenants_list = data if isinstance(data, list) else data.get("tenants", [])
                        now = datetime.now(UTC).isoformat()
                        for t in tenants_list:
                            created = t.get("created_at") or now
                            await conn.execute(
                                text("""
                                    INSERT OR IGNORE INTO tenants (tenant_id, name, is_active, daily_quota_usd, monthly_quota_usd, created_at, updated_at)
                                    VALUES (:tid, :name, :active, :daily, :monthly, :created, :updated)
                                """),
                                {
                                    "tid": t.get("tenant_id", "default"),
                                    "name": t.get("name", "Unknown"),
                                    "active": t.get("is_active", True),
                                    "daily": t.get("daily_quota_usd", 50.0),
                                    "monthly": t.get("monthly_quota_usd", 1000.0),
                                    "created": created,
                                    "updated": now,
                                },
                            )
                        logger.info("Imported %d tenant(s) from tenants.json", len(tenants_list))
                    except Exception as e:
                        logger.warning("Failed to import tenants.json: %s", e)

            # Auto-create tenants referenced by users but missing from tenants table
            from datetime import UTC, datetime

            now = datetime.now(UTC).isoformat()
            user_tenants = await conn.execute(text("SELECT DISTINCT tenant_id FROM users"))
            for (tid,) in user_tenants.fetchall():
                if tid:
                    existing = await conn.execute(text("SELECT 1 FROM tenants WHERE tenant_id = :tid"), {"tid": tid})
                    if existing.scalar() is None:
                        await conn.execute(
                            text("""
                                INSERT INTO tenants (tenant_id, name, is_active, daily_quota_usd, monthly_quota_usd, created_at, updated_at)
                                VALUES (:tid, :name, 1, 50.0, 1000.0, :now, :now)
                            """),
                            {"tid": tid, "name": tid, "now": now},
                        )
                        logger.info("Auto-created missing tenant %r (referenced by users table)", tid)

            # Repair tenants with empty/null timestamps (caused by earlier migration bugs)
            await conn.execute(
                text("UPDATE tenants SET created_at = :now WHERE created_at IS NULL OR created_at = ''"),
                {"now": now},
            )
            await conn.execute(
                text("UPDATE tenants SET updated_at = :now WHERE updated_at IS NULL OR updated_at = ''"),
                {"now": now},
            )

    # Check session factory BEFORE trying get_local_provider(), which raises
    # a cryptic RuntimeError when the persistence engine isn't ready yet.
    sf = get_session_factory()
    if sf is None:
        logger.info("Persistence engine not available; skipping admin bootstrap check")
        return

    from app.gateway.deps import get_local_provider

    provider = get_local_provider()

    admin_count = await provider.count_admin_users()

    if admin_count == 0:
        logger.info("=" * 60)
        logger.info("  First boot detected — no admin account exists.")
        logger.info("  Visit /setup to complete admin account creation.")
        logger.info("=" * 60)
        return

    # Migrate legacy "admin" roles to the three-role model
    # - "admin" + default tenant → "superadmin"
    # - "admin" + non-default tenant → "tenant_admin"
    async with sf() as session:
        from sqlalchemy import update as sa_update

        result = await session.execute(
            sa_update(UserRow)
            .where(UserRow.system_role == "admin", UserRow.tenant_id == "default")
            .values(system_role="superadmin")
        )
        if result.rowcount:
            logger.info("Migrated %d default-tenant admin(s) to superadmin", result.rowcount)

        result = await session.execute(
            sa_update(UserRow)
            .where(UserRow.system_role == "admin", UserRow.tenant_id != "default")
            .values(system_role="tenant_admin")
        )
        if result.rowcount:
            logger.info("Migrated %d non-default-tenant admin(s) to tenant_admin", result.rowcount)

        await session.commit()

    # Admin already exists — run orphan thread migration for any
    # LangGraph thread metadata that pre-dates the auth module.
    async with sf() as session:
        stmt = select(UserRow).where(UserRow.system_role == "superadmin").limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()

    if row is None:
        return  # Should not happen (admin_count > 0 above), but be safe.

    admin_id = str(row.id)

    # Reassign thread metadata that was created during no-auth periods
    # (_DefaultUser.id = "default") to the real superadmin.  Without this,
    # check_access(require_existing=False) would still deny because the row
    # exists but with a non-matching user_id.
    try:
        async with sf() as meta_session:
            result = await meta_session.execute(
                text("UPDATE threads_meta SET user_id = :admin WHERE user_id = 'default'"),
                {"admin": admin_id},
            )
            if result.rowcount:
                await meta_session.commit()
                logger.info("Reassigned %d thread(s) from 'default' user to admin", result.rowcount)
    except Exception:
        logger.debug("Thread metadata user_id migration skipped (non-fatal)")

    # LangGraph store orphan migration — non-fatal.
    # This covers the "no-auth → with-auth" upgrade path for users
    # whose existing LangGraph thread metadata has no user_id set.
    store = getattr(app.state, "store", None)
    if store is not None:
        try:
            migrated = await _migrate_orphaned_threads(store, admin_id)
            if migrated:
                logger.info("Migrated %d orphan LangGraph thread(s) to admin", migrated)
        except Exception:
            logger.exception("LangGraph thread migration failed (non-fatal)")


async def _iter_store_items(store, namespace, *, page_size: int = 500):
    """Paginated async iterator over a LangGraph store namespace.

    Replaces the old hardcoded ``limit=1000`` call with a cursor-style
    loop so that environments with more than one page of orphans do
    not silently lose data. Terminates when a page is empty OR when a
    short page arrives (indicating the last page).
    """
    offset = 0
    while True:
        batch = await store.asearch(namespace, limit=page_size, offset=offset)
        if not batch:
            return
        for item in batch:
            yield item
        if len(batch) < page_size:
            return
        offset += page_size


async def _migrate_orphaned_threads(store, admin_user_id: str) -> int:
    """Migrate LangGraph store threads with no user_id to the given admin.

    Uses cursor pagination so all orphans are migrated regardless of
    count. Returns the number of rows migrated.
    """
    migrated = 0
    async for item in _iter_store_items(store, ("threads",)):
        metadata = item.value.get("metadata", {})
        if not metadata.get("user_id"):
            metadata["user_id"] = admin_user_id
            item.value["metadata"] = metadata
            await store.aput(("threads",), item.key, item.value)
            migrated += 1
    return migrated


async def _sync_postgres_sequences() -> None:
    """Reset autoincrement sequences to MAX(id) so nextval() never collides.

    After pg_restore or manual INSERT with explicit IDs the sequence
    value can lag behind the actual data.  Without this, the next
    ``session.add(row)`` triggers an IntegrityError on the PK.

    No-op for SQLite (autoincrement is rowid-based, no sequence drift)
    and memory backends.
    """
    from sqlalchemy import text

    from deerflow.persistence.engine import get_engine

    engine = get_engine()
    if engine is None or engine.url.get_backend_name() != "postgresql":
        return

    tables = ("run_events", "memory_audit")
    try:
        async with engine.begin() as conn:
            for table in tables:
                await conn.execute(text(
                    f"SELECT setval("
                    f"  pg_get_serial_sequence('{table}', 'id'),"
                    f"  COALESCE((SELECT MAX(id) FROM {table}), 1)"
                    f")"
                ))
            logger.info("PostgreSQL sequences synced for %s", ", ".join(tables))
    except Exception:
        logger.warning("Failed to sync PostgreSQL sequences (non-fatal)", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""

    # Load config and check necessary environment variables at startup
    try:
        app.state.config = get_app_config()
        apply_logging_level(app.state.config.log_level)
        logger.info("Configuration loaded successfully")
    except Exception as e:
        error_msg = f"Failed to load configuration during gateway startup: {e}"
        logger.exception(error_msg)
        raise RuntimeError(error_msg) from e
    config = get_gateway_config()
    logger.info(f"Starting API Gateway on {config.host}:{config.port}")

    # Surface the active PDF converter (Sprint C.3.1). One INFO line at
    # boot makes "why are my PDF uploads silently empty?" diagnosable
    # without needing to grep through per-upload logs.
    try:
        from deerflow.utils.file_conversion import log_pdf_converter_status

        log_pdf_converter_status()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Failed to resolve pdf_converter status at startup: %s", exc)

    # Initialize LangGraph runtime components (StreamBridge, RunManager, checkpointer, store)
    async with langgraph_runtime(app):
        logger.info("LangGraph runtime initialised")

        # Ensure admin user exists (auto-create on first boot)
        # Must run AFTER langgraph_runtime so app.state.store is available for thread migration
        await _ensure_admin_user(app)

        # Sync PostgreSQL autoincrement sequences with actual data.
        # After pg_restore / manual inserts the sequence can lag behind
        # MAX(id), causing IntegrityError on the next insert.
        await _sync_postgres_sequences()

        # Start the closed-loop overdue-scan periodic task. No-op when
        # closure_service is unavailable (backend=memory).
        try:
            from deerflow.closed_loop.jobs import start_overdue_scanner

            start_overdue_scanner(app)
        except Exception:
            logger.exception("Failed to start closure overdue scanner (non-fatal)")

        # Start IM channel service if any channels are configured
        try:
            from app.channels.service import start_channel_service

            channel_service = await start_channel_service(app.state.config)
            logger.info("Channel service started: %s", channel_service.get_status())
        except Exception:
            logger.exception("No IM channels configured or channel service failed to start")

        # Start Nacos service registration if configured
        nacos_registry = None
        try:
            from deerflow.config.nacos_config import get_nacos_config
            from deerflow.rpc.nacos_registry import NacosRegistry

            nacos_cfg = get_nacos_config()
            if nacos_cfg is not None:
                nacos_registry = NacosRegistry(nacos_cfg)
                await nacos_registry.start()
                app.state.nacos_registry = nacos_registry
                logger.info("Nacos service registration started")
            else:
                logger.info("Nacos service discovery not configured, skipping")
        except Exception:
            logger.exception("Failed to start Nacos registration (non-fatal)")

        # Pre-initialise shared SmsAdapter so first request doesn't stall
        try:
            from deerflow.integrations.sms_adapter_resolver import ensure_sms_adapter
            await asyncio.wait_for(ensure_sms_adapter(), timeout=10.0)
        except Exception:
            logger.exception("Failed to pre-initialise SmsAdapter (non-fatal)")

        yield

        # Stop closure overdue scanner first so it does not race with engine teardown.
        try:
            from deerflow.closed_loop.jobs import stop_overdue_scanner

            await asyncio.wait_for(
                stop_overdue_scanner(app),
                timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Closure overdue scanner shutdown exceeded %.1fs; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to stop closure overdue scanner")

        # Stop Nacos registration on shutdown
        nacos_registry = getattr(app.state, "nacos_registry", None)
        if nacos_registry is not None:
            try:
                await asyncio.wait_for(
                    nacos_registry.stop(),
                    timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning(
                    "Nacos deregistration exceeded %.1fs; proceeding with worker exit.",
                    _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.exception("Failed to stop Nacos registration")

        # Stop channel service on shutdown (bounded to prevent worker hang)
        try:
            from app.channels.service import stop_channel_service

            await asyncio.wait_for(
                stop_channel_service(),
                timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Channel service shutdown exceeded %.1fs; proceeding with worker exit.",
                _SHUTDOWN_HOOK_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to stop channel service")

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    gateway_config = get_gateway_config()
    docs_kwargs = {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"} if gateway_config.enable_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(
        title="DeerFlow API Gateway",
        description="""
## DeerFlow API Gateway

API Gateway for DeerFlow - A LangGraph-based AI agent backend with sandbox execution capabilities.

### Features

- **Models Management**: Query and retrieve available AI models
- **MCP Configuration**: Manage Model Context Protocol (MCP) server configurations
- **Memory Management**: Access and manage global memory data for personalized conversations
- **Skills Management**: Query and manage skills and their enabled status
- **Artifacts**: Access thread artifacts and generated files
- **Health Monitoring**: System health check endpoints

### Architecture

LangGraph requests are handled by nginx reverse proxy.
This gateway provides custom endpoints for models, MCP configuration, skills, and artifacts.
        """,
        version="0.1.0",
        lifespan=lifespan,
        **docs_kwargs,
        openapi_tags=[
            {
                "name": "models",
                "description": "Operations for querying available AI models and their configurations",
            },
            {
                "name": "mcp",
                "description": "Manage Model Context Protocol (MCP) server configurations",
            },
            {
                "name": "memory",
                "description": "Access and manage global memory data for personalized conversations",
            },
            {
                "name": "skills",
                "description": "Manage skills and their configurations",
            },
            {
                "name": "artifacts",
                "description": "Access and download thread artifacts and generated files",
            },
            {
                "name": "uploads",
                "description": "Upload and manage user files for threads",
            },
            {
                "name": "audio",
                "description": "Transcribe chat audio uploads into editable text",
            },
            {
                "name": "threads",
                "description": "Manage DeerFlow thread-local filesystem data",
            },
            {
                "name": "agents",
                "description": "Create and manage custom agents with per-agent config and prompts",
            },
            {
                "name": "suggestions",
                "description": "Generate follow-up question suggestions for conversations",
            },
            {
                "name": "channels",
                "description": "Manage IM channel integrations (Feishu, Slack, Telegram)",
            },
            {
                "name": "assistants-compat",
                "description": "LangGraph Platform-compatible assistants API (stub)",
            },
            {
                "name": "runs",
                "description": "LangGraph Platform-compatible runs lifecycle (create, stream, cancel)",
            },
            {
                "name": "authentication",
                "description": "Authentication endpoints (login, token refresh, API key management)",
            },
            {
                "name": "health",
                "description": "Health check and system status endpoints",
            },
            {
                "name": "insights",
                "description": "Feedback analytics dashboard, improvement suggestions, and KB candidates",
            },
        ],
    )

    # CORS is handled by nginx - no need for FastAPI middleware

    # Authentication middleware (tenant extraction + JWT/API Key validation)
    app.middleware("http")(create_auth_middleware())

    # Rate limiting middleware (no-op when rate_limit.enabled=false)
    create_rate_limit_middleware(app)
    # Auth: reject unauthenticated requests to non-public paths (fail-closed safety net)
    app.add_middleware(AuthMiddleware)

    # Expose internal auth token so subprocess scripts (e.g. list_equipment.py)
    # can call Gateway APIs without user credentials.
    from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, create_internal_auth_headers

    os.environ["DEER_FLOW_INTERNAL_AUTH_VALUE"] = create_internal_auth_headers()[INTERNAL_AUTH_HEADER_NAME]

    # CSRF: Double Submit Cookie pattern for state-changing requests
    app.add_middleware(CSRFMiddleware)

    # CORS: when GATEWAY_CORS_ORIGINS is set (dev without nginx), add CORS middleware.
    # In production, nginx handles CORS and no middleware is needed.
    cors_origins_env = os.environ.get("GATEWAY_CORS_ORIGINS", "")
    if cors_origins_env:
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
        # Validate: wildcard origin with credentials is a security misconfiguration
        for origin in cors_origins:
            if origin == "*":
                logger.error("GATEWAY_CORS_ORIGINS contains wildcard '*' with allow_credentials=True. This is a security misconfiguration — browsers will reject the response. Use explicit scheme://host:port origins instead.")
                cors_origins = [o for o in cors_origins if o != "*"]
                break
        if cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

    # Include routers
    # Models API is mounted at /api/models
    app.include_router(models.router)

    # Config API is mounted at /api/config
    app.include_router(config.router)

    # MCP API is mounted at /api/mcp
    app.include_router(mcp.router)

    # Memory API is mounted at /api/memory
    app.include_router(memory.router)

    # Skills API is mounted at /api/skills
    app.include_router(skills.router)

    # Artifacts API is mounted at /api/threads/{thread_id}/artifacts
    app.include_router(artifacts.router)

    # Uploads API is mounted at /api/threads/{thread_id}/uploads
    app.include_router(uploads.router)

    # Audio transcription API is mounted at /api/threads/{thread_id}/audio
    app.include_router(audio.router)

    # Thread cleanup API is mounted at /api/threads/{thread_id}
    app.include_router(threads.router)

    # Agents API is mounted at /api/agents
    app.include_router(agents.router)

    # Suggestions API is mounted at /api/threads/{thread_id}/suggestions
    app.include_router(suggestions.router)

    # Channels API is mounted at /api/channels
    app.include_router(channels.router)

    # Assistants compatibility API (LangGraph Platform stub)
    app.include_router(assistants_compat.router)

    # Auth API is mounted at /api/v1/auth
    app.include_router(auth.router)

    # Feedback API is mounted at /api/threads/{thread_id}/runs/{run_id}/feedback
    app.include_router(feedback.router)

    # Thread Runs API (LangGraph Platform-compatible runs lifecycle)
    app.include_router(thread_runs.router)

    # Stateless Runs API (stream/wait without a pre-existing thread)
    app.include_router(runs.router)

    # RAG API is mounted at /api/rag
    app.include_router(rag.router)

    # Auth API is mounted at /api/auth
    app.include_router(auth_router.router)

    # InsBase Auth API is mounted at /api/v1/auth/ins-base
    app.include_router(ins_base_auth.router)

    # Cost API is mounted at /api/cost
    app.include_router(cost.router)

    # Admin API is mounted at /api/admin
    app.include_router(admin.router)

    # Simple Feedback API is mounted at /api/feedback
    app.include_router(feedback.simple_feedback_router)

    # Tenant status API is mounted at /api/tenant
    app.include_router(tenant_status.router)
    app.include_router(tenant_industrial_migration.router)

    # Knowledge base API
    app.include_router(knowledge_bases.router)

    # Tenant Agents CRUD API
    app.include_router(tenant_agents.router)

    # Report Templates platform (Phase 5)
    app.include_router(report_templates.router)
    app.include_router(report_runs.router)
    app.include_router(report_template_telemetry.router)
    app.include_router(blueprints.router)
    app.include_router(marketplace.router)
    app.include_router(marketplace.publish_router)

    # Tenant MCP Servers CRUD API
    app.include_router(tenant_mcp_servers.router)

    # Tenant HTTP Connectors CRUD API
    app.include_router(tenant_connectors.router)

    # GenUI interaction API
    app.include_router(genui.router)

    # GenUI telemetry and block recovery API
    app.include_router(genui_telemetry.router)

    # Personalized greeting API
    app.include_router(greetings.router)

    # Organize tree & Machine API (proxy to ins-bus-rpc)
    app.include_router(organize.router)
    app.include_router(machine.router)

    # Point API (proxy to ins-bus-rpc /pointModel)
    app.include_router(point.router)

    # Abnormal (SMS) proxy for A2UI components
    app.include_router(abnormal.router)

    # Workbench API (proxy to external 服务平台)
    app.include_router(workbench.router)

    # Closed-loop tickets API
    app.include_router(closure_tickets.router)

    # System diagnostics (admin-only): pdf-converter status etc.
    app.include_router(system.router)

    # Unified capability configuration view (ISSUE-10)
    app.include_router(capabilities.router)

    # Insights dashboard API (feedback loop)
    app.include_router(insights.router)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict:
        """Health check endpoint.

        Returns:
            Service health status information.
        """
        return {"status": "healthy", "service": "deer-flow-gateway"}

    @app.get("/health/live", tags=["health"])
    async def liveness_probe() -> dict:
        """Kubernetes liveness probe — no external dependency checks, no caching."""
        return {"status": "alive"}

    _readiness_cache: dict | None = None
    _readiness_cache_time: float = 0
    _READINESS_CACHE_TTL = 10.0

    @app.get("/health/ready", tags=["health"])
    async def readiness_probe() -> dict:
        """Kubernetes readiness probe — checks PostgreSQL, Redis, vector store.

        Results are cached for 10 seconds to avoid excessive probe load.
        Returns 503 if any critical backend is unreachable.
        """
        import time

        nonlocal _readiness_cache, _readiness_cache_time

        now = time.monotonic()
        if _readiness_cache is not None and (now - _readiness_cache_time) < _READINESS_CACHE_TTL:
            result = {**_readiness_cache, "cached": True}
            status_code = 200 if _readiness_cache.get("status") == "ready" else 503
            from fastapi.responses import JSONResponse
            return JSONResponse(content=result, status_code=status_code)

        checks: dict[str, dict] = {}

        # PostgreSQL check
        pg_ok, pg_detail = await _check_postgres()
        checks["postgres"] = pg_detail

        # Redis check
        redis_ok, redis_detail = await _check_redis()
        checks["redis"] = redis_detail

        overall_ready = pg_ok and redis_ok
        status_text = "ready" if overall_ready else "not_ready"
        result = {"status": status_text, "checks": checks, "cached": False}

        _readiness_cache = result
        _readiness_cache_time = now

        from fastapi.responses import JSONResponse
        return JSONResponse(content=result, status_code=200 if overall_ready else 503)

    @app.get("/health/metrics")
    async def health_metrics() -> Response:
        """Expose health-check counters in Prometheus text-exposition format."""
        from app.gateway.health_metrics import format_prometheus
        return Response(content=format_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


async def _check_postgres() -> tuple[bool, dict]:
    """Check PostgreSQL connectivity."""
    from app.gateway.health_metrics import record_health_check
    try:
        from deerflow.config.app_config import get_app_config
        config = get_app_config()
        if config.database.backend != "postgres":
            return True, {"status": "skipped", "message": "database.backend is not postgres"}
        import asyncio
        import time
        start = time.monotonic()
        import psycopg
        loop = asyncio.get_running_loop()

        def _pg_check() -> None:
            with psycopg.connect(config.database.postgres_url, autocommit=True) as conn:
                conn.execute("SELECT 1")

        await asyncio.wait_for(loop.run_in_executor(None, _pg_check), timeout=5.0)
        latency = round((time.monotonic() - start) * 1000)
        record_health_check("postgres", "ok")
        return True, {"status": "ok", "latency_ms": latency}
    except TimeoutError:
        record_health_check("postgres", "timeout")
        return False, {"status": "timeout", "message": "PostgreSQL did not respond within 5s"}
    except Exception as e:
        record_health_check("postgres", "error")
        return False, {"status": "error", "message": str(e)[:200]}


async def _check_redis() -> tuple[bool, dict]:
    """Check Redis connectivity."""
    from app.gateway.health_metrics import record_health_check
    try:
        from deerflow.config.app_config import get_app_config
        config = get_app_config()
        sb = config.stream_bridge
        sb_type = sb.type if sb else "memory"
        if sb_type != "redis":
            return True, {"status": "skipped", "message": "stream_bridge.type is not redis"}
        import asyncio
        import time

        import redis as redis_lib
        start = time.monotonic()
        redis_url = (sb.redis_url if sb else "") or os.getenv("REDIS_URL", "redis://localhost:6379")
        loop = asyncio.get_running_loop()
        client = redis_lib.from_url(redis_url, socket_connect_timeout=5)
        await asyncio.wait_for(loop.run_in_executor(None, client.ping), timeout=5.0)
        client.close()
        latency = round((time.monotonic() - start) * 1000)
        record_health_check("redis", "ok")
        return True, {"status": "ok", "latency_ms": latency}
    except TimeoutError:
        record_health_check("redis", "timeout")
        return False, {"status": "timeout", "message": "Redis did not respond within 5s"}
    except Exception as e:
        record_health_check("redis", "error")
        return False, {"status": "error", "message": str(e)[:200]}


# Create app instance for uvicorn
app = create_app()
