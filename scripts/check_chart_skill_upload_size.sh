#!/usr/bin/env bash
# Assert the rendered outer Ingress preserves the Gateway's .skill upload policy.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT

helm template deer-flow "$repo_root/deploy/helm/deer-flow" --include-crds >"$rendered"

if ! grep -Eq 'nginx\.ingress\.kubernetes\.io/proxy-body-size: "?101m"?[[:space:]]*$' "$rendered"; then
    echo "Rendered Ingress must allow 101m for 100 MiB .skill uploads plus multipart framing." >&2
    exit 1
fi

if ! grep -Eq 'nginx\.ingress\.kubernetes\.io/proxy-request-buffering: "?off"?[[:space:]]*$' "$rendered"; then
    echo "Rendered Ingress must stream .skill uploads without request buffering." >&2
    exit 1
fi

if ! grep -Eq 'nginx\.ingress\.kubernetes\.io/proxy-read-timeout: "?600"?[[:space:]]*$' "$rendered"; then
    echo "Rendered Ingress must allow 600 seconds for .skill upload validation." >&2
    exit 1
fi

echo "Chart skill-upload ingress policy check passed."
