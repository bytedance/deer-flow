#!/bin/sh
set -eu

experiment=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo=$(CDPATH= cd -- "$experiment/../../.." && pwd -P)
: "${DSH_CHECKOUT:?Set DSH_CHECKOUT to the absolute path of a built DSH checkout}"
if [ -n "${PROBE_PYTHON:-}" ]; then
    python=$PROBE_PYTHON
else
    uv sync --project "$repo/backend" --frozen --no-install-workspace
    python=$(uv run --project "$repo/backend" --no-sync python -c 'import sys; print(sys.executable)')
fi
temp_home=$(mktemp -d "${TMPDIR:-/tmp}/dsh-gateway-home.XXXXXXXX")
trap 'rmdir "$temp_home" 2>/dev/null || true' EXIT
env -i PATH="$PATH" HOME="$temp_home" DSH_CHECKOUT="$DSH_CHECKOUT" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$experiment:$repo/backend:$repo/backend/packages/extension-api:$repo/backend/packages/harness:$repo/backend/tests" \
    "$python" -m pytest -p no:cacheprovider --tb=short -q "$experiment/test_gateway.py" "$@"
