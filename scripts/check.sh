#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "  Checking Required Dependencies"
echo "=========================================="
echo ""

FAILED=0

echo "Checking Node.js..."
if command -v node >/dev/null 2>&1; then
    NODE_VERSION=$(node -v | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 22 ]; then
        echo "  ✓ Node.js $NODE_VERSION (>= 22 required)"
    else
        echo "  ✗ Node.js $NODE_VERSION found, but version 22+ is required"
        echo "    Install from: https://nodejs.org/"
        FAILED=1
    fi
else
    echo "  ✗ Node.js not found (version 22+ required)"
    echo "    Install from: https://nodejs.org/"
    FAILED=1
fi

echo ""
echo "Checking pnpm..."
# Source the canonical pnpm resolver (also used by serve.sh and the Makefile)
REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
_pnpm_sh="${REPO_ROOT}/scripts/_pnpm.sh"
# shellcheck source=../scripts/_pnpm.sh
if [ -f "$_pnpm_sh" ]; then source "$_pnpm_sh"; fi
PNPM_CMD=$(_get_pnpm_cmd 2>/dev/null) || PNPM_CMD=""

if [ -n "$PNPM_CMD" ]; then
    PNPM_VERSION=$($PNPM_CMD -v)
    if [ "$PNPM_CMD" = "pnpm" ] || [ "$PNPM_CMD" = "pnpm.cmd" ]; then
        echo "  ✓ pnpm $PNPM_VERSION"
    else
        echo "  ✓ pnpm $PNPM_VERSION (via Corepack)"
    fi
else
    echo "  ✗ pnpm not found"
    echo "    Install: npm install -g pnpm"
    echo "    Or enable Corepack: corepack enable"
    echo "    Or visit: https://pnpm.io/installation"
    FAILED=1
fi

echo ""
echo "Checking uv..."
if command -v uv >/dev/null 2>&1; then
    UV_VERSION=$(uv --version | awk '{print $2}')
    echo "  ✓ uv $UV_VERSION"
else
    echo "  ✗ uv not found"
    echo "    Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "    Or visit: https://docs.astral.sh/uv/getting-started/installation/"
    FAILED=1
fi

echo ""
echo "Checking nginx..."
if command -v nginx >/dev/null 2>&1; then
    NGINX_VERSION=$(nginx -v 2>&1 | awk -F'/' '{print $2}')
    echo "  ✓ nginx $NGINX_VERSION"
else
    echo "  ✗ nginx not found"
    echo "    macOS:   brew install nginx"
    echo "    Ubuntu:  sudo apt install nginx"
    echo "    Or visit: https://nginx.org/en/download.html"
    FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "=========================================="
    echo "  ✓ All dependencies are installed!"
    echo "=========================================="
    echo ""
    echo "You can now run:"
    echo "  make install  - Install project dependencies"
    echo "  make setup    - Create a minimal working config (recommended)"
    echo "  make config   - Copy the full config template (manual setup)"
    echo "  make doctor   - Verify config and dependency health"
    echo "  make dev      - Start development server"
    echo "  make start    - Start production server"
else
    echo "=========================================="
    echo "  ✗ Some dependencies are missing"
    echo "=========================================="
    echo ""
    echo "Please install the missing tools and run 'make check' again."
    exit 1
fi
