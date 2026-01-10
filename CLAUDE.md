# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**DeerFlow** is a multi-agent research framework built on LangGraph that orchestrates AI agents to conduct deep research, generate reports, and create content like podcasts and presentations.

### Technology Stack

- **Backend**: Python 3.12+, FastAPI, LangGraph, LangChain, litellm
- **Frontend**: Next.js 15 (React 19), TypeScript, pnpm, Tailwind CSS
- **Package Management**: `uv` (Python), `pnpm` (Node.js)
- **Testing**: pytest (Python), Jest (JavaScript)
- **Linting/Formatting**: Ruff (Python), ESLint/Prettier (JavaScript)

## Development Commands

### Python Backend

```bash
# Install dependencies (uv handles venv creation and package installation)
uv sync

# Install dev/test dependencies
make install-dev  # or: uv pip install -e ".[dev,test]"

# Development server with auto-reload
uv run server.py --reload
# Or using make
make serve

# Console UI (command-line interface)
uv run main.py

# Run tests
make test              # Run all tests
pytest tests/unit/test_*.py  # Run specific test file
make coverage          # Run with coverage report

# Code quality
make format            # Format code with Ruff
make lint              # Lint and fix code with Ruff

# LangGraph Studio (visual workflow debugging)
make langgraph-dev
```

### Frontend (Web UI)

```bash
cd web/
pnpm install           # Install dependencies
pnpm dev               # Development server (localhost:3000)
pnpm build             # Production build
pnpm lint              # ESLint
pnpm typecheck         # TypeScript type check
pnpm test:run          # Run Jest tests
pnpm format:write      # Prettier formatting
```

### Full Stack Development

```bash
# Run both backend and frontend in development mode
./bootstrap.sh -d      # macOS/Linux
bootstrap.bat -d       # Windows
```

### Docker

```bash
docker build -t deer-flow-api .
docker run -d -t -p 127.0.0.1:8000:8000 --env-file .env --name deer-flow-api-app deer-flow-api
docker compose build && docker compose up  # Both frontend and backend
```

## Architecture

### Multi-Agent System (LangGraph)

The system uses a **state-based workflow** where agents communicate through LangGraph's StateGraph:

**Main Workflow Components:**

1. **Coordinator** (`src/graph/nodes.py:coordinator_node`)
   - Entry point managing workflow lifecycle
   - Initiates research process based on user input

2. **Background Investigator** (`src/graph/nodes.py:background_investigation_node`)
   - Optional pre-planning web search for context enhancement

3. **Planner** (`src/graph/nodes.py:planner_node`)
   - Decomposes research objectives into structured plans
   - Determines if more research is needed or if ready to report

4. **Research Team** (`src/graph/nodes.py:research_team_node`)
   - Orchestrates specialized agents based on plan step types:
   - **Researcher** (`researcher_node`): Web search, crawling, MCP tools
   - **Analyst** (`analyst_node`): Data analysis tasks
   - **Coder** (`coder_node`): Code analysis and execution via Python REPL

5. **Human Feedback** (`src/graph/nodes.py:human_feedback_node`)
   - Interactive plan modification and approval
   - Supports auto-acceptance mode

6. **Reporter** (`src/graph/nodes.py:reporter_node`)
   - Aggregates findings and generates final reports

**State Management** (`src/graph/types.py`):
- Extends LangGraph's `MessagesState` with custom fields
- Uses `MemorySaver` for in-memory persistence or MongoDB/PostgreSQL for production checkpointing
- Key state fields: `research_topic`, `current_plan`, `final_report`, `enable_clarification`

**Graph Flow** (`src/graph/builder.py`):
```
START → coordinator → background_investigator → planner
                                                         ↓
                                              research_team → reporter → END
                                                         ↑
                                                   human_feedback
```

### Directory Structure

```
src/
├── agents/          # Agent definitions and tool interception
├── config/          # Configuration management (YAML, env vars)
├── crawler/         # Web crawling (Jina, InfoQuest)
├── graph/           # LangGraph workflow (builder, nodes, state types)
├── llms/            # LLM provider integrations (litellm-based)
├── prompts/         # Agent prompt templates and models
├── server/          # FastAPI web server and API endpoints
├── tools/           # External tools (search, TTS, Python REPL, MCP)
└── rag/             # RAG integration (Qdrant, Milvus, RAGFlow, etc.)

web/                 # Next.js web UI
├── src/app/         # Next.js App Router pages and API routes
├── src/components/  # UI components and design system
└── src/core/        # Frontend utilities, API clients, state management
```

## Configuration

### Required Setup

```bash
# Copy example configuration files
cp .env.example .env
cp conf.yaml.example conf.yaml
```

### Key Environment Variables (.env)

- `TAVILY_API_KEY` - Web search (default search engine)
- `INFOQUEST_API_KEY` - Alternative search/crawling (BytePlus)
- `BRAVE_SEARCH_API_KEY` - Alternative search engine
- `LANGSMITH_API_KEY` - LangSmith tracing (optional)
- `LANGGRAPH_CHECKPOINT_DB_URL` - MongoDB/PostgreSQL for persistence
- `RAG_PROVIDER` - RAG backend (ragflow, qdrant, milvus)
- `SEARCH_API` - Search engine selection (tavily, infoquest, duckduckgo, brave_search, arxiv)

### Application Configuration (conf.yaml)

- LLM model configurations (providers, model names, API keys)
- Crawler engine selection (jina, infoquest)
- MCP server configurations
- See `docs/configuration_guide.md` for details

## Common Development Tasks

### Adding a New Agent

1. Define agent in `src/agents/agents.py`
2. Add node function in `src/graph/nodes.py`
3. Register in `src/graph/builder.py:_build_base_graph()`
4. Add tools to agent prompt in `src/prompts/`

### Adding a New Tool

1. Implement tool in `src/tools/`
2. Register in agent prompts in `src/prompts/`
3. Add tests for tool functionality in `tests/`

### Frontend Component Development

1. Add component to `web/src/components/`
2. Update API client in `web/src/core/api/` if needed
3. Add TypeScript types for API responses
4. Use Radix UI primitives and Tailwind CSS for styling

### Running Single Test

```bash
# Unit test
pytest tests/unit/test_workflow.py -v

# Integration test
pytest tests/integration/test_api.py -v

# With coverage
pytest tests/unit/test_configuration.py --cov=src/config --cov-report=term-missing
```

## Important Patterns

### Agent Communication
- Agents communicate via LangGraph state, not direct function calls
- Each agent reads from and writes to shared state
- State is preserved across checkpoints for conversation history

### Tool Integration
- Tools are registered via `@tool` decorator in LangChain
- MCP (Model Context Protocol) servers provide extensible tool integrations
- Each agent has specific tool permissions defined in prompts

### Streaming Responses
- Backend uses SSE (Server-Sent Events) via `sse-starlette`
- Frontend uses streaming APIs in `web/src/core/api/` for real-time updates
- LangGraph's `astream()` yields state updates during workflow execution

### Error Handling
- Use async/await for I/O operations
- Handle API failures gracefully with proper error messages
- Log errors with appropriate context using the logging module

## Known Issues

- **LangGraph Checkpoint Postgres v2.0.23+** has serialization issues (see langgraph #5557)
- The project pins to `langgraph-checkpoint-postgres==2.0.21` in `pyproject.toml`
- psycopg may require `libpq` system library or `psycopg[binary]` extra

## GitHub Issue Workflow

When fixing GitHub issues, create branches named `fix/<issue-number>`.
