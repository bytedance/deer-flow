#!/usr/bin/env bash
#
# cleanup-containers.sh - Clean up DeerFlow sandbox containers
#
# This script cleans up both Docker and Apple Container runtime containers
# to ensure compatibility across different container runtimes.
#

set -e

PREFIX="${1:-deer-flow-sandbox}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Cleaning up sandbox containers with prefix: ${PREFIX}"

# Function to clean up Docker containers
cleanup_docker() {
    if command -v docker &> /dev/null; then
        echo -n "Checking Docker containers... "
        # Docker's name filter matches substrings. Check the returned names as
        # well so a container like not-deer-flow-sandbox is never stopped.
        DOCKER_LIST=$(docker ps --filter "name=${PREFIX}-" --format '{{.ID}} {{.Names}} {{.Status}}' 2>/dev/null || true)
        docker_ids=()
        docker_rows=()
        while read -r cid name status; do
            case "$name" in
                "$PREFIX"-*) docker_ids+=("$cid"); docker_rows+=("$cid $name $status") ;;
            esac
        done <<< "$DOCKER_LIST"

        if [ "${#docker_ids[@]}" -gt 0 ]; then
            echo ""
            echo "Found Docker containers to clean up:"
            printf '  %s\n' "${docker_rows[@]}"
            echo "Stopping Docker containers..."
            docker stop "${docker_ids[@]}" >/dev/null 2>&1 || true
            echo -e "${GREEN}✓ Docker containers stopped${NC}"
        else
            echo -e "${GREEN}none found${NC}"
        fi
    else
        echo "Docker not found, skipping..."
    fi
}

# Function to clean up Apple Container containers
cleanup_apple_container() {
    if command -v container &> /dev/null; then
        echo -n "Checking Apple Container containers... "

        # List all containers and filter by name
        CONTAINER_LIST=$(container list --format json 2>/dev/null || echo "[]")

        if [ "$CONTAINER_LIST" != "[]" ] && [ -n "$CONTAINER_LIST" ]; then
            # Extract container IDs that match our prefix
            CONTAINER_IDS=$(echo "$CONTAINER_LIST" | CLEANUP_CONTAINER_PREFIX="$PREFIX" python3 -c '
import json
import os
import sys
try:
    containers = json.load(sys.stdin)
    if isinstance(containers, list):
        prefix = os.environ["CLEANUP_CONTAINER_PREFIX"] + "-"
        for c in containers:
            if isinstance(c, dict):
                configuration = c.get("configuration")
                cid = configuration.get("id") if isinstance(configuration, dict) else None
                if isinstance(cid, str) and cid.startswith(prefix):
                    print(cid)
except:
    pass
' 2>/dev/null || echo "")

            if [ -n "$CONTAINER_IDS" ]; then
                echo ""
                echo "Found Apple Container containers to clean up:"
                echo "$CONTAINER_IDS" | while read -r cid; do
                    echo "  - $cid"
                done

                echo "Stopping Apple Container containers..."
                echo "$CONTAINER_IDS" | while read -r cid; do
                    container stop "$cid" 2>/dev/null || true
                done
                echo -e "${GREEN}✓ Apple Container containers stopped${NC}"
            else
                echo -e "${GREEN}none found${NC}"
            fi
        else
            echo -e "${GREEN}none found${NC}"
        fi
    else
        echo "Apple Container not found, skipping..."
    fi
}

# Clean up both runtimes
cleanup_docker
cleanup_apple_container

echo -e "${GREEN}✓ Container cleanup complete${NC}"
