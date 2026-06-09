#!/bin/bash
# 在 Linux x86_64 (glibc) 机器上跑一次，把 @earendil-works/pi-coding-agent
# 装到临时 staging prefix，再打成 tarball 一次性 vendor 进镜像。
#
# 产物：offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz
#
# 用法：./offline-claude/bundle-pi-coding-agent.sh [版本号]
# 默认版本：0.78.1
#
# 重要：本脚本产生的 tarball 内嵌 native/WASM binary，**host = 目标平台**。
# 镜像本身是 linux/amd64，必须在 Linux x86_64 主机上跑。
# macOS / Windows / Linux arm64 / Alpine 都会产出不能用的 binary。
#
# 关于依赖：pi-agent-core / pi-ai / pi-tui / photon-node / 等都是 pi-coding-agent
# 的 transitive dependencies。一次 `npm install -g @earendil-works/pi-coding-agent`
# 会把整条依赖树装到 staging 下的 lib/node_modules/。不需要单装那几个包。
#
# 关于 install scripts：pi-coding-agent 本身以及整条依赖链的 hasInstallScript
# 都为 None，因此本脚本不加 --ignore-scripts（与 bundle-claude-code.sh 风格一致；
# 加了也无害，但会与现有脚本不一致）。
set -euo pipefail

VERSION="${1:-0.78.1}"
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
    echo "  the tarball embeds platform-specific assets and is NOT portable." >&2
    exit 1
fi

# --- preflight: pick downloader (curl preferred, wget fallback) ---
# fd / ripgrep 要从 GitHub Releases 拉，没有 downloader 时 fail-fast，
# 避免 curl 缺失被 pipe 吞掉只看到下游 tar 的 "unexpected end of file"。
if command -v curl >/dev/null 2>&1; then
    _download() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
    _download() { wget -qO- "$1"; }
else
    echo "✗ ERROR: neither 'curl' nor 'wget' is installed; needed to fetch fd/ripgrep." >&2
    echo "  Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y curl" >&2
    echo "  Alpine:        apk add --no-cache curl" >&2
    echo "  RHEL/CentOS:   sudo dnf install -y curl" >&2
    exit 1
fi

echo "==> Installing @earendil-works/pi-coding-agent@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g @earendil-works/pi-coding-agent@"${VERSION}" 2>&1 | tail -20

# 校验 bin 存在
BIN_PATH="$STAGING/bin/pi"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"

# 校验版本
PKG_JSON="$STAGING/lib/node_modules/@earendil-works/pi-coding-agent/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

# 额外 vendor fd + ripgrep：pi 启动时若 PATH / ~/.pi/agent/bin 找不到它们，
# 会从 GitHub Releases 自动下载（见 pi-coding-agent/dist/utils/tools-manager.js）。
# 完全离线环境必须提前 vendor 到 $STAGING/bin/；镜像构建后它们落在
# /usr/local/bin/，被 `pi` 的 getToolPath() 在 PATH 上找到，从而根本不会
# 触发 downloadTool()。
# 版本：默认 fd v10.2.0 + ripgrep v14.1.0，可用 FD_VERSION / RG_VERSION 覆盖。
FD_VERSION="${FD_VERSION:-10.2.0}"
RG_VERSION="${RG_VERSION:-14.1.0}"

echo "==> Vendoring fd v${FD_VERSION}..."
mkdir -p "$STAGING/fd-staging"
_download "https://github.com/sharkdp/fd/releases/download/v${FD_VERSION}/fd-v${FD_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
    | tar -xz -C "$STAGING/fd-staging"
cp "$STAGING/fd-staging/fd-v${FD_VERSION}-x86_64-unknown-linux-gnu/fd" "$STAGING/bin/fd"
chmod +x "$STAGING/bin/fd"
rm -rf "$STAGING/fd-staging"
"$STAGING/bin/fd" --version

echo "==> Vendoring ripgrep v${RG_VERSION}..."
mkdir -p "$STAGING/rg-staging"
_download "https://github.com/BurntSushi/ripgrep/releases/download/${RG_VERSION}/ripgrep-${RG_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C "$STAGING/rg-staging"
cp "$STAGING/rg-staging/ripgrep-${RG_VERSION}-x86_64-unknown-linux-musl/rg" "$STAGING/bin/rg"
chmod +x "$STAGING/bin/rg"
rm -rf "$STAGING/rg-staging"
"$STAGING/bin/rg" --version

echo "==> Bundling staging directory..."
TARBALL="$OUT_DIR/pi-coding-agent-bundled-${VERSION}-${PLATFORM}.tar.gz"
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
# 注意 `[^/]+` 而非 `[^/]*`：空段不算包名。
tar -tzf "$TARBALL" \
  | grep -oE 'node_modules/(@[^/]+/[^/]+|[^@/][^/]+)/' \
  | sed 's|node_modules/||; s|/$||' \
  | sort -u
