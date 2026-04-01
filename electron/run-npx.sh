#!/bin/bash
#
# DeerFlow Desktop - NPX Runner (Alternative)
#
# Uses npx with local cache directory (no system-wide install)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="$SCRIPT_DIR/.cache"
mkdir -p "$CACHE_DIR"

# Set npm to use local cache
export NPM_CONFIG_CACHE="$CACHE_DIR/npm"
export NPM_CONFIG_PREFIX="$CACHE_DIR/npm-global"
mkdir -p "$NPM_CONFIG_CACHE"
mkdir -p "$NPM_CONFIG_PREFIX"

# Electron version - using stable v28
ELECTRON_VERSION="28.3.3"

echo "Using local npm cache: $CACHE_DIR"
echo ""

# Check if backend is running
echo "Checking DeerFlow backend..."
if curl -s http://localhost:2026/health >/dev/null 2>&1; then
    echo "✓ Backend is running"
else
    echo "⚠ Backend not detected at http://localhost:2026"
    echo "  Please start with: make docker-start"
    echo ""
fi

# Run Electron via npx (downloads to local cache on first run)
echo "Starting DeerFlow Desktop (Electron $ELECTRON_VERSION)..."
echo ""
cd "$SCRIPT_DIR"

# Use --yes to auto-install without prompt
exec npx --yes --cache "$NPM_CONFIG_CACHE" "electron@$ELECTRON_VERSION" . "$@"
