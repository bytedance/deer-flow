# Documentation

This directory contains detailed documentation for the DeerFlow backend.

## Quick Links

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [API.md](API.md) | Complete API reference |
| [AUTH_DESIGN.md](AUTH_DESIGN.md) | User authentication, CSRF, and per-user isolation design |
| [CONFIGURATION.md](CONFIGURATION.md) | Configuration options |
| [SETUP.md](SETUP.md) | Quick setup guide |

## Feature Documentation

| Document | Description |
|----------|-------------|
| [STREAMING.md](STREAMING.md) | Token-level streaming design: Gateway vs DeerFlowClient paths, `stream_mode` semantics, per-id dedup |
| [DURABLE_WORKFLOW_CORE_RFC.md](DURABLE_WORKFLOW_CORE_RFC.md) | Upstream RFC draft for a native Durable Workflow Runtime Layer in DeerFlow core |
| [DURABLE_WORKFLOW_RUNTIME_PLAN.md](DURABLE_WORKFLOW_RUNTIME_PLAN.md) | Runtime-first PR plan for workflow identity, status, events, idempotency, lease, and recovery |
| [DURABLE_WORKFLOW_FRONTDOOR.md](DURABLE_WORKFLOW_FRONTDOOR.md) | Durable workflow intake/frontdoor architecture and PR stack |
| [DURABLE_WORKFLOW_PR_STACK.md](DURABLE_WORKFLOW_PR_STACK.md) | Prefix-safe upstream PR sequence for durable runtime, recovery, intake, and worker readiness |
| [FILE_UPLOAD.md](FILE_UPLOAD.md) | File upload functionality |
| [PATH_EXAMPLES.md](PATH_EXAMPLES.md) | Path types and usage examples |
| [SANDBOX_MEMORY_PROFILING.md](SANDBOX_MEMORY_PROFILING.md) | Sandbox memory baseline and runtime comparison guide |
| [summarization.md](summarization.md) | Context summarization feature |
| [plan_mode_usage.md](plan_mode_usage.md) | Plan mode with TodoList |
| [AUTO_TITLE_GENERATION.md](AUTO_TITLE_GENERATION.md) | Automatic title generation |

## Development

| Document | Description |
|----------|-------------|
| [TODO.md](TODO.md) | Planned features and known issues |

## Getting Started

1. **New to DeerFlow?** Start with [SETUP.md](SETUP.md) for quick installation
2. **Configuring the system?** See [CONFIGURATION.md](CONFIGURATION.md)
3. **Understanding the architecture?** Read [ARCHITECTURE.md](ARCHITECTURE.md)
4. **Building integrations?** Check [API.md](API.md) for API reference

## Document Organization

```
docs/
├── README.md                  # This file
├── ARCHITECTURE.md            # System architecture
├── API.md                     # API reference
├── AUTH_DESIGN.md             # User authentication and isolation design
├── CONFIGURATION.md           # Configuration guide
├── SETUP.md                   # Setup instructions
├── FILE_UPLOAD.md             # File upload feature
├── PATH_EXAMPLES.md           # Path usage examples
├── summarization.md           # Summarization feature
├── plan_mode_usage.md         # Plan mode feature
├── STREAMING.md               # Token-level streaming design
├── DURABLE_WORKFLOW_CORE_RFC.md # Upstream durable workflow core RFC draft
├── DURABLE_WORKFLOW_RUNTIME_PLAN.md # Runtime-first durable workflow PR plan
├── DURABLE_WORKFLOW_FRONTDOOR.md # Durable workflow frontdoor design
├── DURABLE_WORKFLOW_PR_STACK.md # Prefix-safe durable runtime PR sequence
├── AUTO_TITLE_GENERATION.md   # Title generation
├── TITLE_GENERATION_IMPLEMENTATION.md  # Title implementation details
└── TODO.md                    # Roadmap and issues
```
