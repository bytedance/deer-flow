#!/bin/bash
# 任何带 node/npm + 网络的机器上跑（macOS / Linux 任意 arch 都行）。
# pi-acp 是纯 JS 适配器（无 native binary），跨平台，suffix 仅为命名一致。
#
# 产物：offline-claude/pi-acp-bundled-${VERSION}-linux-x64.tar.gz
# 用法：./offline-claude/bundle-pi-acp.sh [版本号]
# 默认版本：0.0.27
set -euo pipefail

VERSION="${1:-0.0.27}"
PLATFORM_SUFFIX="linux-x64"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

echo "==> Installing pi-acp@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g pi-acp@"${VERSION}" 2>&1 | tail -20

BIN_PATH="$STAGING/bin/pi-acp"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"

PKG_JSON="$STAGING/lib/node_modules/pi-acp/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
TARBALL="$OUT_DIR/pi-acp-bundled-${VERSION}-${PLATFORM_SUFFIX}.tar.gz"
tar -czf "$TARBALL" -C "$STAGING" .
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$TARBALL"
echo "  sha256: $(shasum -a 256 "$TARBALL" | awk '{print $1}')"

echo ""
echo "Binaries in bundled tarball:"
# tar -C staging . 写出的 entry 路径以 ./ 开头（GNU tar 约定），
# 要 anchor `\./` 才能抓到 ./bin/<name>。
tar -tzf "$TARBALL" | grep -E '^\./bin/' | sort
