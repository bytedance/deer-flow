#!/usr/bin/env bash
#
# start-daemon.sh — Start DeerFlow in daemon (background) mode
#
# Thin wrapper around serve.sh --daemon.
# Kept for backward compatibility.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$REPO_ROOT/scripts/serve.sh" --dev --daemon "$@"
