#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$REPO_ROOT/scripts/local-runtime-lib.sh"

assert_eq() {
  local actual="$1"
  local expected="$2"
  local message="$3"

  if [[ "$actual" != "$expected" ]]; then
    echo "assertion failed: $message" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    exit 1
  fi
}

test_health_sample_requires_all_200s_and_live_pid() {
  if is_healthy_runtime_sample "200" "200" "200" "0"; then
    echo "expected dead pid sample to be unhealthy" >&2
    exit 1
  fi

  if is_healthy_runtime_sample "200" "502" "200" "1"; then
    echo "expected route 502 sample to be unhealthy" >&2
    exit 1
  fi

  if ! is_healthy_runtime_sample "200" "200" "200" "1"; then
    echo "expected fully healthy sample to be healthy" >&2
    exit 1
  fi
}

test_next_stable_health_count_only_grows_on_fully_healthy_samples() {
  local count="0"

  count="$(next_stable_health_count "$count" "200" "502" "200" "1")"
  assert_eq "$count" "0" "unhealthy sample must reset the stable count"

  count="$(next_stable_health_count "$count" "200" "200" "200" "1")"
  assert_eq "$count" "1" "first healthy sample increments the counter"

  count="$(next_stable_health_count "$count" "200" "200" "200" "1")"
  assert_eq "$count" "2" "second consecutive healthy sample increments again"

  count="$(next_stable_health_count "$count" "200" "000" "200" "1")"
  assert_eq "$count" "0" "a later unhealthy sample must reset the counter"
}

test_clear_stale_frontend_lock_removes_lock_file_only_when_present() {
  local temp_dir
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' RETURN

  mkdir -p "$temp_dir/.next/dev"
  : > "$temp_dir/.next/dev/lock"

  clear_stale_frontend_lock "$temp_dir"

  if [[ -e "$temp_dir/.next/dev/lock" ]]; then
    echo "expected stale lock file to be removed" >&2
    exit 1
  fi

  clear_stale_frontend_lock "$temp_dir"
}

test_health_sample_requires_all_200s_and_live_pid
test_next_stable_health_count_only_grows_on_fully_healthy_samples
test_clear_stale_frontend_lock_removes_lock_file_only_when_present

echo "local-runtime-lib tests passed"
