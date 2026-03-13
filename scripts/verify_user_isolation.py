#!/usr/bin/env python3
"""
Simple user isolation verification.
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'backend/src'))

def main():
    print("=" * 50)
    print("用户隔离验证")
    print("=" * 50)
    print()

    # Clean up
    print("清理测试数据...")
    users_file = PROJECT_ROOT / "backend/.deer-flow/users/users.json"
    if users_file.exists():
        os.remove(users_file)
    print("✓ 已清理")
    print()

    # Start Gateway
    print("启动 Gateway...")
    env = os.environ.copy()
    env['DEER_FLOW_JWT_SECRET'] = "test-secret-key"

    process = subprocess.Popen(
        ['uv', 'run', 'uvicorn', 'src.gateway.app:app',
         '--host', '0.0.0.0', '--port', '8001'],
        cwd=str(PROJECT_ROOT / 'backend'),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for startup
    for i in range(10):
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:8001/health")
            urllib.request.urlopen(req, timeout=1)
            print("✓ Gateway 已启动")
            break
        except:
            time.sleep(0.5)
    else:
        print("✗ Gateway 启动失败")
        return 1

    print()

    try:
        # Register users
        print("1. 注册用户...")
        import urllib.request

        def register(email, password):
            data = json.dumps({"email": email, "password": password}).encode('utf-8')
            req = urllib.request.Request(
                "http://localhost:8001/api/auth/register",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)

        user1 = register("user1@test.com", "password123")
        user2 = register("user2@test.com", "password123")

        print(f"  ✓ 用户1: {user1['email']} (ID: {user1['user_id']})")
        print(f"  ✓ 用户2: {user2['email']} (ID: {user2['user_id']})")
        print()

        # Verify IDs
        print("2. 验证用户ID...")
        if user1['user_id'] != user2['user_id']:
            print(f"  ✓ 用户ID不同")
            print(f"    用户1: {user1['user_id']}")
            print(f"    用户2: {user2['user_id']}")
        else:
            print("  ✗ 用户ID相同!")
            return 1
        print()

        # Test memory isolation
        print("3. 测试内存隔离...")
        from src.agents.memory.updater import _save_memory_to_file, _create_empty_memory
        from src.gateway.middleware.auth import decode_access_token

        decoded1 = decode_access_token(user1['access_token'])
        decoded2 = decode_access_token(user2['access_token'])

        # Save memory
        mem1 = _create_empty_memory()
        mem1['user']['workContext']['summary'] = '用户1的数据'
        _save_memory_to_file(mem1, user_id=decoded1.user_id)
        print(f"  ✓ 保存用户1的memory")

        mem2 = _create_empty_memory()
        mem2['user']['workContext']['summary'] = '用户2的数据'
        _save_memory_to_file(mem2, user_id=decoded2.user_id)
        print(f"  ✓ 保存用户2的memory")
        print()

        time.sleep(1)

        # Read via API
        def get_memory(token):
            req = urllib.request.Request(
                "http://localhost:8001/api/memory",
                headers={'Authorization': f'Bearer {token}'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)

        mem_data1 = get_memory(user1['access_token'])
        mem_data2 = get_memory(user2['access_token'])

        sum1 = mem_data1['user']['workContext']['summary']
        sum2 = mem_data2['user']['workContext']['summary']

        print(f"  用户1的memory: {sum1}")
        print(f"  用户2的memory: {sum2}")

        if '用户1' in sum1 and '用户2' in sum2:
            print("  ✓ 内存隔离正常!")
        else:
            print("  ✗ 内存隔离失败!")
            return 1
        print()

        # Check file system
        print("4. 检查文件系统...")
        from pathlib import Path
        base = PROJECT_ROOT / 'backend/.deer-flow/users'

        if (base / decoded1.user_id).exists() and (base / decoded2.user_id).exists():
            print("  ✓ 文件系统隔离正常")
            print(f"    {base}/")
            print(f"      ├── {decoded1.user_id}/")
            print(f"      └── {decoded2.user_id}/")
        else:
            print("  ✗ 目录不存在!")
            return 1
        print()

        # Test backward compatibility
        print("5. 测试向后兼容性...")
        req = urllib.request.Request("http://localhost:8001/api/auth/me")
        with urllib.request.urlopen(req, timeout=5) as response:
            default_info = json.load(response)

        if default_info['user_id'] == 'default':
            print("  ✓ 默认用户正常工作")
        print()

        print("=" * 50)
        print("✓ 所有测试通过!")
        print("=" * 50)
        print()
        print("用户隔离功能正常工作!")

        return 0

    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        print("\n停止 Gateway...")
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()

if __name__ == "__main__":
    sys.exit(main())
