#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="$ROOT/.clawdbot/active-tasks.json"
WORKTREE_ROOT="$ROOT/.clawdbot/worktrees"
SESSION_PREFIX="claw"
DEFAULT_BASE_BRANCH="$(python3 - <<'PY'
import json, pathlib
p = pathlib.Path('.clawdbot/swarm.config.json')
print(json.loads(p.read_text())['default_branch'])
PY
)"

TASK=""
AGENT=""
ROLE=""
BRANCH=""
PROMPT_FILE=""
MODEL=""
BASE_BRANCH="${DEFAULT_BASE_BRANCH}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --prompt-file) PROMPT_FILE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --base) BASE_BRANCH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$TASK" || -z "$AGENT" || -z "$ROLE" || -z "$BRANCH" || -z "$PROMPT_FILE" ]]; then
  echo "Usage: $0 --task <id> --agent <codex|claude> --role <role> --branch <branch> --prompt-file <file> [--model <model>] [--base <branch>]" >&2
  exit 1
fi

mkdir -p "$WORKTREE_ROOT"
SESSION="${SESSION_PREFIX}-${TASK}"
WORKTREE="$WORKTREE_ROOT/$TASK"
PROMPT_TMP="$ROOT/.clawdbot/.prompt-${TASK}.txt"

if [[ -e "$WORKTREE" ]]; then
  echo "Worktree already exists: $WORKTREE" >&2
  exit 1
fi

cd "$ROOT"

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "Branch already exists locally: $BRANCH" >&2
  exit 1
fi

git worktree add "$WORKTREE" -b "$BRANCH" "$BASE_BRANCH"

python3 - "$PROMPT_FILE" "$PROMPT_TMP" "$TASK" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
task = sys.argv[3]
text = src.read_text()
text = text.replace("{{TASK}}", task)
dst.write_text(text)
PY

PROMPT_ESCAPED="$(python3 - "$PROMPT_TMP" <<'PY'
import pathlib, shlex, sys
print(shlex.quote(pathlib.Path(sys.argv[1]).read_text()))
PY
)"

if [[ "$AGENT" == "codex" ]]; then
  CMD="codex"
  if [[ -n "$MODEL" ]]; then CMD="$CMD --model $(python3 -c 'import shlex,sys; print(shlex.quote(sys.argv[1]))' "$MODEL")"; fi
  CMD="$CMD $PROMPT_ESCAPED"
elif [[ "$AGENT" == "claude" ]]; then
  CMD="claude --print --permission-mode bypassPermissions"
  if [[ -n "$MODEL" ]]; then CMD="$CMD --model $(python3 -c 'import shlex,sys; print(shlex.quote(sys.argv[1]))' "$MODEL")"; fi
  CMD="$CMD -p $PROMPT_ESCAPED"
else
  echo "Unsupported agent: $AGENT" >&2
  exit 1
fi

tmux new-session -d -s "$SESSION" -c "$WORKTREE" "$CMD"

python3 - "$REGISTRY" "$TASK" "$SESSION" "$AGENT" "$ROLE" "$WORKTREE" "$BRANCH" <<'PY'
import json, pathlib, sys, time
p = pathlib.Path(sys.argv[1])
data = json.loads(p.read_text())
data.append({
  "id": sys.argv[2],
  "tmux_session": sys.argv[3],
  "agent": sys.argv[4],
  "role": sys.argv[5],
  "worktree": sys.argv[6],
  "branch": sys.argv[7],
  "status": "running",
  "started_at": int(time.time())
})
p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

echo "Started $AGENT agent"
echo "- task: $TASK"
echo "- session: $SESSION"
echo "- worktree: $WORKTREE"
echo "- branch: $BRANCH"
