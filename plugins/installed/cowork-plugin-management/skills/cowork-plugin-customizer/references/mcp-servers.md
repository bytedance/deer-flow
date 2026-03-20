# MCP Discovery and Connection

How to find and connect MCPs during plugin customization.

## Available Tools

### `search_mcp_registry`
Search the MCP directory for available connectors.

**Input:** `{ "keywords": ["array", "of", "search", "terms"] }`

**Output:** Up to 10 results, each with:
- `name`: MCP display name
- `description`: One-liner description
- `tools`: List of tool names the MCP provides
- `url`: MCP endpoint URL (use this in `.mcp.json`)
- `directoryUuid`: UUID for use with suggest_connectors
- `connected`: Boolean - whether user has this MCP connected

### `suggest_connectors`
Display Connect buttons to let users install/connect MCPs.

**Input:** `{ "directoryUuids": ["uuid1", "uuid2"] }`

**Output:** Renders UI with Connect buttons for each MCP

## Category-to-Keywords Mapping

| Category | Search Keywords |
|----------|-----------------|
| `project-management` | `["asana", "jira", "linear", "monday", "tasks"]` |
| `software-coding` | `["github", "gitlab", "bitbucket", "code"]` |
| `chat` | `["slack", "teams", "discord"]` |
| `documents` | `["google docs", "notion", "confluence"]` |
| `calendar` | `["google calendar", "calendar"]` |
| `email` | `["gmail", "outlook", "email"]` |
| `design-graphics` | `["figma", "sketch", "design"]` |
| `analytics-bi` | `["datadog", "grafana", "analytics"]` |
| `crm` | `["salesforce", "hubspot", "crm"]` |
| `wiki-knowledge-base` | `["notion", "confluence", "outline", "wiki"]` |
| `data-warehouse` | `["bigquery", "snowflake", "redshift"]` |
| `conversation-intelligence` | `["gong", "chorus", "call recording"]` |

## Workflow

1. **Find customization point**: Look for `~~`-prefixed values (e.g., `~~Jira`)
2. **Check earlier phase findings**: Did you already learn which tool they use?
   - **Yes**: Search for that specific tool to get its `url`, skip to step 5
   - **No**: Continue to step 3
3. **Search**: Call `search_mcp_registry` with mapped keywords
4. **Present choices and ask user**: Show all results, ask which they use
5. **Connect if needed**: If not connected, call `suggest_connectors`
6. **Update MCP config**: Add config using the `url` from search results

## Updating Plugin MCP Configuration

### Finding the Config File

1. **Check `plugin.json`** for an `mcpServers` field:
   ```json
   {
     "name": "my-plugin",
     "mcpServers": "./config/servers.json"
   }
   ```
   If present, edit the file at that path.

2. **If no `mcpServers` field**, use `.mcp.json` at the plugin root (default).

3. **If `mcpServers` points only to `.mcpb` files** (bundled servers), create a new `.mcp.json` at the plugin root.

### Config File Format

Both wrapped and unwrapped formats are supported:

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```

Use the `url` field from `search_mcp_registry` results.

**Note:** First-party integrations (Gmail, Google Calendar, Google Drive) are connected at the user level and don't need plugin `.mcp.json` entries.
