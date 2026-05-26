# Hosting DeerFlow as an MCP Server

DeerFlow can be exposed as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing external AI agents and tools — such as Claude Code, OpenCode, Cursor, or any MCP-compatible client — to invoke DeerFlow's research and reasoning capabilities as tools.

> **Note:** This is the _reverse_ of DeerFlow's existing MCP client support (see [MCP_SERVER.md](MCP_SERVER.md)). Here, DeerFlow acts as the **server** that other agents call into.

## Quick Start

```bash
cd backend
make mcp-server
```

Or run directly:

```bash
cd backend
PYTHONPATH=. uv run python -m deerflow.mcp.server
```

The server uses **stdio** transport and exposes two tools.

## Exposed Tools

| Tool | Description | Planning | Best For |
|------|-------------|----------|----------|
| `deerflow_research` | Deep research with web search, planning, and multi-step reasoning | Yes | Complex questions, report generation, multi-source synthesis |
| `deerflow_ask` | Quick Q&A without planning overhead | No | Factual questions, code explanations, simple tasks |

## Configuration

The MCP server uses DeerFlow's standard configuration resolution:

1. `DEER_FLOW_CONFIG_PATH` environment variable (if set)
2. `config.yaml` in the current working directory
3. `config.yaml` in the parent directory

Ensure your `config.yaml` has at least one model configured. See the main [Configuration Guide](CONFIGURATION.md) for model setup.

## Integration Examples

### Claude Code / OpenCode

Add to your MCP configuration (e.g., `~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "deerflow": {
      "type": "local",
      "command": ["uv", "run", "python", "-m", "deerflow.mcp.server"],
      "cwd": "/path/to/deer-flow/backend",
      "env": {
        "PYTHONPATH": "."
      }
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%/Claude/claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "deerflow": {
      "command": "uv",
      "args": ["run", "python", "-m", "deerflow.mcp.server"],
      "cwd": "/path/to/deer-flow/backend",
      "env": {
        "PYTHONPATH": "."
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "deerflow": {
      "command": "uv",
      "args": ["run", "python", "-m", "deerflow.mcp.server"],
      "cwd": "/path/to/deer-flow/backend",
      "env": {
        "PYTHONPATH": "."
      }
    }
  }
}
```

## Programmatic Usage

```python
from deerflow.mcp import create_mcp_server

server = create_mcp_server()
server.run(transport="stdio")
```

The `create_mcp_server()` factory returns a configured `FastMCP` instance that can be customized before running.

## Architecture

```
┌─────────────────────┐       stdio        ┌─────────────────────┐
│   MCP Client        │◄──────────────────►│   DeerFlow MCP      │
│   (Claude, OpenCode │       JSON-RPC      │   Server            │
│    Cursor, etc.)    │                     │                     │
└─────────────────────┘                     │  ┌───────────────┐  │
                                            │  │ deerflow_     │  │
                                            │  │ research()    │──┼──► Lead Agent
                                            │  ├───────────────┤  │    (planning,
                                            │  │ deerflow_     │  │     web search,
                                            │  │ ask()         │──┼──►  reasoning)
                                            │  └───────────────┘  │
                                            └─────────────────────┘
```

The MCP server imports DeerFlow's `make_lead_agent` directly and invokes it in-process — no HTTP services or additional infrastructure needed.

## Troubleshooting

**Server won't start:**
- Ensure you're running from the `backend/` directory (or set `PYTHONPATH=.`)
- Ensure dependencies are installed: `uv sync`
- Check that `config.yaml` exists and has valid model configuration

**Tools return errors:**
- Check `config.yaml` model settings — the configured model must be accessible
- For models requiring authentication (e.g., Codex), ensure credentials are valid
- Logs are written to stderr at WARNING level by default

**First invocation is slow:**
- The first call initializes the agent graph and (optionally) external MCP tools
- Subsequent calls reuse the initialized state
