#!/usr/bin/env bash
set -euo pipefail

ROOT="${FEATURES_TOOL_ROOT:-/opt/features-tool}"

if [ ! -d "$ROOT" ]; then
  echo "features-tool directory not found: $ROOT" >&2
  exit 1
fi

cd "$ROOT"
PYTHONPATH=. python3 tools/get_waveform_data_tool.py "$@"
