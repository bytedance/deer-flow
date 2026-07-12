#!/usr/bin/env bash
# Pre-pull sandbox container image for DeerFlow

set -uo pipefail

echo "=========================================="
echo "  Pre-pulling Sandbox Container Image"
echo "=========================================="
echo ""

# Try to extract image from config.yaml (handles both commented and uncommented sandbox sections)
IMAGE=""
CONFIGURED=1
if [ -f "config.yaml" ]; then
    # Look for uncommented image: field under the sandbox section
    IMAGE=$(grep -A 20 "^sandbox:" config.yaml 2>/dev/null | grep "^  image:" | awk '{print $2}' | head -1 || true)
fi

if [ -z "$IMAGE" ]; then
    # NOTE: not ":latest". The mirror's `:latest` tag is frozen on an old
    # pre-1.9.3 digest that lacks the /v1/bash/* routes required-secrets
    # skills need (see #3921/#3922) — pulling it here would defeat the whole
    # point of this pre-pull helper. Keep this pinned to a version >= 1.9.3.
    IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"
    CONFIGURED=0
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

if [ "$CONFIGURED" -eq 0 ]; then
    echo ""
    echo "⚠ NOTE: pulling this image does not make the sandbox use it."
    echo "  config.yaml has no uncommented 'sandbox.image', so AioSandboxProvider"
    echo "  falls back to its own built-in default at runtime, which is still"
    echo "  pinned to ':latest' (frozen on an old pre-1.9.3 digest — see #3921)."
    echo "  To actually run on $IMAGE, add it explicitly:"
    echo ""
    echo "    sandbox:"
    echo "      image: $IMAGE"
fi
