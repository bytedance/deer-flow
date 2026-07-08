#!/bin/bash
# =============================================================================
# echart-skill Wheel Downloader (maintainer tool)
# =============================================================================
# Downloads platform wheels for offline distribution.
# Run this BEFORE packaging a release to bundle pre-downloaded dependencies.
#
# Usage:
#   bash scripts/download_wheels.sh              # download all platforms
#   bash scripts/download_wheels.sh --core-only  # core deps only (smaller)
#
# Output:  wheels/  directory with .whl files ready for offline install.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
WHEELS_DIR="$ROOT_DIR/wheels"
CORE_REQ="$ROOT_DIR/requirements-core.txt"
FULL_REQ="$ROOT_DIR/requirements.txt"

CORE_ONLY=false
if [[ "${1:-}" == "--core-only" ]]; then
    CORE_ONLY=true
fi

if $CORE_ONLY; then
    echo "📦 Downloading CORE dependencies only (smaller offline package)"
    REQ_FILE="$CORE_REQ"
else
    echo "📦 Downloading ALL dependencies (core + optional)"
    REQ_FILE="$FULL_REQ"
fi

# Clean previous wheels
rm -rf "$WHEELS_DIR"
mkdir -p "$WHEELS_DIR"

# =========================================================================
# Phase 1: Download for current platform (includes pure-Python + native)
# =========================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase 1/2: Downloading for current platform"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

pip download -d "$WHEELS_DIR" -r "$REQ_FILE" 2>&1 | sed 's/^/  /'

CURRENT_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l | tr -d ' ')
echo ""
echo "  ✅ Current platform: $CURRENT_COUNT wheels downloaded"

# =========================================================================
# Phase 2: Download native wheels for other platforms
# =========================================================================
# Cross-platform targets: (platform_tag, python_versions, description)
CROSS_TARGETS=(
    "macosx_11_0_arm64:cp312 cp311 cp310:macOS Apple Silicon (arm64)"
    "macosx_11_0_x86_64:cp312 cp311 cp310:macOS Intel (x86_64)"
    "win_amd64:cp312 cp311 cp310:Windows x64"
    "manylinux2014_x86_64:cp312 cp311 cp310:Linux x64"
)

# Packages with native extensions (need per-platform wheels).
# Pure-Python packages are already covered by Phase 1 (py3-none-any.whl).
NATIVE_PACKAGES=(
    "duckdb"
    "pandas"
)
if ! $CORE_ONLY; then
    NATIVE_PACKAGES+=(
        "psycopg2-binary"
        "pymongo"
    )
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Phase 2/2: Downloading native wheels for other platforms"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

for TARGET in "${CROSS_TARGETS[@]}"; do
    IFS=':' read -r PLATFORM_TAG PY_VERSIONS DESC <<< "$TARGET"

    # Skip if this is our current platform
    CURRENT_OS=$(uname -s)
    CURRENT_ARCH=$(uname -m)
    if [[ "$CURRENT_OS" == "Darwin" && "$DESC" == macOS* ]]; then
        if [[ "$CURRENT_ARCH" == "arm64" && "$PLATFORM_TAG" == "macosx_11_0_arm64" ]]; then
            echo "  ⏭  Skipping $DESC (current platform, already downloaded)"
            echo ""
            continue
        elif [[ "$CURRENT_ARCH" == "x86_64" && "$PLATFORM_TAG" == "macosx_11_0_x86_64" ]]; then
            echo "  ⏭  Skipping $DESC (current platform, already downloaded)"
            echo ""
            continue
        fi
    fi

    echo "  📥 $DESC  (platform: $PLATFORM_TAG)"
    echo ""

    for PY_VER in $PY_VERSIONS; do
        ABI="cp${PY_VER#cp}"
        echo "     Python $ABI …"

        # Try to download native packages for this platform+Python combo.
        # Ignore failures — some packages may not publish wheels for every ABI.
        for PKG in "${NATIVE_PACKAGES[@]}"; do
            pip download \
                --only-binary=:all: \
                --platform "$PLATFORM_TAG" \
                --python-version "${PY_VER#cp}" \
                --implementation cp \
                --abi "$ABI" \
                --no-deps \
                -d "$WHEELS_DIR" \
                "$PKG" \
                2>&1 | sed 's/^/       /' || true
        done
        echo ""
    done

    echo "  ✅ $DESC done"
    echo ""
done

# =========================================================================
# Report
# =========================================================================
WHEEL_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l | tr -d ' ')
TOTAL_SIZE=$(du -sh "$WHEELS_DIR" 2>/dev/null | cut -f1)

echo "============================================"
echo "✅ Done! Downloaded $WHEEL_COUNT wheels ($TOTAL_SIZE)"
echo "   Location: $WHEELS_DIR/"
echo ""

# Show breakdown by platform
echo "   Platform breakdown:"
for PLAT in "arm64" "x86_64" "win_amd64" "manylinux"; do
    COUNT=$(ls -1 "$WHEELS_DIR"/*${PLAT}*.whl 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$COUNT" -gt 0 ]]; then
        echo "     $PLAT: $COUNT wheels"
    fi
done
PURE_COUNT=$(ls -1 "$WHEELS_DIR"/*py3-none-any*.whl 2>/dev/null | wc -l | tr -d ' ')
echo "     pure-python: $PURE_COUNT wheels"
echo ""

# Write info file
cat > "$WHEELS_DIR/.wheels_info" << EOF
# echart-skill offline wheels
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Python versions: 3.10, 3.11, 3.12
# Total: $WHEEL_COUNT wheels ($TOTAL_SIZE)
EOF

echo "📦 To include in release:"
echo "   bash package.sh --offline"
echo "============================================"
