#!/usr/bin/env bash
set -euo pipefail

is_healthy_runtime_sample() {
  local frontend_code="$1"
  local route_code="$2"
  local api_code="$3"
  local frontend_pid_alive="$4"

  [[ "$frontend_pid_alive" == "1" ]] &&
    [[ "$frontend_code" == "200" ]] &&
    [[ "$route_code" == "200" ]] &&
    [[ "$api_code" == "200" ]]
}

next_stable_health_count() {
  local current_count="$1"
  local frontend_code="$2"
  local route_code="$3"
  local api_code="$4"
  local frontend_pid_alive="$5"

  if is_healthy_runtime_sample "$frontend_code" "$route_code" "$api_code" "$frontend_pid_alive"; then
    echo $((current_count + 1))
    return 0
  fi

  echo "0"
}

clear_stale_frontend_lock() {
  local frontend_dir="$1"
  local lock_file="$frontend_dir/.next/dev/lock"

  if [[ -e "$lock_file" ]]; then
    rm -f "$lock_file"
  fi
}
