#!/usr/bin/env bash
#
# check_image_arch.sh - Check architecture of binaries inside a DeerFlow image
#
# Usage:
#   ./scripts/check_image_arch.sh [image_name]
#   ./scripts/check_image_arch.sh                    # defaults to deer-flow-gateway:latest
#
# Checks the architecture of:
#   - uv binary (/usr/local/bin/uv)
#   - python binary (/usr/local/bin/python3)
#   - node binary (/usr/local/bin/node)

set -e

IMAGE="${1:-deer-flow-gateway:latest}"
TMP_CONTAINER="arch_check_$$"

echo "Checking image: $IMAGE"
echo ""

cleanup() {
    docker rm -f "$TMP_CONTAINER" 2>/dev/null || true
}
trap cleanup EXIT

# Create container from image (don't start it)
docker create --name "$TMP_CONTAINER" "$IMAGE" >/dev/null 2>&1

# Check each binary
for binary in /usr/local/bin/uv /usr/local/bin/python3 /usr/local/bin/node; do
    printf "%-30s " "$binary:"
    if docker cp "$TMP_CONTAINER:$binary" /tmp/bin_check_$$ 2>/dev/null; then
        file /tmp/bin_check_$$
        rm -f /tmp/bin_check_$$
    else
        echo "(not found)"
    fi
done

echo ""
docker inspect "$IMAGE" --format='Docker reports: Architecture={{.Architecture}}'
