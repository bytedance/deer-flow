# app.plugins Design Overview

This document describes the current role of `backend/app/plugins`, its plugin design contract, dependency boundaries, and how the current `auth` plugin provides services with minimal intrusion into the host application.

## 1. Overall Role

`app.plugins` is the application-side plugin boundary.

Its purpose is not to implement a generic plugin marketplace. Instead, it provides a clear boundary inside `app` for separable business capabilities, so that a capability can:

1. carry its own domain model, runtime state, and adapters inside the plugin
2. interact with the host application only through a limited set of seams
3. remain replaceable, removable, and extensible over time

The only real plugin currently implemented under this directory is [`auth`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth).

The current direction is not “put all logic into app”. It is:

1. the host application owns unified bootstrap, shared infrastructure, and top-level router assembly
2. each plugin owns its own business contract, persistence definitions, runtime state, and outward-facing adapters

## 2. Plugin Design Contract

### 2.1 A plugin should carry its own implementation

The primary contract visible in the current codebase is:

A plugin’s own ORM, runtime, domain, and adapters should be implemented inside the plugin itself. Core business behavior should not be scattered into unrelated external modules.

The `auth` plugin already follows that pattern with a fairly complete internal structure:

1. `domain`
   - config, errors, JWT, password logic, domain models, service
2. `storage`
   - plugin-owned ORM models, repository contracts, and repository implementations
3. `runtime`
   - plugin-owned runtime config state
4. `api`
   - plugin-owned HTTP router and schemas
5. `security`
   - plugin-owned middleware, dependencies, CSRF logic, and LangGraph adapter
6. `authorization`
   - plugin-owned permission model, policy resolution, and hooks
7. `injection`
   - plugin-owned route-policy loading, injection, and validation

In other words, a plugin should be a self-contained capability module, not a bag of helpers.

### 2.2 The host app should provide shared infrastructure, not plugin internals

The current contract is not that every plugin must be fully infrastructure-independent.

It is:

1. a plugin may reuse the application’s shared `engine`, `session_factory`, FastAPI app, and router tree
2. but the plugin must still own its table definitions, repositories, runtime config, and business/auth behavior

This is stated explicitly in [`auth/plugin.toml`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/plugin.toml):

1. `storage.mode = "shared_infrastructure"`
2. the plugin owns its storage definitions and repositories
3. but it reuses the application’s shared persistence infrastructure

So the real rule is not “never reuse infrastructure”. The real rule is “do not outsource plugin business semantics to the rest of the app”.

### 2.3 Dependencies should remain one-way

The intended dependency direction in the current design is:

```text
gateway / app bootstrap
  -> plugin public adapters
     -> plugin domain / storage / runtime
```

Not:

```text
plugin domain
  -> depends on app business modules
```

A plugin may depend on:

1. shared persistence infrastructure
2. `app.state` provided by the host application
3. generic framework capabilities such as FastAPI / Starlette

But its core business rules should not depend on unrelated app business modules, otherwise hot-swappability becomes unrealistic.

## 3. The Current auth Plugin Structure

The current `auth` plugin is effectively a self-contained authentication and authorization package with its own models, services, and adapters.

### 3.1 domain

[`auth/domain`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/domain) owns:

1. `config.py`
   - auth-related configuration definition and loading
2. `errors.py`
   - error codes and response contracts
3. `jwt.py`
   - token encoding and decoding
4. `password.py`
   - password hashing and verification
5. `models.py`
   - auth domain models
6. `service.py`
   - `AuthService` as the core business service

`AuthService` depends only on the plugin’s own `DbUserRepository` plus the shared session factory. The auth business logic is not reimplemented in `gateway`.

### 3.2 storage

[`auth/storage`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage) clearly shows the “ORM is owned by the plugin” contract:

1. [`models.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage/models.py)
   - defines the plugin-owned `users` table model
2. [`contracts.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage/contracts.py)
   - defines `User`, `UserCreate`, and `UserRepositoryProtocol`
3. [`repositories.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage/repositories.py)
   - implements `DbUserRepository`

The key point is:

1. the plugin defines its own ORM model
2. the plugin defines its own repository protocol
3. the plugin implements its own repository
4. external code only needs to provide a session or session factory

That is the minimal shared seam the boundary should preserve.

### 3.3 runtime

[`auth/runtime/config_state.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/runtime/config_state.py) keeps plugin-owned runtime config state:

1. `get_auth_config()`
2. `set_auth_config()`
3. `reset_auth_config()`

This matters because runtime state is also part of the plugin boundary. If future plugins need their own caches, state holders, or feature flags, they should follow the same pattern and keep them inside the plugin.

### 3.4 adapters

The `auth` plugin exposes capability through four main adapter groups:

1. `api/router.py`
   - HTTP endpoints
2. `security/*`
   - middleware, dependencies, request-user resolution, actor-context bridge
3. `authorization/*`
   - capabilities, policy evaluators, auth hooks
4. `injection/*`
   - route-policy registry, guard injection, startup validation

These adapters all follow the same rule:

1. entry-point behavior is defined inside the plugin
2. the host app only assembles and wires it

## 4. How a Plugin Interacts with the Host App

### 4.1 The top-level router only includes plugin routers

[`app/gateway/router.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/router.py) simply:

1. imports `app.plugins.auth.api.router`
2. calls `include_router(auth_router)`

That means the host app integrates auth HTTP behavior by assembly, not by duplicating login/register logic in `gateway`.

### 4.2 registrar performs wiring, not takeover

In [`app/gateway/registrar.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/registrar.py), the host app mainly does this:

1. `app.state.authz_hooks = build_authz_hooks()`
2. loads and validates the route-policy registry
3. calls `install_route_guards(app)`
4. calls `app.add_middleware(CSRFMiddleware)`
5. calls `app.add_middleware(AuthMiddleware)`

So the host app only wires the plugin in:

1. register middleware
2. install route guards
3. expose hooks and registries through `app.state`

The actual auth logic, authz logic, and route-policy semantics still live inside the plugin.

### 4.3 The plugin reuses shared sessions, but still owns business repositories

In [`auth/security/dependencies.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/security/dependencies.py):

1. the plugin reads the shared session factory from `request.app.state.persistence.session_factory`
2. constructs `DbUserRepository` itself
3. constructs `AuthService` itself

This is a good low-intrusion seam:

1. the outside world provides only shared infrastructure handles
2. the plugin decides how to instantiate its internal dependencies

## 5. Hot-Swappability and Low-Intrusion Principles

### 5.1 If a plugin serves other modules, it should minimize intrusion

When a plugin provides services to the rest of the app, the preferred patterns are:

1. expose a router
2. expose middleware or dependencies
3. expose hooks or protocols
4. inject a small number of shared objects through `app.state`
5. use config-driven route policies or capabilities instead of hardcoding checks inside business routes

Patterns to avoid:

1. large plugin-specific branches spread across `gateway`
2. unrelated business modules importing plugin ORM internals and rebuilding plugin logic themselves
3. plugin state being maintained across many global modules

### 5.2 Low-intrusion seams already visible in auth

The current `auth` plugin already uses four important low-intrusion seams:

1. router integration
   - `gateway.router` only calls `include_router`
2. middleware integration
   - `registrar` only registers `AuthMiddleware` and `CSRFMiddleware`
3. policy injection
   - `install_route_guards(app)` appends `Depends(enforce_route_policy)` uniformly to routes
4. hook seam
   - `authz_hooks` is exposed via `app.state`, so permission providers and policy builders can be replaced

This structure has three practical benefits:

1. host-app changes stay concentrated in the assembly layer
2. plugin core logic stays concentrated inside the plugin directory
3. swapping implementations does not require editing business routes one by one

### 5.3 Route policy is a key low-intrusion mechanism

[`auth/injection/registry_loader.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/injection/registry_loader.py), [`validation.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/injection/validation.py), and [`route_injector.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/injection/route_injector.py) together form an important contract:

1. route policies live in the plugin-owned `route_policies.yaml`
2. startup validates that policy entries and real routes stay aligned
3. guards are attached by uniform injection instead of manual per-endpoint code

That allows the plugin to:

1. describe which routes are public, which capabilities are required, and which owner policies apply
2. avoid large invasive changes to the host routing layer
3. remain easier to replace or trim down later

## 6. What “ORM and runtime are implemented inside the plugin” Should Mean

That contract should be read as three concrete rules:

1. data models belong to the plugin
   - the plugin’s own tables, Pydantic contracts, repository protocols, and repository implementations stay inside the plugin directory
2. runtime state belongs to the plugin
   - plugin-owned config caches, context bridges, and plugin-level hooks stay inside the plugin
3. the outside world exposes infrastructure, not plugin semantics
   - for example shared `session_factory`, FastAPI app, and `app.state`

Using `auth` as the example:

1. the `users` table is defined inside the plugin, not in `app.infra`
2. `AuthService` is implemented inside the plugin, not in `gateway`
3. `get_auth_config()` is maintained inside the plugin, not cached elsewhere
4. `AuthMiddleware`, `route_guard`, and `AuthzHooks` are all provided by the plugin itself

This is the structural prerequisite for meaningful pluginization later.

## 7. Current Scope and Non-Goals

At the current stage, the role of `app.plugins` is mainly:

1. to create module boundaries for separable application-side capabilities
2. to let each plugin own its own domain/storage/runtime/adapters
3. to connect plugins to the host app through assembly-oriented seams

The current non-goals are also clear:

1. this is not yet a full generic plugin discovery/installation system
2. plugins are not dynamically enabled or disabled at runtime
3. shared infrastructure is not being duplicated into every plugin

So at this stage, “hot-swappable” should be interpreted more precisely as:

1. plugin boundaries stay as independent as possible
2. integration points stay concentrated in the assembly layer
3. replacing or removing a plugin should mostly affect a small number of places such as `registrar`, router includes, and `app.state` hooks

## 8. Suggested Evolution Rules

If `app.plugins` is going to become a more stable plugin boundary, the codebase should keep following these rules:

1. each plugin directory should keep a `domain` / `storage` / `runtime` / `adapter` split
2. plugin-owned ORM and repositories should not drift into shared business directories
3. when a plugin serves the rest of the app, it should prefer exposing protocols, hooks, routers, and middleware over forcing external code to import internal implementation details
4. seams between a plugin and the host app should stay mostly limited to:
   - `router.include_router(...)`
   - `app.add_middleware(...)`
   - `app.state.*`
   - lifespan/bootstrap wiring
5. config-driven integration should be preferred over scattered hardcoded integration
6. startup validation should be preferred over implicit runtime failure

## 9. Summary

The current `app.plugins` contract can be summarized in one sentence:

Each plugin owns its own business implementation, ORM, and runtime; the host application provides shared infrastructure and assembly seams; and services should be integrated through low-intrusion, replaceable boundaries so the system can evolve toward real hot-swappability.
