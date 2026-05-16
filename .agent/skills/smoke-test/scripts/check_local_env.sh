#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  Checking Local Development Environment"
echo "=========================================="
echo ""

all_passed=true

# Check Node.js
echo "1. Checking Node.js..."
if command -v node >/dev/null 2>&1; then
    NODE_VERSION=$(node --version | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 22 ]; then
        echo "✓ Node.js is installed (version: $NODE_VERSION)"
    else
        echo "✗ Node.js version is too old (current: $NODE_VERSION, required: 22+)"
        all_passed=false
    fi
else
    echo "✗ Node.js is not installed"
    all_passed=false
fi
echo ""

# Check pnpm
echo "2. Checking pnpm..."
if command -v pnpm >/dev/null 2>&1; then
    echo "✓ pnpm is installed (version: $(pnpm --version))"
else
    echo "✗ pnpm is not installed"
    echo "  Install command: npm install -g pnpm"
    all_passed=false
fi
echo ""

# Check uv
echo "3. Checking uv..."
if command -v uv >/dev/null 2>&1; then
    echo "✓ uv is installed (version: $(uv --version))"
else
    echo "✗ uv is not installed"
    all_passed=false
fi
echo ""

# Check nginx
echo "4. Checking nginx..."
if command -v nginx >/dev/null 2>&1; then
    echo "✓ nginx is installed (version: $(nginx -v 2>&1))"
else
    echo "✗ nginx is not installed"
    echo "  macOS: brew install nginx"
    echo "  Linux: install it with the system package manager"
    all_passed=false
fi
echo ""

# Check ports
echo "5. Checking ports..."
if ! command -v lsof >/dev/null 2>&1; then
    echo "✗ lsof is not installed, so port availability cannot be verified"
    echo "  Install lsof and rerun this check"
    all_passed=false
else
    for port in 2026 3000 8001 2024; do
        if lsof -i :$port >/dev/null 2>&1; then
            echo "⚠  Port $port is already in use:"
            lsof -i :$port | head -2
            all_passed=false
        else
            echo "✓ Port $port is available"
        fi
    done
fi
echo ""

# Summary
echo "=========================================="
echo "  Environment Check Summary"
echo "=========================================="
echo ""
if [ "$all_passed" = true ]; then
    echo "✅ All environment checks passed!"
    echo ""
    echo "Next step: run make install to install dependencies"
    exit 0
else
    echo "❌ Some checks failed. Please fix the issues above first"
    exit 1
fi
