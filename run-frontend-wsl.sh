#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$REPO_ROOT/scripts/local-runtime-lib.sh"

cd "$REPO_ROOT/frontend"
clear_stale_frontend_lock "$PWD"
exec /usr/bin/node node_modules/next/dist/bin/next dev --turbo
