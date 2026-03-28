#!/bin/bash; set -e
DEER_FLOW_HOME="${DEER_FLOW_HOME:-/persist/.deer-flow}"
mkdir -p "$DEER_FLOW_HOME"
CFG="$DEER_FLOW_HOME/config.yaml"
[ -f "$CFG" ] && echo "[deploy] Config exists" && exit 0
cat > "$CFG" << 'CONF'
config_version: 3
log_level: info
models:
  - name: gpt-4o
    display_name: GPT-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o
    api_key: ${OPENAI_API_KEY}
    max_tokens: 4096
    temperature: 0.7
    supports_vision: true
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
CONF
echo "[deploy] Config created at $CFG"
