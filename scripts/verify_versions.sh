#!/usr/bin/env bash
# Verify that every project version source agrees.
#
# Sources checked:
#   deploy/helm/deer-flow/Chart.yaml   — version + appVersion
#   backend/pyproject.toml             — version
#   frontend/package.json              — version
#   backend/uv.lock                    — root package version, via `uv lock --check`
#
# Usage:
#   scripts/verify_versions.sh             # all sources must be mutually equal
#   scripts/verify_versions.sh 2.1.0       # all sources must equal 2.1.0
#
# Exit status is 0 when consistent, 1 otherwise. The release workflows
# (.github/workflows/chart.yaml and container.yaml) call this on v* tags — via
# the reusable .github/workflows/verify-versions.yml — to gate publishing when
# a version source was forgotten. Requires `uv` on PATH for the lock check.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CHART="$ROOT/deploy/helm/deer-flow/Chart.yaml"
PYPROJECT="$ROOT/backend/pyproject.toml"
PACKAGE="$ROOT/frontend/package.json"
UV_LOCK="$ROOT/backend/uv.lock"

for f in "$CHART" "$PYPROJECT" "$PACKAGE" "$UV_LOCK"; do
  if [ ! -f "$f" ]; then
    echo "::error::missing version file: $f" >&2
    exit 1
  fi
done

CHART_VERSION=$(awk '/^version:/ {print $2; exit}' "$CHART")
APP_VERSION=$(awk '/^appVersion:/ {gsub(/"/, ""); print $2; exit}' "$CHART")
PY_VERSION=$(awk -F'"' '/^version[[:space:]]*=/ {print $2; exit}' "$PYPROJECT")
JS_VERSION=$(grep -m1 '"version"' "$PACKAGE" | awk -F'"' '{print $4}')
PY_NAME=$(awk -F'"' '/^name[[:space:]]*=/ {print $2; exit}' "$PYPROJECT")
LOCK_VERSION=$(awk -v name="$PY_NAME" '
  /^\[\[package\]\]/ { root = 0 }
  $0 == "name = \"" name "\"" { root = 1 }
  root && /^version = / { gsub(/"/, "", $3); print $3; exit }
' "$UV_LOCK")
# Display only: `uv lock --check` below is what passes or fails the lock.
[ -n "$LOCK_VERSION" ] || LOCK_VERSION="(root entry not found; 'uv lock --check' is authoritative)"

printf 'Chart.yaml version:     %s\n' "$CHART_VERSION"
printf 'Chart.yaml appVersion:  %s\n' "$APP_VERSION"
printf 'backend/pyproject.toml: %s\n' "$PY_VERSION"
printf 'frontend/package.json:  %s\n' "$JS_VERSION"
printf 'backend/uv.lock:        %s\n' "$LOCK_VERSION"

# mismatch <name> <actual> <expected>: prints a GitHub Actions annotation and
# returns 1 when they differ, 0 when equal.
mismatch() {
  if [ "$2" != "$3" ]; then
    echo "::error::$1 is '$2' but expected '$3'." >&2
    return 1
  fi
  return 0
}

EXPECTED="${1:-}"
status=0

if [ -n "$EXPECTED" ]; then
  printf 'Expected:               %s (from tag v%s)\n\n' "$EXPECTED" "$EXPECTED"
  mismatch "Chart.yaml version"     "$CHART_VERSION" "$EXPECTED" || status=1
  mismatch "Chart.yaml appVersion"  "$APP_VERSION"   "$EXPECTED" || status=1
  mismatch "backend/pyproject.toml" "$PY_VERSION"    "$EXPECTED" || status=1
  mismatch "frontend/package.json"  "$JS_VERSION"    "$EXPECTED" || status=1
else
  echo
  mismatch "Chart.yaml appVersion"  "$APP_VERSION"  "$CHART_VERSION" || status=1
  mismatch "backend/pyproject.toml" "$PY_VERSION"   "$CHART_VERSION" || status=1
  mismatch "frontend/package.json"  "$JS_VERSION"   "$CHART_VERSION" || status=1
fi

# backend/uv.lock records the root package version in uv's PEP 440 form
# (2.1.0-rc0 is stored as 2.1.0rc0), so let uv judge whether it still matches
# pyproject.toml instead of re-implementing the normalization. A stale lock
# passes the checks above, then fails the backend image's `uv sync --locked`
# after the chart and the other images are already published.
if ! command -v uv >/dev/null 2>&1; then
  echo "::error::uv is required to check backend/uv.lock; install it from https://docs.astral.sh/uv/." >&2
  status=1
elif ! lock_output=$(cd "$ROOT/backend" && uv lock --check 2>&1); then
  printf '%s\n' "$lock_output" >&2
  echo "::error::'uv lock --check' failed on backend/uv.lock (output above); if the lock is stale, run scripts/bump_version.sh." >&2
  status=1
fi

if [ "$status" -ne 0 ]; then
  if [ -n "$EXPECTED" ]; then
    echo "Tip: run scripts/bump_version.sh $EXPECTED to align all sources." >&2
  else
    echo "Tip: run scripts/bump_version.sh <version> to align all sources." >&2
  fi
  exit 1
fi

echo "OK — all version sources agree on ${CHART_VERSION}."
