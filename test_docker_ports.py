#!/usr/bin/env python3
"""
Test script to verify Docker port configuration works correctly.
"""

import subprocess
import time
import requests
import sys

def test_docker_backend():
    """Test that Docker backend runs on custom port."""
    print("🐳 Testing Docker backend with custom port...")
    
    try:
        # Start backend with docker compose
        print("Starting backend container...")
        result = subprocess.run([
            "docker", "compose", "up", "-d", "backend"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Failed to start backend: {result.stderr}")
            return False
        
        # Wait for container to start
        print("Waiting for container to start...")
        time.sleep(5)
        
        # Test API endpoint
        try:
            response = requests.get("http://localhost:8030/docs", timeout=10)
            if response.status_code == 200:
                print("✅ Backend API responding on port 8030")
                
                # Check logs for correct port
                logs_result = subprocess.run([
                    "docker", "logs", "deer-flow-backend"
                ], capture_output=True, text=True)
                
                if "0.0.0.0:8030" in logs_result.stdout:
                    print("✅ Backend started on correct port 8030")
                    return True
                else:
                    print("❌ Backend not running on expected port")
                    return False
            else:
                print(f"❌ API not responding: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to connect to API: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        return False
    finally:
        # Clean up
        print("Cleaning up...")
        subprocess.run(["docker", "compose", "down"], capture_output=True)

def main():
    """Run Docker port tests."""
    print("🧪 Testing DeerFlow Docker port configuration...\n")
    
    if test_docker_backend():
        print("\n🎉 Docker port configuration test passed!")
        return 0
    else:
        print("\n❌ Docker port configuration test failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())