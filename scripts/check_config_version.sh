#!/usr/bin/env bash
# Check the Helm chart's embedded config_version is not behind config.example.yaml.
#
# The chart's `config:` block in deploy/helm/deer-flow/values.yaml embeds a
# config_version that must not lag config.example.yaml. A stale version is
# silent in-cluster (the image ships no example to compare against, so
# _check_config_version never warns) but means the chart's config is authored
# against an older schema - so this fails the build, not a user's install.
# config_version gates no runtime behavior; it only drives the outdated-warning,
# so a bare version bump needs no field changes.
#
# Usage:
#   scripts/check_config_version.sh
#
# Called by .github/workflows/chart.yaml (validate-chart, on PRs + v* tags) and
# .github/workflows/nightly.yaml (validate-chart) so both stay in sync.
#
# Exit status is 0 when the chart is current, 1 otherwise.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EXAMPLE_YAML="$ROOT/config.example.yaml"
VALUES_YAML="$ROOT/deploy/helm/deer-flow/values.yaml"

for f in "$EXAMPLE_YAML" "$VALUES_YAML"; do
  if [ ! -f "$f" ]; then
    echo "::error::missing file: $f" >&2
    exit 1
  fi
done

example=$(grep -E '^config_version:[[:space:]]+[0-9]+' "$EXAMPLE_YAML" | head -1 | awk '{print $2}')
chart=$(awk '/^config:[[:space:]]*\|/{f=1; next} f && /^[[:space:]]+config_version:[[:space:]]+[0-9]+/ {print $2; exit}' "$VALUES_YAML")

printf 'config.example.yaml config_version=%s\n' "$example"
printf 'chart values.yaml     config_version=%s\n' "$chart"

if [ -z "$example" ] || [ -z "$chart" ]; then
  echo "::error::could not parse config_version from one of the files" >&2
  exit 1
fi

if [ "$chart" -lt "$example" ]; then
  echo "::error::chart config_version ($chart) is behind config.example.yaml ($example). Bump 'config_version' in deploy/helm/deer-flow/values.yaml (and the README example) to $example." >&2
  exit 1
fi

echo "OK - chart config_version ($chart) is current with config.example.yaml ($example)."
