#!/bin/bash
# OpenClaw to DeerFlow Chat Script
# Usage: bash chat.sh "Your message here"

set -e

MESSAGE="$1"

if [ -z "$MESSAGE" ]; then
    echo "Usage: bash chat.sh \"Your message here\""
    exit 1
fi

# Resolve base URLs from env
DEERFLOW_URL="${DEERFLOW_URL:-http://localhost:2026}"
DEERFLOW_GATEWAY_URL="${DEERFLOW_GATEWAY_URL:-$DEERFLOW_URL}"
DEERFLOW_LANGGRAPH_URL="${DEERFLOW_LANGGRAPH_URL:-$DEERFLOW_URL/api/langgraph}"

echo "=== Checking DeerFlow health ==="
HEALTH=$(curl -s "$DEERFLOW_GATEWAY_URL/health")
if [ $? -ne 0 ]; then
    echo "Error: DeerFlow is not running at $DEERFLOW_GATEWAY_URL"
    echo "Please start DeerFlow first (e.g., make dev or make docker-start)"
    exit 1
fi
echo "DeerFlow is healthy: $HEALTH"

echo ""
echo "=== Creating new thread ==="
THREAD_RESPONSE=$(curl -s -X POST "$DEERFLOW_LANGGRAPH_URL/threads" \
    -H "Content-Type: application/json" \
    -d '{}')

THREAD_ID=$(echo "$THREAD_RESPONSE" | grep -o '"thread_id":"[^"]*"' | cut -d'"' -f4)
echo "Created thread: $THREAD_ID"

echo ""
echo "=== Sending message ==="
echo "Message: $MESSAGE"
echo ""

# Stream the response
curl -s -N -X POST "$DEERFLOW_LANGGRAPH_URL/threads/$THREAD_ID/runs/stream" \
    -H "Content-Type: application/json" \
    -d "{
        \"assistant_id\": \"lead_agent\",
        \"input\": {
            \"messages\": [
                {
                    \"type\": \"human\",
                    \"content\": [{\"type\": \"text\", \"text\": \"$MESSAGE\"}]
                }
            ]
        },
        \"stream_mode\": [\"values\", \"messages-tuple\"],
        \"stream_subgraphs\": true,
        \"config\": {
            \"recursion_limit\": 1000
        },
        \"context\": {
            \"thinking_enabled\": true,
            \"is_plan_mode\": true,
            \"subagent_enabled\": true,
            \"thread_id\": \"$THREAD_ID\"
        }
    }" | while read -r line; do
    # Parse SSE events and extract message content
    if [[ "$line" == data:* ]]; then
        data="${line#data: }"
        # Extract message content from the JSON
        echo "$data" | grep -o '"content":"[^"]*"' | head -1 || true
    fi
done

echo ""
echo ""
echo "=== Done ==="
echo "Thread ID: $THREAD_ID"
echo "You can continue the conversation by calling this script again with the same THREAD_ID"
