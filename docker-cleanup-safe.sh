#!/usr/bin/env bash
#
# Safe Docker Cleanup Script
#
# This script cleans up Docker resources while preserving:
# - Images from external registries (Docker Hub, etc.) with valid checksums
# - Currently running containers
# - Non-dangling volumes (actively used)
#
# What it cleans:
# - Stopped deer-flow containers
# - Locally built deer-flow images (deer-flow-*)
# - Build cache
# - Dangling/unused images, containers, networks, volumes
#

set -euo pipefail

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                    Safe Docker Cleanup Script                          ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
info() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

# Function to ask for confirmation
confirm() {
    read -p "$1 [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]]
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Analyzing Docker resources"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# List deer-flow containers
DEERFLOW_CONTAINERS=$(docker ps -a --filter "name=deer-flow" --format "{{.ID}}" 2>/dev/null || echo "")
if [ -n "$DEERFLOW_CONTAINERS" ]; then
    echo "DeerFlow containers found:"
    docker ps -a --filter "name=deer-flow" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
else
    info "No deer-flow containers found"
fi
echo ""

# List deer-flow images (locally built)
DEERFLOW_IMAGES=$(docker images --filter "reference=deer-flow-*" --format "{{.ID}}" 2>/dev/null || echo "")
if [ -n "$DEERFLOW_IMAGES" ]; then
    echo "DeerFlow images found (locally built):"
    docker images --filter "reference=deer-flow-*" --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}"
else
    info "No locally built deer-flow images found"
fi
echo ""

# List external images (from registries)
echo "External images from registries (will be preserved):"
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}" | \
    grep -E "^(docker.io|registry|gcr.io|quay.io|ghcr.io|[^/]+\.[^/]+/|[^/]+:[0-9]+/)" | head -10
echo ""

# List dangling images
DANGLING_IMAGES=$(docker images -f "dangling=true" -q 2>/dev/null || echo "")
if [ -n "$DANGLING_IMAGES" ]; then
    echo "Dangling images (untagged):"
    docker images -f "dangling=true" --format "table {{.ID}}\t{{.CreatedAt}}\t{{.Size}}" | head -10
    DANGLING_COUNT=$(echo "$DANGLING_IMAGES" | wc -l | tr -d ' ')
    warn "$DANGLING_COUNT dangling images found"
else
    info "No dangling images found"
fi
echo ""

# List dangling volumes
DANGLING_VOLUMES=$(docker volume ls -qf dangling=true 2>/dev/null || echo "")
if [ -n "$DANGLING_VOLUMES" ]; then
    VOLUME_COUNT=$(echo "$DANGLING_VOLUMES" | wc -l | tr -d ' ')
    warn "$VOLUME_COUNT dangling volumes found"
else
    info "No dangling volumes found"
fi
echo ""

# Build cache info
BUILD_CACHE_SIZE=$(docker system df --format "{{.Reclaimable}}" | head -1)
info "Build cache reclaimable: $BUILD_CACHE_SIZE"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Cleanup Options"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Option 1: Stop and remove deer-flow containers
if [ -n "$DEERFLOW_CONTAINERS" ]; then
    if confirm "Remove deer-flow containers?"; then
        echo "Stopping and removing deer-flow containers..."
        docker stop $(docker ps -q --filter "name=deer-flow") 2>/dev/null || true
        docker rm -f $(docker ps -a -q --filter "name=deer-flow") 2>/dev/null || true
        info "DeerFlow containers removed"
    else
        warn "Skipped: DeerFlow containers"
    fi
else
    info "No deer-flow containers to remove"
fi
echo ""

# Option 2: Remove locally built deer-flow images
if [ -n "$DEERFLOW_IMAGES" ]; then
    if confirm "Remove locally built deer-flow images?"; then
        echo "Removing deer-flow images..."
        docker rmi -f $(docker images --filter "reference=deer-flow-*" -q) 2>/dev/null || true
        info "DeerFlow images removed"
    else
        warn "Skipped: DeerFlow images"
    fi
else
    info "No locally built deer-flow images to remove"
fi
echo ""

# Option 3: Remove dangling images
if [ -n "$DANGLING_IMAGES" ]; then
    if confirm "Remove dangling (untagged) images?"; then
        echo "Removing dangling images..."
        docker image prune -f >/dev/null 2>&1
        info "Dangling images removed"
    else
        warn "Skipped: Dangling images"
    fi
else
    info "No dangling images to remove"
fi
echo ""

# Option 4: Clean build cache
if confirm "Clean Docker build cache?"; then
    echo "Cleaning build cache..."
    docker builder prune -f >/dev/null 2>&1
    info "Build cache cleaned"
else
    warn "Skipped: Build cache"
fi
echo ""

# Option 5: Remove dangling volumes
if [ -n "$DANGLING_VOLUMES" ]; then
    if confirm "Remove dangling volumes?"; then
        echo "Removing dangling volumes..."
        for volume in $DANGLING_VOLUMES; do
            docker volume rm "${volume}" 2>/dev/null || true
        done
        info "Dangling volumes removed"
    else
        warn "Skipped: Dangling volumes"
    fi
else
    info "No dangling volumes to remove"
fi
echo ""

# Option 6: System-wide prune (safe - excludes external images)
if confirm "Run system-wide prune (stops containers, removes networks, unused images)?"; then
    echo "Running system prune..."
    # Note: This does NOT use -a flag, so it won't remove tagged images from registries
    docker system prune -f >/dev/null 2>&1
    info "System prune completed"
else
    warn "Skipped: System prune"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show disk space reclaimed
docker system df
echo ""

info "Cleanup completed!"
echo ""
echo "Note: External images from registries (Docker Hub, etc.) were preserved."
echo "      Use 'docker images' to see remaining images."
echo ""
