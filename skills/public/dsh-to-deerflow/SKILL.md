---
name: dsh-to-deerflow
description: "Interact with DeerFlow AI agent platform via its HTTP API from a DeepSeek Harness (dsh) agent. Use this skill when a dsh headless task needs to delegate deep research or analysis to DeerFlow, start or continue a DeerFlow conversation thread, check DeerFlow status or health, or list DeerFlow models/skills/agents. Also use when the user mentions deerflow, deer flow, deepseek-harness, dsh, or wants a dsh-driven agent to run a deep research task that DeerFlow can handle."
---

# DeerFlow Skill (DeepSeek Harness host)

Communicate with a running DeerFlow instance via its HTTP API from inside a DeepSeek Harness (dsh)
agent. DeerFlow is an AI agent platform built on LangGraph that orchestrates sub-agents for
research, code execution, web browsing, and more. dsh (github.com/deepseek-ai/deepseek-harness)
is a plugin-based agent harness; its `bash` tool is the bridge to DeerFlow — everything here runs
as plain `curl` / helper-script shell commands.

## Architecture

DeerFlow exposes two API surfaces behind an Nginx reverse proxy:

| Service        | Direct Port | Via Proxy                        | Purpose                          |
|----------------|-------------|----------------------------------|----------------------------------|
| Gateway API    | 8001        | `$DEERFLOW_GATEWAY_URL`          | REST endpoints and embedded agent runtime |
| LangGraph-compatible API | 8001 | `$DEERFLOW_LANGGRAPH_URL`       | Agent threads, runs, streaming   |

## Environment Variables

All URLs are configurable via environment variables. **Read these env vars before making any request.**

| Variable                | Default                                  | Description                        |
|-------------------------|------------------------------------------|------------------------------------|
| `DEERFLOW_URL`          | `http://localhost:2026`                  | Unified proxy base URL             |
| `DEERFLOW_GATEWAY_URL`  | `${DEERFLOW_URL}`                        | Gateway API base (models, skills, memory, uploads) |
| `DEERFLOW_LANGGRAPH_URL`| `${DEERFLOW_URL}/api/langgraph`          | LangGraph API base (threads, runs) |

When making curl calls, always resolve the URL like this:

```bash
# Resolve base URLs from env (do this FIRST before any API call)
DEERFLOW_URL="${DEERFLOW_URL:-http://localhost:2026}"
DEERFLOW_GATEWAY_URL="${DEERFLOW_GATEWAY_URL:-$DEERFLOW_URL}"
DEERFLOW_LANGGRAPH_URL="${DEERFLOW_LANGGRAPH_URL:-$DEERFLOW_URL/api/langgraph}"
```

dsh note: the bash tool inherits the environment of the dsh process, so export
`DEERFLOW_URL` (and overrides) **before launching the dsh run** — exporting them inside a bash
tool call only affects that single call.

## dsh Workflow

### 1. Install this skill into the task workspace

dsh discovers project skills from the task working directory. Copy the skill there (and make sure
the workdir is a git repository — dsh resolves the project root by walking up to `.git`, so run
`git init` in a fresh workdir first):

```bash
cd <task-workdir>
git init -q 2>/dev/null || true
mkdir -p .agents/skills
cp -r <source-of-this-skill>/dsh-to-deerflow .agents/skills/
```

### 2. Check health first

```bash
bash .agents/skills/dsh-to-deerflow/scripts/status.sh health
```

If unreachable, DeerFlow is not running. Report that as a blocker with the start hint
(`cd <deerflow-dir> && make dev`, or `make docker-start` for the Docker setup) instead of
retrying in a loop.

### 3. Ask DeerFlow

```bash
bash .agents/skills/dsh-to-deerflow/scripts/chat.sh "Your question here"
```

The script prints the final AI response to stdout and `Thread: <thread_id>` to stderr.
The response may also end with `Created File: <url>` artifact links (DeerFlow-generated files) —
include both the text and the artifact URLs in the task result.

### 4. Handle long research runs

Deep research in pro/ultra mode can take minutes and may exceed a single bash tool call budget
(`timeoutMs`). Run the chat script in the background, then poll across tool calls:

```bash
nohup bash .agents/skills/dsh-to-deerflow/scripts/chat.sh "Research question" \
  > deerflow-out.txt 2> deerflow-err.txt &
```

- Poll with `read`/`cat` on `deerflow-out.txt`; the run is done when the file holds the final answer.
- The `Thread ID:` line appears in `deerflow-err.txt` and can be read even while the run continues.
- Alternatively pass a generous `timeoutMs` to the bash tool for one blocking call.

### 5. Continue a conversation

Reuse the `thread_id` from a previous run:

```bash
bash .agents/skills/dsh-to-deerflow/scripts/chat.sh "Follow-up question" "<thread_id>"
```

## Available Operations

### 1. Health Check

```bash
curl -s "$DEERFLOW_GATEWAY_URL/health"
```

### 2. Send a Message (Streaming)

This is the primary operation. It creates a thread and streams the agent's response.

**Step 1: Create a thread**

```bash
curl -s -X POST "$DEERFLOW_LANGGRAPH_URL/threads" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response: `{"thread_id": "<uuid>", ...}`

**Step 2: Stream a run**

```bash
curl -s -N -X POST "$DEERFLOW_LANGGRAPH_URL/threads/<thread_id>/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "lead_agent",
    "input": {
      "messages": [
        {
          "type": "human",
          "content": [{"type": "text", "text": "YOUR MESSAGE HERE"}]
        }
      ]
    },
    "stream_mode": ["values", "messages-tuple"],
    "stream_subgraphs": true,
    "config": {
      "recursion_limit": 1000
    },
    "context": {
      "thinking_enabled": true,
      "is_plan_mode": true,
      "subagent_enabled": true,
      "thread_id": "<thread_id>"
    }
  }'
```

The response is an SSE stream. Each event has the format
```
event: <event_type>
data: <json_data>
```

Key event types:
- `metadata` — run metadata including `run_id`
- `values` — full state snapshot with `messages` array
- `messages-tuple` — incremental message updates (AI text chunks, tool calls, tool results)
- `end` — stream is complete

**Context modes** (set via `context`):
- Flash mode: `thinking_enabled: false, is_plan_mode: false, subagent_enabled: false`
- Standard mode: `thinking_enabled: true, is_plan_mode: false, subagent_enabled: false`
- Pro mode: `thinking_enabled: true, is_plan_mode: true, subagent_enabled: false`
- Ultra mode: `thinking_enabled: true, is_plan_mode: true, subagent_enabled: true`

### 3. Continue a Conversation

Reuse the same `thread_id` from step 2 and POST another run with the new message.

### 4. List Models

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/models"
```

Returns: `{"models": [{"name": "...", "provider": "...", ...}, ...]}`

### 5. List Skills

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/skills"
```

Returns: `{"skills": [{"name": "...", "enabled": true, ...}, ...]}`

### 6. Enable/Disable a Skill

```bash
curl -s -X PUT "$DEERFLOW_GATEWAY_URL/api/skills/<skill_name>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### 7. List Agents

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/agents"
```

Returns: `{"agents": [{"name": "...", ...}, ...]}`

### 8. Get Memory

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/memory"
```

Returns user context, facts, and conversation history summaries.

### 9. Upload Files to a Thread

```bash
curl -s -X POST "$DEERFLOW_GATEWAY_URL/api/threads/<thread_id>/uploads" \
  -F "files=@/path/to/file.pdf"
```

Supports PDF, PPTX, XLSX, DOCX — automatically converts to Markdown.

### 10. List Uploaded Files

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/threads/<thread_id>/uploads/list"
```

### 11. Get Thread History

```bash
curl -s "$DEERFLOW_LANGGRAPH_URL/threads/<thread_id>/history"
```

### 12. List Threads

```bash
curl -s -X POST "$DEERFLOW_LANGGRAPH_URL/threads/search" \
  -H "Content-Type: application/json" \
  -d '{"limit": 20, "sort_by": "updated_at", "sort_order": "desc"}'
```

## Status Helper

`scripts/status.sh` wraps the read-only operations:

```bash
bash .agents/skills/dsh-to-deerflow/scripts/status.sh health|models|skills|agents|threads|memory|thread <id>
```

## Parsing SSE Output

The chat script already handles this. For manual curl streams, to extract the final AI response
from a `values` event:
- Look for the last `event: values` block
- Parse its `data` JSON
- The `messages` array contains all messages; the last one with `type: "ai"` is the response
- The `content` field of that message is the AI's text reply

## Error Handling

- If health check fails, DeerFlow is not running. Report the start hint (`make dev` or
  `make docker-start`) as the blocker and stop instead of retrying blindly.
- If the stream returns an error event, extract and surface the error message verbatim.
- Common issues: port not open, services still starting up, config errors.

## Tips

- For quick questions, use flash mode (fastest, no planning).
- For research tasks, use pro or ultra mode (enables planning and sub-agents).
- You can upload files first, then reference them in your message.
- Thread IDs persist — you can return to a conversation later.
- Prefer the helper scripts over hand-rolled curl: they resolve env vars, parse SSE,
  and extract artifacts consistently.
