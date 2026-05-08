#!/usr/bin/env bash

detect_uv_extras() {
    local config_file=""
    local backend=""

    if [ -n "${DEER_FLOW_CONFIG_PATH:-}" ] && [ -f "${DEER_FLOW_CONFIG_PATH}" ]; then
        config_file="${DEER_FLOW_CONFIG_PATH}"
    elif [ -f "backend/config.yaml" ]; then
        config_file="backend/config.yaml"
    elif [ -f "config.yaml" ]; then
        config_file="config.yaml"
    else
        return 0
    fi

    backend=$(awk '
        /^[[:space:]]*database:[[:space:]]*$/ { in_database=1; next }
        in_database && /^[^[:space:]#]/ { in_database=0 }
        in_database && /^[[:space:]]*backend:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*backend:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    if [ "$backend" = "postgres" ]; then
        echo "postgres"
    fi
}
