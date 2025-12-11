# MCP Integrations (Beta)

This feature is disabled by default. You can enable it by setting the environment variable `ENABLE_MCP_SERVER_CONFIGURATION=true`.

> [!WARNING]
> Please enable this feature only after securing your front-end and back-end in a managed environment.
> Otherwise, your system could be compromised.

## Enabling MCP

Set the following environment variable in your `.env` file:

```bash
ENABLE_MCP_SERVER_CONFIGURATION=true
```

Then restart the DeerFlow server.

---

## MCP Server Examples

### 1. GitHub Trending

Fetches trending repositories from GitHub.

```json
{
  "mcpServers": {
    "mcp-github-trending": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-github-trending"]
    }
  }
}
```

**Available Tools:**
- `get_github_trending_repositories` - Get trending repositories by language and time range

---

### 2. Filesystem Access

Provides secure file system access with configurable allowed directories.

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/path/to/allowed/directory"
      ]
    }
  }
}
```

**Available Tools:**
- `read_text_file` - Read contents of a text file
- `read_multiple_files` - Read multiple files at once
- `write_file` - Write content to a file
- `edit_file` - Edit a file with line-based replacements
- `create_directory` - Create a new directory
- `list_directory` - List files and directories
- `directory_tree` - Get a recursive tree view
- `move_file` - Move or rename files
- `search_files` - Search for files by pattern
- `get_file_info` - Get file metadata

---

### 3. Brave Search

Web search using Brave Search API.

**Prerequisites:** Get API key from [Brave Search API](https://brave.com/search/api/)

```json
{
  "mcpServers": {
    "brave-search": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "your-brave-api-key"
      }
    }
  }
}
```

**Available Tools:**
- `brave_web_search` - Perform web searches
- `brave_local_search` - Search for local businesses and places

---

### 4. Tavily Search

AI-optimized search engine for research tasks.

**Prerequisites:** Get API key from [Tavily](https://tavily.com/)

```json
{
  "mcpServers": {
    "tavily": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "tavily-mcp"],
      "env": {
        "TAVILY_API_KEY": "tvly-your-api-key"
      }
    }
  }
}
```

**Available Tools:**
- `tavily-search` - Perform AI-optimized web search
- `tavily-extract` - Extract content from web pages

---

## Adding MCP Tools to Agents

When using MCP tools in DeerFlow, you need to specify:

1. **`enabled_tools`** - Which tools from the MCP server to enable
2. **`add_to_agents`** - Which DeerFlow agents can use these tools (`researcher`, `coder`, or both)

### Example: Full Configuration for Chat API

```json
{
  "messages": [{"role": "user", "content": "Research the top GitHub trends"}],
  "mcp_settings": {
    "servers": {
      "github-trending": {
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-github-trending"],
        "enabled_tools": ["get_github_trending_repositories"],
        "add_to_agents": ["researcher"]
      }
    }
  }
}
```

---

## APIs

### Get MCP Server Metadata

**POST /api/mcp/server/metadata**

Use this endpoint to discover available tools from an MCP server.

For `stdio` type:
```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
}
```

For `sse` type:
```json
{
  "transport": "sse",
  "url": "http://localhost:3000/sse",
  "headers": {
    "Authorization": "Bearer your-token"
  }
}
```

For `streamable_http` type:
```json
{
  "transport": "streamable_http",
  "url": "http://localhost:3000/mcp",
  "headers": {
    "API_KEY": "your-api-key"
  }
}
```

### Chat Stream with MCP

**POST /api/chat/stream**

```json
{
  "messages": [{"role": "user", "content": "Your research query"}],
  "thread_id": "unique-thread-id",
  "mcp_settings": {
    "servers": {
      "your-mcp-server": {
        "transport": "stdio",
        "command": "uvx",
        "args": ["your-mcp-package"],
        "env": {
          "API_KEY": "your-api-key"
        },
        "enabled_tools": ["tool1", "tool2"],
        "add_to_agents": ["researcher"]
      }
    }
  }
}
```

---

## Additional Resources

- [MCP Official Documentation](https://modelcontextprotocol.io/)
- [MCP Server Registry](https://github.com/modelcontextprotocol/servers)
