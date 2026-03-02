import requests
import os
import mimetypes
from pathlib import Path

# Load environment variables
env_path = Path("/home/dingkd/deer-flow/.env")
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"\'')

API_KEY = os.environ.get("WEKNORA_API_KEY")
BASE_URL = os.environ.get("WEKNORA_BASE_URL", "http://127.0.0.1:39001")

if "weknora.localhost" in BASE_URL:
    BASE_URL = "http://127.0.0.1:39001"
BASE_URL = BASE_URL.rstrip("/")

HEADERS = {
    "X-API-Key": API_KEY,
    # Do NOT set Content-Type here, let requests set multipart/form-data boundary
}

TARGET_KB_NAME = "券商研报"
TEST_FILE = "/home/dingkd/Downloads/20260204_方正证券_金融工程专题_曹春晓_个人AI助理OpenClaw部署及其在金融投研中的应用研究——AI Agent赋能金融投研应用系列之二.pdf"

def get_kb_id(name):
    url = f"{BASE_URL}/api/v1/knowledge-bases"
    try:
        resp = requests.get(url, headers={"X-API-Key": API_KEY})
        data = resp.json()
        if data.get("success"):
            for kb in data.get("data", []):
                if kb.get("name") == name:
                    return kb.get("id")
    except Exception as e:
        print(f"Error getting KB ID: {e}")
    return None

def upload_file(kb_id, file_path):
    url = f"{BASE_URL}/api/v1/knowledge-bases/{kb_id}/knowledge/file"
    print(f"Uploading to: {url}")
    
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found at {file_path}")
        return False
        
    try:
        with open(path, "rb") as f:
            files = {
                "file": (path.name, f, "application/pdf")
            }
            data = {
                "enable_multimodel": "true"
            }
            
            resp = requests.post(url, headers=HEADERS, files=files, data=data)
            
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.text}")
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    print("Upload SUCCESS")
                    return True
                else:
                    print(f"Upload FAILED: {result.get('error')}")
            return False
    except Exception as e:
        print(f"Exception during upload: {e}")
        return False

def main():
    print(f"Target File: {TEST_FILE}")
    kb_id = get_kb_id(TARGET_KB_NAME)
    
    if not kb_id:
        print(f"Knowledge Base '{TARGET_KB_NAME}' not found.")
        return

    print(f"Found KB ID: {kb_id}")
    upload_file(kb_id, TEST_FILE)

if __name__ == "__main__":
    main()
