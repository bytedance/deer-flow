#!/usr/bin/env sh

# Shared helpers for LangGraph development startup.
# For non-persistent dev runtimes, start from a fresh in-memory state so a
# crashed run cannot poison the next restart via backend/.langgraph_api.
# When LangGraph is backed by a persistent checkpointer (sqlite/postgres),
# preserve LangGraph's local metadata so thread lookups still resolve after
# restart.

langgraph_dev_state_dir() {
    repo_root="${1:?repo_root is required}"
    printf '%s/backend/.langgraph_api\n' "$repo_root"
}

reset_langgraph_dev_state() {
    repo_root="${1:?repo_root is required}"
    state_dir="$(langgraph_dev_state_dir "$repo_root")"
    rm -rf "$state_dir"
}

langgraph_dev_config_path() {
    repo_root="${1:?repo_root is required}"

    if [ -n "${DEER_FLOW_CONFIG_PATH:-}" ] && [ -f "${DEER_FLOW_CONFIG_PATH}" ]; then
        printf '%s\n' "${DEER_FLOW_CONFIG_PATH}"
        return 0
    fi

    if [ -f "${repo_root}/backend/config.yaml" ]; then
        printf '%s/backend/config.yaml\n' "$repo_root"
        return 0
    fi

    if [ -f "${repo_root}/config.yaml" ]; then
        printf '%s/config.yaml\n' "$repo_root"
        return 0
    fi

    return 1
}

langgraph_dev_uses_persistent_checkpointer() {
    repo_root="${1:?repo_root is required}"
    config_path="$(langgraph_dev_config_path "$repo_root" || true)"

    if [ -z "$config_path" ]; then
        return 1
    fi

    python3 - "$config_path" <<'PY'
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
with config_path.open(encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

checkpointer = config.get("checkpointer") or {}
cp_type = checkpointer.get("type")
raise SystemExit(0 if cp_type in {"sqlite", "postgres"} else 1)
PY
}

prepare_langgraph_dev_runtime() {
    repo_root="${1:?repo_root is required}"

    if langgraph_dev_uses_persistent_checkpointer "$repo_root"; then
        unset LANGGRAPH_DISABLE_FILE_PERSISTENCE
        return 0
    fi

    reset_langgraph_dev_state "$repo_root"
    export LANGGRAPH_DISABLE_FILE_PERSISTENCE=true
}
