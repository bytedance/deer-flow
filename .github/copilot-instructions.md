# GitHub Copilot Instructions for DeerFlow

This file provides guidance to GitHub Copilot when working with the DeerFlow repository.

## Project Overview

**DeerFlow** (Deep Exploration and Efficient Research Flow) is a community-driven Deep Research framework built on LangGraph. It orchestrates AI agents to conduct deep research, generate reports, and create content like podcasts and presentations.

### Technology Stack

- **Backend**: Python 3.12+, FastAPI, LangGraph, LangChain
- **Frontend**: Next.js (React), TypeScript, pnpm
- **Package Management**: uv (Python), pnpm (Node.js)
- **Testing**: pytest (Python), Jest (JavaScript)
- **Linting/Formatting**: Ruff (Python), ESLint/Prettier (JavaScript)

## Architecture Overview

### Core Components

1. **Multi-Agent System**: Built on LangGraph with state-based workflows
   - **Coordinator**: Entry point managing workflow lifecycle
   - **Planner**: Decomposes research objectives into structured plans
   - **Research Team**: Specialized agents (Researcher, Coder) executing plans
   - **Reporter**: Aggregates findings and generates final reports
   - **Human-in-the-loop**: Interactive plan modification and approval

2. **State Management**
   - Uses LangGraph StateGraph for agent communication
   - MemorySaver for conversation persistence
   - Checkpointing with MongoDB/PostgreSQL support

3. **External Integrations**
   - Search engines: Tavily, Brave Search, DuckDuckGo
   - Web crawling: Jina for content extraction
   - TTS: Volcengine TTS API
   - RAG: RAGFlow and VikingDB support
   - MCP: Model Context Protocol integration

### Directory Structure

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

tests/               # Test suite
├── unit/            # Unit tests
└── integration/     # Integration tests
```

## Development Workflow

### Environment Setup

1. **Python Environment**:
   ```bash
   # Use uv for dependency management
   uv sync
   
   # For development dependencies
   uv pip install -e ".[dev]"
   uv pip install -e ".[test]"
   ```

2. **Configuration Files**:
   ```bash
   # Copy and configure environment files
   cp .env.example .env
   cp conf.yaml.example conf.yaml
   ```

3. **Frontend Setup**:
   ```bash
   cd web/
   pnpm install
   ```

### Running the Application

- **Backend Development Server**: `uv run server.py --reload`
- **Console UI**: `uv run main.py`
- **Frontend Development**: `cd web && pnpm dev`
- **Full Stack**: `./bootstrap.sh -d` (macOS/Linux) or `bootstrap.bat -d` (Windows)
- **LangGraph Studio**: `make langgraph-dev`

### Testing

- **Python Tests**: `make test` or `pytest tests/`
- **Python Coverage**: `make coverage`
- **Frontend Tests**: `cd web && pnpm test:run`
- **Frontend Lint**: `make lint-frontend`

### Code Quality

- **Python Formatting**: `make format` (uses Ruff)
- **Python Linting**: `make lint` (uses Ruff)
- **Frontend Linting**: `cd web && pnpm lint`
- **Frontend Type Check**: `cd web && pnpm typecheck`

## Coding Standards

### Python Code

1. **Style Guidelines**:
   - Follow PEP 8 guidelines
   - Use type hints wherever possible
   - Line length: 88 characters (Ruff default)
   - Python version requirement: >= 3.12

2. **Code Organization**:
   - Write clear, documented code with descriptive docstrings
   - Keep functions and methods focused and single-purpose
   - Comment complex logic
   - Use meaningful variable and function names

3. **Testing Requirements**:
   - Add tests for new features in `tests/` directory
   - Maintain test coverage (minimum 25%)
   - Use pytest fixtures for test setup
   - Test both unit and integration scenarios

4. **LangGraph Patterns**:
   - Agents communicate via LangGraph state
   - Each agent has specific tool permissions
   - Use persistent checkpoints for conversation history
   - Follow the node → edge → state pattern

### TypeScript/JavaScript Code

1. **Style Guidelines**:
   - Use TypeScript for type safety
   - Follow ESLint configuration
   - Use Prettier for consistent formatting
   - Prefer functional components with hooks

2. **Component Structure**:
   - Place UI components in `web/src/components/`
   - Use the established design system
   - Keep components focused and reusable
   - Export types alongside components

3. **API Integration**:
   - API utilities in `web/src/core/api/`
   - Handle errors gracefully
   - Use proper TypeScript types for API responses

## Configuration Management

### Environment Variables (.env)

Key environment variables to configure:
- `TAVILY_API_KEY`: Web search integration
- `BRAVE_SEARCH_API_KEY`: Alternative search engine
- `LANGSMITH_API_KEY`: LangSmith tracing (optional)
- `LANGGRAPH_CHECKPOINT_DB_URL`: MongoDB/PostgreSQL for persistence
- `RAGFLOW_API_URL`: RAG integration

### Application Configuration (conf.yaml)

- LLM model configurations
- Provider-specific settings
- Search engine preferences
- MCP server configurations

## Common Development Tasks

### Adding New Features

1. **New Agent**:
   - Add agent definition in `src/agents/`
   - Update graph in `src/graph/builder.py`
   - Register agent tools in prompts

2. **New Tool**:
   - Implement tool in `src/tools/`
   - Register in agent prompts
   - Add tests for tool functionality

3. **New Workflow**:
   - Create graph builder in `src/[feature]/graph/builder.py`
   - Define state management
   - Add nodes and edges

4. **Frontend Component**:
   - Add component to `web/src/components/`
   - Update API in `web/src/core/api/`
   - Add corresponding types

### Debugging

- **LangGraph Studio**: `make langgraph-dev` for visual workflow debugging
- **LangSmith**: Configure `LANGSMITH_API_KEY` for tracing
- **Server Logs**: Check FastAPI server output for backend issues
- **Browser DevTools**: Use for frontend debugging

## Important Patterns

### Agent Communication
- Agents communicate through LangGraph state
- State is preserved across checkpoints
- Use proper type annotations for state

### Content Generation Pipeline
1. Planning: Planner creates research plan
2. Research: Researcher gathers information
3. Processing: Coder analyzes data/code
4. Reporting: Reporter synthesizes findings
5. Post-processing: Optional podcast/PPT generation

### Error Handling
- Use try-except blocks with specific exception types
- Log errors with appropriate context
- Provide meaningful error messages to users
- Handle API failures gracefully

### Async Operations
- Use async/await for I/O operations
- Properly handle concurrent operations
- Use appropriate timeout values
- Clean up resources in finally blocks

## Pre-commit Hooks

The repository uses pre-commit hooks for code quality:
```bash
chmod +x pre-commit
ln -s ../../pre-commit .git/hooks/pre-commit
```

## Dependencies

### Adding New Dependencies

- **Python**: Add to `pyproject.toml` dependencies, then run `uv sync`
- **JavaScript**: Use `pnpm add <package>` in the `web/` directory

### Dependency Updates

- Keep dependencies up to date
- Test thoroughly after updates
- Check compatibility with Python 3.12+ and Node.js 22+

## Documentation

### When to Update Documentation

- New features: Update relevant docs in `docs/` directory
- API changes: Update `docs/API.md`
- Configuration changes: Update `docs/configuration_guide.md`
- Breaking changes: Clearly document in README and CONTRIBUTING

### Documentation Style

- Use clear, concise language
- Include code examples where applicable
- Keep documentation in sync with code
- Use markdown formatting consistently

## Security Considerations

- Never commit API keys or secrets to the repository
- Use `.env` files for sensitive configuration
- Validate and sanitize user inputs
- Follow security best practices for web applications
- Be cautious with code execution features

## Community Guidelines

- Be respectful and inclusive
- Follow the MIT License terms
- Give constructive feedback in code reviews
- Help others learn and grow
- Stay focused on improving the project

## Getting Help

- Check existing documentation in `docs/`
- Review `Agent.md` for architecture details
- See `CONTRIBUTING` for contribution guidelines
- Check GitHub issues for known problems
- Join community discussions for support

## Additional Resources

- Main README: Comprehensive project overview
- Agent.md: Detailed architecture and agent guidance
- CONTRIBUTING: Full contribution guidelines
- docs/configuration_guide.md: Configuration details
- docs/API.md: API documentation
- docs/mcp_integrations.md: MCP integration guide
