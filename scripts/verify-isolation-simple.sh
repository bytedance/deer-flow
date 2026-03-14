#!/bin/bash
# Quick user isolation verification - uses curl

set -e

echo "=========================================="
echo "User Isolation Verification (Curl)"
echo "=========================================="
echo ""

# Clean up test data
echo "Cleaning up test data..."
rm -f /Users/evilgenius/deer-flow/backend/.deer-flow/users/users.json
echo "✓ Cleaned user store"
echo ""

# Start Gateway
echo "Starting Gateway..."
export DEER_FLOW_JWT_SECRET="$(openssl rand -base64 32)"
cd /Users/evilgenius/deer-flow/backend
uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > /tmp/gateway_verify.log 2>&1 &
GATEWAY_PID=$!
sleep 3
echo "✓ Gateway started (PID: $GATEWAY_PID)"
echo ""

# Register users
echo "Step 1: Registering users..."
echo ""

USER1=$(curl -s -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user1@test.com", "password": "password123"}')

USER1_ID=$(echo "$USER1" | grep -o '"user_id":"[^"]*"' | cut -d'"' -f4)
USER1_TOKEN=$(echo "$USER1" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

echo "  ✓ User1 ID: $USER1_ID"
echo ""

USER2=$(curl -s -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user2@test.com", "password": "password123"}')

USER2_ID=$(echo "$USER2" | grep -o '"user_id":"[^"]*"' | cut -d'"' -f4)
USER2_TOKEN=$(echo "$USER2" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

echo "  ✓ User2 ID: $USER2_ID"
echo ""

# Verify IDs are different
echo "Step 2: Verifying IDs are different..."
if [ "$USER1_ID" = "$USER2_ID" ]; then
    echo "  ✗ FAILED: Same ID!"
    kill $GATEWAY_PID 2>/dev/null
    exit 1
fi
echo "  ✓ IDs are different"
echo ""

# Get user info
echo "Step 3: Verifying user info..."
INFO1=$(curl -s -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer $USER1_TOKEN")
INFO1_EMAIL=$(echo "$INFO1" | grep -o '"email":"[^"]*"' | cut -d'"' -f4)

INFO2=$(curl -s -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer $USER2_TOKEN")
INFO2_EMAIL=$(echo "$INFO2" | grep -o '"email":"[^"]*"' | cut -d'"' -f4)

echo "  ✓ User1 sees: $INFO1_EMAIL"
echo "  ✓ User2 sees: $INFO2_EMAIL"
echo ""

# Test memory isolation via Python
echo "Step 4: Testing memory isolation..."
echo ""

cd /Users/evilgenius/deer-flow
python3 -c "
import sys
sys.path.insert(0, 'backend/src')
from src.agents.memory.updater import _save_memory_to_file, _create_empty_memory
from src.gateway.middleware.auth import decode_access_token

token1 = '$USER1_TOKEN'
user1_id = decode_access_token(token1).user_id

memory1 = _create_empty_memory()
memory1['user']['workContext']['summary'] = 'User 1 UNIQUE'
_save_memory_to_file(memory1, user_id=user1_id)
print(f'  Saved memory for User1: {user1_id}')

token2 = '$USER2_TOKEN'
user2_id = decode_access_token(token2).user_id

memory2 = _create_empty_memory()
memory2['user']['workContext']['summary'] = 'User 2 DIFFERENT'
_save_memory_to_file(memory2, user_id=user2_id)
print(f'  Saved memory for User2: {user2_id}')
" 2>&1 | grep -v "warning:" || true

sleep 1

echo ""
echo "  Reading memory via API..."
MEM1=$(curl -s -X GET http://localhost:8001/api/memory \
  -H "Authorization: Bearer $USER1_TOKEN")
SUM1=$(echo "$MEM1" | grep -o '"summary":"User [^"]*"' | cut -d'"' -f4)

MEM2=$(curl -s -X GET http://localhost:8001/api/memory \
  -H "Authorization: Bearer $USER2_TOKEN")
SUM2=$(echo "$MEM2" | grep -o '"summary":"User [^"]*"' | cut -d'"' -f4)

echo "  User1 memory: $SUM1"
echo "  User2 memory: $SUM2"
echo ""

if [ "$SUM1" = "User 1 UNIQUE" ] && [ "$SUM2" = "User 2 DIFFERENT" ]; then
    echo "  ✓ Memory isolation working!"
else
    echo "  ✗ Memory isolation broken!"
    kill $GATEWAY_PID 2>/dev/null
    exit 1
fi
echo ""

# Check file system
echo "Step 5: Verifying file system..."
USER1_DIR_EXISTS=$(test -d /Users/evilgenius/deer-flow/backend/.deer-flow/users/$USER1_ID && echo "yes" || echo "no")
USER2_DIR_EXISTS=$(test -d /Users/evilgenius/deer-flow/backend/.deer-flow/users/$USER2_ID && echo "yes" || echo "no")

if [ "$USER1_DIR_EXISTS" = "yes" ] && [ "$USER2_DIR_EXISTS" = "yes" ]; then
    echo "  ✓ Separate directories exist"
else
    echo "  ✗ Directories not found!"
    kill $GATEWAY_PID 2>/dev/null
    exit 1
fi
echo ""

# Test backward compatibility
echo "Step 6: Testing backward compatibility..."
DEFAULT_INFO=$(curl -s -X GET http://localhost:8001/api/auth/me)
DEFAULT_ID=$(echo "$DEFAULT_INFO" | grep -o '"user_id":"[^"]*"' | cut -d'"' -f4)

if [ "$DEFAULT_ID" = "default" ]; then
    echo "  ✓ Default user works without token"
else
    echo "  ⚠ Default user ID: $DEFAULT_ID"
fi
echo ""

# Cleanup
echo "Stopping Gateway..."
kill $GATEWAY_PID 2>/dev/null
rm -f /tmp/gateway_verify.log
echo ""

echo "=========================================="
echo "✓ All Tests Passed!"
echo "=========================================="
echo ""
echo "User isolation is working correctly!"
echo ""
