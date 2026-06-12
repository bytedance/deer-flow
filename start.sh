#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
case "$ACTION" in
  start|down)
    ;;
  *)
    echo "Usage: $0 {start|down}" >&2
    exit 1
    ;;
esac

cd "$(dirname "$0")"
exec scripts/deploy_x86.sh "$ACTION"
