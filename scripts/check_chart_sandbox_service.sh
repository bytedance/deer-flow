#!/usr/bin/env bash
# Assert the Helm chart emits the sandbox Service-type env correctly:
#   - default (sandboxServiceType unset -> ClusterIP):
#       SANDBOX_SERVICE_TYPE=ClusterIP, NODE_HOST absent
#   - provisioner.sandboxServiceType=NodePort:
#       SANDBOX_SERVICE_TYPE=NodePort, NODE_HOST present
#   - NodePort + provisioner.nodeHost=<ip>:
#       NODE_HOST takes the literal value (not the downward API)
#
# Locks in the gating added for #3929 so a future change - e.g. re-adding an
# unconditional NODE_HOST, or dropping the `default "ClusterIP"` fallback that
# keeps a stale values.yaml from sending an empty string the provisioner
# rejects - fails CI rather than silently regressing the sandbox exposure
# surface. The provisioner itself is mode-aware since #4016; this guards the
# chart wiring that selects the mode.
#
# Usage:
#   scripts/check_chart_sandbox_service.sh
#
# Called by .github/workflows/chart.yaml (validate-chart, on PRs + v* tags).
# Requires `helm` (ubuntu-latest ships helm 3 preinstalled).
#
# Exit status is 0 when all assertions pass, 1 otherwise.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART="$ROOT/deploy/helm/deer-flow"

if ! command -v helm >/dev/null 2>&1; then
  echo "::error::helm is required to run this check" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! helm template deer-flow "$CHART" --include-crds >"$TMP/default.yaml"; then
  echo "::error::default chart render failed" >&2
  exit 1
fi
if ! helm template deer-flow "$CHART" --include-crds \
  --set provisioner.sandboxServiceType=NodePort >"$TMP/nodeport.yaml"; then
  echo "::error::NodePort chart render failed" >&2
  exit 1
fi
if ! helm template deer-flow "$CHART" --include-crds \
  --set provisioner.sandboxServiceType=NodePort \
  --set provisioner.nodeHost=192.168.1.10 >"$TMP/nodeport-host.yaml"; then
  echo "::error::NodePort+nodeHost chart render failed" >&2
  exit 1
fi

# An env-var list item renders as `  - name: <NAME>`. Matching the item (not the
# comments that merely mention the name) is what makes the NODE_HOST-absent
# assertion meaningful.
has_env() { grep -qE "^[[:space:]]*- name: $1\$" "$2"; }
env_value() { grep -A1 -E "^[[:space:]]*- name: $1\$" "$2" | grep -oE 'value: "[^"]*"' | head -1; }

errors=0
check() {  # check <0|1> <desc>  (0 == pass)
  if [ "$1" -eq 0 ]; then
    echo "  PASS  $2"
  else
    echo "  FAIL  $2"
    errors=$((errors + 1))
  fi
}

echo "## Default render (provisioner.sandboxServiceType unset -> ClusterIP)"
has_env SANDBOX_SERVICE_TYPE "$TMP/default.yaml"; check $? "SANDBOX_SERVICE_TYPE env present"
[ "$(env_value SANDBOX_SERVICE_TYPE "$TMP/default.yaml")" = 'value: "ClusterIP"' ]; check $? "SANDBOX_SERVICE_TYPE == ClusterIP"
if has_env NODE_HOST "$TMP/default.yaml"; then check 1 "NODE_HOST env absent"; else check 0 "NODE_HOST env absent"; fi

echo "## NodePort opt-in (provisioner.sandboxServiceType=NodePort)"
has_env SANDBOX_SERVICE_TYPE "$TMP/nodeport.yaml"; check $? "SANDBOX_SERVICE_TYPE env present"
[ "$(env_value SANDBOX_SERVICE_TYPE "$TMP/nodeport.yaml")" = 'value: "NodePort"' ]; check $? "SANDBOX_SERVICE_TYPE == NodePort"
has_env NODE_HOST "$TMP/nodeport.yaml"; check $? "NODE_HOST env present"

echo "## NodePort + provisioner.nodeHost=192.168.1.10"
[ "$(env_value NODE_HOST "$TMP/nodeport-host.yaml")" = 'value: "192.168.1.10"' ]; check $? "NODE_HOST == 192.168.1.10 (literal, not downward API)"

echo
if [ "$errors" -eq 0 ]; then
  echo "All sandbox Service-type render assertions passed."
  exit 0
fi
echo "::error::$errors assertion(s) failed (see above)" >&2
exit 1
