#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$REPO_ROOT/logs/frontend-wsl.pid"

pkill -f "langgraph dev" >/dev/null 2>&1 || true
pkill -f "uvicorn app.gateway.app:app" >/dev/null 2>&1 || true
pkill -f "next dev" >/dev/null 2>&1 || true
rm -f "$PID_FILE"

echo "Stopped DeerFlow local services."
