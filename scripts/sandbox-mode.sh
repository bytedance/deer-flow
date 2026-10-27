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
    /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
    in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
    in_sandbox && !seen_use && /^[[:space:]]*use:[[:space:]]*/ {
        sandbox_use=$0
        sub(/^[[:space:]]*use:[[:space:]]*/, "", sandbox_use)
        seen_use=1
    }
    in_sandbox && !seen_url && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
        provisioner_url=$0
        sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", provisioner_url)
        seen_url=1
    }
    END {
        if (index(sandbox_use, "deerflow.sandbox.local:LocalSandboxProvider")) {
            print "local"
        } else if (index(sandbox_use, "deerflow.community.aio_sandbox:AioSandboxProvider")) {
            print empty_scalar(provisioner_url) ? "aio" : "provisioner"
        } else {
            print "local"
        }
    }
' "$config_file"
