#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

actual="$("$REPO_ROOT/scripts/gateway-reload-flags.sh")"

[[ "$actual" == *"--reload"* ]]
[[ "$actual" == *"--reload-include=*.yaml"* ]]
[[ "$actual" == *"--reload-include=.env"* ]]
[[ "$actual" == *"--reload-exclude=.deer-flow"* ]]
[[ "$actual" == *"--reload-exclude=.deer-flow/*"* ]]
[[ "$actual" == *"--reload-exclude=*/user-data/outputs/*"* ]]
