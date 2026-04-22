# Auth Plugin

This package is the future Level 2 auth plugin boundary for DeerFlow.

Scope:

- Auth domain logic: config, errors, models, JWT, password hashing, service
- Auth adapters: HTTP router, FastAPI dependencies, middleware, LangGraph adapter
- Auth storage: user/account models and repositories

Non-scope:

- Shared app/container bootstrap
- Shared persistence engine/session lifecycle
- Generic plugin discovery/registration framework

Target architecture:

- The plugin owns its storage definitions and business logic
- The plugin reuses the application's shared persistence infrastructure
- The gateway only assembles the plugin instead of owning auth logic directly
