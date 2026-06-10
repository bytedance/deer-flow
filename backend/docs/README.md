# Documentation

This directory contains detailed documentation for the DeerFlow backend.

## Quick Links

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture overview |
| [API.md](API.md) | Complete API reference |
| [CONFIGURATION.md](CONFIGURATION.md) | Configuration options |
| [SETUP.md](SETUP.md) | Quick setup guide |

## Core Systems

| Document | Description |
|----------|-------------|
| [MIDDLEWARES.md](MIDDLEWARES.md) | 18 个中间件详解，执行顺序和交互图 |
| [AGENTS_SYSTEM.md](AGENTS_SYSTEM.md) | 多级 Agent 系统 (Builtin/Tenant/User) |
| [REPORT_TEMPLATES.md](REPORT_TEMPLATES.md) | DSL 报告模板平台 |
| [TOOLS_SYSTEM.md](TOOLS_SYSTEM.md) | 工具系统详解 |
| [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) | 记忆系统 (每用户隔离、事实提取) |
| [INSIGHTS_SYSTEM.md](INSIGHTS_SYSTEM.md) | 洞察系统 (反馈闭环) |
| [RAG.md](RAG.md) | 知识库 (RAG) |
| [HTTP_CONNECTORS.md](HTTP_CONNECTORS.md) | HTTP 连接器工具 |
| [STREAMING.md](STREAMING.md) | 流式设计 (Gateway vs DeerFlowClient) |
| [MCP_SERVER.md](MCP_SERVER.md) | MCP 服务器配置 |

## Feature Documentation

| Document | Description |
|----------|-------------|
| [FILE_UPLOAD.md](FILE_UPLOAD.md) | File upload functionality |
| [PATH_EXAMPLES.md](PATH_EXAMPLES.md) | Path types and usage examples |
| [summarization.md](summarization.md) | Context summarization feature |
| [plan_mode_usage.md](plan_mode_usage.md) | Plan mode with TodoList |
| [AUTO_TITLE_GENERATION.md](AUTO_TITLE_GENERATION.md) | Automatic title generation |
| [GUARDRAILS.md](GUARDRAILS.md) | Guardrail middleware and providers |

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
├── CONFIGURATION.md           # Configuration guide
├── SETUP.md                   # Setup instructions
├── FILE_UPLOAD.md             # File upload feature
├── PATH_EXAMPLES.md           # Path usage examples
├── summarization.md           # Summarization feature
├── plan_mode_usage.md         # Plan mode feature
├── STREAMING.md               # Token-level streaming design
├── AUTO_TITLE_GENERATION.md   # Title generation
├── TITLE_GENERATION_IMPLEMENTATION.md  # Title implementation details
└── TODO.md                    # Roadmap and issues
```
