# deerflow.runtime Design Overview

This document describes the current implementation of `backend/packages/harness/deerflow/runtime`, including its overall design, boundary model, the collaboration between `runs` and `stream_bridge`, how it interacts with external infrastructure and the `app` layer, and how `actor_context` is dynamically injected to provide user isolation.

## 1. Overall Role

`deerflow.runtime` is the runtime kernel layer of DeerFlow.

It sits below agents / tools / middlewares and above app / gateway / infra. Its purpose is to define runtime semantics and boundary contracts, without directly owning web endpoints, ORM models, or concrete infrastructure implementations.

Its public surface is re-exported from [`__init__.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/__init__.py) and currently exposes four main capability areas:

1. `runs`
   - Run domain types, execution facade, lifecycle observers, and store protocols
2. `stream_bridge`
   - Stream event bridge contract and public stream types
3. `actor_context`
   - Request/task-scoped actor context and user-isolation bridge
4. `serialization`
   - Runtime serialization helpers for LangChain / LangGraph data and outward-facing events

Structurally, the current package looks like:

```text
runtime
  ├─ runs
  │   ├─ facade / types / observer / store
  │   ├─ internal/*
  │   └─ callbacks/*
  ├─ stream_bridge
  │   ├─ contract
  │   └─ exceptions
  ├─ actor_context
  └─ serialization / converters
```

## 2. Overall Design and Constraint Model

### 2.1 Design Goal

The core goal of `runtime` is to decouple runtime control-plane semantics from infrastructure implementations.

It only cares about:

1. What a run is and how run state changes over time
2. What lifecycle events and stream events are produced during execution
3. Which capabilities must be injected from the outside, such as checkpointer, event store, stream bridge, and durable stores
4. Who the current actor is, and how lower layers can use that for isolation

It deliberately does not care about:

1. Whether events are stored in memory, Redis, or another transport
2. How run / thread / feedback data is persisted
3. HTTP / SSE / FastAPI details
4. How the auth plugin resolves the request user

### 2.2 Boundary Rules

The current package has a fairly clear boundary model:

1. `runs` owns execution orchestration, not ORM or SQL writes
2. `stream_bridge` defines stream semantics, not app-level bridge construction
3. `actor_context` defines runtime context, not auth-plugin behavior
4. Durable data enters only through boundary protocols:
   - `RunCreateStore`
   - `RunQueryStore`
   - `RunDeleteStore`
   - `RunEventStore`
5. Lifecycle side effects enter only through `RunObserver`
6. User isolation is not implemented ad hoc in each module; it is propagated through actor context

In one sentence:

`runtime` defines semantics and contracts; `app.infra` provides implementations.

## 3. runs Subsystem Design

### 3.1 Purpose

`runtime/runs` is the run orchestration domain. It is responsible for:

1. Defining run domain objects and status transitions
2. Organizing create / stream / wait / join / cancel / delete behavior
3. Maintaining the in-process runtime control plane
4. Emitting stream events and lifecycle events during execution
5. Collecting trace, token, title, and message data through callbacks

### 3.2 Core Objects

See [`runs/types.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/types.py).

The most important types are:

1. `RunSpec`
   - Built by the app-side input layer
   - The real execution input
2. `RunRecord`
   - The runtime record managed by `RunRegistry`
3. `RunStatus`
   - `pending`, `starting`, `running`, `success`, `error`, `interrupted`, `timeout`
4. `RunScope`
   - Distinguishes stateful vs stateless execution and temporary thread behavior

### 3.3 Current Constraints

The current implementation explicitly limits some parts of the problem space:

1. `multitask_strategy` currently supports only `reject` and `interrupt` on the main path
2. `enqueue`, `after_seconds`, and batch execution are not on the current primary path
3. `RunRegistry` is an in-process state source, not a durable source of truth
4. External queries may use durable stores, but the live control plane still centers on the in-memory registry

### 3.4 Facade and Internal Components

`RunsFacade` in [`runs/facade.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/facade.py) provides the unified API:

1. `create_background`
2. `create_and_stream`
3. `create_and_wait`
4. `join_stream`
5. `join_wait`
6. `cancel`
7. `get_run`
8. `list_runs`
9. `delete_run`

Internally it composes:

1. `RunRegistry`
2. `ExecutionPlanner`
3. `RunSupervisor`
4. `RunStreamService`
5. `RunWaitService`
6. `RunCreateStore` / `RunQueryStore` / `RunDeleteStore`
7. `RunObserver`

So `RunsFacade` is the public entry point, while execution and state transitions are distributed across smaller components.

## 4. stream_bridge Design and Implementation

### 4.1 Why stream_bridge Is a Separate Abstraction

`StreamBridge` is defined in [`stream_bridge/contract.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/stream_bridge/contract.py).

It exists because run execution needs an event channel that is:

1. Subscribable
2. Replayable
3. Terminal-state aware
4. Resume-capable

That behavior must not be hard-coupled to HTTP SSE, in-memory queues, or Redis-specific details.

So:

1. harness defines stream semantics
2. the app layer owns backend selection and implementation

### 4.2 Contract Contents

The abstract `StreamBridge` currently exposes:

1. `publish(run_id, event, data)`
2. `publish_end(run_id)`
3. `publish_terminal(run_id, kind, data)`
4. `subscribe(run_id, last_event_id, heartbeat_interval)`
5. `cleanup(run_id, delay=0)`
6. `cancel(run_id)`
7. `mark_awaiting_input(run_id)`
8. `start()`
9. `close()`

Public types include:

1. `StreamEvent`
2. `StreamStatus`
3. `ResumeResult`
4. `HEARTBEAT_SENTINEL`
5. `END_SENTINEL`
6. `CANCELLED_SENTINEL`

### 4.3 Semantic Boundary

The contract explicitly distinguishes:

1. `end` / `cancel` / `error`
   - Real business-level terminal events for a run
2. `close()`
   - Bridge-level shutdown
   - Not equivalent to run cancellation

### 4.4 Current Implementation Style

The concrete implementation currently used is the app-layer [`MemoryStreamBridge`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/stream_bridge/adapters/memory.py).

Its design is effectively “one in-memory event log per run”:

1. `_RunStream` stores the event list, offset mapping, status, subscriber count, and awaiting-input state
2. `publish()` generates increasing event IDs and appends to the per-run log
3. `subscribe()` supports replay, heartbeat, resume, and terminal exit
4. `cleanup_loop()` handles:
   - old streams
   - active streams with no publish activity
   - orphan terminal streams
   - TTL expiration
5. `mark_awaiting_input()` extends timeout behavior for HITL flows

The Redis implementation is still only a placeholder in [`RedisStreamBridge`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/stream_bridge/adapters/redis.py).

### 4.5 Call Chain

The stream bridge participates in the execution chain like this:

```text
RunsFacade
  -> RunStreamService
  -> StreamBridge
  -> app route converts events to SSE
```

More concretely:

1. `_RunExecution._start()` publishes `metadata`
2. `_RunExecution._stream()` converts agent `astream()` output into bridge events
3. `_RunExecution._finish_success()` / `_finish_failed()` / `_finish_aborted()` publish terminal events
4. `RunWaitService` waits by subscribing for `values`, `error`, or terminal events
5. The app route layer converts those events into outward-facing SSE

### 4.6 Future Extensions

Likely future directions include:

1. A real Redis bridge for cross-process / multi-instance streaming
2. Stronger Last-Event-ID gap recovery behavior
3. Richer HITL state handling
4. Cross-node run coordination and more explicit dead-letter strategies

## 5. External Communication and Store Read/Write Boundaries

### 5.1 Two Main Outward Boundaries

`runtime` does not send HTTP requests directly and does not write ORM models directly, but it communicates outward through two main boundaries:

1. `StreamBridge`
   - For outward-facing stream events
2. `store` / `observer`
   - For durable data and lifecycle side effects

### 5.2 Store Boundary Protocols

Under [`runs/store`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/store), the harness layer defines:

1. `RunCreateStore`
2. `RunQueryStore`
3. `RunDeleteStore`
4. `RunEventStore`

These are not harness-internal persistence implementations. They are app-facing contracts declared by the runtime.

### 5.3 How the app Layer Supplies Store Implementations

The app layer currently provides:

1. [`AppRunCreateStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/store/create_store.py)
2. [`AppRunQueryStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/store/query_store.py)
3. [`AppRunDeleteStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/store/delete_store.py)
4. [`AppRunEventStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/run_events.py)
5. [`JsonlRunEventStore`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/run_events/jsonl_store.py)

The shared pattern is:

1. harness depends only on protocols
2. the app layer owns session lifecycle, commit behavior, access control, and backend choice
3. durable data eventually lands in `store.repositories.*` or JSONL files

### 5.4 How Run Lifecycle Data Leaves the Runtime

The single-run executor [`_RunExecution`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/internal/execution/executor.py) does not write to the database directly.

It exports data through three paths:

1. bridge events
   - Streamed outward to subscribers
2. callback -> `RunEventStore`
   - Execution trace / message / tool / custom events are persisted in batches
3. lifecycle event -> `RunObserver`
   - Run started, completed, failed, cancelled, and thread-status updates are emitted for app observers

### 5.5 `RunEventStore` Backends

The app-side factory [`app/infra/run_events/factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/run_events/factory.py) currently selects:

1. `run_events.backend == "db"`
   - `AppRunEventStore`
2. `run_events.backend == "jsonl"`
   - `JsonlRunEventStore`

So the runtime does not care whether events end up in a database or in files. It only requires the event-store protocol.

## 6. Run Lifecycle Data, Callbacks, Write-Back, and Query Flow

### 6.1 Main Single-Run Flow

The main `_RunExecution.run()` flow is:

1. `_start()`
2. `_prepare()`
3. `_stream()`
4. `_finish_after_stream()`
5. `finally`
   - `_emit_final_thread_status()`
   - `callbacks.flush()`
   - `bridge.cleanup(run_id)`

### 6.2 What the Start Phase Records

`_start()`:

1. sets run status to `running`
2. emits `RUN_STARTED`
3. extracts the first human message and emits `HUMAN_MESSAGE`
4. captures the pre-run checkpoint ID
5. publishes a `metadata` stream event

### 6.3 What the Callbacks Collect

Callbacks live under [`runs/callbacks`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/callbacks).

The main ones are:

1. `RunEventCallback`
   - Records `run_start`, `run_end`, `llm_request`, `llm_response`, `tool_start`, `tool_end`, `tool_result`, `custom_event`, and more
   - Flushes batches into `RunEventStore`
2. `RunTokenCallback`
   - Aggregates token usage, LLM call counts, lead/subagent/middleware token split, message counts, first human message, and last AI message
3. `RunTitleCallback`
   - Extracts thread title from title middleware output or custom events

### 6.4 How completion_data Is Produced

`RunTokenCallback.completion_data()` yields `RunCompletionData`, including:

1. `total_input_tokens`
2. `total_output_tokens`
3. `total_tokens`
4. `llm_call_count`
5. `lead_agent_tokens`
6. `subagent_tokens`
7. `middleware_tokens`
8. `message_count`
9. `last_ai_message`
10. `first_human_message`

The executor includes this data in lifecycle payloads on success, failure, and cancellation.

### 6.5 How the app Layer Writes Lifecycle Results Back

The executor emits `RunLifecycleEvent` objects through [`RunEventEmitter`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/runs/internal/execution/events.py).

The app-layer [`StorageRunObserver`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/storage/runs.py) then persists durable state:

1. `RUN_STARTED`
   - Marks the run as `running`
2. `RUN_COMPLETED`
   - Writes completion data
   - Syncs thread title if present
3. `RUN_FAILED`
   - Writes error and completion data
4. `RUN_CANCELLED`
   - Writes `interrupted` state and completion data
5. `THREAD_STATUS_UPDATED`
   - Syncs thread status

### 6.6 Query Paths

`RunsFacade.get_run()` and `list_runs()` have two paths:

1. If a `RunQueryStore` is injected, durable state is used first
2. Otherwise, the facade falls back to `RunRegistry`

So:

1. the in-memory registry is the control plane
2. the durable store is the preferred query surface

## 7. How actor_context Is Dynamically Injected for User Isolation

### 7.1 Design Goal

`actor_context` is defined in [`actor_context.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/packages/harness/deerflow/runtime/actor_context.py).

Its purpose is to let the runtime and lower-level infrastructure modules depend on a stable notion of “who the current actor is” without importing the auth plugin, FastAPI request objects, or a specific user model.

### 7.2 Current Implementation

The current implementation is a request/task-scoped context built on top of `ContextVar`:

1. `ActorContext`
   - Currently carries only `user_id`
2. `_current_actor`
   - A `ContextVar[ActorContext | None]`
3. `bind_actor_context(actor)`
   - Binds the current actor
4. `reset_actor_context(token)`
   - Restores the previous context
5. `get_actor_context()`
   - Returns the current actor
6. `get_effective_user_id()`
   - Returns the current user ID or `DEFAULT_USER_ID`
7. `resolve_user_id(value=AUTO | explicit | None)`
   - Resolves repository/storage-facing user IDs consistently

### 7.3 How the app Layer Injects It Dynamically

Dynamic injection currently happens at the app/auth boundary.

For HTTP request flows:

1. [`app.plugins.auth.security.middleware`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/security/middleware.py)
   - Builds `ActorContext(user_id=...)` from the authenticated request user
   - Binds and resets runtime actor context around request handling
2. [`app.plugins.auth.security.actor_context`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/security/actor_context.py)
   - Provides `bind_request_actor_context(request)` and `bind_user_actor_context(user_id)`
   - Allows routes and non-HTTP entry points to bind runtime actor context explicitly

For non-HTTP / external channel flows:

1. [`app/channels/manager.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/channels/manager.py)
2. [`app/channels/feishu.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/channels/feishu.py)

Those entry points also wrap execution with `bind_user_actor_context(user_id)` before they enter runtime-facing code. This matters because:

1. the runtime does not need to distinguish HTTP from Feishu or other channels
2. any entry point that can resolve a user ID can inject the same isolation semantics
3. the same runtime/store/path/memory code can stay protocol-agnostic

So the runtime itself does not know what a request is, and it does not know the auth plugin’s user model. It only knows whether an `ActorContext` is currently bound in the `ContextVar`.

### 7.4 Propagation Semantics After Injection

In practice, “dynamic injection” here does not mean manually threading `user_id` through every function signature. The app boundary binds the actor into a `ContextVar`, and runtime-facing code reads it only where isolation is actually needed.

The current semantics are:

1. an entry boundary calls `bind_actor_context(...)`
2. the async call chain created inside that context sees the same actor view
3. the boundary restores the previous value with `reset_actor_context(token)` when the request/task exits

That gives two practical outcomes:

1. most runtime interfaces do not need to carry `user_id` as an explicit parameter through every layer
2. boundaries that do need durable isolation or path isolation can still read explicitly via `resolve_user_id()` or `get_effective_user_id()`

### 7.5 How User Isolation Actually Works

User isolation is implemented through “dynamic injection + boundary-specific reads”.

The main paths are:

1. path / uploads / sandbox / memory
   - Use `get_effective_user_id()` to derive per-user directories and resource scopes
2. app storage adapters
   - Use `resolve_user_id(AUTO)` in `RunStoreAdapter`, `ThreadMetaStorage`, and related boundaries
3. run event store
   - `AppRunEventStore` reads `get_actor_context()` and decides whether the current actor may see a thread

So user isolation is not centralized in a single middleware and then forgotten. Instead:

1. the app boundary dynamically binds the actor into runtime context
2. runtime and lower layers read that context when they need isolation input
3. each boundary applies the user ID according to its own responsibility

### 7.6 Why This Approach Works Well

The current design has several practical strengths:

1. The runtime does not depend on a specific auth implementation
2. HTTP and non-HTTP entry points can reuse the same isolation mechanism
3. The same user ID propagates naturally into paths, memory, store access, and event visibility
4. Where stronger enforcement is needed, `AUTO` + `resolve_user_id()` can require a bound actor context

### 7.7 Future Extensions

`ActorContext` already contains explicit future-extension hints. The current pattern can be extended without changing the architecture:

1. `tenant_id`
   - For multi-tenant isolation
2. `subject_id`
   - For a more stable identity key
3. `scopes`
   - For finer-grained authorization
4. `auth_source`
   - To track the source channel or auth mechanism

The recommended extension model is to preserve the current shape:

1. The app/auth boundary binds a richer `ActorContext`
2. The runtime depends only on abstract context fields, never on request/user objects
3. Lower layers read only the fields they actually need
4. Store / path / sandbox / stream / memory boundaries can gradually become tenant-aware or scope-aware

More concretely, stronger isolation can be added incrementally at the boundaries:

1. store boundaries
   - add `tenant_id` filtering in `RunStoreAdapter`, `ThreadMetaStorage`, and feedback/event stores
2. path and sandbox boundaries
   - shard directories by `tenant_id/user_id` instead of `user_id` alone
3. event-visibility boundaries
   - layer `scopes` or `subject_id` checks into run-event and thread queries
4. external-channel boundaries
   - populate `auth_source` so API, channel, and internal-job traffic can be distinguished

That keeps the runtime dependent on the abstract “current actor context” concept, not on FastAPI request objects or a specific auth implementation.

## 8. Interaction with the app Layer

### 8.1 How the app Layer Wires the Runtime

The app composition root for runs is [`app/gateway/services/runs/facade_factory.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/services/runs/facade_factory.py).

It assembles:

1. `RunRegistry`
2. `ExecutionPlanner`
3. `RunSupervisor`
4. `RunStreamService`
5. `RunWaitService`
6. `RunsRuntime`
   - `bridge`
   - `checkpointer`
   - `store`
   - `event_store`
   - `agent_factory_resolver`
7. `StorageRunObserver`
8. `AppRunCreateStore`
9. `AppRunQueryStore`
10. `AppRunDeleteStore`

### 8.2 How app.state Provides Infrastructure

In [`app/gateway/registrar.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/registrar.py):

1. `init_persistence()` creates:
   - `persistence`
   - `checkpointer`
   - `run_store`
   - `thread_meta_storage`
   - `run_event_store`
2. `init_runtime()` creates:
   - `stream_bridge`

Those objects are then attached to `app.state` for dependency injection and facade construction.

### 8.3 The app Boundary for `stream_bridge`

Concrete stream bridge construction now belongs entirely to the app layer:

1. harness exports only the `StreamBridge` contract
2. [`app.infra.stream_bridge.build_stream_bridge`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/infra/stream_bridge/factory.py) constructs the actual implementation

That is a very explicit boundary:

1. harness defines runtime semantics and interfaces
2. app selects and constructs infrastructure

## 9. Summary

The most accurate one-line summary of `deerflow.runtime` today is:

It is a runtime kernel built around run orchestration, a stream bridge as the streaming boundary, actor context as the dynamic isolation bridge, and store / observer protocols as the durable and side-effect boundaries.

More concretely:

1. `runs` owns orchestration and lifecycle progression
2. `stream_bridge` owns stream semantics
3. `actor_context` owns runtime-scoped user context and isolation bridging
4. `serialization` / `converters` own outward event and message formatting
5. the app layer owns real persistence, stream infrastructure, and auth-driven context injection

The main strengths of this structure are:

1. Runtime semantics are decoupled from infrastructure implementations
2. Request identity is decoupled from runtime logic
3. HTTP, CLI, and channel-worker entry points can reuse the same runtime boundaries
4. The system can grow toward multi-tenancy, cross-process stream bridges, and richer durable backends without changing the core model

The current limitations are also clear:

1. `RunRegistry` is still an in-process control plane
2. The Redis bridge is not implemented yet
3. Some multitask strategies and batch capabilities are still outside the main path
4. `ActorContext` currently carries only `user_id`, not richer fields such as tenant, scopes, or auth source

So the best way to understand the current code is not as a final platform, but as a runtime kernel with clear semantics and extension boundaries.
