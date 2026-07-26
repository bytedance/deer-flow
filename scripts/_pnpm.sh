#!/usr/bin/env bash
#
# _pnpm.sh — Cross-platform pnpm command resolver with Corepack fallback
#
# Resolves a pnpm-compatible command using this precedence:
#  1. `pnpm` / `pnpm.cmd` if it exists on PATH
#  2. `corepack pnpm` if corepack is available
#  3. Nothing (caller should handle the error)
#
# Usage (from shell scripts):
#   source "$REPO_ROOT/scripts/_pnpm.sh"
#   PNPM_CMD=$(_get_pnpm_cmd)
#   if [ -z "$PNPM_CMD" ]; then
#       echo "pnpm not found" >&2
#       exit 1
#   fi
#   $PNPM_CMD install

_get_pnpm_cmd() {
    # Check for pnpm first
    if command -v pnpm >/dev/null 2>&1; then
        echo "pnpm"
        return 0
    fi

    # Check for pnpm.cmd (Windows)
    if command -v pnpm.cmd >/dev/null 2>&1; then
        echo "pnpm.cmd"
        return 0
    fi

    # Check for corepack
    if command -v corepack >/dev/null 2>&1; then
        echo "corepack pnpm"
        return 0
    fi

    # Check for corepack.cmd (Windows)
    if command -v corepack.cmd >/dev/null 2>&1; then
        echo "corepack.cmd pnpm"
        return 0
    fi

    # Not found
    return 1
}
