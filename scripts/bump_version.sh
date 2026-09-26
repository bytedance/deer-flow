#!/usr/bin/env bash
# Bump the project version across every version source in lockstep.
#
# Usage:
#   scripts/bump_version.sh <version>     # e.g. scripts/bump_version.sh 2.2.0
#
# Updates:
#   backend/pyproject.toml              (version = "...")
#   backend/uv.lock                     (root package version, via `uv lock`)
#   frontend/package.json               ("version": "...")
#   deploy/helm/deer-flow/Chart.yaml    (version: + appVersion:)
#
# Requires `uv` on PATH: backend/uv.lock pins the root package version too, and
# lint CI runs `uv lock --check`, so the lock has to move with the sources.
#
# This does NOT edit CHANGELOG.md or create/push a git tag — keep those manual.
# After running, commit and tag v<version> to trigger the release workflows
# (container.yaml + chart.yaml), which gate on scripts/verify_versions.sh.

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <version>   (e.g. $0 2.2.0)" >&2
  exit 1
fi

VERSION="${1#v}"  # tolerate a leading "v" (tag form) if passed by mistake

if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([0-9A-Za-z.+-]+)?$'; then
  echo "error: '$VERSION' is not a valid SemVer (expected X.Y.Z[, -prerelease])" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYPROJECT="$ROOT/backend/pyproject.toml"
PACKAGE="$ROOT/frontend/package.json"
CHART="$ROOT/deploy/helm/deer-flow/Chart.yaml"

for f in "$PYPROJECT" "$PACKAGE" "$CHART"; do
  if [ ! -f "$f" ]; then
    echo "error: expected version file not found: $f" >&2
    exit 1
  fi
done

# backend/uv.lock records the root package's version as well (uv normalizes a
# prerelease, so `2.1.0-rc0` is stored as `2.1.0rc0`). Leaving it behind is not
# a cosmetic drift: `uv lock --check` in lint CI fails on the stale lock, and
# `uv sync --locked` refuses the tree — so the release step would produce a
# commit whose own CI is red. Refresh it here, and fail before editing anything
# when uv is missing rather than leaving a half-bumped tree behind.
if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' is required to refresh backend/uv.lock in lockstep; install it from https://docs.astral.sh/uv/ and re-run" >&2
  exit 1
fi

python3 - "$PYPROJECT" "$PACKAGE" "$CHART" "$VERSION" <<'PY'
import re
import sys

pyproject, package, chart, version = sys.argv[1:5]

# backend/pyproject.toml — version = "..."
with open(pyproject) as f:
    src = f.read()
new = re.sub(r'(?m)^version\s*=\s*".*?"', f'version = "{version}"', src, count=1)
if new == src:
    sys.exit(f"error: no top-level 'version' field in {pyproject}")
with open(pyproject, "w") as f:
    f.write(new)

# frontend/package.json — "version": "..." (preserve indentation; minimal diff)
with open(package) as f:
    src = f.read()
new = re.sub(
    r'(?m)^(\s*)"version"\s*:\s*".*?"',
    lambda m: f'{m.group(1)}"version": "{version}"',
    src,
    count=1,
)
if new == src:
    sys.exit(f'error: no top-level "version" field in {package}')
with open(package, "w") as f:
    f.write(new)

# deploy/helm/deer-flow/Chart.yaml — version: X.Y.Z and appVersion: "X.Y.Z"
with open(chart) as f:
    src = f.read()
new = re.sub(r'(?m)^version:\s*\S+', f'version: {version}', src, count=1)
new = re.sub(r'(?m)^appVersion:\s*".*?"', f'appVersion: "{version}"', new, count=1)
if new == src:
    sys.exit(f"error: could not find version/appVersion in {chart}")
with open(chart, "w") as f:
    f.write(new)
PY

if ! (cd "$ROOT/backend" && uv lock); then
  echo "error: 'uv lock' failed; backend/uv.lock still pins the previous version. Fix the resolution error and re-run, or revert the version edits above." >&2
  exit 1
fi

echo "Bumped version to $VERSION in:"
echo "  backend/pyproject.toml"
echo "  backend/uv.lock"
echo "  frontend/package.json"
echo "  deploy/helm/deer-flow/Chart.yaml (version + appVersion)"
echo

if ! bash "$ROOT/scripts/verify_versions.sh" "$VERSION"; then
  echo "error: post-bump verification failed." >&2
  exit 1
fi

echo
echo "Next steps:"
echo "  1. Update CHANGELOG.md"
echo "  2. git add -A && git commit -m \"release: v$VERSION\""
echo "  3. git tag v$VERSION && git push origin v$VERSION"
