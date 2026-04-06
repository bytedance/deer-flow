#!/bin/sh
set -eu

export NGINX_LISTEN_PORT="${NGINX_LISTEN_PORT:-${PORT:-8080}}"

if [ -z "${GATEWAY_UPSTREAM:-}" ]; then
    echo "GATEWAY_UPSTREAM must be set for the Railway nginx service" >&2
    exit 1
fi

envsubst '${GATEWAY_UPSTREAM} ${NGINX_LISTEN_PORT}' \
    < /etc/nginx/nginx.conf.template \
    > /etc/nginx/nginx.conf

exec nginx -g 'daemon off;'
