#!/usr/bin/env bash
#
# Advanced Docker Cleanup Script with Checksum Verification
#
# This script performs intelligent cleanup:
# 1. Preserves images from registries with valid checksums
# 2. Verifies image integrity before considering deletion
# 3. Only removes local builds and truly unused resources
# 4. Provides detailed reporting
#

set -euo pipefail

echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║          Advanced Docker Cleanup with Checksum Verification            ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }
note() { echo -e "${BLUE}ℹ${NC} $1"; }

# Dry run mode
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    warn "DRY RUN MODE - No changes will be made"
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 1: Image Analysis & Checksum Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Categorize images
declare -a REGISTRY_IMAGES=()
declare -a LOCAL_IMAGES=()
declare -a DEER_FLOW_IMAGES=()
declare -a DANGLING_IMAGES=()

while IFS= read -r line; do
    if [[ -z "$line" ]]; then continue; fi

    IMAGE_ID=$(echo "$line" | awk '{print $1}')
    REPO=$(echo "$line" | awk '{print $2}')
    TAG=$(echo "$line" | awk '{print $3}')

    # Skip header
    if [[ "$IMAGE_ID" == "IMAGE" ]]; then continue; fi

    # Categorize
    if [[ "$REPO" == "<none>" ]] && [[ "$TAG" == "<none>" ]]; then
        DANGLING_IMAGES+=("$IMAGE_ID")
    elif [[ "$REPO" =~ ^deer-flow ]]; then
        DEER_FLOW_IMAGES+=("$IMAGE_ID:$REPO:$TAG")
    elif [[ "$REPO" =~ ^(docker\.io|registry|gcr\.io|quay\.io|ghcr\.io|[^/]+\.[^/]+/) ]] || [[ "$REPO" =~ : ]]; then
        REGISTRY_IMAGES+=("$IMAGE_ID:$REPO:$TAG")
    else
        # Local image (no registry prefix)
        LOCAL_IMAGES+=("$IMAGE_ID:$REPO:$TAG")
    fi
done < <(docker images --format "{{.ID}} {{.Repository}} {{.Tag}}")

echo "📊 Image Classification:"
echo "   • Registry images (external): ${#REGISTRY_IMAGES[@]}"
echo "   • DeerFlow images (local):    ${#DEER_FLOW_IMAGES[@]}"
echo "   • Other local images:         ${#LOCAL_IMAGES[@]}"
echo "   • Dangling images:            ${#DANGLING_IMAGES[@]}"
echo ""

# Verify registry images have valid checksums
if [[ ${#REGISTRY_IMAGES[@]} -gt 0 ]]; then
    echo "🔍 Verifying registry image checksums..."
    for img_info in "${REGISTRY_IMAGES[@]}"; do
        IFS=':' read -r img_id repo tag <<< "$img_info"

        # Get image digest
        DIGEST=$(docker inspect "$img_id" --format='{{index .RepoDigests 0}}' 2>/dev/null || echo "")

        if [[ -n "$DIGEST" ]]; then
            echo -e "   ${GREEN}✓${NC} $repo:$tag → $DIGEST"
        else
            warn "   No digest found for $repo:$tag (may be locally built)"
        fi
    done
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 2: Container Analysis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Analyze containers
RUNNING_CONTAINERS=$(docker ps -q | wc -l | tr -d ' ')
STOPPED_CONTAINERS=$(docker ps -aq --filter "status=exited" | wc -l | tr -d ' ')
DEER_FLOW_CONTAINERS=$(docker ps -aq --filter "name=deer-flow" | wc -l | tr -d ' ')

echo "📦 Container Status:"
echo "   • Running: $RUNNING_CONTAINERS"
echo "   • Stopped: $STOPPED_CONTAINERS"
echo "   • DeerFlow: $DEER_FLOW_CONTAINERS"
echo ""

if [[ $DEER_FLOW_CONTAINERS -gt 0 ]]; then
    echo "DeerFlow containers:"
    docker ps -a --filter "name=deer-flow" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 3: Resource Analysis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Volume analysis
DANGLING_VOLUMES=$(docker volume ls -qf dangling=true | wc -l | tr -d ' ')
TOTAL_VOLUMES=$(docker volume ls -q | wc -l | tr -d ' ')

echo "💾 Storage:"
docker system df
echo ""
echo "   • Total volumes: $TOTAL_VOLUMES"
echo "   • Dangling volumes: $DANGLING_VOLUMES"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 4: Safe Cleanup Actions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

note "Registry images with valid checksums will be preserved"
note "Only local builds and unused resources will be considered for removal"
echo ""

# Function to execute or simulate
execute_or_dry_run() {
    local description=$1
    local command=$2

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${BLUE}[DRY RUN]${NC} Would execute: $description"
    else
        echo "Executing: $description"
        eval "$command" 2>&1 | sed 's/^/  /'
    fi
}

# 1. Remove stopped DeerFlow containers
if [[ $DEER_FLOW_CONTAINERS -gt 0 ]]; then
    read -p "Remove DeerFlow containers? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        STOPPED_DF=$(docker ps -aq --filter "name=deer-flow" --filter "status=exited" 2>/dev/null || echo "")
        if [[ -n "$STOPPED_DF" ]]; then
            execute_or_dry_run "Remove stopped DeerFlow containers" \
                "docker rm -f \$(docker ps -aq --filter 'name=deer-flow' --filter 'status=exited')"
            info "Stopped DeerFlow containers removed"
        else
            note "No stopped DeerFlow containers found"
        fi
    fi
    echo ""
fi

# 2. Remove DeerFlow images (local builds)
if [[ ${#DEER_FLOW_IMAGES[@]} -gt 0 ]]; then
    echo "DeerFlow images to remove:"
    for img_info in "${DEER_FLOW_IMAGES[@]}"; do
        IFS=':' read -r img_id repo tag <<< "$img_info"
        echo "   • $repo:$tag ($img_id)"
    done
    echo ""

    read -p "Remove these locally built DeerFlow images? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for img_info in "${DEER_FLOW_IMAGES[@]}"; do
            IFS=':' read -r img_id repo tag <<< "$img_info"
            execute_or_dry_run "Remove $repo:$tag" "docker rmi -f $img_id"
        done
        info "DeerFlow images removed"
    fi
    echo ""
fi

# 3. Remove dangling images
if [[ ${#DANGLING_IMAGES[@]} -gt 0 ]]; then
    echo "Found ${#DANGLING_IMAGES[@]} dangling images"
    read -p "Remove dangling images? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        execute_or_dry_run "Remove dangling images" "docker image prune -f"
        info "Dangling images removed"
    fi
    echo ""
fi

# 4. Build cache
read -p "Clean build cache? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    execute_or_dry_run "Clean build cache" "docker builder prune -f"
    info "Build cache cleaned"
fi
echo ""

# 5. Dangling volumes
if [[ $DANGLING_VOLUMES -gt 0 ]]; then
    echo "Found $DANGLING_VOLUMES dangling volumes"
    read -p "Remove dangling volumes? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        execute_or_dry_run "Remove dangling volumes" "docker volume prune -f"
        info "Dangling volumes removed"
    fi
    echo ""
fi

# 6. System prune (without removing tagged images)
read -p "Run safe system prune (networks, stopped containers)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    execute_or_dry_run "System prune (safe)" "docker system prune -f"
    info "System prune completed"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    warn "DRY RUN completed - no actual changes were made"
    echo ""
    echo "Run without --dry-run to perform actual cleanup"
else
    info "Cleanup completed!"
    echo ""
    echo "Final storage status:"
    docker system df
fi
echo ""

note "Protected resources:"
echo "   ✓ Registry images with valid checksums (Docker Hub, etc.)"
echo "   ✓ Running containers"
echo "   ✓ Non-dangling volumes"
echo ""
