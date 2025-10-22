# Agent.md

This file provides guidance to AI agents when working with code in this repository.

## Architecture Overview

**DeerFlow** is a multi-agent research framework built on LangGraph that orchestrates AI agents to conduct deep research, generate reports, and create content like podcasts and presentations.

### Core Architecture

The system uses a **modular multi-agent architecture** with these key components:

- **Coordinator**: Entry point managing workflow lifecycle
- **Planner**: Decomposes research objectives into structured plans
- **Research Team**: Specialized agents (Researcher, Coder) executing plans
- **Reporter**: Aggregates findings and generates final reports
- **Human-in-the-loop**: Interactive plan modification and approval

### Graph Structure

Built on **LangGraph** with state-based workflows:
- **StateGraph** manages agent communication
- **MemorySaver** provides conversation persistence
- **Checkpointing** supports MongoDB/PostgreSQL storage
- **Nodes**: coordinator → planner → research_team → reporter

### Key Directories

```
src/
├── agents/          # Agent definitions and behaviors
├── config/          # Configuration management (YAML, env vars)
├── crawler/         # Web crawling and content extraction
├── graph/           # LangGraph workflow definitions
├── llms/            # LLM provider integrations (OpenAI, DeepSeek, etc.)
├── prompts/         # Agent prompt templates
├── server/          # FastAPI web server and endpoints
├── tools/           # External tools (search, TTS, Python REPL)
└── rag/             # RAG integration for private knowledgebases

web/                 # Next.js web UI (React, TypeScript)
├── src/app/         # Next.js pages and API routes
├── src/components/  # UI components and design system
└── src/core/        # Frontend utilities and state management
```

## Development Commands

### Backend (Python)
```bash
# Install dependencies
uv sync

# Development server
uv run server.py --reload

# Console UI
uv run main.py

# Run tests
make test                    # Run all tests
make coverage               # Run tests with coverage
pytest tests/unit/test_*.py # Run specific test file

# Code quality
make lint                   # Ruff linting
make format                 # Ruff formatting

# LangGraph Studio (debugging)
make langgraph-dev          # Start LangGraph development server
```

### Frontend (Web UI)
```bash
cd web/
pnpm install                # Install dependencies
pnpm dev                    # Development server (localhost:3000)
pnpm build                  # Production build
pnpm typecheck              # Type checking
pnpm lint                   # ESLint
pnpm format:write           # Prettier formatting
```

### Full Stack Development
```bash
# Run both backend and frontend
./bootstrap.sh -d           # macOS/Linux
bootstrap.bat -d           # Windows
```

### Docker
```bash
# Build and run
make build                  # Build Docker image
docker compose up          # Run with Docker Compose

# Production deployment
docker build -t deer-flow-api .
docker run -p 8000:8000 deer-flow-api
```

### Fix GitHub issues
create a branch named `fix/<issue-number>` to address specific GitHub issues.

## Configuration

### Environment Setup
```bash
# Required: Copy example configs
cp .env.example .env
cp conf.yaml.example conf.yaml

# Key environment variables:
# TAVILY_API_KEY          # Web search
# BRAVE_SEARCH_API_KEY    # Alternative search
# LANGSMITH_API_KEY       # LangSmith tracing (optional)
# LANGGRAPH_CHECKPOINT_DB_URL  # MongoDB/PostgreSQL for persistence
```

### LangGraph Studio
```bash
# Local debugging with checkpointing
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.12 langgraph dev --allow-blocking
```

## Common Development Tasks

### Testing
```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/integration/

# Specific component
pytest tests/unit/config/test_configuration.py

# With coverage
pytest --cov=src tests/ --cov-report=html
```

### Code Quality
```bash
# Format code
make format

# Check linting
make lint

# Type checking (frontend)
cd web && pnpm typecheck
```

### Adding New Features
1. **New Agent**: Add agent in `src/agents/` + update graph in `src/graph/builder.py`
2. **New Tool**: Add tool in `src/tools/` + register in agent prompts
3. **New Workflow**: Create graph builder in `src/[feature]/graph/builder.py`
4. **Frontend Component**: Add to `web/src/components/` + update API in `web/src/core/api/`

### Configuration Changes
- **LLM Models**: Update `conf.yaml` with new providers
- **Search Engines**: Modify `.env` SEARCH_API variable
- **RAG Integration**: Configure RAGFLOW_API_URL in `.env`
- **MCP Servers**: Add MCP settings in configuration

## Architecture Patterns

### Agent Communication
- **Message Passing**: Agents communicate via LangGraph state
- **Tool Access**: Each agent has specific tool permissions
- **State Management**: Persistent checkpoints for conversation history

### Content Generation Pipeline
1. **Planning**: Planner creates research plan
2. **Research**: Researcher gathers information
3. **Processing**: Coder analyzes data/code
4. **Reporting**: Reporter synthesizes findings
5. **Post-processing**: Optional podcast/PPT generation

### External Integrations
- **Search**: Tavily, Brave Search, DuckDuckGo
- **Crawling**: Jina for web content extraction
- **TTS**: Volcengine TTS API
- **RAG**: RAGFlow and VikingDB support
- **MCP**: Model Context Protocol integration