import requests
import os
import json
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
    "Content-Type": "application/json"
}

def list_kbs():
    url = f"{BASE_URL}/api/v1/knowledge-bases"
    try:
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code != 200:
            print(f"Error listing KBs: {resp.status_code} {resp.text}")
            return []
        data = resp.json()
        if data.get("success"):
            return data.get("data", [])
        else:
            print(f"API Error: {data}")
            return []
    except Exception as e:
        print(f"Exception: {e}")
        return []

def list_files(kb_id):
    url = f"{BASE_URL}/api/v1/knowledge-bases/{kb_id}/knowledge"
    try:
        resp = requests.get(url, headers=HEADERS, params={"page": 1, "page_size": 100})
        if resp.status_code != 200:
            print(f"Error listing files: {resp.status_code} {resp.text}")
            return []
        data = resp.json()
        if data.get("success"):
            return data.get("data", [])
        else:
            print(f"API Error: {data}")
            return []
    except Exception as e:
        print(f"Exception: {e}")
        return []

def main():
    print(f"Checking WeKnora at: {BASE_URL}")
    kbs = list_kbs()
    print(f"Found {len(kbs)} Knowledge Bases:")
    
    for kb in kbs:
        kb_id = kb.get("id")
        kb_name = kb.get("name")
        print(f"\n--- KB: {kb_name} ({kb_id}) ---")
        
        files = list_files(kb_id)
        if not files:
            print("  (Empty)")
        else:
            print(f"  Files ({len(files)}):")
            for f in files:
                status = f.get('parse_status', 'unknown')
                error = f.get('error_message', '')
                print(f"  - {f.get('title')} (ID: {f.get('id')})")
                print(f"    Status: {status}")
                if error:
                    print(f"    Error: {error}")
                print(f"    Created: {f.get('created_at')}")

if __name__ == "__main__":
    main()
