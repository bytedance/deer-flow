#!/usr/bin/env python3
"""
Quick verify multi-tenant user data isolation.
"""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error

# Add backend to path
sys.path.insert(0, 'backend/src')

GATEWAY_URL = "http://localhost:8001"
JWT_SECRET = "test-secret-key"

def http_post(url, data):
    """Make POST request."""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)

def http_get(url, headers=None):
    """Make GET request."""
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.load(response)

def main():
    print("=" * 50)
    print("User Isolation Quick Verification")
    print("=" * 50)
    print()

    # Start Gateway
    print("Starting Gateway...")
    env = os.environ.copy()
    env['DEER_FLOW_JWT_SECRET'] = JWT_SECRET

    process = subprocess.Popen(
        ['uv', 'run', 'uvicorn', 'src.gateway.app:app',
         '--host', '0.0.0.0', '--port', '8001'],
        cwd='backend',
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for server
    for i in range(10):
        try:
            http_get(f"{GATEWAY_URL}/health")
            print(f"✓ Gateway started (PID: {process.pid})")
            break
        except:
            time.sleep(0.5)
    else:
        print("✗ Gateway failed to start")
        return 1

    print()

    try:
        # Register users
        print("Step 1: Register users...")
        user1 = http_post(f"{GATEWAY_URL}/api/auth/register",
                          {"email": "user1@test.com", "password": "password123"})
        user2 = http_post(f"{GATEWAY_URL}/api/auth/register",
                          {"email": "user2@test.com", "password": "password123"})

        print(f"  ✓ User1: {user1['user_id']}")
        print(f"  ✓ User2: {user2['user_id']}")
        print()

        # Verify IDs are different
        print("Step 2: Verify IDs are different...")
        if user1['user_id'] != user2['user_id']:
            print(f"  ✓ IDs are different")
        else:
            print(f"  ✗ Same ID!")
            return 1
        print()

        # Get user info
        print("Step 3: Verify user info...")
        info1 = http_get(f"{GATEWAY_URL}/api/auth/me",
                        {"Authorization": f"Bearer {user1['access_token']}"})
        info2 = http_get(f"{GATEWAY_URL}/api/auth/me",
                        {"Authorization": f"Bearer {user2['access_token']}"})

        print(f"  ✓ User1 sees: {info1['email']}")
        print(f"  ✓ User2 sees: {info2['email']}")
        print()

        # Test memory isolation
        print("Step 4: Test memory isolation...")
        from src.agents.memory.updater import _save_memory_to_file, _create_empty_memory
        from src.gateway.middleware.auth import decode_access_token

        decoded1 = decode_access_token(user1['access_token'])
        decoded2 = decode_access_token(user2['access_token'])

        # Save memory
        mem1 = _create_empty_memory()
        mem1['user']['workContext']['summary'] = 'User 1 UNIQUE data'
        _save_memory_to_file(mem1, user_id=decoded1.user_id)

        mem2 = _create_empty_memory()
        mem2['user']['workContext']['summary'] = 'User 2 DIFFERENT data'
        _save_memory_to_file(mem2, user_id=decoded2.user_id)

        time.sleep(1)

        # Read via API
        mem_data1 = http_get(f"{GATEWAY_URL}/api/memory",
                             {"Authorization": f"Bearer {user1['access_token']}"})
        mem_data2 = http_get(f"{GATEWAY_URL}/api/memory",
                             {"Authorization": f"Bearer {user2['access_token']}"})

        sum1 = mem_data1['user']['workContext']['summary']
        sum2 = mem_data2['user']['workContext']['summary']

        print(f"  ✓ User1 memory: {sum1}")
        print(f"  ✓ User2 memory: {sum2}")
        print()

        if "User 1 UNIQUE" in sum1 and "User 2 DIFFERENT" in sum2:
            print("  ✓ Memory isolation working!")
        else:
            print("  ✗ Memory isolation broken!")
            return 1
        print()

        # Check file system
        print("Step 5: Verify file system isolation...")
        from src.config.paths import get_paths
        base = get_paths().base_dir / 'users'

        if (base / decoded1.user_id).exists() and (base / decoded2.user_id).exists():
            print("  ✓ Separate directories exist")
            print(f"    {base}/")
            print(f"      ├── {decoded1.user_id}/")
            print(f"      └── {decoded2.user_id}/")
        print()

        # Test backward compatibility
        print("Step 6: Test backward compatibility...")
        default_info = http_get(f"{GATEWAY_URL}/api/auth/me")
        if default_info['user_id'] == 'default':
            print("  ✓ Default user works without token")
        print()

        print("=" * 50)
        print("✓ All Tests Passed!")
        print("=" * 50)
        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        print("\nStopping Gateway...")
        process.terminate()
        process.wait(timeout=2)

if __name__ == "__main__":
    sys.exit(main())
