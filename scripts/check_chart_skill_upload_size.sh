#!/usr/bin/env bash
# Assert the rendered outer Ingress preserves the Gateway's .skill upload limit.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

helm template deer-flow "$repo_root/deploy/helm/deer-flow" --include-crds >"$rendered"

if ! grep -Eq 'nginx\.ingress\.kubernetes\.io/proxy-body-size: "?101m"?' "$rendered"; then
    echo "Rendered Ingress must allow 101m for 100 MiB .skill uploads plus multipart framing." >&2
    exit 1
fi

echo "Chart skill-upload ingress size check passed."
