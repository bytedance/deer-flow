#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_REPO="$REPO_ROOT"
OUTPUT_DIR="${TMPDIR:-/tmp}/deerflow-kernel"
FORCE=0

usage() {
    cat <<'EOF'
Usage: export-deerflow-kernel.sh [options]

Export the standalone deerflow-kernel repository skeleton from the current
DeerFlow monorepo checkout.

Options:
  --source-dir DIR   Source deer-flow repository. Default: current repo root
  --output DIR       Export destination. Default: ${TMPDIR:-/tmp}/deerflow-kernel
  --force            Remove the output directory before export
  -h, --help         Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source-dir)
            SOURCE_REPO="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --force)
            FORCE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

HARNESS_PKG_DIR="$SOURCE_REPO/backend/packages/harness/deerflow"
HARNESS_PYPROJECT="$SOURCE_REPO/backend/packages/harness/pyproject.toml"
LANGGRAPH_JSON="$SOURCE_REPO/backend/langgraph.json"

for required in "$HARNESS_PKG_DIR" "$HARNESS_PYPROJECT" "$LANGGRAPH_JSON"; do
    if [[ ! -e "$required" ]]; then
        echo "Required source path not found: $required" >&2
        exit 1
    fi
done

if [[ -e "$OUTPUT_DIR" ]]; then
    if [[ "$FORCE" != "1" ]]; then
        echo "Output directory already exists: $OUTPUT_DIR" >&2
        echo "Re-run with --force to replace it." >&2
        exit 1
    fi
    rm -rf "$OUTPUT_DIR"
fi

mkdir -p "$OUTPUT_DIR"

cp -a "$HARNESS_PKG_DIR" "$OUTPUT_DIR/deerflow"
cp "$SOURCE_REPO/LICENSE" "$OUTPUT_DIR/LICENSE"

find "$OUTPUT_DIR/deerflow" \
    \( -type d -name '__pycache__' -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
    -print0 | xargs -0 -r rm -rf

SOURCE_COMMIT="unknown"
if git -C "$SOURCE_REPO" rev-parse HEAD >/dev/null 2>&1; then
    SOURCE_COMMIT="$(git -C "$SOURCE_REPO" rev-parse HEAD)"
fi

python_requires="$(sed -n 's/^requires-python[[:space:]]*=[[:space:]]*"\([^"]*\)"/\1/p' "$HARNESS_PYPROJECT" | head -n 1)"
if [[ -z "$python_requires" ]]; then
    python_requires=">=3.12"
fi

cat > "$OUTPUT_DIR/pyproject.toml" <<EOF
[project]
name = "deerflow-kernel"
version = "0.1.0"
description = "Standalone DeerFlow harness kernel package"
readme = "README.md"
requires-python = "$python_requires"
dependencies = [
    "agent-client-protocol>=0.4.0",
    "agent-sandbox>=0.0.19",
    "dotenv>=0.9.9",
    "exa-py>=1.0.0",
    "httpx>=0.28.0",
    "kubernetes>=30.0.0",
    "langchain>=1.2.3",
    "langchain-anthropic>=1.3.4",
    "langchain-deepseek>=1.0.1",
    "langchain-mcp-adapters>=0.1.0",
    "langchain-openai>=1.1.7",
    "langfuse>=3.4.1",
    "langgraph>=1.0.6,<1.0.10",
    "langgraph-api>=0.7.0,<0.8.0",
    "langgraph-cli>=0.4.14",
    "langgraph-runtime-inmem>=0.22.1",
    "markdownify>=1.2.2",
    "markitdown[all,xlsx]>=0.0.1a2",
    "pydantic>=2.12.5",
    "pyyaml>=6.0.3",
    "readabilipy>=0.3.0",
    "tavily-python>=0.7.17",
    "firecrawl-py>=1.15.0",
    "tiktoken>=0.8.0",
    "ddgs>=9.10.0",
    "duckdb>=1.4.4",
    "langchain-google-genai>=4.2.1",
    "langgraph-checkpoint-sqlite>=3.0.3",
    "langgraph-sdk>=0.1.51",
]

[project.optional-dependencies]
ollama = ["langchain-ollama>=0.3.0"]
pymupdf = ["pymupdf4llm>=0.0.17"]

[project.scripts]
deerflow-kernel = "deerflow.kernel_cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["deerflow"]

[tool.hatch.build]
include = [
    "langgraph.json",
    "README.md",
    "LICENSE",
]
EOF

cat > "$OUTPUT_DIR/deerflow/kernel_cli.py" <<'EOF'
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def _load_langgraph_config() -> dict:
    config_path = _repo_root() / "langgraph.json"
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _cmd_version() -> int:
    try:
        from importlib.metadata import version

        print(version("deerflow-kernel"))
        return 0
    except Exception as exc:
        print(f"failed to resolve installed package version: {exc}", file=sys.stderr)
        return 1


def _cmd_check() -> int:
    try:
        import deerflow  # noqa: F401
        from deerflow.agents import make_lead_agent  # noqa: F401

        config = _load_langgraph_config()
        print("kernel import check passed")
        print(f"graph entry: {config['graphs']['lead_agent']}")
        return 0
    except Exception as exc:
        print(f"kernel check failed: {exc}", file=sys.stderr)
        return 1


def _cmd_show_langgraph_json() -> int:
    config = _load_langgraph_config()
    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="deerflow-kernel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version")
    subparsers.add_parser("check")
    subparsers.add_parser("show-langgraph-json")

    args = parser.parse_args()
    if args.command == "version":
        return _cmd_version()
    if args.command == "check":
        return _cmd_check()
    if args.command == "show-langgraph-json":
        return _cmd_show_langgraph_json()
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
EOF

cat > "$OUTPUT_DIR/langgraph.json" <<'EOF'
{
  "$schema": "https://langgra.ph/schema.json",
  "python_version": "3.12",
  "dependencies": [
    "."
  ],
  "graphs": {
    "lead_agent": "deerflow.agents:make_lead_agent"
  },
  "checkpointer": {
    "path": "./deerflow/agents/checkpointer/async_provider.py:make_checkpointer"
  }
}
EOF

cat > "$OUTPUT_DIR/README.md" <<'EOF'
# deerflow-kernel

This repository is an extracted standalone kernel package generated from the
open-source DeerFlow repository.

- Source repository: __SOURCE_REPO__
- Source commit: __SOURCE_COMMIT__

## Contents

- deerflow/: harness runtime, agents, tools, sandbox, memory, MCP, skills
- langgraph.json: LangGraph graph and checkpointer entrypoints
- pyproject.toml: standalone package metadata for deerflow-kernel

## Local build

```bash
uv build
```

## Quick validation

```bash
uv run deerflow-kernel check
```

## Regenerating this repository

This repository is intended to be regenerated from the main DeerFlow monorepo
using scripts/export-deerflow-kernel.sh in the source repository.
EOF

sed -i \
    -e "s|__SOURCE_REPO__|$SOURCE_REPO|g" \
    -e "s|__SOURCE_COMMIT__|$SOURCE_COMMIT|g" \
    "$OUTPUT_DIR/README.md"

cat > "$OUTPUT_DIR/.gitignore" <<'EOF'
__pycache__/
*.pyc
*.pyo
.venv/
venv/
dist/
build/
*.egg-info/
.DS_Store
EOF

echo "Export completed: $OUTPUT_DIR"
echo "Source commit: $SOURCE_COMMIT"
