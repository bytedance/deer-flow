#!/usr/bin/env bash
# status.sh — Check DeerFlow status and list available resources.
# Host-agnostic helper shared by the claude/zcode/dsh -to-deerflow skills.
# Keep in sync with the other *-to-deerflow copies when changing behavior.
#
# Usage:
#   bash status.sh                  # health + summary
#   bash status.sh models           # list models
#   bash status.sh skills           # list skills
#   bash status.sh agents           # list agents
#   bash status.sh threads          # list recent threads
#   bash status.sh memory           # show memory
#   bash status.sh thread <id>      # show thread history
#
# Environment variables:
#   DEERFLOW_URL           — Unified proxy base URL (default: http://localhost:2026)
#   DEERFLOW_GATEWAY_URL   — Gateway API base URL (default: $DEERFLOW_URL)
#   DEERFLOW_LANGGRAPH_URL — LangGraph API base URL (default: $DEERFLOW_URL/api/langgraph)

set -euo pipefail

DEERFLOW_URL="${DEERFLOW_URL:-http://localhost:2026}"
GATEWAY_URL="${DEERFLOW_GATEWAY_URL:-$DEERFLOW_URL}"
LANGGRAPH_URL="${DEERFLOW_LANGGRAPH_URL:-$DEERFLOW_URL/api/langgraph}"
GATEWAY_URL="${GATEWAY_URL%/}"
GATEWAY_URL="${GATEWAY_URL%/}"
LANGGRAPH_URL="${LANGGRAPH_URL%/}"
COOKIE_ARGS=()
if [ -n "${DEERFLOW_COOKIE:-}" ]; then
  COOKIE_ARGS=(-b "$DEERFLOW_COOKIE")
fi
CMD="${1:-health}"
ARG="${2:-}"

case "$CMD" in
  health)
    echo "Checking DeerFlow at ${GATEWAY_URL}..."
    HTTP_CODE=$(curl -s --connect-timeout 10 "${COOKIE_ARGS[@]}" -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/health" 2>/dev/null || true)
    HTTP_CODE="${HTTP_CODE:-000}"
    if [ "$HTTP_CODE" = "000" ]; then
      echo "UNREACHABLE — DeerFlow is not running at ${GATEWAY_URL}"
      exit 1
    elif [ "$HTTP_CODE" -ge 400 ]; then
      echo "ERROR — Health check returned HTTP ${HTTP_CODE}"
      exit 1
    else
      echo "OK — DeerFlow is running (HTTP ${HTTP_CODE})"
    fi
    ;;
  models)
    RESP=$(curl -s --connect-timeout 10 "${COOKIE_ARGS[@]}" "${GATEWAY_URL}/api/models" || true)
    printf '%s' "$RESP" | python3 -m json.tool 2>/dev/null || {
      echo "ERROR: non-JSON or failed response from ${GATEWAY_URL}/api/models:" >&2
      printf '%s' "$RESP" | head -c 200 >&2
      echo >&2
      exit 1
    }
    ;;
  skills)
    RESP=$(curl -s --connect-timeout 10 "${COOKIE_ARGS[@]}" "${GATEWAY_URL}/api/skills" || true)
    printf '%s' "$RESP" | python3 -m json.tool 2>/dev/null || {
      echo "ERROR: non-JSON or failed response from ${GATEWAY_URL}/api/skills:" >&2
      printf '%s' "$RESP" | head -c 200 >&2
      echo >&2
      exit 1
    }
    ;;
  agents)
    RESP=$(curl -s --connect-timeout 10 "${COOKIE_ARGS[@]}" "${GATEWAY_URL}/api/agents" || true)
    printf '%s' "$RESP" | python3 -m json.tool 2>/dev/null || {
      echo "ERROR: non-JSON or failed response from ${GATEWAY_URL}/api/agents:" >&2
      printf '%s' "$RESP" | head -c 200 >&2
      echo >&2
      exit 1
    }
    ;;
  threads)
    curl -s "${COOKIE_ARGS[@]}" -X POST "${LANGGRAPH_URL}/threads/search" \
      -H "Content-Type: application/json" \
      -d '{"limit": 20}' \
      | python3 -c "
import json, sys
threads = json.load(sys.stdin)
if not isinstance(threads, list):
    print(f'Unexpected response (not a thread list): {str(threads)[:200]}')
    sys.exit(1)
if not threads:
    print('No threads found.')
    sys.exit(0)
for t in threads:
    if not isinstance(t, dict):
        continue
    tid = t.get('thread_id', '?')
    updated = t.get('updated_at', '?')
    title = (t.get('values') or {}).get('title', '(untitled)')
    print(f'{tid}  {updated}  {title}')
"
    ;;
  memory)
    RESP=$(curl -s --connect-timeout 10 "${COOKIE_ARGS[@]}" "${GATEWAY_URL}/api/memory" || true)
    printf '%s' "$RESP" | python3 -m json.tool 2>/dev/null || {
      echo "ERROR: non-JSON or failed response from ${GATEWAY_URL}/api/memory:" >&2
      printf '%s' "$RESP" | head -c 200 >&2
      echo >&2
      exit 1
    }
    ;;
  thread)
    if [ -z "$ARG" ]; then
      echo "Usage: status.sh thread <thread_id>" >&2
      exit 1
    fi
    curl -s "${COOKIE_ARGS[@]}" -X POST "${LANGGRAPH_URL}/threads/${ARG}/history" \
      -H "Content-Type: application/json" \
      -d '{"limit": 10}' | python3 -c "
import json, sys
data = json.load(sys.stdin)
if isinstance(data, list):
    for state in data[:5]:
        values = state.get('values', {})
        msgs = values.get('messages', [])
        for m in msgs[-5:]:
            if not isinstance(m, dict):
                continue
            role = m.get('type', '?')
            content = m.get('content', '')
            if isinstance(content, list):
                content = ' '.join(p.get('text','') for p in content if isinstance(p, dict))
            preview = content[:200] if content else '(empty)'
            print(f'[{role}] {preview}')
        print('---')
else:
    print(json.dumps(data, indent=2))
"
    ;;
  *)
    echo "Unknown command: ${CMD}" >&2
    echo "Usage: status.sh [health|models|skills|agents|threads|memory|thread <id>]" >&2
    exit 1
    ;;
esac
