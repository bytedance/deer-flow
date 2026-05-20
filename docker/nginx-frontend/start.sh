#!/bin/bash
set -e

# Configure nginx from template
cp /etc/nginx/nginx.conf.template /etc/nginx/nginx.conf
test -e /proc/net/if_inet6 || sed -i '/^[[:space:]]*listen[[:space:]]\+\[::\]:2026;/d' /etc/nginx/nginx.conf

# Rewrite frontend upstream to localhost since Next.js runs in this container
sed -i 's|frontend:3000|localhost:3000|' /etc/nginx/nginx.conf

# Start Next.js in background (pre-built dist)
if [ -f /app/frontend/package.json ]; then
    echo "Starting Next.js production server..."
    cd /app/frontend && pnpm start > /var/log/nextjs.log 2>&1 &
    echo "Next.js started (PID: $!)"
else
    echo "WARNING: Frontend dist not found at /app/frontend/package.json"
    echo "Run 'make docker-build-frontend-dist' first, then start again."
fi

# Start nginx in foreground
echo "Starting nginx..."
exec nginx -g 'daemon off;'
