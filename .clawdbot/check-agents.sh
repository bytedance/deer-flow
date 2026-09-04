#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="$ROOT/.clawdbot/active-tasks.json"

cd "$ROOT"

python3 - "$REGISTRY" <<'PY'
import json, pathlib, subprocess, sys
p = pathlib.Path(sys.argv[1])
if not p.exists():
    print("Registry missing")
    raise SystemExit(1)
items = json.loads(p.read_text())
if not items:
    print("No active tasks.")
    raise SystemExit(0)

print("Active tasks:")
for item in items:
    session = item.get("tmux_session")
    worktree = pathlib.Path(item.get("worktree", ""))
    branch = item.get("branch", "")

    tmux_ok = subprocess.run(["tmux", "has-session", "-t", session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    branch_ok = subprocess.run(["git", "show-ref", "--verify", f"refs/heads/{branch}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    worktree_ok = worktree.exists()

    print(f"- {item['id']}")
    print(f"  role: {item.get('role')}")
    print(f"  agent: {item.get('agent')}")
    print(f"  tmux: {'ok' if tmux_ok else 'missing'}")
    print(f"  worktree: {'ok' if worktree_ok else 'missing'}")
    print(f"  branch: {'ok' if branch_ok else 'missing'}")

remote = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
origin = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)
upstream = subprocess.run(["git", "remote", "get-url", "upstream"], capture_output=True, text=True)
print("\nGitHub integration:")
print(f"- any remote configured: {'yes' if bool(remote.stdout.strip()) else 'no'}")
print(f"- upstream configured: {'yes' if upstream.returncode == 0 else 'no'}")
print(f"- origin configured: {'yes' if origin.returncode == 0 else 'no'}")
print(f"- gh authenticated: {'yes' if auth.returncode == 0 else 'no'}")
PY
