#!/bin/bash
# 在一台 Linux x86_64 (glibc) 的有网机器上跑一次，把 @anthropic-ai/claude-code
# 2.1.139 装到临时 staging prefix，再把整个 staging 打成 tar 一次性 vendor 进镜像。
#
# 产物：offline-claude/claude-code-bundled-2.1.139-linux-x64.tar.gz
#
# 用法：./scripts/bundle-claude-code.sh [版本号]
# 默认版本：2.1.139
#
# 重要：本脚本产生的 tarball 内嵌 native binary，**host 平台 = 目标平台**。
# 请在 Linux x86_64 (glibc，非 musl/alpine) 机器上跑。在 macOS / Windows /
# Linux arm64 / Alpine 上跑会产出对应平台的 binary，**不能**被 Linux x86_64
# 镜像加载。脚本会硬 guard 检测 host，不对就直接报错退出。
set -euo pipefail

VERSION="${1:-2.1.139}"
PLATFORM="linux-x64"
PLATFORM_PKG="@anthropic-ai/claude-code-${PLATFORM}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

# --- preflight: confirm host is Linux x86_64 ---
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
if [ "$HOST_OS" != "Linux" ] || [ "$HOST_ARCH" != "x86_64" ]; then
    echo "✗ ERROR: this script must run on Linux x86_64 (glibc)." >&2
    echo "  detected: ${HOST_OS} ${HOST_ARCH}" >&2
    echo "  the tarball embeds a native binary and is NOT portable." >&2
    echo "  run on an Ubuntu/Debian/RHEL/equivalent x86_64 host, or a Linux x86_64 container." >&2
    exit 1
fi

echo "==> Installing @anthropic-ai/claude-code@${VERSION} into staging prefix..."
# host = linux-x64 → npm 自动从 optionalDependencies 里挑中匹配 linux+x64
# 的唯一一个子包 ${PLATFORM_PKG}；postinstall (install.cjs) 同样按
# process.platform='linux' + arch()='x64' + glibc 解析，hardlink native binary
# 到 bin/claude.exe。无需额外加 --os / --cpu flag（host 已是目标平台）。
npm install --prefix "$STAGING" -g @anthropic-ai/claude-code@"${VERSION}" 2>&1 | tail -20

echo "==> Verifying ${PLATFORM_PKG} in staging..."
# main 包的 bin 启动入口期望把同 package 内 node_modules/<platform-pkg>/claude
# hardlink 到 bin/claude.exe —— 这是 install.cjs 的契约。
NATIVE_BIN="$STAGING/lib/node_modules/@anthropic-ai/claude-code/node_modules/${PLATFORM_PKG}/claude"
if [ ! -f "$NATIVE_BIN" ]; then
    echo "    ✗ MISSING: ${NATIVE_BIN}" >&2
    echo "    install.cjs 看上去没把 ${PLATFORM_PKG} 放进去；检查上方 npm 输出。" >&2
    exit 1
fi
echo "    ✓ native binary present"
ls -lh "$NATIVE_BIN" | sed 's/^/      /'
if command -v file >/dev/null 2>&1; then
    file "$NATIVE_BIN" | sed 's/^/      /'
fi

echo "==> Verifying version string in main package.json..."
PKG_JSON="$STAGING/lib/node_modules/@anthropic-ai/claude-code/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
# 整个 staging 目录打包，含：
#   STAGING/bin/claude                                              — npm 生成的 bin shim
#   STAGING/lib/node_modules/@anthropic-ai/claude-code/             — package 自身（无 deps）
#       bin/claude.exe  (install.cjs 已 hardlink 成 native binary)
#       cli-wrapper.cjs, install.cjs, sdk-tools.d.ts, package.json
#       node_modules/${PLATFORM_PKG}/claude                         — 唯一的 native source
#   STAGING/etc/, include/, share/                                  — npm prefix 元数据（无害）
TARBALL="$OUT_DIR/claude-code-bundled-${VERSION}-${PLATFORM}.tar.gz"
tar -czf "$TARBALL" -C "$STAGING" .

echo "==> Cleaning up..."
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$TARBALL"
echo "  sha256: $(shasum -a 256 "$TARBALL" | awk '{print $1}')"

# 顺便打印所有 install 进来的 top-level packages（正确处理 scoped 命名空间）
echo ""
echo "Top-level packages in bundled tarball:"
tar -tzf "$TARBALL" \
  | grep -oE 'lib/node_modules/(@[^/]+/[^/]+|[^@/][^/]*)/' \
  | sed 's|lib/node_modules/||; s|/$||' \
  | sort -u

echo ""
echo "Native platform packages present (should be exactly ${PLATFORM_PKG}):"
tar -tzf "$TARBALL" \
  | grep -oE 'claude-code-(darwin|linux|win32)-[a-z0-9-]+' \
  | sort -u
