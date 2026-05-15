# Storage Package Design

## Background

DeerFlow currently has several persistence responsibilities spread across app, gateway, runtime, and legacy persistence modules. This makes the persistence boundary difficult to reason about and creates several migration risks:

- Routers and runtime services can accidentally depend on concrete persistence implementations instead of stable contracts.
- User/auth, run metadata, thread metadata, feedback, run events, and checkpointer setup are initialized through different paths.
- Some persistence behavior is duplicated between memory, SQLite, and PostgreSQL-oriented code paths.
- Incremental migration is hard because app-level code and storage-level code are coupled.
- Adding or validating another SQL backend requires touching app/runtime code instead of a storage-owned package.

The storage package is introduced to make application data persistence a package-level capability with explicit contracts, a clear boundary, and SQL backend compatibility.

## Goals

- Provide a standalone `packages/storage` package for durable application data.
- Support SQLite, PostgreSQL, and MySQL through a shared persistence construction flow.
- Keep LangGraph checkpointer initialization compatible with the same database backend.
- Expose repository contracts as the only package-level data access boundary.
- Let the app layer depend on app-owned adapters under `app.infra.storage`, not on storage DB implementation classes.
- Allow the app/gateway migration to happen in small steps without forcing a large rewrite.

## Non-Goals

- This design does not remove legacy persistence in the first PR.
- This design does not move routers directly onto storage package models.
- This design does not make app routers own SQLAlchemy sessions.
- Cron persistence is intentionally out of scope for the storage package foundation.
- Memory backend is not part of the durable storage package. Memory compatibility, if still needed by app runtime, belongs outside `packages/storage`.

## Storage Design Principles

### Package-Owned Durable Storage

`packages/storage` owns durable application data persistence. It defines:

- configuration shape for storage-backed persistence
- SQLAlchemy models
- repository contracts and DTOs
- SQL repository implementations
- persistence factory functions
- compatibility helpers for config-driven initialization

The package should be usable without importing `app.gateway`, routers, auth providers, or runtime-specific gateway objects.

### SQL Backend Compatibility

The package supports three SQL backends:

- SQLite for local/single-node deployments
- PostgreSQL for production multi-node deployments
- MySQL for deployments that standardize on MySQL

Backend-specific differences are handled inside the storage package:

- SQLAlchemy async engine URL construction
- LangGraph checkpointer connection-string compatibility
- JSON metadata filtering across SQLite/PostgreSQL/MySQL
- SQL dialect behavior around locking, aggregation, and JSON type semantics

### Unified Persistence Bundle

Storage initialization returns an `AppPersistence` bundle:

```python
@dataclass(slots=True)
class AppPersistence:
    checkpointer: Checkpointer
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    setup: Callable[[], Awaitable[None]]
    aclose: Callable[[], Awaitable[None]]
```

The app runtime can initialize persistence once, call `setup()`, and then inject:

- `checkpointer`
- `session_factory`
- repository adapters

This keeps checkpointer and application data aligned to the same backend without requiring routers to understand database configuration.

## Package Layout

```text
backend/packages/storage/
  store/
    config/
      storage_config.py
      app_config.py
    persistence/
      factory.py
      types.py
      base_model.py
      json_compat.py
      drivers/
        sqlite.py
        postgres.py
        mysql.py
    repositories/
      contracts/
        user.py
        run.py
        thread_meta.py
        feedback.py
        run_event.py
      models/
        user.py
        run.py
        thread_meta.py
        feedback.py
        run_event.py
      db/
        user.py
        run.py
        thread_meta.py
        feedback.py
        run_event.py
      factory.py
```

## Persistence Construction

The primary storage entrypoint is:

```python
from store.persistence import create_persistence_from_storage_config

persistence = await create_persistence_from_storage_config(storage_config)
await persistence.setup()
```

For app-level compatibility with existing database config shape:

```python
from store.persistence import create_persistence_from_database_config

persistence = await create_persistence_from_database_config(config.database)
await persistence.setup()
```

Expected app startup flow:

```python
persistence = await create_persistence_from_database_config(config.database)
await persistence.setup()

app.state.persistence = persistence
app.state.checkpointer = persistence.checkpointer
app.state.session_factory = persistence.session_factory
```

Expected app shutdown flow:

```python
await app.state.persistence.aclose()
```

## Repository Contract Design

Repository contracts are the storage package's public data access boundary. They live under `store.repositories.contracts` and are re-exported from `store.repositories`.

The key contract groups are:

- `UserRepositoryProtocol`
- `RunRepositoryProtocol`
- `ThreadMetaRepositoryProtocol`
- `FeedbackRepositoryProtocol`
- `RunEventRepositoryProtocol`

Each contract owns:

- input DTOs, such as `UserCreate`, `RunCreate`, `ThreadMetaCreate`
- output DTOs, such as `User`, `Run`, `ThreadMeta`
- repository protocol methods
- domain-specific exceptions when needed, such as `InvalidMetadataFilterError`

Repository construction is session-based:

```python
from store.repositories import build_run_repository

async with persistence.session_factory() as session:
    repo = build_run_repository(session)
    run = await repo.get_run(run_id)
```

This keeps transaction ownership explicit. The storage package does not hide commits or session lifecycle inside global singletons.

## App/Infra Calling Contract

The app layer should not call `store.repositories.db.*` directly. The intended app boundary is `app.infra.storage`.

`app.infra.storage` is responsible for:

- receiving `session_factory` from FastAPI runtime initialization
- owning session lifecycle for app-facing repository methods
- translating storage DTOs to app/gateway DTOs only when needed
- preserving the existing app-facing names during migration
- depending on storage repository protocols, not concrete DB classes

Expected adapter pattern:

```python
class StorageRunRepository(RunRepositoryProtocol):
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def get_run(self, run_id: str):
        async with self._session_factory() as session:
            repo = build_run_repository(session)
            return await repo.get_run(run_id)
```

For gateway compatibility, app state can keep existing names while the implementation changes:

```python
app.state.run_store = StorageRunStore(run_repository)
app.state.feedback_repo = StorageFeedbackStore(feedback_repository)
app.state.thread_store = StorageThreadMetaStore(thread_meta_repository)
app.state.run_event_store = StorageRunEventStore(run_event_repository)
app.state.checkpointer = persistence.checkpointer
app.state.session_factory = persistence.session_factory
```

The app-facing objects may expose legacy method names during migration, but their internal data access should go through storage contracts.

## Boundary Rules

### Allowed Calls

Storage package callers may use:

```python
from store.persistence import create_persistence_from_database_config
from store.persistence import create_persistence_from_storage_config
from store.repositories import build_run_repository
from store.repositories import build_user_repository
from store.repositories import build_thread_meta_repository
from store.repositories import build_feedback_repository
from store.repositories import build_run_event_repository
from store.repositories import RunRepositoryProtocol
from store.repositories import UserRepositoryProtocol
```

App layer callers should use:

```python
from app.infra.storage import StorageRunRepository
from app.infra.storage import StorageUserDataRepository
from app.infra.storage import StorageThreadMetaRepository
from app.infra.storage import StorageFeedbackRepository
from app.infra.storage import StorageRunEventRepository
```

### Prohibited Calls

App/gateway/router/auth code must not import:

```python
from store.repositories.db import DbRunRepository
from store.repositories.models import Run
from store.persistence.base_model import MappedBase
```

Routers must not:

- create SQLAlchemy engines
- create SQLAlchemy sessions directly
- call storage DB repository classes directly
- commit/rollback storage transactions directly unless explicitly scoped by an infra adapter
- depend on storage SQLAlchemy model classes

Storage package code must not import:

```python
import app.gateway
import app.infra
import deerflow.runtime
```

The dependency direction is:

```text
app/gateway -> app.infra.storage -> packages/storage contracts/factories -> packages/storage db implementations
```

The reverse direction is forbidden.

## Checkpointer Compatibility

The storage persistence bundle initializes the LangGraph checkpointer alongside application data persistence.

Backend-specific notes:

- SQLite uses `langgraph-checkpoint-sqlite`.
- PostgreSQL uses `langgraph-checkpoint-postgres` and requires a string `postgresql://...` connection URL.
- MySQL uses `langgraph-checkpoint-mysql` and requires a string MySQL connection URL.

SQLAlchemy may use async driver URLs such as `postgresql+asyncpg://...` or `mysql+aiomysql://...`, but LangGraph checkpointer constructors expect plain string connection URLs. This conversion belongs inside the storage driver implementation.

## JSON Metadata Filtering

Thread metadata search supports dialect-aware JSON filtering through `store.persistence.json_compat`.

The matcher supports:

- `None`
- `bool`
- `int`
- `float`
- `str`

It rejects:

- unsafe keys
- nested JSON path expressions
- dict/list values
- integers outside signed 64-bit range

This prevents SQL/JSON path injection, avoids compiled-cache type drift, and preserves type semantics such as `True != 1` and explicit JSON `null` not matching a missing key.

## Step-by-Step Implementation Plan

### Step 1: Introduce Storage Package Foundation

- Add `backend/packages/storage`.
- Add storage config models.
- Add `AppPersistence`.
- Add SQLite/PostgreSQL/MySQL persistence drivers.
- Add repository contracts, models, DB implementations, and factory helpers.
- Add package dependency wiring.
- Exclude cron persistence.

### Step 2: Harden Storage Backend Compatibility

- Validate SQLite setup and repository behavior.
- Validate PostgreSQL and MySQL with local E2E tests.
- Fix checkpointer connection-string compatibility.
- Fix PostgreSQL locking and aggregation differences.
- Add dialect-aware JSON metadata filtering.

### Step 3: Add App Infra Adapters

- Add `backend/app/infra/storage`.
- Implement app-facing repositories that own session lifecycle.
- Keep storage contracts as the only data access boundary.
- Add legacy compatibility adapters for existing app/gateway method shapes.
- Keep app/gateway imports out of `packages/storage`.

### Step 4: Switch FastAPI Runtime Injection

- Initialize storage persistence in FastAPI startup/lifespan.
- Attach `persistence`, `checkpointer`, and `session_factory` to `app.state`.
- Preserve existing external state names:
  - `run_store`
  - `feedback_repo`
  - `thread_store`
  - `run_event_store`
  - `checkpointer`
  - `session_factory`
- Start with user/auth provider construction, then migrate run/thread/feedback/run_event.

### Step 5: Router and Auth Compatibility

- Ensure routers consume app-facing adapters, not storage DB classes.
- Ensure auth providers depend on user repository contracts.
- Keep router response shapes unchanged.
- Add focused auth/admin/router regression tests.

### Step 6: Cleanup Legacy Persistence

- Compare old persistence usage after app/gateway migration.
- Remove unused old repository implementations only after all call sites move.
- Keep compatibility shims only where needed for a transition window.
- Delete memory backend paths from storage-owned durable persistence.

## Testing Strategy

Unit tests should cover:

- config parsing
- persistence setup
- table creation
- repository CRUD/query behavior
- typed JSON metadata filtering
- dialect SQL compilation
- cron exclusion

E2E tests should cover:

- SQLite persistence setup
- PostgreSQL temporary database setup
- MySQL temporary database setup
- repository contract behavior across all supported SQL backends
- JSON/Unicode round trip
- rollback behavior
- persistence close/cleanup

E2E tests may remain local-only if CI does not provide PostgreSQL/MySQL services.
