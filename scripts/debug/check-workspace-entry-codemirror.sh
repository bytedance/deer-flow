#!/usr/bin/env bash

set -euo pipefail

container_name="${1:-deer-flow-frontend}"
workspace_url="${2:-http://127.0.0.1:3000/workspace/chats/new}"

tmp_file="$(mktemp)"
cleanup() {
  rm -f "$tmp_file"
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required to run this check." >&2
  exit 2
fi

docker exec "$container_name" sh -lc "wget -Y off -qO- '$workspace_url'" >"$tmp_file"

match_count="$(
  { grep -oiE 'codemirror' "$tmp_file" || true; } | wc -l | tr -d '[:space:]'
)"

if [[ "$match_count" -gt 0 ]]; then
  echo "FAIL: workspace initial HTML eagerly includes CodeMirror-related assets."
  echo "Route: $workspace_url"
  echo "Matches: $match_count"
  echo
  echo "Sample asset paths:"
  grep -oE '/_next[^"'"'"' ]*codemirror[^"'"'"' ]*' "$tmp_file" | sed -n '1,12p' || true
  exit 1
fi

echo "PASS: workspace initial HTML does not include CodeMirror-related assets."
echo "Route: $workspace_url"
