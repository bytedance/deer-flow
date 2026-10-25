#!/usr/bin/env bash
# Run the config-upgrade integration suite without inheriting a host uv mirror.
# This is an opt-in test command; normal uv and config-upgrade calls keep the
# operator's configured package indexes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# uv's extra indexes take precedence over the default index. Clear both the
# current and deprecated environment spellings before selecting public PyPI.
unset UV_INDEX UV_EXTRA_INDEX_URL UV_INDEX_URL
export UV_DEFAULT_INDEX=https://pypi.org/simple

cd "$REPO_ROOT/backend"
exec uv run --locked pytest -q tests/test_config_version.py "$@"
