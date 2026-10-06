#!/usr/bin/env bash
#
# check-data-not-in-use.sh - Refuse while a DeerFlow Gateway container is running
#
# `make clean` deletes backend/.deer-flow, the runtime data directory (database,
# users, threads, uploads, secrets). Both Docker stacks mount it into the
# Gateway container: docker-compose.yaml mounts ${DEER_FLOW_HOME} (default
# backend/.deer-flow) and docker-compose-dev.yaml mounts ../backend/. `make stop`
# only stops local services, so deleting the directory under a running Gateway
# would pull its open database out from under it.
#
# Exits 0 when Docker is missing or unreachable: no container can then be
# holding this checkout's data.

set -e

GATEWAY_CONTAINER="deer-flow-gateway"

if ! command -v docker >/dev/null 2>&1; then
    exit 0
fi

# Match the exact name: `docker ps --filter name=` is a substring match. Docker
# on Windows may end lines with CRLF.
if ! names=$(docker ps --format '{{.Names}}' 2>/dev/null); then
    exit 0
fi
if printf '%s\n' "$names" | tr -d '\r' | grep -qx "$GATEWAY_CONTAINER"; then
    echo "Refusing to delete DeerFlow runtime data: the $GATEWAY_CONTAINER container is running, and both Docker stacks mount backend/.deer-flow into it." >&2
    echo "Stop the Docker stack first (make down, or make docker-stop for the dev stack), then run make clean again." >&2
    exit 1
fi
