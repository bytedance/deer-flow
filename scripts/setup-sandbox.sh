#!/usr/bin/env bash
# Pre-pull sandbox container image for DeerFlow

set -uo pipefail

echo "=========================================="
echo "  Pre-pulling Sandbox Container Image"
echo "=========================================="
echo ""

# Try to extract image from config.yaml (handles both commented and uncommented sandbox sections)
IMAGE=""
if [ -f "config.yaml" ]; then
    # Look for uncommented image: field under the sandbox section
    IMAGE=$(grep -A 20 "^sandbox:" config.yaml 2>/dev/null | grep "^  image:" | awk '{print $2}' | head -1 || true)
fi

if [ -z "$IMAGE" ]; then
    IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"
    echo "Using default image: $IMAGE"
else
    echo "Using configured image: $IMAGE"
fi

echo ""

if command -v container >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then
    echo "Detected Apple Container on macOS, pulling image..."
    container image pull "$IMAGE" || echo "⚠ Apple Container pull failed, will try Docker"
fi

if command -v docker >/dev/null 2>&1; then
    echo "Pulling image using Docker..."
    if docker pull "$IMAGE"; then
        echo ""
        echo "✓ Sandbox image pulled successfully"
    else
        echo ""
        echo "⚠ Failed to pull sandbox image (this is OK for local sandbox mode)"
    fi
else
    echo "✗ Neither Docker nor Apple Container is available"
    echo "  Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
