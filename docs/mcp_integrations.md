# MCP Integrations（Beta）

Now This feature is diabled by default. You can enable it by setting the environment ENABLE_MCP_SERVER_CONFIGURATION to be true

> [!WARNING]
> Please enable this feature before securing your frond-end and back-end in a managed environment.
> Otherwise, you system could be compromised.

This feature is diabled by default. You can enable it by setting the environment ENABLE_MCP_SERVER_CONFIGURATION
Please enable this feature before securing your frond-end and back-end in an internal environment.q

## Example of MCP Server Configuration

```json
{
  "mcpServers": {
    "mcp-github-trending": {
      "transport": "stdio",
      "command": "uvx",
      "args": [
          "mcp-github-trending"
      ]
    }
  }
}
```

## APIs

### Get metadata of MCP Server

**POST /api/mcp/server/metadata**

For `stdio` type:
```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "tavily-mcp@0.1.3"],
  "env": {"TAVILY_API_KEY":  "tvly-dev-xxx"}
}
```

For `sse` type:
```json
{
  "transport": "sse",
  "url": "http://localhost:3000/sse",
  "env": {
    "API_KEY": "value"
  }
}
```

### Chat Stream

**POST /api/chat/stream**

```json
{
  ...
  "mcp_settings": {
    "servers": {
      "mcp-github-trending": {
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-github-trending"],
        "env": {
          "MCP_SERVER_ID": "mcp-github-trending"
        },
        "enabled_tools": ["get_github_trending_repositories"],
        "add_to_agents": ["researcher"]
      }
    }
  },
}
```
