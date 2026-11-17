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

example_raw=$(awk '/^config_version:[[:space:]]+/ {sub(/^config_version:[[:space:]]+/, ""); print; exit}' "$EXAMPLE_YAML")
chart_raw=$(awk '
  /^config:[[:space:]]*\|/ { in_config=1; next }
  in_config && /^[[:space:]]+config_version:[[:space:]]+/ {
    sub(/^[[:space:]]+config_version:[[:space:]]+/, "")
    print
    exit
  }
' "$VALUES_YAML")

printf 'config.example.yaml config_version=%s\n' "$example_raw"
printf 'chart values.yaml     config_version=%s\n' "$chart_raw"

if [ -z "$example_raw" ] || [ -z "$chart_raw" ]; then
  echo "::error::could not parse config_version from one of the files" >&2
  exit 1
fi

version_pattern='^(0|[1-9][0-9]{0,17})([[:space:]]+#.*)?[[:space:]]*$'
if [[ ! "$example_raw" =~ $version_pattern || ! "$chart_raw" =~ $version_pattern ]]; then
  printf '::error::config_version must be a canonical decimal integer of at most 18 digits, without leading zeros (config.example.yaml: %s, values.yaml: %s)\n' "$example_raw" "$chart_raw" >&2
  exit 1
fi

example=$(printf '%s\n' "$example_raw" | awk '{print $1}')
chart=$(printf '%s\n' "$chart_raw" | awk '{print $1}')

if [ "$chart" -lt "$example" ]; then
  echo "::error::chart config_version ($chart) is behind config.example.yaml ($example). Bump 'config_version' in deploy/helm/deer-flow/values.yaml (and the README example) to $example." >&2
  exit 1
fi

echo "OK - chart config_version ($chart) is current with config.example.yaml ($example)."
