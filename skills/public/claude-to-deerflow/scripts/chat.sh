#!/usr/bin/env bash
# chat.sh — Send a message to DeerFlow and collect the streaming response.
#
# Usage:
#   bash chat.sh "Your question here"
#   bash chat.sh "Your question" <thread_id>          # continue conversation
#   bash chat.sh "Your question" "" pro                # specify mode
#   DEERFLOW_URL=http://host:2026 bash chat.sh "hi"   # custom endpoint
#
# Environment variables:
#   DEERFLOW_URL          — Unified proxy base URL (default: http://localhost:2026)
#   DEERFLOW_GATEWAY_URL  — Gateway API base URL (default: $DEERFLOW_URL)
#   DEERFLOW_LANGGRAPH_URL — LangGraph API base URL (default: $DEERFLOW_URL/api/langgraph)
#
# Modes: flash, standard, pro (default), ultra

set -euo pipefail

DEERFLOW_URL="${DEERFLOW_URL:-http://localhost:2026}"
GATEWAY_URL="${DEERFLOW_GATEWAY_URL:-$DEERFLOW_URL}"
LANGGRAPH_URL="${DEERFLOW_LANGGRAPH_URL:-$DEERFLOW_URL/api/langgraph}"
MESSAGE="${1:?Usage: chat.sh <message> [thread_id] [mode]}"
THREAD_ID="${2:-}"
MODE="${3:-pro}"

# --- Health check ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "000" ] || [ "$HTTP_CODE" -ge 400 ]; then
  echo "ERROR: DeerFlow is not reachable at ${GATEWAY_URL} (HTTP ${HTTP_CODE})" >&2
  echo "Make sure DeerFlow is running. Start it with: cd <deerflow-dir> && make dev" >&2
  exit 1
fi

# --- Create or reuse thread ---
if [ -z "$THREAD_ID" ]; then
  THREAD_RESP=$(curl -s -X POST "${LANGGRAPH_URL}/threads" \
    -H "Content-Type: application/json" \
    -d '{}')
  THREAD_ID=$(echo "$THREAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['thread_id'])" 2>/dev/null)
  if [ -z "$THREAD_ID" ]; then
    echo "ERROR: Failed to create thread. Response: ${THREAD_RESP}" >&2
    exit 1
  fi
  echo "Thread: ${THREAD_ID}" >&2
fi

# --- Build context based on mode ---
case "$MODE" in
  flash)
    CONTEXT='{"thinking_enabled":false,"is_plan_mode":false,"subagent_enabled":false,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  standard)
    CONTEXT='{"thinking_enabled":true,"is_plan_mode":false,"subagent_enabled":false,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  pro)
    CONTEXT='{"thinking_enabled":true,"is_plan_mode":true,"subagent_enabled":false,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  ultra)
    CONTEXT='{"thinking_enabled":true,"is_plan_mode":true,"subagent_enabled":true,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  *)
    echo "ERROR: Unknown mode '${MODE}'. Use: flash, standard, pro, ultra" >&2
    exit 1
    ;;
esac

# --- Escape message for JSON ---
ESCAPED_MSG=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$MESSAGE")

# --- Build request body ---
BODY=$(cat <<ENDJSON
{
  "assistant_id": "lead_agent",
  "input": {
    "messages": [
      {
        "type": "human",
        "content": [{"type": "text", "text": ${ESCAPED_MSG}}]
      }
    ]
  },
  "stream_mode": ["values", "messages-tuple"],
  "stream_subgraphs": true,
  "config": {
    "recursion_limit": 1000
  },
  "context": ${CONTEXT}
}
ENDJSON
)

# --- Stream the run and extract final response ---
# We collect the full SSE output, then parse the last values event to get the AI response.
TMPFILE=$(mktemp)
trap "rm -f '$TMPFILE'" EXIT

curl -s -N -X POST "${LANGGRAPH_URL}/threads/${THREAD_ID}/runs/stream" \
  -H "Content-Type: application/json" \
  -d "$BODY" > "$TMPFILE"

# Parse the SSE output: extract the last "event: values" data block and get the final AI message
python3 - "$TMPFILE" "$GATEWAY_URL" "$THREAD_ID" << 'PYEOF'
import json
import sys

sse_file = sys.argv[1] if len(sys.argv) > 1 else None
gateway_url = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:2026"
thread_id = sys.argv[3] if len(sys.argv) > 3 else ""
if not sse_file:
    sys.exit(1)

with open(sse_file, "r") as f:
    raw = f.read()

# Parse SSE events
events = []
current_event = None
current_data_lines = []

for line in raw.split("\n"):
    if line.startswith("event:"):
        if current_event and current_data_lines:
            events.append((current_event, "\n".join(current_data_lines)))
        current_event = line[len("event:"):].strip()
        current_data_lines = []
    elif line.startswith("data:"):
        current_data_lines.append(line[len("data:"):].strip())
    elif line == "" and current_event:
        if current_data_lines:
            events.append((current_event, "\n".join(current_data_lines)))
        current_event = None
        current_data_lines = []

# Flush remaining
if current_event and current_data_lines:
    events.append((current_event, "\n".join(current_data_lines)))

import posixpath

def extract_response_text(messages):
    """Mirror manager.py _extract_response_text: handles ask_clarification interrupt + regular AI."""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        msg_type = msg.get("type")
        # ask_clarification interrupt: tool message with name ask_clarification
        if msg_type == "tool" and msg.get("name") == "ask_clarification":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content
        # Regular AI message
        if msg_type == "ai":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                text = "".join(parts)
                if text:
                    return text
    return ""

def extract_artifacts(messages):
    """Mirror manager.py _extract_artifacts: only artifacts from the last response cycle."""
    artifacts = []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "human":
            break
        if msg.get("type") == "ai":
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("name") == "present_files":
                    paths = tc.get("args", {}).get("filepaths", [])
                    if isinstance(paths, list):
                        artifacts.extend(p for p in paths if isinstance(p, str))
    return artifacts

def artifact_url(virtual_path):
    # virtual_path like /mnt/user-data/outputs/file.md
    # API endpoint: {gateway}/api/threads/{thread_id}/artifacts/{path without leading slash}
    path = virtual_path.lstrip("/")
    return f"{gateway_url}/api/threads/{thread_id}/artifacts/{path}"

def format_artifact_text(artifacts):
    urls = [artifact_url(p) for p in artifacts]
    if len(urls) == 1:
        return f"Created File: {urls[0]}"
    return "Created Files:\n" + "\n".join(urls)

# Find the last "values" event with messages
result_messages = None
for event_type, data_str in reversed(events):
    if event_type != "values":
        continue
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        continue
    if "messages" in data:
        result_messages = data["messages"]
        break

if result_messages is not None:
    response_text = extract_response_text(result_messages)
    artifacts = extract_artifacts(result_messages)
    if artifacts:
        artifact_text = format_artifact_text(artifacts)
        response_text = (response_text + "\n\n" + artifact_text) if response_text else artifact_text
    if response_text:
        print(response_text)
    else:
        print("(No response from agent)", file=sys.stderr)
        sys.exit(1)
else:
    # Check for error events
    for event_type, data_str in events:
        if event_type == "error":
            print(f"ERROR from DeerFlow: {data_str}", file=sys.stderr)
            sys.exit(1)
    print("No AI response found in the stream.", file=sys.stderr)
    if len(raw) < 2000:
        print(f"Raw SSE output:\n{raw}", file=sys.stderr)
    sys.exit(1)
PYEOF

echo ""
echo "---"
echo "Thread ID: ${THREAD_ID}" >&2
