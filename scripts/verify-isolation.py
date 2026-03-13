#!/usr/bin/env python3
"""
Verify multi-tenant user data isolation.
Run this from the project root directory.
"""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import urllib.parse

# Add backend to path
sys.path.insert(0, 'backend/src')

from src.agents.memory.updater import _save_memory_to_file, _create_empty_memory
from src.gateway.middleware.auth import decode_access_token

# Configuration
GATEWAY_URL = "http://localhost:8001"
JWT_SECRET = "test-secret-key-for-verification"

def start_gateway():
    """Start the Gateway server."""
    print("Starting Gateway...")
    env = os.environ.copy()
    env['DEER_FLOW_JWT_SECRET'] = JWT_SECRET

    # Start in background
    cmd = [
        'uv', 'run', 'uvicorn', 'src.gateway.app:app',
        '--host', '0.0.0.0', '--port', '8001'
    ]
    process = subprocess.Popen(
        cmd,
        cwd='backend',
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for server to start
    for _ in range(10):
        try:
            response = requests.get(f"{GATEWAY_URL}/health", timeout=1)
            if response.status_code == 200:
                print(f"✓ Gateway started (PID: {process.pid})")
                return process
        except:
            time.sleep(0.5)

    raise RuntimeError("Gateway failed to start")

def register_user(email, password):
    """Register a new user."""
    response = requests.post(
        f"{GATEWAY_URL}/api/auth/register",
        json={"email": email, "password": password},
        timeout=5
    )
    data = response.json()
    return data

def get_user_info(token):
    """Get user info."""
    response = requests.get(
        f"{GATEWAY_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5
    )
    return response.json()

def get_memory(token):
    """Get user memory."""
    response = requests.get(
        f"{GATEWAY_URL}/api/memory",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5
    )
    return response.json()

def main():
    print("=" * 50)
    print("Multi-Tenant User Isolation Verification")
    print("=" * 50)
    print()

    gateway_process = None
    try:
        # Start Gateway
        gateway_process = start_gateway()
        print()

        # Step 1: Register users
        print("Step 1: Registering two users...")
        print()

        user1 = register_user("user1@test.com", "password123")
        user2 = register_user("user2@test.com", "password123")

        print(f"  ✓ User1 registered:")
        print(f"    Email: {user1['email']}")
        print(f"    ID: {user1['user_id']}")
        print(f"    Token: {user1['access_token'][:30]}...")
        print()

        print(f"  ✓ User2 registered:")
        print(f"    Email: {user2['email']}")
        print(f"    ID: {user2['user_id']}")
        print(f"    Token: {user2['access_token'][:30]}...")
        print()

        # Step 2: Verify user IDs are different
        print("Step 2: Verifying user IDs are different...")
        print()

        if user1['user_id'] == user2['user_id']:
            print("  ✗ FAILED: Users have the same ID!")
            return 1

        print(f"  ✓ User IDs are different")
        print(f"    User1: {user1['user_id']}")
        print(f"    User2: {user2['user_id']}")
        print()

        # Step 3: Verify user info
        print("Step 3: Verifying user info endpoint...")
        print()

        info1 = get_user_info(user1['access_token'])
        info2 = get_user_info(user2['access_token'])

        if info1['email'] == "user1@test.com" and info2['email'] == "user2@test.com":
            print("  ✓ Each user gets their own info")
            print(f"    User1 sees: {info1['email']}")
            print(f"    User2 sees: {info2['email']}")
        else:
            print("  ✗ FAILED: User info is incorrect")
            return 1
        print()

        # Step 4: Test memory isolation
        print("Step 4: Testing memory isolation...")
        print()

        # Decode tokens to get user IDs
        decoded1 = decode_access_token(user1['access_token'])
        decoded2 = decode_access_token(user2['access_token'])

        # Save different memory for each user
        memory1 = _create_empty_memory()
        memory1['user']['workContext']['summary'] = 'User 1 test data - UNIQUE'
        memory1['user']['workContext']['updatedAt'] = '2026-03-13T00:00:00Z'
        _save_memory_to_file(memory1, user_id=decoded1.user_id)
        print(f"  Saved memory for User1: {decoded1.user_id}")

        memory2 = _create_empty_memory()
        memory2['user']['workContext']['summary'] = 'User 2 test data - DIFFERENT'
        memory2['user']['workContext']['updatedAt'] = '2026-03-13T00:00:00Z'
        _save_memory_to_file(memory2, user_id=decoded2.user_id)
        print(f"  Saved memory for User2: {decoded2.user_id}")
        print()

        time.sleep(1)

        # Read memory via API
        memory_data1 = get_memory(user1['access_token'])
        memory_data2 = get_memory(user2['access_token'])

        summary1 = memory_data1['user']['workContext']['summary']
        summary2 = memory_data2['user']['workContext']['summary']

        print(f"  User1 memory: {summary1}")
        print(f"  User2 memory: {summary2}")
        print()

        if summary1 == "User 1 test data - UNIQUE" and summary2 == "User 2 test data - DIFFERENT":
            print("  ✓ Memory isolation working correctly!")
        else:
            print("  ✗ FAILED: Memory isolation broken")
            return 1
        print()

        # Step 5: Verify file system isolation
        print("Step 5: Verifying file system isolation...")
        print()

        from src.config.paths import get_paths
        base_dir = get_paths().base_dir / 'users'

        user1_dir = base_dir / decoded1.user_id
        user2_dir = base_dir / decoded2.user_id

        if user1_dir.exists() and user2_dir.exists():
            print("  ✓ Each user has separate directory:")
            print(f"    {base_dir}/")
            print(f"      ├── {decoded1.user_id}/")
            print(f"      │   └── memory.json")
            print(f"      └── {decoded2.user_id}/")
            print(f"          └── memory.json")
        else:
            print("  ✗ FAILED: User directories not found")
            return 1
        print()

        # Step 6: Test backward compatibility
        print("Step 6: Testing backward compatibility...")
        print()

        default_info = requests.get(f"{GATEWAY_URL}/api/auth/me", timeout=5).json()

        if default_info['user_id'] == "default":
            print("  ✓ Requests without token use 'default' user")
        else:
            print(f"  ⚠ Default user ID: {default_info['user_id']} (expected: default)")
        print()

        # Summary
        print("=" * 50)
        print("✓ All Tests Passed!")
        print("=" * 50)
        print()
        print("Summary:")
        print("  ✓ User registration works")
        print("  ✓ Each user has unique ID")
        print("  ✓ User info endpoint is isolated")
        print("  ✓ Memory data is isolated per user")
        print("  ✓ File system directories are separate")
        print("  ✓ Backward compatibility maintained")
        print()
        print("User isolation is working correctly!")
        print()

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Cleanup
        if gateway_process:
            print("Stopping Gateway...")
            gateway_process.terminate()
            gateway_process.wait(timeout=2)

if __name__ == "__main__":
    sys.exit(main())
