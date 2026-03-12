#!/usr/bin/env bash

# Shared helpers for LangGraph development startup.
# Dev mode should always start from a fresh in-memory runtime state so a
# crashed run cannot poison the next restart via backend/.langgraph_api.

langgraph_dev_state_dir() {
    local repo_root="${1:?repo_root is required}"
    printf '%s/backend/.langgraph_api\n' "$repo_root"
}

reset_langgraph_dev_state() {
    local repo_root="${1:?repo_root is required}"
    local state_dir
    state_dir="$(langgraph_dev_state_dir "$repo_root")"
    rm -rf "$state_dir"
}

prepare_langgraph_dev_env() {
    export LANGGRAPH_DISABLE_FILE_PERSISTENCE=true
}
