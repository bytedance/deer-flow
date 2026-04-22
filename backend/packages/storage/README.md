# deerflow-storage Design Overview

This document explains the current responsibilities of `backend/packages/storage`, its overall design, how database integration works, how persistence models are defined, what database access interfaces it exposes, and how the `app` layer consumes it through `infra`.

## 1. Package Role

`deerflow-storage` is DeerFlow's unified persistence foundation package. Its purpose is to pull database integration and business data persistence out of the `app` layer and provide them as a reusable storage layer.

At the moment, it mainly provides two kinds of capabilities:

1. A checkpointer for the LangGraph runtime.
2. ORM models, repository contracts, and database implementations for DeerFlow application data.

This package does not expose HTTP endpoints directly, does not depend on FastAPI routes directly, and does not own business orchestration. It acts as a storage kernel.

## 2. Overall Layering

The current code is roughly split into the following layers:

```text
config
  └─ Reads configuration, resolves environment variables, and determines database parameters

persistence
  └─ Creates AsyncEngine / SessionFactory / LangGraph checkpointer

repositories/contracts
  └─ Defines domain objects and repository protocols (Pydantic + Protocol)

repositories/models
  └─ Defines SQLAlchemy ORM table models

repositories/db
  └─ Implements database access on top of AsyncSession

app.infra.storage
  └─ Adapts storage repositories into app-facing interfaces

gateway / runtime
  └─ Uses infra through dependency injection, facades, observers, and event stores
```

The core idea is:

1. The `storage` package only decides how data is stored and what is stored.
2. `app.infra` translates low-level repositories into application-facing semantics.
3. `gateway` and `runtime` depend only on interfaces exposed by `infra`, not on ORM models or SQL directly.

## 3. How Database Integration Works

### 3.1 Configuration Entry

Database configuration is defined in [`store/config/storage_config.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/config/storage_config.py), while the outer application configuration is loaded by [`store/config/app_config.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/config/app_config.py).

The configuration flow has several notable traits:

1. It loads from `backend/config.yaml` or the repository root `config.yaml` by default.
2. It supports overriding the path via `DEER_FLOW_CONFIG_PATH`.
3. It supports `$ENV_VAR` syntax in config values.
4. Timezone configuration also affects how timestamp fields are handled in the storage layer.

### 3.2 Persistence Entry Point

The unified entry point is `create_persistence()` in [`store/persistence/factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/factory.py).

It performs three main tasks:

1. Builds a SQLAlchemy URL from `StorageConfig`.
2. Selects the SQLite / MySQL / PostgreSQL builder based on the configured driver.
3. Returns `AppPersistence`, which contains:
   - `checkpointer`
   - `engine`
   - `session_factory`
   - `setup`
   - `aclose`

So the application startup does not just get a bare database connection. It gets a full runtime persistence bundle.

### 3.3 Driver Integration Pattern

Driver implementations live in:

1. [`store/persistence/drivers/sqlite.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/drivers/sqlite.py)
2. [`store/persistence/drivers/mysql.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/drivers/mysql.py)
3. [`store/persistence/drivers/postgres.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/drivers/postgres.py)

All three follow the same pattern:

1. Create an `AsyncEngine`
2. Create an `async_sessionmaker`
3. Create the LangGraph async checkpointer for that backend
4. In `setup()`, initialize the checkpointer first, then run `MappedBase.metadata.create_all`
5. In `aclose()`, close the engine and checkpointer in order

This means the current initialization strategy is:

1. Checkpointer tables and business tables are initialized together at runtime startup.
2. Business tables currently rely on `SQLAlchemy create_all()`.
3. There is no separate migration orchestration path inside this package as the main workflow.

### 3.4 Current SQLite Behavior

SQLite uses [`StorageConfig.sqlite_storage_path`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/config/storage_config.py) to generate the database file path, which defaults to `.deer-flow/data/deerflow.db`.

For SQLite, the model primary key type falls back to `Integer PRIMARY KEY`, because SQLite auto-increment behavior works more reliably with that than with `BIGINT`.

## 4. How Persistence Models Are Defined

### 4.1 Base Model Conventions

Base definitions are in [`store/persistence/base_model.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/base_model.py).

That file standardizes several things:

1. `MappedBase` as the declarative base for all ORM models.
2. `DataClassBase` to support native dataclass-style models.
3. `Base` to include `created_time` and `updated_time`.
4. `id_key` as the unified primary key definition.
5. `UniversalText` as a cross-dialect long-text type.
6. `TimeZone` as a timezone-aware datetime type wrapper.

As a result, new models in this package usually follow this pattern:

1. Inherit from `Base` if they need `created_time` and `updated_time`.
2. Inherit from `DataClassBase` if they only need dataclass-style mapping without `updated_time`.
3. Use `id: Mapped[id_key]` for the primary key.

### 4.2 Current Business Models

Models are under [`store/repositories/models`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/models):

1. `Run`
   - Table: `runs`
   - Stores run metadata, status, token statistics, message summaries, and error details.
2. `ThreadMeta`
   - Table: `thread_meta`
   - Stores thread-level metadata, status, title, and ownership data.
3. `RunEvent`
   - Table: `run_events`
   - Stores events and messages emitted by a run.
   - Uses a `(thread_id, seq)` unique constraint to maintain per-thread ordering.
4. `Feedback`
   - Table: `feedback`
   - Stores feedback records associated with runs.

### 4.3 Model Field Design Traits

There are a few common conventions in the current models:

1. Business identifiers are string fields such as `run_id`, `thread_id`, and `feedback_id`; the auto-increment `id` is only an internal primary key.
2. Structured extension data is usually stored in a JSON `metadata` column, while the ORM attribute name is often `meta`.
3. Long text fields use `UniversalText`.
4. Timestamp fields go through `TimeZone` to keep timezone handling consistent.

`RunEvent.content` has one additional rule:

1. If `content` is a `dict`, it is serialized to JSON before being written.
2. A `content_is_dict=True` marker is added into `metadata`.
3. On reads, the value is deserialized again based on that marker.

This lets `run_events` support both plain text messages and structured event payloads.

## 5. How Database Access Interfaces Are Defined

### 5.1 contracts: Repository Contract Layer

Contracts are defined in [`store/repositories/contracts`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/contracts).

This layer does two things:

1. Uses Pydantic models to define input and output objects such as `RunCreate`, `Run`, `ThreadMetaCreate`, and `ThreadMeta`.
2. Uses `Protocol` to define repository interfaces such as `RunRepositoryProtocol` and `ThreadMetaRepositoryProtocol`.

That means upper layers depend on contracts and protocols rather than on a specific SQLAlchemy implementation.

### 5.2 db: Database Implementation Layer

Implementations live in [`store/repositories/db`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/db).

Each repository implementation follows the same pattern:

1. The constructor receives an `AsyncSession`
2. It uses `select / update / delete` for database operations
3. It converts ORM models into the Pydantic objects defined by the contracts layer

For example:

1. `DbRunRepository` handles CRUD and completion-stat updates for the `runs` table.
2. `DbThreadMetaRepository` handles thread metadata retrieval, updates, and search.
3. `DbRunEventRepository` handles batched event append, message pagination, and deletion by thread or run.
4. `DbFeedbackRepository` handles feedback creation and retrieval.

### 5.3 factory: Repository Construction Entry

[`store/repositories/factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/factory.py) provides unified factory functions:

1. `build_run_repository(session)`
2. `build_thread_meta_repository(session)`
3. `build_feedback_repository(session)`
4. `build_run_event_repository(session)`

So upper layers only need an `AsyncSession` and do not need to depend directly on concrete repository class names.

## 6. What the Package Exposes

If you look only at the `storage` package itself, it exposes two categories of interfaces.

### 6.1 Runtime Persistence Entry

Exported from [`store/persistence/__init__.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/persistence/__init__.py):

1. `create_persistence()`
2. `AppPersistence`
3. The ORM base classes and shared persistence types

This is the entry point used by the application to initialize database access and the checkpointer.

### 6.2 Repository Contracts and Builders

Exported from [`store/repositories/__init__.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/storage/store/repositories/__init__.py):

1. Contract-layer input and output models
2. Repository `Protocol`s
3. Repository builder factory functions

This is how the application integrates business persistence by repository contract.

In other words, the `storage` package does not provide an HTTP SDK to the `app` layer. It provides:

1. Initialization capabilities
2. A session factory
3. Repository protocols and repository builders

## 7. How the app Layer Uses It Through infra

The `app` layer does not operate on `store.repositories.db.*` directly. It goes through `app.infra.storage`.

Relevant code lives in:

1. [`backend/app/infra/storage/runs.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/runs.py)
2. [`backend/app/infra/storage/thread_meta.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/thread_meta.py)
3. [`backend/app/infra/storage/run_events.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/run_events.py)

### 7.1 Why the infra Layer Exists

The `app` layer does not want raw repository interfaces. It needs persistence services aligned with application semantics:

1. Automatic session lifecycle management
2. Automatic commit / rollback behavior
3. Actor / user visibility checks
4. Conversion from lower-level Pydantic models into app-facing dict structures
5. Alignment with the expectations of facades, observers, and routers

### 7.2 Run Integration

`RunStoreAdapter` wraps `build_run_repository(session)` with a `session_factory` and exposes:

1. `get`
2. `list_by_thread`
3. `create`
4. `update_status`
5. `set_error`
6. `update_run_completion`
7. `delete`

Important details:

1. Each call creates its own `AsyncSession`.
2. Read and write flows manage transactions separately.
3. Visibility filtering is applied through `actor_context` and `user_id`.
4. Run creation serializes metadata and kwargs before persisting them.

### 7.3 Thread Integration

Thread metadata is split into two layers:

1. `ThreadMetaStoreAdapter`
   - A session-managed wrapper around the repository.
2. `ThreadMetaStorage`
   - A higher-level app-facing interface.

`ThreadMetaStorage` adds application-oriented methods such as:

1. `ensure_thread`
2. `ensure_thread_running`
3. `sync_thread_title`
4. `sync_thread_assistant_id`
5. `sync_thread_status`
6. `sync_thread_metadata`
7. `search_threads`

So the `app` layer typically depends on `ThreadMetaStorage`, not directly on the low-level repository protocol.

### 7.4 RunEvent Integration

`AppRunEventStore` is a runtime-oriented event storage adapter. It is not just a CRUD wrapper. It is shaped around the runtime event-store protocol:

1. `put_batch`
2. `list_messages`
3. `list_events`
4. `list_messages_by_run`
5. `count_messages`
6. `delete_by_thread`
7. `delete_by_run`

It also performs thread visibility checks. If the current actor has a `user_id`, it first loads the thread owner and then decides whether the actor can read or write events for that thread.

## 8. How storage Is Wired at app Startup

Application startup wiring happens in [`backend/app/gateway/registrar.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/registrar.py).

The `init_persistence()` flow is:

1. Call `create_persistence()`
2. Run `app_persistence.setup()`
3. Use `session_factory` to build:
   - `RunStoreAdapter`
   - `ThreadMetaStoreAdapter`
   - `FeedbackStoreAdapter`
   - `AppRunEventStore`
4. Build `ThreadMetaStorage` on top of that
5. Inject all of them into `app.state`

So from the application's point of view, `storage` is not wired as a single global repository object. Instead:

1. Lower layers share a single `session_factory`
2. Upper layers create sessions per call through adapters
3. The final objects are attached to `FastAPI app.state` for routers and services

## 9. How gateway and service Layers Use These Capabilities

### 9.1 Dependency Injection

[`backend/app/gateway/dependencies/repositories.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/dependencies/repositories.py) reads the following objects from `request.app.state`:

1. `run_store`
2. `thread_meta_repo`
3. `thread_meta_storage`
4. `feedback_repo`

These are then exposed as FastAPI dependencies to route handlers.

### 9.2 Usage in Thread Routes

In [`backend/app/gateway/routers/langgraph/threads.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/routers/langgraph/threads.py):

1. Thread creation calls `ThreadMetaStorage.ensure_thread()`
2. Thread search calls `ThreadMetaStorage.search_threads()`
3. Thread deletion calls `ThreadMetaStorage.delete_thread()`

So the thread API does not touch ORM tables directly. It goes through the infra layer.

### 9.3 Usage in the Runs Facade

[`backend/app/gateway/services/runs/facade_factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/facade_factory.py) injects storage-related objects into `RunsFacade`:

1. `run_read_repo`
2. `run_write_repo`
3. `run_delete_repo`
4. `thread_meta_storage`
5. `run_event_store`

These are then consumed by app-layer components such as:

1. `AppRunCreateStore`
2. `AppRunQueryStore`
3. `AppRunDeleteStore`
4. `StorageRunObserver`

### 9.4 How Run Lifecycle State Is Written Back

`StorageRunObserver` is a key integration path.

It listens to runtime lifecycle events and writes their results back into persistence:

1. `RUN_STARTED` -> updates run status to `running`
2. `RUN_COMPLETED` -> updates completion stats and, when needed, syncs the thread title
3. `RUN_FAILED` -> updates error state and error details
4. `RUN_CANCELLED` -> updates run status to `interrupted`
5. `THREAD_STATUS_UPDATED` -> syncs thread status

This means the `storage` package itself does not listen to runtime events directly, but `app.infra.storage` already plugs it into the runtime observer system.

## 10. How It Communicates with External Systems

The phrase "external communication" splits into two cases here.

### 10.1 Communication with Databases

The `storage` package communicates with SQLite / MySQL / PostgreSQL through SQLAlchemy async engines.

The main entry points are:

1. `create_async_engine`
2. `AsyncSession`
3. Repository-level `select / update / delete`

The LangGraph checkpointer also communicates with the database through backend-specific async savers, but that logic is centralized in `persistence/drivers`.

### 10.2 Communication with External Application Interfaces

The `storage` package does not expose external APIs by itself. External communication is handled by the `app` layer.

The typical path is:

1. An HTTP request enters a FastAPI route
2. The route gets an `infra` adapter through dependency injection
3. `infra` calls a `storage` repository
4. The route converts the result into an API response

There is also a runtime-event path:

1. The runtime emits a run lifecycle event or a run event
2. An observer or event store calls `infra`
3. `infra` calls `storage`
4. The data is persisted into the database

So more precisely, `storage` does not communicate outward on its own. It acts as the database boundary inside the application and is consumed by both the HTTP layer and the runtime layer.

## 11. Current Design Philosophy

The current code reflects a fairly clear design philosophy:

1. Unify checkpointer storage and application data storage under one entry point.
2. Use repository contracts to isolate upper layers from ORM details.
3. Use an `infra` adapter layer to isolate app semantics from storage semantics.
4. Prefer async SQLAlchemy to fit the modern async application stack.
5. Keep database dialect differences contained in shared base types and driver builders.
6. Keep actor / user visibility rules in app infra rather than hard-coding them into ORM models.

That means this is not meant to be a full business data layer. It is a composable low-level persistence package.

## 12. Scope and Boundaries

What the current `storage` package is responsible for:

1. Database connection parameters and initialization
2. LangGraph checkpointer integration
3. ORM base model conventions
4. Core DeerFlow persistence models
5. Repository contracts and database implementations

What it is not responsible for:

1. FastAPI route protocols
2. Authentication and authorization
3. Business workflow orchestration
4. Actor context binding
5. SSE / stream-bridge network communication
6. Higher-level facade semantics

Those responsibilities live in `app.gateway`, `app.plugins.auth`, `deerflow.runtime`, and `app.infra`.

## 13. Example End-to-End Call Chains

For "create a run and then update its state when execution finishes", the chain looks like this:

```text
HTTP POST /api/threads/{thread_id}/runs
  -> gateway router
  -> RunsFacade
  -> AppRunCreateStore
  -> RunStoreAdapter
  -> build_run_repository(session)
  -> DbRunRepository
  -> runs table

execution completes
  -> runtime emits lifecycle event
  -> StorageRunObserver
  -> RunStoreAdapter / ThreadMetaStorage
  -> DbRunRepository / DbThreadMetaRepository
  -> runs / thread_meta tables
```

For "query the messages of a run", the chain looks like this:

```text
HTTP GET /api/threads/{thread_id}/runs/{run_id}/messages
  -> gateway router
  -> get run_event_store from app.state
  -> AppRunEventStore
  -> build_run_event_repository(session)
  -> DbRunEventRepository
  -> run_events table
```

## 14. Summary

In one sentence, the role of `backend/packages/storage` in the current system is:

It is DeerFlow's database and persistence foundation, unifying database integration, ORM models, repository contracts, database implementations, and LangGraph checkpointer integration; the `app` layer then turns those low-level capabilities into thread, run, event, and feedback semantics through `infra`, and exposes them through HTTP routes and the runtime event system.
