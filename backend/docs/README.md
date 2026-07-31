# Documentation

This directory contains detailed documentation for the DeerFlow backend.

## Quick Links

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [HEXAGONAL_ARCHITECTURE_zh.md](HEXAGONAL_ARCHITECTURE_zh.md) | 六边形（Ports & Adapters）分层规范：标准结构（AWS 三文件夹 + domain 七件套）、Commands/Events 设计、规则清单与执法、调用关系 |
| [FEEDBACK_DESIGN_zh.md](FEEDBACK_DESIGN_zh.md) | 用户反馈模块设计：首个完成的六边形切片，聚合/端口/适配器逐层走读与二次开发指引 |
| [API.md](API.md) | Complete API reference |
| [AUTH_DESIGN.md](AUTH_DESIGN.md) | User authentication, CSRF, platform-trust (IM / Internal Auth), and per-user isolation |
| [SSO.md](SSO.md) | OIDC / SSO single sign-on |
| [IM_CHANNEL_CONNECTIONS.md](IM_CHANNEL_CONNECTIONS.md) | IM channel user binding (`channel_connections`) |
| [CONFIGURATION.md](CONFIGURATION.md) | Configuration options |
| [SETUP.md](SETUP.md) | Quick setup guide |

## Feature Documentation

| Document | Description |
|----------|-------------|
| [STREAMING.md](STREAMING.md) | Token-level streaming design: Gateway vs DeerFlowClient paths, `stream_mode` semantics, per-id dedup |
| [RUN_EVENT_STREAM.md](RUN_EVENT_STREAM.md) | Persisted run event stream contract: envelope, producers, consumers, and known gaps |
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
5. **Wondering why the layers are split the way they are?** Read [HEXAGONAL_ARCHITECTURE_zh.md](HEXAGONAL_ARCHITECTURE_zh.md) for the rules, then [FEEDBACK_DESIGN_zh.md](FEEDBACK_DESIGN_zh.md) for a worked example

## Document Organization

```
docs/
├── README.md                  # This file
├── ARCHITECTURE.md            # System architecture
├── HEXAGONAL_ARCHITECTURE_zh.md  # Hexagonal layering rules (zh)
├── FEEDBACK_DESIGN_zh.md      # Feedback module design (zh) — first hexagonal slice
├── API.md                     # API reference
├── AUTH_DESIGN.md             # User authentication and isolation design
├── CONFIGURATION.md           # Configuration guide
├── SETUP.md                   # Setup instructions
├── FILE_UPLOAD.md             # File upload feature
├── PATH_EXAMPLES.md           # Path usage examples
├── summarization.md           # Summarization feature
├── plan_mode_usage.md         # Plan mode feature
├── STREAMING.md               # Token-level streaming design
├── RUN_EVENT_STREAM.md        # Persisted run event stream contract
├── AUTO_TITLE_GENERATION.md   # Title generation
├── TITLE_GENERATION_IMPLEMENTATION.md  # Title implementation details
└── TODO.md                    # Roadmap and issues
```
