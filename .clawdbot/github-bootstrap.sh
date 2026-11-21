#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Remotes =="
git remote -v || true

echo
echo "== gh auth =="
if gh auth status >/dev/null 2>&1; then
  echo "gh authenticated: yes"
else
  echo "gh authenticated: no"
fi

echo
echo "Recommended next steps:"
echo "1) Login: gh auth login"
echo "2) Create or connect a fork as origin"
echo "   - If you want gh to fork automatically later, login first."
echo "   - Or add your own fork manually:"
echo "     git remote add origin <your-fork-url>"
echo "3) Verify push access: git remote -v && gh auth status"

echo
echo "Suggested remote layout for this repo:"
echo "- upstream = https://github.com/bytedance/deer-flow.git"
echo "- origin   = your fork"
