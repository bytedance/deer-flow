#!/usr/bin/env bash
# Assert the Helm chart keeps the Gateway and provisioner on the same logical
# DeerFlow state root when the shared home PVC backs sandbox projection mounts.
#
# The Gateway sends provisioner extra_mount host paths rooted at
# DEER_FLOW_HOST_BASE_DIR. In USERDATA_PVC mode the provisioner validates those
# paths against its own DEER_FLOW_HOST_BASE_DIR, then converts the relative
# suffix to a deer-flow/<suffix> PVC subPath. The Gateway must mount that same
# PVC subtree at the logical state root. Drift in any leg of this contract can
# either reject valid mounts with HTTP 400 or resolve them to the wrong subtree.
#
# When persistence.home.enabled=false the provisioner does not receive the
# Gateway's home PVC, so this check intentionally leaves its state-root env
# unset rather than making pod-local Gateway paths look hostPath-compatible.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="$ROOT/deploy/helm/deer-flow"

if ! command -v helm >/dev/null 2>&1; then
  echo "::error::helm is required to run this check" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

render_component() {
  local template="$1"
  local output="$2"
  shift 2
  helm template deer-flow "$CHART" --include-crds --show-only "$template" "$@" >"$output"
}

if ! render_component templates/gateway-deployment.yaml "$TMP/gateway.yaml"; then
  echo "::error::gateway chart render failed" >&2
  exit 1
fi
if ! render_component templates/provisioner-deployment.yaml "$TMP/provisioner.yaml"; then
  echo "::error::provisioner chart render failed" >&2
  exit 1
fi
if ! render_component templates/provisioner-deployment.yaml "$TMP/provisioner-ephemeral.yaml"   --set persistence.home.enabled=false; then
  echo "::error::ephemeral provisioner chart render failed" >&2
  exit 1
fi

env_value() {
  grep -A1 -E "^[[:space:]]*- name: $1$" "$2" |
    grep -E "^[[:space:]]*value:" |
    head -1 |
    sed -E 's/^[[:space:]]*value:[[:space:]]*"?([^"]*)"?[[:space:]]*$/\1/'
}

has_env() { grep -qE "^[[:space:]]*- name: $1$" "$2"; }

has_gateway_home_mount_contract() {
  grep -A1 -E '^[[:space:]]*mountPath: /app/backend/\.deer-flow$' "$1" |
    grep -qE '^[[:space:]]*subPath: deer-flow$'
}

errors=0
check() {
  if [ "$1" -eq 0 ]; then
    echo "  PASS  $2"
  else
    echo "  FAIL  $2"
    errors=$((errors + 1))
  fi
}

gateway_root="$(env_value DEER_FLOW_HOST_BASE_DIR "$TMP/gateway.yaml")"
provisioner_root="$(env_value DEER_FLOW_HOST_BASE_DIR "$TMP/provisioner.yaml")"

echo "## Shared home PVC render"
[ -n "$gateway_root" ]; check $? "Gateway DEER_FLOW_HOST_BASE_DIR is present"
[ -n "$provisioner_root" ]; check $? "Provisioner DEER_FLOW_HOST_BASE_DIR is present"
[ "$gateway_root" = "$provisioner_root" ]; check $? "Gateway and provisioner state roots match"
[ "$gateway_root" = "/app/backend/.deer-flow" ]; check $? "Shared logical state root is /app/backend/.deer-flow"
has_env USERDATA_PVC_NAME "$TMP/provisioner.yaml"; check $? "Provisioner USERDATA_PVC_NAME is present"
has_gateway_home_mount_contract "$TMP/gateway.yaml"; check $? "Gateway home mount keeps subPath deer-flow at the shared logical root"

echo "## persistence.home.enabled=false render"
if has_env DEER_FLOW_HOST_BASE_DIR "$TMP/provisioner-ephemeral.yaml"; then
  check 1 "Provisioner state root stays unset without the shared home PVC"
else
  check 0 "Provisioner state root stays unset without the shared home PVC"
fi

echo
if [ "$errors" -eq 0 ]; then
  echo "All sandbox storage path-contract assertions passed."
  exit 0
fi

echo "::error::$errors assertion(s) failed (see above)" >&2
exit 1
