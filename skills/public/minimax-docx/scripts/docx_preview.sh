#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") <file.docx>"
  echo "Preview DOCX content as plain text."
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

INPUT="$1"

if [ ! -f "$INPUT" ]; then
  echo "Error: File not found: $INPUT"
  exit 1
fi

FILE_SIZE=$(du -h "$INPUT" | cut -f1)
echo "=== DOCX Preview: $(basename "$INPUT") ==="
echo "File size: $FILE_SIZE"

if command -v pandoc &>/dev/null; then
  CONTENT=$(pandoc -f docx -t plain "$INPUT" 2>/dev/null)
  WORD_COUNT=$(echo "$CONTENT" | wc -w | tr -d ' ')
  EST_PAGES=$(( (WORD_COUNT + 249) / 250 ))
  echo "Word count: $WORD_COUNT"
  echo "Estimated pages: $EST_PAGES"
  echo "---"
  echo "$CONTENT"
else
  echo "(pandoc not available, falling back to raw XML extract)"
  echo "---"
  unzip -p "$INPUT" word/document.xml 2>/dev/null | head -100
fi
