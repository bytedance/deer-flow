#!/usr/bin/env bash

set -euo pipefail

container_name="${1:-deer-flow-frontend}"
homepage_url="${2:-http://127.0.0.1:3000/}"
expected_entry_path="${3:-/workspace/chats/new}"

tmp_file="$(mktemp)"
cleanup() {
  rm -f "$tmp_file"
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required to run this check." >&2
  exit 2
fi

docker exec "$container_name" sh -lc "wget -Y off -qO- '$homepage_url'" >"$tmp_file"

root_workspace_link_count="$(
  { grep -o 'href=\"/workspace\"' "$tmp_file" || true; } |
    wc -l |
    tr -d '[:space:]'
)"

new_chat_link_count="$(
  { grep -o "href=\"${expected_entry_path}\"" "$tmp_file" || true; } |
    wc -l |
    tr -d '[:space:]'
)"

if [[ "$expected_entry_path" != "/workspace" && "$root_workspace_link_count" -gt 0 ]]; then
  echo "FAIL: homepage workspace entry still points to /workspace."
  echo "Route: $homepage_url"
  echo "Bare /workspace links: $root_workspace_link_count"
  exit 1
fi

if [[ "$new_chat_link_count" -eq 0 ]]; then
  echo "FAIL: homepage is missing the expected workspace entry link."
  echo "Route: $homepage_url"
  echo "Expected entry path: $expected_entry_path"
  exit 1
fi

echo "PASS: homepage workspace entry points to $expected_entry_path."
echo "Route: $homepage_url"
