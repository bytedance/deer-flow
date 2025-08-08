#!/usr/bin/env python3
"""
Test script to verify port configuration changes work correctly.
"""

import os
import subprocess
import sys
import time
import requests
from pathlib import Path

def test_backend_port_config():
    """Test that backend respects BACKEND_PORT environment variable."""
    print("Testing backend port configuration...")
    
    # Test with custom port
    test_port = "8080"
    env = os.environ.copy()
    env["BACKEND_PORT"] = test_port
    
    # Test server.py help to see if it shows the correct default
    result = subprocess.run([
        sys.executable, "server.py", "--help"
    ], capture_output=True, text=True, env=env)
    
    if result.returncode == 0:
        # Remove line breaks and extra spaces for easier matching
        clean_output = " ".join(result.stdout.split())
        if "from BACKEND_PORT env var or" in clean_output:
            print("✅ Backend port configuration working correctly")
            return True
        else:
            print("❌ Backend port configuration not working")
            print(f"Expected to see 'from BACKEND_PORT env var or' in help output")
            print(f"Actual output: {result.stdout}")
            return False
    else:
        print(f"❌ Failed to run server.py --help: {result.stderr}")
        return False

def test_env_file_structure():
    """Test that .env.example has the correct structure."""
    print("Testing .env.example structure...")
    
    env_example_path = Path(".env.example")
    if not env_example_path.exists():
        print("❌ .env.example file not found")
        return False
    
    content = env_example_path.read_text()
    
    required_vars = [
        "BACKEND_PORT=8000",
        "FRONTEND_PORT=3000",
        "NEXT_PUBLIC_API_URL=\"http://localhost:${BACKEND_PORT}/api\"",
        "ALLOWED_ORIGINS=http://localhost:${FRONTEND_PORT}"
    ]
    
    for var in required_vars:
        if var not in content:
            print(f"❌ Missing or incorrect variable in .env.example: {var}")
            return False
    
    print("✅ .env.example structure is correct")
    return True

def test_docker_compose_structure():
    """Test that docker-compose.yml uses environment variables."""
    print("Testing docker-compose.yml structure...")
    
    compose_path = Path("docker-compose.yml")
    if not compose_path.exists():
        print("❌ docker-compose.yml file not found")
        return False
    
    content = compose_path.read_text()
    
    required_patterns = [
        "${BACKEND_PORT:-8000}:${BACKEND_PORT:-8000}",
        "${FRONTEND_PORT:-3000}:${FRONTEND_PORT:-3000}",
        "BACKEND_PORT=${BACKEND_PORT:-8000}",
        "FRONTEND_PORT=${FRONTEND_PORT:-3000}"
    ]
    
    for pattern in required_patterns:
        if pattern not in content:
            print(f"❌ Missing pattern in docker-compose.yml: {pattern}")
            return False
    
    print("✅ docker-compose.yml structure is correct")
    return True

def test_package_json_structure():
    """Test that web/package.json uses environment variables."""
    print("Testing web/package.json structure...")
    
    package_path = Path("web/package.json")
    if not package_path.exists():
        print("❌ web/package.json file not found")
        return False
    
    content = package_path.read_text()
    
    required_patterns = [
        "--port ${FRONTEND_PORT:-3000}",
        "localhost:${FRONTEND_PORT:-3000}"
    ]
    
    for pattern in required_patterns:
        if pattern not in content:
            print(f"❌ Missing pattern in web/package.json: {pattern}")
            return False
    
    print("✅ web/package.json structure is correct")
    return True

def main():
    """Run all tests."""
    print("🧪 Testing DeerFlow port configuration changes...\n")
    
    tests = [
        test_env_file_structure,
        test_docker_compose_structure,
        test_package_json_structure,
        test_backend_port_config,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            print()  # Add spacing between tests
        except Exception as e:
            print(f"❌ Test failed with exception: {e}\n")
    
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Port configuration is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please check the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())