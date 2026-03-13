#!/bin/bash
# Verify OpenRouter models configuration and availability

set -e

echo "=========================================="
echo "OpenRouter Models Verification"
echo "=========================================="
echo ""

# Check if OPENROUTER_API_KEY is set
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "⚠️  OPENROUTER_API_KEY environment variable is not set"
    echo ""
    echo "Please set it with:"
    echo "  export OPENROUTER_API_KEY='your-key-here'"
    echo ""
    echo "Or add to .env file:"
    echo "  echo 'OPENROUTER_API_KEY=your-key-here' >> .env"
    exit 1
fi

echo "✓ OPENROUTER_API_KEY is set"
echo ""

# Check config.yaml
echo "Checking config.yaml..."
if grep -q "openrouter-claude-3.5-sonnet" config.yaml; then
    echo "✓ OpenRouter models found in config.yaml"
else
    echo "✗ OpenRouter models not found in config.yaml"
    exit 1
fi
echo ""

# Start Gateway and test
echo "Starting Gateway to verify models..."
cd backend
export DEER_FLOW_JWT_SECRET="$(openssl rand -base64 32)"
uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > /dev/null 2>&1 &
GATEWAY_PID=$!

# Wait for Gateway to start
sleep 3

# Test models endpoint
echo "Testing /api/models endpoint..."
MODELS_RESPONSE=$(curl -s http://localhost:8001/api/models)

if echo "$MODELS_RESPONSE" | grep -q "openrouter-claude-3.5-sonnet"; then
    echo "✓ OpenRouter models are available via API"
    echo ""
    echo "Available models:"
    echo "$MODELS_RESPONSE" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for m in data['models']:
    print(f\"  - {m['name']}: {m['display_name']}\")
"
else
    echo "✗ Failed to retrieve models from API"
fi

# Cleanup
kill $GATEWAY_PID 2>/dev/null

echo ""
echo "=========================================="
echo "Verification Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Start the full application: make dev"
echo "2. Open http://localhost:2026 in your browser"
echo "3. Click the model selector in the chat interface"
echo "4. You should see the OpenRouter models listed"
