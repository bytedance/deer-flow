#!/usr/bin/env bash
#
# clean_runtime_data.sh - Delete local runtime data for `make clean`
#
# `make clean` runs this through RUN_SHELL_SCRIPT because Makefile recipes
# execute under cmd.exe on Windows (`SHELL := cmd.exe`), where a bare
# `rm -rf backend/.deer-flow 2>/dev/null || true` line is a silent no-op:
# cmd has no `rm`, `2>/dev/null` is not cmd redirection, and the recipe's
# `-` prefix swallows the failure while "✓ Cleanup complete" still prints.
# The deleted tree holds the local database, users, threads, uploads, memory,
# and secrets; logs/*.log are the service logs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

rm -rf "${REPO_ROOT}/backend/.deer-flow"
# -r keeps the old recipe's scope: a stray directory named like a log is
# removed too instead of aborting the script under set -e.
rm -rf "${REPO_ROOT}"/logs/*.log
