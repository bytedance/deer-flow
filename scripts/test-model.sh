#!/bin/bash
# Test OpenRouter model via API

# Check API key
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "Error: OPENROUTER_API_KEY not set"
    echo "Set it with: export OPENROUTER_API_KEY='your-key'"
    exit 1
fi

# Start Gateway
cd backend
export DEER_FLOW_JWT_SECRET="$(openssl rand -base64 32)"
uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > /dev/null 2>&1 &
GATEWAY_PID=$!
sleep 3

echo "Testing OpenRouter model..."
echo ""

# Test with curl
curl -s http://localhost:8001/api/models | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Available models:')
for m in data['models']:
    flags = []
    if m.get('supports_thinking'):
        flags.append('thinking')
    if m.get('supports_vision'):
        flags.append('vision')
    flag_str = f' [{\", \".join(flags)}]' if flags else ''
    print(f\"  ✓ {m['display_name']}{flag_str}\")
"

# Cleanup
kill $GATEWAY_PID 2>/dev/null
