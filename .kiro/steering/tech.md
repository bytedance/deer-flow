# DeerFlow Technical Stack

## Core Technologies
- **Python**: Version 3.12+ required
- **Node.js**: Version 22+ for web UI
- **LangGraph**: Workflow orchestration for multi-agent systems
- **LangChain**: LLM integration and tooling
- **FastAPI**: API server implementation
- **React/Next.js**: Web UI frontend

## Key Dependencies
- **LLM Integration**: langchain-openai, langchain-community, litellm
- **Graph Workflow**: langgraph
- **Web Crawling**: readabilipy, markdownify
- **Search Tools**: tavily, duckduckgo-search, arxiv
- **MCP Integration**: mcp, langchain-mcp-adapters
- **UI**: tiptap (Notion-like editor)

## Environment Management
- **UV**: Recommended for Python environment and dependency management
- **NVM**: For managing Node.js versions
- **PNPM**: For web UI dependency management

## Build & Run Commands

### Setup
```bash
# Clone and setup Python environment
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
uv sync

# Configure environment
cp .env.example .env
cp conf.yaml.example conf.yaml

# Setup web UI (optional)
cd web
pnpm install
```

### Run Console UI
```bash
uv run main.py                           # Basic mode with prompt
uv run main.py "Your research question"  # Direct query
uv run main.py --interactive             # Interactive mode with built-in questions
```

### Run Web UI
```bash
# Development mode (both backend and frontend)
./bootstrap.sh -d    # macOS/Linux
bootstrap.bat -d     # Windows

# Access at http://localhost:3000
```

### Run API Server
```bash
# Start the API server
uvicorn src.server:app --host localhost --port 8000

# Or use the server script
python server.py --host localhost --port 8000
```

### Docker
```bash
# Build and run API server
docker build -t deer-flow-api .
docker run -d -t -p 8000:8000 --env-file .env --name deer-flow-api-app deer-flow-api

# Run both backend and frontend
docker compose build
docker compose up
```

### Testing
```bash
make test           # Run all tests
make coverage       # Run with coverage
make lint           # Run linting
make format         # Format code
```

### LangGraph Studio (Debugging)
```bash
# Start LangGraph server for debugging
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.12 langgraph dev --allow-blocking
```