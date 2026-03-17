#!/usr/bin/env python3
"""Clean up corrupted threads with invalid JSON data."""
 
import json
import sys
from pathlib import Path
 
sys.path.insert(0, str(Path(__file__).parent.parent))
 
from langchain.langgraph_sdk import Client
 
 
def cleanup_corrupted_threads():
    """Find and delete threads with corrupted values"""
    client = Client(api_url="http://localhost:2024")
    
    print("Fetching threads...")
    threads = client.threads.search(limit=100)
    
    corrupted_threads = []
    
    for thread in threads:
        if not thread.values:
            continue
            
        try:
            json.dumps(thread.values)
        except (TypeError, ValueError) as e:
            print(f"Found corrupted thread: {thread.thread_id}")
            print(f"Error: {e}")
            corrupted_threads.append(thread.thread_id)
    
    if not corrupted_threads:
        print("No corrupted threads found!")
        return
    
    print(f"\nFound {len(corrupted_threads)} corrupted threads:")
    for thread_id in corrupted_threads:
        print(f"  - {thread_id}")
    
    response = input(f"\nDelete these {len(corrupted_threads)} threads? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled.")
        return
    
    for thread_id in corrupted_threads:
        try:
            client.threads.delete(thread_id)
            print(f"Deleted thread: {thread_id}")
        except Exception as e:
            print(f"Error deleting thread {thread_id}: {e}")
    
    print(f"\nCleanup complete. Deleted {len(corrupted_threads)} corrupted threads.")
 
 
if __name__ == "__main__":
    cleanup_corrupted_threads()