#!/bin/bash
# 在任何带 node/npm + 网络的机器上跑一次（macOS / Linux 任意 arch 都可以），
# 把 @agentclientprotocol/claude-agent-acp 装到临时 staging prefix，
# 再把整个 staging 打成 tar 一次性 vendor 进镜像。
#
# 产物：offline-claude/claude-agent-acp-bundled-${VERSION}-linux-x64.tar.gz
# （目录沿用 offline-claude/，与 claude-code 的 bundle 同居；命名沿用 -linux-x64
#  后缀保持和 claude-code-bundled 风格一致；ACP 包纯 JS、跨平台，suffix 实际无约束）
#
# 用法：./scripts/bundle-claude-agent-acp.sh [版本号]
# 默认版本：0.42.0
#
# 与 bundle-claude-code.sh 的关键区别：
#  - 本包纯 JS（bin 指向 dist/index.js，走 node），无 native binary，
#    因此不需要 host = 目标平台的硬 guard；macOS / linux 任意 arch / 容器内
#    都能跑，产出的 tarball 在 linux/amd64 + linux/arm64 镜像里都能用。
set -euo pipefail

VERSION="${1:-0.42.0}"
PLATFORM_SUFFIX="linux-x64"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

echo "==> Installing @agentclientprotocol/claude-agent-acp@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g @agentclientprotocol/claude-agent-acp@"${VERSION}" 2>&1 | tail -20

# 校验二进制确实在（npm 读包 bin 字段后在 $STAGING/bin/ 下生成 shim）
BIN_PATH="$STAGING/bin/claude-agent-acp"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    echo "    实际生成在 $STAGING/bin/ 下的二进制是：" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    echo "    检查上方 npm 输出，看包 bin 字段是否被正确解析。" >&2
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"
ls -lh "$BIN_PATH" | sed 's/^/      /'
if command -v file >/dev/null 2>&1; then
    file "$BIN_PATH" | sed 's/^/      /'
fi

echo "==> Verifying version string in package.json..."
PKG_JSON="$STAGING/lib/node_modules/@agentclientprotocol/claude-agent-acp/package.json"
if [ ! -f "$PKG_JSON" ]; then
    echo "    ✗ MISSING: $PKG_JSON" >&2
    exit 1
fi
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
# 整个 staging 目录打包，含：
#   STAGING/bin/claude-agent-acp                       — npm 生成的 bin shim
#   STAGING/lib/node_modules/@agentclientprotocol/     — scoped 命名空间
#       claude-agent-acp/                              — 主包（含 dist/index.js, package.json, deps）
#       sdk/                                            — 包依赖（如果存在）
#   STAGING/etc/, include/, share/                      — npm prefix 元数据（无害）
TARBALL="$OUT_DIR/claude-agent-acp-bundled-${VERSION}-${PLATFORM_SUFFIX}.tar.gz"
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
echo "Binaries in bundled tarball:"
tar -tzf "$TARBALL" | grep -E '^bin/' | sort
