# API Reference

This document provides a complete reference for the DeerFlow backend APIs.

## Overview

DeerFlow backend exposes two sets of APIs:

1. **LangGraph-compatible API** - Agent interactions, threads, and streaming (`/api/langgraph/*`)
2. **Gateway API** - Models, MCP, skills, uploads, and artifacts (`/api/*`)

All APIs are accessed through the Nginx reverse proxy at port 2026.

For agent conversations, clients can either pre-create a thread
(`POST /api/langgraph/threads`) or start immediately with the stateless stream
endpoint (`POST /api/langgraph/runs/stream`). The latter auto-creates a thread
and returns `thread_id` and `run_id` in the response `Content-Location` header.

## LangGraph-compatible API

Base URL: `/api/langgraph`

The public LangGraph-compatible API follows LangGraph SDK conventions. In the unified nginx deployment, Gateway owns `/api/langgraph/*` and translates those paths to its native `/api/*` run, thread, and streaming routers.

### Threads

#### Create Thread

```http
POST /api/langgraph/threads
Content-Type: application/json
```

**Request Body:**
```json
{
  "metadata": {}
}
```

**Response:**
```json
{
  "thread_id": "abc123",
  "created_at": "2024-01-15T10:30:00Z",
  "metadata": {}
}
```

#### Get Thread State

```http
GET /api/langgraph/threads/{thread_id}/state
```

**Response:**
```json
{
  "values": {
    "messages": [...],
    "sandbox": {...},
    "artifacts": [...],
    "thread_data": {...},
    "title": "Conversation Title"
  },
  "next": [],
  "config": {...}
}
```

### Runs

#### Create Run

Execute the agent with input.

```http
POST /api/langgraph/threads/{thread_id}/runs
Content-Type: application/json
```

**Request Body:**
```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Hello, can you help me?"
      }
    ]
  },
  "config": {
    "recursion_limit": 100,
    "configurable": {
      "model_name": "gpt-4",
      "thinking_enabled": false,
      "is_plan_mode": false
    }
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

**Stream Mode Compatibility:**
- Use: `values`, `messages-tuple`, `custom`, `updates`, `events`, `debug`, `tasks`, `checkpoints`
- Do not use: `tools` (deprecated/invalid in current `langgraph-api` and will trigger schema validation errors)

**Recursion Limit:**

`config.recursion_limit` caps the number of graph steps LangGraph will execute
in a single run. The unified Gateway path defaults to `100` in
`build_run_config` (see `backend/app/gateway/services.py`), which is a safer
starting point for plan-mode or subagent-heavy runs. Clients can still set
`recursion_limit` explicitly in the request body; increase it if you run deeply
nested subagent graphs. For safety, the Gateway clamps any client-supplied value
to a configurable server ceiling (`max_recursion_limit` in `config.yaml`,
default `1000`) so a single run cannot execute unbounded graph steps (runaway
LLM cost / DoS); invalid or non-positive values fall back to the `100` default.

**Configurable Options:**
- `model_name` (string): Override the default model
- `thinking_enabled` (boolean): Enable extended thinking for supported models
- `is_plan_mode` (boolean): Enable TodoList middleware for task tracking

**Response:** Server-Sent Events (SSE) stream

```
event: values
data: {"messages": [...], "title": "..."}

event: messages
data: {"content": "Hello! I'd be happy to help.", "role": "assistant"}

event: end
data: {}
```

#### Get Run History

```http
GET /api/langgraph/threads/{thread_id}/runs
```

**Response:**
```json
{
  "runs": [
    {
      "run_id": "run123",
      "status": "success",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

#### Stream Run

Stream responses in real-time.

```http
POST /api/langgraph/threads/{thread_id}/runs/stream
Content-Type: application/json
```

Same request body as Create Run. Returns SSE stream.

#### Stateless Stream Run

Start a conversation without creating a thread first. Gateway auto-creates a
thread when `config.configurable.thread_id` is omitted, and returns both
identifiers in the response `Content-Location` header.

```http
POST /api/langgraph/runs/stream
Content-Type: application/json
Accept: text/event-stream
```

Through Nginx, `/api/langgraph/runs/stream` is rewritten to the native Gateway
path `POST /api/runs/stream`.

**Request Body:** Same as [Create Run](#create-run). Omit `thread_id` to start a
new conversation; include it to continue an existing one:

```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Hello, can you help me?"
      }
    ]
  },
  "config": {
    "recursion_limit": 100,
    "configurable": {
      "model_name": "gpt-4",
      "thinking_enabled": false,
      "is_plan_mode": false
    }
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

**Response:** Server-Sent Events (SSE) stream with a `Content-Location` header:

```http
Content-Location: /api/threads/{thread_id}/runs/{run_id}
```

Clients should parse `thread_id` and `run_id` from this header (the path ends
with `/runs/{run_id}`). Persist `thread_id` and send it back on the next turn
via `config.configurable.thread_id` to keep conversation history.

**Continuing a conversation:**

```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "What did I just ask?"
      }
    ]
  },
  "config": {
    "configurable": {
      "thread_id": "abc123",
      "model_name": "gpt-4"
    }
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

---

## Gateway API

Base URL: `/api`

### Models

#### List Models

Get all available LLM models from configuration.

```http
GET /api/models
```

**Response:**
```json
{
  "models": [
    {
      "name": "gpt-4",
      "display_name": "GPT-4",
      "supports_thinking": false,
      "supports_vision": true
    },
    {
      "name": "claude-3-opus",
      "display_name": "Claude 3 Opus",
      "supports_thinking": false,
      "supports_vision": true
    },
    {
      "name": "deepseek-v3",
      "display_name": "DeepSeek V3",
      "supports_thinking": true,
      "supports_vision": false
    }
  ]
}
```

#### Get Model Details

```http
GET /api/models/{model_name}
```

**Response:**
```json
{
  "name": "gpt-4",
  "display_name": "GPT-4",
  "model": "gpt-4",
  "max_tokens": 4096,
  "supports_thinking": false,
  "supports_vision": true
}
```

### MCP Configuration

#### Get MCP Config

Get current MCP server configurations.

```http
GET /api/mcp/config
```

Requires an authenticated admin session. Sensitive env/header/OAuth secret
values are masked in the response.

**Response:**
```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "***"
      },
      "description": "GitHub operations"
    }
  }
}
```

#### Update MCP Config

Update MCP server configurations.

```http
PUT /api/mcp/config
Content-Type: application/json
```

Requires an authenticated admin session. API-managed `stdio` MCP servers may
only use allowed executable names for `command` (default: `npx`, `uvx`). Set
`DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST` to a comma-separated list when a
deployment needs additional trusted launchers.

**Request Body:**
```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "$GITHUB_TOKEN"
      },
      "description": "GitHub operations"
    }
  }
}
```

**Response:**
```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "***"
      },
      "description": "GitHub operations"
    }
  }
}
```

#### Reset MCP Tools Cache

Clear cached MCP tools and persistent MCP sessions process-wide. This affects
all threads and users in the current Gateway process. Tools are loaded again
from configured MCP servers on the next agent run or tool lookup.

```http
POST /api/mcp/cache/reset
```

Requires an authenticated admin session.

**Response:**
```json
{
  "success": true,
  "message": "MCP tools cache reset. Tools will reload on next use."
}
```

### Skills

#### List Skills

Get all available skills.

```http
GET /api/skills
```

**Response:**
```json
{
  "skills": [
    {
      "name": "pdf-processing",
      "display_name": "PDF Processing",
      "description": "Handle PDF documents efficiently",
      "enabled": true,
      "license": "MIT",
      "path": "public/pdf-processing"
    },
    {
      "name": "frontend-design",
      "display_name": "Frontend Design",
      "description": "Design and build frontend interfaces",
      "enabled": false,
      "license": "MIT",
      "path": "public/frontend-design"
    }
  ]
}
```

#### Get Skill Details

```http
GET /api/skills/{skill_name}
```

**Response:**
```json
{
  "name": "pdf-processing",
  "display_name": "PDF Processing",
  "description": "Handle PDF documents efficiently",
  "enabled": true,
  "license": "MIT",
  "path": "public/pdf-processing",
  "allowed_tools": ["read_file", "write_file", "bash"],
  "content": "# PDF Processing\n\nInstructions for the agent..."
}
```

#### Enable Skill

```http
POST /api/skills/{skill_name}/enable
```

**Response:**
```json
{
  "success": true,
  "message": "Skill 'pdf-processing' enabled"
}
```

#### Disable Skill

```http
POST /api/skills/{skill_name}/disable
```

**Response:**
```json
{
  "success": true,
  "message": "Skill 'pdf-processing' disabled"
}
```

#### Install Skill

Install a skill from a `.skill` file.

```http
POST /api/skills/install
Content-Type: multipart/form-data
```

**Request Body:**
- `file`: The `.skill` file to install

**Response:**
```json
{
  "success": true,
  "message": "Skill 'my-skill' installed successfully",
  "skill": {
    "name": "my-skill",
    "display_name": "My Skill",
    "path": "custom/my-skill"
  }
}
```

### File Uploads

#### Upload Files

Upload one or more files to a thread.

```http
POST /api/threads/{thread_id}/uploads
Content-Type: multipart/form-data
```

**Request Body:**
- `files`: One or more files to upload

**Response:**
```json
{
  "success": true,
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/threads/abc123/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf",
      "markdown_file": "document.md",
      "markdown_path": ".deer-flow/threads/abc123/user-data/uploads/document.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/document.md",
      "markdown_artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/document.md"
    }
  ],
  "message": "Successfully uploaded 1 file(s)"
}
```

**Supported Document Formats** (auto-converted to Markdown):
- PDF (`.pdf`)
- PowerPoint (`.ppt`, `.pptx`)
- Excel (`.xls`, `.xlsx`)
- Word (`.doc`, `.docx`)

#### List Uploaded Files

```http
GET /api/threads/{thread_id}/uploads/list
```

**Response:**
```json
{
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/threads/abc123/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf",
      "extension": ".pdf",
      "modified": 1705997600.0
    }
  ],
  "count": 1
}
```

#### Delete File

```http
DELETE /api/threads/{thread_id}/uploads/{filename}
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted document.pdf"
}
```

### Thread Cleanup

Remove DeerFlow-managed local thread files under `.deer-flow/threads/{thread_id}` after the LangGraph thread itself has been deleted.

```http
DELETE /api/threads/{thread_id}
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted local thread data for abc123"
}
```

**Error behavior:**
- `422` for invalid thread IDs
- `500` returns a generic `{"detail": "Failed to delete local thread data."}` response while full exception details stay in server logs

### Artifacts

#### Get Artifact

Download or view an artifact generated by the agent.

```http
GET /api/threads/{thread_id}/artifacts/{path}
```

**Path Examples:**
- `/api/threads/abc123/artifacts/mnt/user-data/outputs/result.txt`
- `/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf`

**Query Parameters:**
- `download` (boolean): If `true`, force download with Content-Disposition header

**Response:** File content with appropriate Content-Type

---

## Error Responses

All APIs return errors in a consistent format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

**HTTP Status Codes:**
- `400` - Bad Request: Invalid input
- `404` - Not Found: Resource not found
- `422` - Validation Error: Request validation failed
- `500` - Internal Server Error: Server-side error

---

## Authentication

DeerFlow enforces authentication for all non-public HTTP routes. Public routes are limited to health/docs metadata and these public auth endpoints:

- `POST /api/v1/auth/initialize` creates the first admin account when no admin exists.
- `POST /api/v1/auth/login/local` logs in with email/password and sets an HttpOnly `access_token` cookie.
- `POST /api/v1/auth/register` creates a regular `user` account and sets the session cookie.
- `POST /api/v1/auth/logout` clears the session cookie.
- `GET /api/v1/auth/setup-status` reports whether the first admin still needs to be created.

The authenticated auth endpoints are:

- `GET /api/v1/auth/me` returns the current user.
- `POST /api/v1/auth/change-password` changes password, optionally changes email during setup, increments `token_version`, and reissues the cookie.

Protected state-changing requests also require the CSRF double-submit token: send the `csrf_token` cookie value as the `X-CSRF-Token` header. Login/register/initialize/logout are bootstrap auth endpoints: they are exempt from the double-submit token but still reject hostile browser `Origin` headers.

User isolation is enforced from the authenticated user context:

- Thread metadata is scoped by `threads_meta.user_id`; search/read/write/delete APIs only expose the current user's threads.
- Thread files live under `{base_dir}/users/{user_id}/threads/{thread_id}/user-data/` and are exposed inside the sandbox as `/mnt/user-data/`.
- Memory and custom agents are stored under `{base_dir}/users/{user_id}/...`.

Note: MCP outbound connections can still use OAuth for configured HTTP/SSE MCP servers; that is separate from DeerFlow API authentication.

---

## Rate Limiting

No rate limiting is implemented by default. For production deployments, configure rate limiting in Nginx:

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

location /api/ {
    limit_req zone=api burst=20 nodelay;
    proxy_pass http://backend;
}
```

---

## Streaming Support

Gateway's LangGraph-compatible API streams run events with Server-Sent Events (SSE).

**Thread-scoped streaming** (thread must exist):

```http
POST /api/langgraph/threads/{thread_id}/runs/stream
Accept: text/event-stream
```

**Stateless streaming** (no pre-created thread; Gateway auto-creates one):

```http
POST /api/langgraph/runs/stream
Accept: text/event-stream
```

Both endpoints return `Content-Location: /api/threads/{thread_id}/runs/{run_id}`.
The DeerFlow web UI and LangGraph SDK clients rely on this header to discover the
assigned `thread_id` and `run_id` on the first message of a new chat.

---

## SDK Usage

### Python (LangGraph SDK)

```python
from langgraph_sdk import get_client

client = get_client(url="http://localhost:2026/api/langgraph")
run_meta: dict[str, str] = {}


def on_run_created(meta) -> None:
    # langgraph-sdk 0.3.x parses Content-Location only when this callback is set.
    if meta.thread_id:
        run_meta["thread_id"] = meta.thread_id
    run_meta["run_id"] = meta.run_id


# Option A: stateless stream — no thread pre-creation
# Gateway auto-creates a thread and returns thread_id/run_id in Content-Location.
async for event in client.runs.stream(
    None,
    "lead_agent",
    input={"messages": [{"role": "user", "content": "Hello"}]},
    config={"configurable": {"model_name": "gpt-4"}},
    stream_mode=["values", "messages-tuple", "custom"],
    on_run_created=on_run_created,
):
    print(event)

thread_id = run_meta["thread_id"]  # persist before the next turn

# Option A (continued): same thread on the next turn
async for event in client.runs.stream(
    None,
    "lead_agent",
    input={"messages": [{"role": "user", "content": "What did I just ask?"}]},
    config={"configurable": {"thread_id": thread_id, "model_name": "gpt-4"}},
    stream_mode=["values", "messages-tuple", "custom"],
    on_run_created=on_run_created,
):
    print(event)

# Option B: thread-scoped stream — create thread first, then stream
thread = await client.threads.create()
async for event in client.runs.stream(
    thread["thread_id"],
    "lead_agent",
    input={"messages": [{"role": "user", "content": "Hello"}]},
    config={"configurable": {"model_name": "gpt-4"}},
    stream_mode=["values", "messages-tuple", "custom"],
    on_run_created=on_run_created,
):
    print(event)
```

### JavaScript/TypeScript

```typescript
// Using fetch for Gateway API
const response = await fetch('/api/models');
const data = await response.json();
console.log(data.models);

function parseRunLocation(contentLocation: string | null) {
  if (!contentLocation) return null;
  const match = /\/threads\/([^/]+)\/runs\/([^/]+)/.exec(contentLocation);
  if (!match) return null;
  return { threadId: match[1], runId: match[2] };
}

// Option A: stateless stream — no thread pre-creation
let threadId: string | undefined;
const firstResponse = await fetch("/api/langgraph/runs/stream", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  },
  body: JSON.stringify({
    input: { messages: [{ role: "user", content: "Hello" }] },
    stream_mode: ["values", "messages-tuple", "custom"],
  }),
});

const created = parseRunLocation(firstResponse.headers.get("Content-Location"));
threadId = created?.threadId;
console.log("thread_id:", created?.threadId, "run_id:", created?.runId);

// Option B: continue the same thread on the next turn
const followUpResponse = await fetch("/api/langgraph/runs/stream", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  },
  body: JSON.stringify({
    input: { messages: [{ role: "user", content: "What did I just ask?" }] },
    config: { configurable: { thread_id: threadId } },
    stream_mode: ["values", "messages-tuple", "custom"],
  }),
});

// Option C: thread-scoped stream when you already have a thread_id
const streamResponse = await fetch(`/api/langgraph/threads/${threadId}/runs/stream`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  },
  body: JSON.stringify({
    input: { messages: [{ role: "user", content: "Hello" }] },
    stream_mode: ["values", "messages-tuple", "custom"],
  }),
});

const reader = streamResponse.body?.getReader();
// Decode and parse SSE frames from reader in your client code.
```

### cURL Examples

```bash
# List models
curl http://localhost:2026/api/models

# Get MCP config
curl http://localhost:2026/api/mcp/config

# Upload file
curl -X POST http://localhost:2026/api/threads/abc123/uploads \
  -F "files=@document.pdf"

# Enable skill
curl -X POST http://localhost:2026/api/skills/pdf-processing/enable

# Stateless stream — no thread pre-creation
curl -s -D - -N -X POST http://localhost:2026/api/langgraph/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Hello"}]},
    "config": {
      "recursion_limit": 100,
      "configurable": {"model_name": "gpt-4"}
    },
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
# Read Content-Location: /api/threads/{thread_id}/runs/{run_id} from the headers.

# Continue the same thread on the next turn
curl -s -N -X POST http://localhost:2026/api/langgraph/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "What did I just ask?"}]},
    "config": {
      "configurable": {"thread_id": "abc123", "model_name": "gpt-4"}
    },
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'

# Thread-scoped flow — create thread first, then stream
curl -X POST http://localhost:2026/api/langgraph/threads \
  -H "Content-Type: application/json" \
  -d '{}'

curl -X POST http://localhost:2026/api/langgraph/threads/abc123/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Hello"}]},
    "config": {
      "recursion_limit": 100,
      "configurable": {"model_name": "gpt-4"}
    },
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```

> The unified Gateway path defaults `config.recursion_limit` to 100 for
> plan-mode and subagent-heavy runs. Clients may still set
> `config.recursion_limit` explicitly — see the [Create Run](#create-run)
> section for details.
