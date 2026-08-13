# MCP (Model Context Protocol) Configuration

DeerFlow supports configurable MCP servers and skills to extend its capabilities, which are loaded from a dedicated `extensions_config.json` file in the project root directory.

## Setup

1. Copy `extensions_config.example.json` to `extensions_config.json` in the project root directory.
   ```bash
   # Copy example configuration
   cp extensions_config.example.json extensions_config.json
   ```
   
2. Enable the desired MCP servers or skills by setting `"enabled": true`.
3. Configure each server’s command, arguments, and environment variables as needed.
4. Restart the application to load and register MCP tools.

## OpenViking MCP Tools

OpenViking's official server exposes a Streamable HTTP MCP endpoint at `/mcp`.
DeerFlow connects to it through the same generic MCP client used for other HTTP
servers:

```json
{
  "mcpServers": {
    "openviking": {
      "enabled": true,
      "type": "http",
      "url": "http://127.0.0.1:1933/mcp",
      "headers": {
        "X-API-Key": "$OPENVIKING_API_KEY"
      }
    }
  }
}
```

Set `OPENVIKING_API_KEY` to a normal owner-bound OpenViking **USER API key**.
The key determines the OpenViking account and user. Do not use a root/admin
key, trusted mode, or add `X-OpenViking-Account`, `X-OpenViking-User`, or
`X-OpenViking-Actor-Peer` headers for this personal single-owner setup.
`X-API-Key` is used here because DeerFlow expands a whole-string `$ENV_VAR`
value without storing a credential in the checked-in configuration.
If `OPENVIKING_API_KEY` is missing or empty during initialization, OpenViking
authentication fails and DeerFlow skips that MCP server, so no OpenViking tools
appear. Changing only the environment variable does not invalidate DeerFlow's
already-populated, file-signature-based MCP tool cache; after setting or fixing
the key, restart DeerFlow, modify and re-save the extensions config, or call the
MCP cache-reset endpoint at `POST /api/mcp/cache/reset`.

OpenViking owns the tool schemas and behavior. DeerFlow performs the standard
MCP initialization and discovery flow, prefixes the discovered names with
`openviking_` by default, and routes calls back through the generic MCP client.
For capability parity with other official OpenViking harnesses, DeerFlow exposes
the native `forget` tool with the other discovered tools. `forget` permanently
deletes a `viking://` URI and should be called only after explicit user
confirmation; DeerFlow does not enforce that confirmation.

Operators who do not want agents to call `forget` can block its default visible
name with DeerFlow's existing guardrail configuration:

```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["openviking_forget"]
```

If `tool_name_prefix` is disabled for the OpenViking server, block `forget`
instead.

This explicit tool path is separate from the automatic OpenViking memory backend
configured under `config.yaml -> memory`. Both may be enabled at the same time:
the memory backend handles automatic turn capture and recall, while MCP tools
are model-selected operations.

For Docker, point `url` at the OpenViking address reachable from the Gateway
container, such as `http://openviking:1933/mcp` for a shared Compose network or
`http://host.docker.internal:1933/mcp` for a host-installed server.

## Routing Hints

Use `routing` when an MCP server should be preferred for specific requests, such
as internal database questions that should use a PostgreSQL MCP tool before web
search. Routing hints are soft model guidance: they add a
`<mcp_routing_hints>` prompt section, but they do not forbid other tools. Use
agent-level allow/deny policy for hard restrictions. If `tool_search.enabled`
defers MCP tool schemas, matching routing metadata can also auto-promote the
deferred schema before the model call. Auto-promotion is controlled by the
top-level `config.yaml -> tool_search.auto_promote_top_k` setting.

```json
{
   "mcpServers": {
      "postgres": {
         "enabled": true,
         "type": "stdio",
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"],
         "routing": {
            "mode": "prefer",
            "priority": 50,
            "keywords": ["orders", "users", "SQL", "database", "table"]
         },
         "tools": {
            "query": {
               "routing": {
                  "mode": "prefer",
                  "priority": 100,
                  "keywords": ["query database", "orders table", "metrics"]
               }
            }
         }
      }
   }
}
```

- `routing.mode`: `off` disables hints; `prefer` emits hints.
- `routing.priority`: `0` to `100`; higher-priority hints are rendered first.
  When `tool_search.enabled=true`, priority also orders auto-promote matches.
- `routing.keywords`: operator-authored terms that describe when to prefer the
  MCP tool. Empty keywords are allowed but do not emit a hint line and do not
  trigger auto-promotion. Auto-promote matching is a case-insensitive substring
  test against the latest user message (not token/word-boundary matching), so
  prefer distinctive keywords — a short term like `api` also matches `rapid`.
  Over-matching only exposes an extra tool schema (soft/additive), never
  disables other tools.
- `tools.<original_tool_name>.routing`: overrides only the fields explicitly
  set for that tool. The key is the MCP server's original tool name, before the
  `<server>_` prefix added for model binding. If the server-level
  `routing.mode` is `off`, a tool override must set `mode: "prefer"`; setting
  only `priority` or `keywords` still inherits `off` and emits no hint.
- `tool_search.auto_promote_top_k`: global limit for auto-promoted deferred MCP
  schemas per model call. Default `3`; valid range `1..5`.

## Tool Name Prefixes

DeerFlow prefixes discovered MCP tool names with `<server_name>_` by default.
This avoids collisions when two enabled servers expose tools with the same
name. A server that already namespaces its own tools can opt out:

```json
{
  "mcpServers": {
    "semantic-scholar": {
      "type": "stdio",
      "command": "uvx",
      "args": ["s2-mcp-server"],
      "tool_name_prefix": false
    }
  }
}
```

With this setting, a server tool named `semantic_scholar_search_papers` keeps
that name instead of becoming
`semantic-scholar_semantic_scholar_search_papers`. The default is `true` for
backward compatibility. Disable it only when every resulting tool name remains
unique across the enabled servers. Stdio tools continue to use DeerFlow's
persistent per-thread session pool regardless of this setting.

## Server Timeouts (Stdio MCP Servers)

Two independent timeouts bound stdio MCP servers. `session_init_timeout` covers
server bring-up — tool discovery (subprocess spawn + `initialize` +
`tools/list`) and persistent-session initialization — and defaults to 60s so a
hung server (e.g. `npx` blocked on a package download, or a server that never
answers `initialize`) cannot block agent construction indefinitely. Set it to
`null` to disable:

```json
{
   "mcpServers": {
      "github": {
         "enabled": true,
         "type": "stdio",
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-github"],
         "env": {
            "GITHUB_TOKEN": "$GITHUB_TOKEN"
         },
         "session_init_timeout": 60,
         "tool_call_timeout": 60
      }
   }
}
```

`tool_call_timeout` limits each individual tool call in seconds and applies only
to `stdio` servers; `http` and `sse` servers use transport-level timeouts, and
DeerFlow logs a warning if `tool_call_timeout` is configured for those
transports.

## Filesystem MCP Servers

DeerFlow already provides built-in file tools for thread-scoped workspace access.
Do not add an MCP filesystem server for the same DeerFlow workspace. The
overlapping file tools use different path semantics, which can make LLM tool
selection and file access behavior unstable.

DeerFlow does not currently adapt the MCP Roots mode for filesystem servers. In
particular, it does not publish per-thread MCP roots or map DeerFlow sandbox
paths such as `/mnt/user-data/...` to paths accepted by
`@modelcontextprotocol/server-filesystem`. Use DeerFlow's built-in file tools
for DeerFlow workspace files.

## OAuth Support (HTTP/SSE MCP Servers)

For `http` and `sse` MCP servers, DeerFlow supports OAuth token acquisition and automatic token refresh.

- Supported grants: `client_credentials`, `refresh_token`
- Configure per-server `oauth` block in `extensions_config.json`
- Secrets should be provided via environment variables (for example: `$MCP_OAUTH_CLIENT_SECRET`)

Example:

```json
{
   "mcpServers": {
      "secure-http-server": {
         "enabled": true,
         "type": "http",
         "url": "https://api.example.com/mcp",
         "oauth": {
            "enabled": true,
            "token_url": "https://auth.example.com/oauth/token",
            "grant_type": "client_credentials",
            "client_id": "$MCP_OAUTH_CLIENT_ID",
            "client_secret": "$MCP_OAUTH_CLIENT_SECRET",
            "scope": "mcp.read",
            "refresh_skew_seconds": 60
         }
      }
   }
}
```

## Custom Tool Interceptors

You can register custom interceptors that run before every MCP tool call. This is useful for injecting per-request headers (e.g., user auth tokens from the LangGraph execution context), logging, or metrics.

Declare interceptors in `extensions_config.json` using the `mcpInterceptors` field:

```json
{
  "mcpInterceptors": [
    "my_package.mcp.auth:build_auth_interceptor"
  ],
  "mcpServers": { ... }
}
```

Each entry is a Python import path in `module:variable` format (resolved via `resolve_variable`). The variable must be a **no-arg builder function** that returns an async interceptor compatible with `MultiServerMCPClient`’s `tool_interceptors` interface, or `None` to skip.

Example interceptor that injects an authorization header from the request-scoped
LangGraph secret context:

```python
from langgraph.config import get_config


def build_auth_interceptor():
    async def interceptor(request, handler):
        config = get_config()
        secrets = (config.get("context") or {}).get("secrets") or {}
        token = secrets.get("MCP_AUTH_TOKEN")
        if token:
            request = request.override(
                headers={**(request.headers or {}), "Authorization": f"Bearer {token}"}
            )
        return await handler(request)

    return interceptor
```

Supply the credential on each run request through `config.context.secrets`:

```json
{
  "metadata": {"source": "my-client"},
  "config": {
    "context": {
      "secrets": {"MCP_AUTH_TOKEN": "<request-scoped credential>"}
    }
  }
}
```

Both `metadata.auth_token` and `config.metadata.auth_token` are rejected with HTTP 422 at run admission and are never supported
interceptor paths. Do not put credentials in either metadata surface; use
`config.context.secrets`, whose values remain available to the live interceptor
but are removed from persisted and API-visible run configuration copies.

- A single string value is accepted and normalized to a one-element list.
- Invalid paths or builder failures are logged as warnings without blocking other interceptors.
- The builder return value must be `callable`; non-callable values are skipped with a warning.

### Migrating legacy MCP credentials

Deployments that previously sent `metadata.auth_token` or `config.metadata.auth_token` must:

1. Update the caller and interceptor to use `config.context.secrets` as shown
   above.
2. Rotate the exposed credential before resuming authenticated MCP traffic.
3. Locate and remove every retained legacy copy according to the deployment's
   retention policy, including database rows, run events, application or proxy
   logs, snapshots, exports, and backups.

Current history APIs hide legacy `metadata.auth_token` and `config.metadata.auth_token` values, but hiding a response does not erase
material already retained by those systems. Restarting or upgrading DeerFlow does
not rotate credentials or perform historical cleanup; operators must complete
both actions explicitly.

## How It Works

MCP servers expose tools that are automatically discovered and integrated into DeerFlow’s agent system at runtime. Once enabled, these tools become available to agents without additional code changes.

## Example Capabilities

MCP servers can provide access to:

- **Databases** (e.g., PostgreSQL)
- **External APIs** (e.g., GitHub, Brave Search)
- **Browser automation** (e.g., Puppeteer)
- **Custom MCP server implementations**

## Learn More

For detailed documentation about the Model Context Protocol, visit:  
https://modelcontextprotocol.io
