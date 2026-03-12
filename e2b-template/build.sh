#!/bin/bash
# Build the DeerFlow E2B sandbox template with pre-baked skills.
#
# Prerequisites:
#   1. Set E2B_ACCESS_TOKEN in your .env or export it
#   2. npm install -g @e2b/cli  (or use npx)
#
# Usage:
#   cd e2b-template && ./build.sh
#
# After building, add the template ID to config.yaml:
#   sandbox:
#     use: src.community.e2b_sandbox:E2bSandboxProvider
#     template: <template-id-from-output>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if available
if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | grep 'E2B_ACCESS_TOKEN' | xargs 2>/dev/null) || true
fi

if [ -z "${E2B_ACCESS_TOKEN:-}" ]; then
    echo "Error: E2B_ACCESS_TOKEN not set."
    echo "Get it from: https://e2b.dev/dashboard?tab=personal"
    echo "Then add to .env:  E2B_ACCESS_TOKEN=your_token"
    exit 1
fi

# Sync skills into build context
echo "Syncing skills to build context..."
rm -rf "$SCRIPT_DIR/skills"
cp -r "$PROJECT_ROOT/skills/public" "$SCRIPT_DIR/skills"

# Build template
echo "Building E2B template..."
cd "$SCRIPT_DIR"
e2b template build --name "deerflow-sandbox" --dockerfile e2b.Dockerfile

echo ""
echo "Done! Add the template ID to your config.yaml:"
echo "  sandbox:"
echo "    use: src.community.e2b_sandbox:E2bSandboxProvider"
echo "    template: <template-id>"
