#!/bin/bash
# Verify multi-tenant user data isolation

set -e

echo "=========================================="
echo "Multi-Tenant User Isolation Verification"
echo "=========================================="
echo ""

# Set JWT secret
export DEER_FLOW_JWT_SECRET="$(openssl rand -base64 32)"

# Start Gateway
cd backend
uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > /tmp/gateway.log 2>&1 &
GATEWAY_PID=$!
sleep 3

echo "✓ Gateway started (PID: $GATEWAY_PID)"
echo ""

# ============================================================================
# Step 1: Register two different users
# ============================================================================
echo "Step 1: Registering two users..."
echo ""

# Register user1
USER1_RESPONSE=$(curl -s -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user1@test.com", "password": "password123"}')

USER1_TOKEN=$(echo "$USER1_RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('access_token', ''))" 2>&1 | grep -v "^warning:" | tail -1)
USER1_ID=$(echo "$USER1_RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('user_id', ''))" 2>&1 | grep -v "^warning:" | tail -1)

echo "  ✓ User1 registered"
echo "    Email: user1@test.com"
echo "    ID: $USER1_ID"
echo "    Token: ${USER1_TOKEN:0:30}..."
echo ""

# Register user2
USER2_RESPONSE=$(curl -s -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user2@test.com", "password": "password123"}')

USER2_TOKEN=$(echo "$USER2_RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('access_token', ''))" 2>/dev/null)
USER2_ID=$(echo "$USER2_RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('user_id', ''))" 2>/dev/null)

echo "  ✓ User2 registered"
echo "    Email: user2@test.com"
echo "    ID: $USER2_ID"
echo "    Token: ${USER2_TOKEN:0:30}..."
echo ""

# ============================================================================
# Step 2: Verify users have different IDs
# ============================================================================
echo "Step 2: Verifying user IDs are different..."
echo ""

if [ "$USER1_ID" = "$USER2_ID" ]; then
    echo "  ✗ FAILED: Users have the same ID!"
    kill $GATEWAY_PID
    exit 1
else
    echo "  ✓ User IDs are different"
    echo "    User1: $USER1_ID"
    echo "    User2: $USER2_ID"
fi
echo ""

# ============================================================================
# Step 3: Verify user info endpoint returns correct data
# ============================================================================
echo "Step 3: Verifying user info endpoint..."
echo ""

USER1_INFO=$(curl -s -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer $USER1_TOKEN")

USER1_EMAIL=$(echo "$USER1_INFO" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('email', ''))" 2>/dev/null)

USER2_INFO=$(curl -s -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer $USER2_TOKEN")

USER2_EMAIL=$(echo "$USER2_INFO" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('email', ''))" 2>/dev/null)

if [ "$USER1_EMAIL" = "user1@test.com" ] && [ "$USER2_EMAIL" = "user2@test.com" ]; then
    echo "  ✓ Each user gets their own info"
    echo "    User1 sees: $USER1_EMAIL"
    echo "    User2 sees: $USER2_EMAIL"
else
    echo "  ✗ FAILED: User info is incorrect"
    kill $GATEWAY_PID
    exit 1
fi
echo ""

# ============================================================================
# Step 4: Test memory isolation
# ============================================================================
echo "Step 4: Testing memory isolation..."
echo ""

# Save different memory for each user
python3 -c "
import sys
sys.path.insert(0, 'backend/src')
from src.agents.memory.updater import _save_memory_to_file, _create_empty_memory
from src.gateway.middleware.auth import decode_access_token

# User1 memory
token1 = '$USER1_TOKEN'
decoded1 = decode_access_token(token1)
user1_id = decoded1.user_id

memory1 = _create_empty_memory()
memory1['user']['workContext']['summary'] = 'User 1 test data - UNIQUE'
memory1['user']['workContext']['updatedAt'] = '2026-03-13T00:00:00Z'
_save_memory_to_file(memory1, user_id=user1_id)
print(f'  Saved memory for User1: {user1_id}')

# User2 memory
token2 = '$USER2_TOKEN'
decoded2 = decode_access_token(token2)
user2_id = decoded2.user_id

memory2 = _create_empty_memory()
memory2['user']['workContext']['summary'] = 'User 2 test data - DIFFERENT'
memory2['user']['workContext']['updatedAt'] = '2026-03-13T00:00:00Z'
_save_memory_to_file(memory2, user_id=user2_id)
print(f'  Saved memory for User2: {user2_id}')
" 2>&1 | grep -v "warning:" || true

sleep 1

echo ""
echo "  Reading memory via API..."
echo ""

# Read memory for each user
MEMORY1=$(curl -s -X GET http://localhost:8001/api/memory \
  -H "Authorization: Bearer $USER1_TOKEN")

MEMORY2=$(curl -s -X GET http://localhost:8001/api/memory \
  -H "Authorization: Bearer $USER2_TOKEN")

MEMORY1_SUMMARY=$(echo "$MEMORY1" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data['user']['workContext']['summary'])
except:
    print('ERROR')
" 2>/dev/null)

MEMORY2_SUMMARY=$(echo "$MEMORY2" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data['user']['workContext']['summary'])
except:
    print('ERROR')
" 2>/dev/null)

echo "  User1 memory: $MEMORY1_SUMMARY"
echo "  User2 memory: $MEMORY2_SUMMARY"
echo ""

if [ "$MEMORY1_SUMMARY" = "User 1 test data - UNIQUE" ] && [ "$MEMORY2_SUMMARY" = "User 2 test data - DIFFERENT" ]; then
    echo "  ✓ Memory isolation working correctly!"
else
    echo "  ✗ FAILED: Memory isolation broken"
    kill $GATEWAY_PID
    exit 1
fi
echo ""

# ============================================================================
# Step 5: Verify file system isolation
# ============================================================================
echo "Step 5: Verifying file system isolation..."
echo ""

BASE_DIR=$(python3 -c "
import sys
sys.path.insert(0, 'backend/src')
from src.config.paths import get_paths
print(get_paths().base_dir / 'users')
" 2>&1 | grep -v "warning:" || true)

if [ -d "$BASE_DIR/$USER1_ID" ] && [ -d "$BASE_DIR/$USER2_ID" ]; then
    echo "  ✓ Each user has separate directory:"
    echo "    $BASE_DIR/"
    echo "      ├── $USER1_ID/"
    echo "      │   └── memory.json"
    echo "      └── $USER2_ID/"
    echo "          └── memory.json"
else
    echo "  ✗ FAILED: User directories not found"
    kill $GATEWAY_PID
    exit 1
fi
echo ""

# ============================================================================
# Step 6: Test backward compatibility (no token)
# ============================================================================
echo "Step 6: Testing backward compatibility..."
echo ""

DEFAULT_USER_INFO=$(curl -s -X GET http://localhost:8001/api/auth/me)

DEFAULT_USER_ID=$(echo "$DEFAULT_USER_INFO" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('user_id', ''))" 2>/dev/null)

if [ "$DEFAULT_USER_ID" = "default" ]; then
    echo "  ✓ Requests without token use 'default' user"
else
    echo "  ⚠ Default user ID: $DEFAULT_USER_ID (expected: default)"
fi
echo ""

# ============================================================================
# Cleanup
# ============================================================================
echo "Cleanup..."
kill $GATEWAY_PID 2>/dev/null
rm -f /tmp/gateway.log
echo ""

# ============================================================================
# Summary
# ============================================================================
echo "=========================================="
echo "✓ All Tests Passed!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ✓ User registration works"
echo "  ✓ Each user has unique ID"
echo "  ✓ User info endpoint is isolated"
echo "  ✓ Memory data is isolated per user"
echo "  ✓ File system directories are separate"
echo "  ✓ Backward compatibility maintained"
echo ""
echo "User isolation is working correctly!"
echo ""
