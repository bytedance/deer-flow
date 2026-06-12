#!/bin/bash
# Package deer-flow directory excluding build artifacts, node_modules, docs, etc.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_NAME="deer-flow"
OUTPUT_FILE="${PROJECT_DIR}/${OUTPUT_NAME}.zip"

echo "Packaging deer-flow to ${OUTPUT_FILE}..."

cd "$PROJECT_DIR"

# Remove existing zip if present
[ -f "$OUTPUT_FILE" ] && rm "$OUTPUT_FILE"

# Create zip with exclusions
zip -r "$OUTPUT_FILE" . \
  -x ".venv" \
  -x "*.venv*" \
  -x "frontend/node_modules" \
  -x "frontend/node_modules/*" \
  -x "frontend/.next" \
  -x "frontend/.next/*" \
  -x "docs/*" \
  -x "docx/*" \
  -x "node_modules" \
  -x "node_modules/*" \
  -x ".DS_Store" \
  -x "*.DS_Store" \
  -x ".git" \
  -x ".git/*" \
  -x ".codegraph/*" \
  -x "logs/*" \
  -x "cookies.txt" \
  -x "*.zip" \
  -x "config.yaml" \
  -x "extensions_config.json" \
  -x "backend.zip"

echo "Done! Output: $OUTPUT_FILE"
ls -lh "$OUTPUT_FILE"
