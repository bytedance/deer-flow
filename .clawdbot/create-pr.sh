#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TITLE="${1:-}"
BODY_FILE="${2:-}"

if [[ -z "$TITLE" ]]; then
  echo "Usage: $0 \"PR title\" [body-file]" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "origin remote is missing. Add your fork first:" >&2
  echo "  git remote add origin <your-fork-url>" >&2
  exit 1
fi

BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" ]]; then
  echo "Could not detect current branch" >&2
  exit 1
fi

if [[ "$BRANCH" == "master" || "$BRANCH" == "main" ]]; then
  echo "Refusing to create PR from default branch: $BRANCH" >&2
  exit 1
fi

echo "Pushing branch to origin: $BRANCH"
git push -u origin "$BRANCH"

if [[ -n "$BODY_FILE" ]]; then
  gh pr create --fill --title "$TITLE" --body-file "$BODY_FILE"
else
  gh pr create --fill --title "$TITLE"
fi
