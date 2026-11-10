#!/usr/bin/env bash
# Shared, read-only mode detection for the Docker dev and production launchers.
# Callers own config-path resolution. Use only Bash/awk: Docker-only hosts do
# not need Python or backend dependencies installed.
set -e

config_file="$1"
if [ ! -f "$config_file" ]; then
    echo "local"
    exit 0
fi

# Keep the existing block-mapping lookup, not a general YAML parser. Recognize
# empty single-line scalars before discarding quote information: quoted "null"
# and "~" are nonempty strings. URL validation, aliases, multiline scalars and
# environment-variable expansion remain outside this lightweight detector.
awk '
    function empty_scalar(value) {
        sub(/[[:space:]]+$/, "", value)
        return value == "" || value ~ /^#/ || value ~ /^(null|Null|NULL|~|""|\047\047)([[:space:]]+#.*)?$/
    }
    /^[[:space:]]*(#|$)/ || /^(---|\.\.\.)([[:space:]]|$)/ || /^%/ { next }
    {
        indent = match($0, /[^[:space:]]/)
        if (!root_indent) root_indent = indent
    }
    indent == root_indent {
        in_sandbox = $0 ~ /^[[:space:]]*sandbox:([[:blank:]]+#.*)?[[:space:]]*$/
        child_indent = 0
        next
    }
    in_sandbox && !child_indent { child_indent = indent }
    in_sandbox && indent == child_indent && !seen_use && /^[[:space:]]*use:[[:space:]]*/ {
        sandbox_use=$0
        sub(/^[[:space:]]*use:[[:space:]]*/, "", sandbox_use)
        # Keep the exact match below so truncated quoted values fall back to local.
        sub(/[[:blank:]]+#.*$/, "", sandbox_use)
        sub(/[[:space:]]+$/, "", sandbox_use)
        seen_use=1
    }
    in_sandbox && indent == child_indent && !seen_url && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
        provisioner_url=$0
        sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", provisioner_url)
        seen_url=1
    }
    END {
        aio_provider = "deerflow.community.aio_sandbox:AioSandboxProvider"
        if (sandbox_use == aio_provider || sandbox_use == "\"" aio_provider "\"" || sandbox_use == "\047" aio_provider "\047") {
            print empty_scalar(provisioner_url) ? "aio" : "provisioner"
        } else {
            print "local"
        }
    }
' "$config_file"
