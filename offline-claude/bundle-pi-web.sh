#!/bin/bash
# 在 Linux x86_64 (glibc) 机器上跑一次，把 @agegr/pi-web 装到临时 staging prefix，
# 再打成 tarball 供离线部署使用。
#
# 产物：offline-claude/pi-web-bundled-${VERSION}-linux-x64.tar.gz
#
# 用法：./offline-claude/bundle-pi-web.sh [版本号]
# 默认版本：0.6.13
#
# 重要：本脚本产生的 tarball **不进** DeerFlow 镜像。pi-web 是 pi 项目的独立
# Web UI，与 DeerFlow 项目无联动；本脚本仅为方便用户离线部署 pi-web 而存在。
# 跑完把 tarball 拿到目标机器上：tar -xzf pi-web-bundled-...-linux-x64.tar.gz -C /opt
# 然后 /opt/bin/pi-web 即可启动。
#
# x86 guard：虽然 pi-web 本身是纯 JS，但它的 next 依赖通过 optionalDependencies
# 拉入 sharp（含 platform-specific native binary）。必须在 Linux x86_64 主机上跑
# 才能产生与目标平台一致的 tarball。
set -euo pipefail

VERSION="${1:-0.6.13}"
PLATFORM="linux-x64"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

# --- preflight: confirm host is Linux x86_64 ---
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
if [ "$HOST_OS" != "Linux" ] || [ "$HOST_ARCH" != "x86_64" ]; then
    echo "✗ ERROR: this script must run on Linux x86_64 (glibc)." >&2
    echo "  detected: ${HOST_OS} ${HOST_ARCH}" >&2
    echo "  pi-web transitively pulls in sharp (native image library)," >&2
    echo "  whose prebuilt binary is platform-specific." >&2
    exit 1
fi

echo "==> Installing @agegr/pi-web@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g @agegr/pi-web@"${VERSION}" 2>&1 | tail -20

# 校验 bin 存在
BIN_PATH="$STAGING/bin/pi-web"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"

# 校验版本
PKG_JSON="$STAGING/lib/node_modules/@agegr/pi-web/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
TARBALL="$OUT_DIR/pi-web-bundled-${VERSION}-${PLATFORM}.tar.gz"
tar -czf "$TARBALL" -C "$STAGING" .
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$TARBALL"
echo "  sha256: $(shasum -a 256 "$TARBALL" | awk '{print $1}')"

echo ""
echo "Top-level packages in bundled tarball:"
# 匹配任意深度的 node_modules/<pkg>/（抓住嵌套在
# lib/node_modules/<pkg>/node_modules/<dep>/ 下的 transitive deps）。
# pi-web 经 next 拉入大量 deps，光顶层 node_modules 看不到，必须放宽到任意深度。
tar -tzf "$TARBALL" \
  | grep -oE 'node_modules/(@[^/]+/[^/]+|[^@/][^/]+)/' \
  | sed 's|node_modules/||; s|/$||' \
  | sort -u
