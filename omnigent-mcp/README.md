# DeerFlow MCP Server

An MCP (Model Context Protocol) stdio server that wraps DeerFlow's REST API as tools so that Omnigent/polly can call DeerFlow directly.

## What it is

This server exposes three tools over the MCP stdio protocol:

| Tool | Description |
|------|-------------|
| `deerflow_run` | Submit a prompt to DeerFlow, wait up to 300 s, return the last assistant message |
| `deerflow_create_thread` | Create a new conversation thread; returns `thread_id` for multi-turn use |
| `deerflow_health` | GET /health — no auth required; returns JSON health status |

## Requirements

- Python ≥ 3.11
- `mcp >= 1.0.0` and `httpx >= 0.28.0` (install via `pip install mcp httpx` or `uv sync`)
- DeerFlow running locally at `http://localhost:2026` (or set `DEERFLOW_URL`)

## Required environment variables

| Variable | Description |
|----------|-------------|
| `DEERFLOW_EMAIL` | Email address used to log in to DeerFlow |
| `DEERFLOW_PASSWORD` | Password for the above account |
| `DEERFLOW_URL` | *(optional)* Base URL; defaults to `http://localhost:2026` |

## How to run

```bash
export DEERFLOW_EMAIL="your@email.com"
export DEERFLOW_PASSWORD="yourpassword"
python3 /Users/lquintela/projects/deer-flow/omnigent-mcp/server.py
```

The server speaks MCP over stdin/stdout and is intended to be launched by an MCP host (Omnigent, Claude Desktop, etc.), not run interactively.

## Adding as an Omnigent MCP server

In your Omnigent / Claude settings, add a stdio MCP server entry:

```json
{
  "type": "stdio",
  "command": "python3",
  "args": ["/Users/lquintela/projects/deer-flow/omnigent-mcp/server.py"],
  "env": {
    "DEERFLOW_EMAIL": "your@email.com",
    "DEERFLOW_PASSWORD": "yourpassword",
    "DEERFLOW_URL": "http://localhost:2026"
  }
}
```

## Tool examples

### One-shot research task

```
deerflow_run(prompt="What are the latest breakthroughs in quantum computing?")
```

### Multi-turn conversation

```python
thread_id = deerflow_create_thread()
# → "abc123..."

deerflow_run(prompt="Summarize the paper on LLM agents", thread_id=thread_id)
deerflow_run(prompt="Now focus on the limitations section", thread_id=thread_id)
```

### Health check

```
deerflow_health()
# → {"status": "ok"}
```

## How auth works

On the first tool call the server POSTs credentials to `/api/v1/auth/login/local` using the HTTP form-encoded format DeerFlow expects. The session cookie is stored in the `httpx.AsyncClient`. Every state-changing request includes the `X-CSRF-Token` header taken from the `csrf_token` cookie (Double Submit Cookie pattern). On a 401/403 the server re-authenticates once and retries automatically.
