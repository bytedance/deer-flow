#!/usr/bin/env bash
#
# nginx-local-conf.sh — Print the nginx config path for local (non-Docker) runs.
#
# docker/nginx/nginx.local.conf listens on loopback only, matching the Docker
# stack's default BIND_HOST. When BIND_HOST names another address, render a
# copy under temp/ that listens there instead and print that path, so local
# runs honor the same opt-in as the Docker stack. Gateway and frontend stay on
# loopback either way: nginx is the only entry point.
#
# Usage: NGINX_CONF="$(bash ./scripts/nginx-local-conf.sh)"

set -e

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
SOURCE_CONF="$REPO_ROOT/docker/nginx/nginx.local.conf"
RENDERED_CONF="$REPO_ROOT/temp/nginx.local.conf"

bind_host="${BIND_HOST:-127.0.0.1}"
if [ "$bind_host" = "127.0.0.1" ]; then
    printf '%s\n' "$SOURCE_CONF"
    exit 0
fi

# The value is written into an nginx directive, so accept address and hostname
# characters only.
bind_host="${bind_host#[}"
bind_host="${bind_host%]}"
case "$bind_host" in
    ''|*[!A-Za-z0-9.:_-]*)
        echo "BIND_HOST must be an IP address or hostname: ${BIND_HOST}" >&2
        exit 1
        ;;
esac

case "$bind_host" in
    0.0.0.0) listen_lines='listen 2026;\nlisten [::]:2026;' ;;
    *:*) listen_lines="listen [$bind_host]:2026;" ;;
    *) listen_lines="listen $bind_host:2026;" ;;
esac

# awk -v expands the \n separator; BSD awk rejects a literal newline there.
mkdir -p "$REPO_ROOT/temp"
awk -v listen_lines="$listen_lines" '
    /^[[:space:]]*listen 127\.0\.0\.1:2026;[[:space:]]*$/ {
        match($0, /^[[:space:]]*/)
        indent = substr($0, 1, RLENGTH)
        n = split(listen_lines, lines, "\n")
        for (i = 1; i <= n; i++) print indent lines[i]
        replaced++
        next
    }
    /^[[:space:]]*listen \[::1\]:2026;[[:space:]]*$/ { next }
    { print }
    END { if (replaced != 1) exit 1 }
' "$SOURCE_CONF" > "$RENDERED_CONF.tmp" || {
    rm -f "$RENDERED_CONF.tmp"
    echo "Could not find the loopback listen directive in $SOURCE_CONF" >&2
    exit 1
}
mv "$RENDERED_CONF.tmp" "$RENDERED_CONF"
printf '%s\n' "$RENDERED_CONF"
