---
name: zcode-to-deerflow
description: "Interact with DeerFlow AI agent platform via its HTTP API from a ZCode session. Use this skill when the user wants to send messages or questions to DeerFlow for research/analysis, start a DeerFlow conversation thread, check DeerFlow status or health, list available models/skills/agents in DeerFlow, manage DeerFlow memory, upload files to DeerFlow threads, or delegate complex research tasks to DeerFlow while working in ZCode. Also use when the user mentions deerflow, deer flow, or wants to run a deep research task that DeerFlow can handle."
---

# DeerFlow Skill (ZCode host)

Communicate with a running DeerFlow instance via its HTTP API from inside a ZCode session.
DeerFlow is an AI agent platform built on LangGraph that orchestrates sub-agents for research,
code execution, web browsing, and more. ZCode is a terminal coding agent: drive DeerFlow through
its Bash tool with `curl` or with the helper scripts shipped in this skill.

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

## ZCode Workflow

### 1. Locate this skill

The skill is discovered from the standard skill locations. Resolve the scripts path to whichever
copy exists first:

```bash
SKILL_DIR=""
for d in ".agents/skills/zcode-to-deerflow" "$HOME/.agents/skills/zcode-to-deerflow"; do
  [ -f "$d/scripts/chat.sh" ] && SKILL_DIR="$d" && break
done
```

### 2. Check health first

```bash
bash "$SKILL_DIR/scripts/status.sh" health
```

If unreachable, tell the user DeerFlow is not running and suggest starting it
(`cd <deerflow-dir> && make dev`, or `make docker-start` for the Docker setup).

### 3. Ask DeerFlow

```bash
bash "$SKILL_DIR/scripts/chat.sh" "Your question here"
```

The script prints the final AI response to stdout and `Thread: <thread_id>` to stderr.
The response may also end with `Created File: <url>` artifact links (DeerFlow-generated files) —
relay both the text and the artifact URLs to the user.

### 4. Handle long research runs

Deep research in pro/ultra mode can take minutes. Run the chat script in the background and poll,
instead of blocking the session:

```bash
nohup bash "$SKILL_DIR/scripts/chat.sh" "Research question" \
  > ~/tmp/deerflow-out.txt 2> ~/tmp/deerflow-err.txt &
# poll: cat ~/tmp/deerflow-out.txt ; the run is done when the file holds the final answer
```

### 5. Continue a conversation

Reuse the `thread_id` printed by a previous run:

```bash
bash "$SKILL_DIR/scripts/chat.sh" "Follow-up question" "<thread_id>"
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
bash "$SKILL_DIR/scripts/status.sh" health|models|skills|agents|threads|memory|thread <id>
```

## Parsing SSE Output

The chat script already handles this. For manual curl streams, to extract the final AI response
from a `values` event:
- Look for the last `event: values` block
- Parse its `data` JSON
- The `messages` array contains all messages; the last one with `type: "ai"` is the response
- The `content` field of that message is the AI's text reply

## Error Handling

- If health check fails, DeerFlow is not running. Tell the user to start it (`make dev` or
  `make docker-start`) and stop instead of retrying blindly.
- If the stream returns an error event, extract and surface the error message verbatim.
- Common issues: port not open, services still starting up, config errors.

## Tips

- For quick questions, use flash mode (fastest, no planning).
- For research tasks, use pro or ultra mode (enables planning and sub-agents).
- You can upload files first, then reference them in your message.
- Thread IDs persist — you can return to a conversation later.
- Prefer the helper scripts over hand-rolled curl: they resolve env vars, parse SSE,
  and extract artifacts consistently.
