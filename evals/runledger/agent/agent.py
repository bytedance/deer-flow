import json
import sys

def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("type") == "task_start":
            ticket = msg.get("input", {}).get("ticket", "")
            send({"type": "tool_call", "name": "search_docs", "call_id": "c1", "args": {"q": ticket}})
        elif msg.get("type") == "tool_result":
            send({"type": "final_output", "output": {"category": "account", "reply": "Reset password instructions sent."}})
            break

if __name__ == "__main__":
    main()
