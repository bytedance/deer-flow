#!/bin/sh
# Stage the DeerFlow sandbox lark-cli runtime layout from official release
# binaries. Runs at image BUILD time (network available).
#
# Usage: LARK_CLI_VERSION=v1.0.65 build-runtime.sh /opt/lark-cli
#
# Produces:
#   <dest>/bin/lark-cli            arch-dispatch launcher (uname -m)
#   <dest>/linux-amd64/lark-cli
#   <dest>/linux-arm64/lark-cli
#   <dest>/.deerflow-lark-cli-runtime.json   {"version": "vX.Y.Z"}
#
# The layout mirrors the Gateway writer (_write_lark_cli_sandbox_launcher) and
# satisfies _validate_lark_cli_sandbox_runtime, so the sandbox PATH contract is
# unchanged.
set -eu

DEST="${1:?destination directory required}"
VERSION="${LARK_CLI_VERSION:?LARK_CLI_VERSION required}"
REPO="larksuite/cli"
ARCHES="amd64 arm64"

# Normalize to a leading-v tag and a bare version.
case "$VERSION" in
  v*) TAG="$VERSION" ;;
  *)  TAG="v$VERSION" ;;
esac
BARE="${TAG#v}"

BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading lark-cli ${TAG} release checksums..."
curl -fsSL "${BASE_URL}/checksums.txt" -o "${WORK}/checksums.txt"

mkdir -p "${DEST}/bin"

for arch in $ARCHES; do
  asset="lark-cli-${BARE}-linux-${arch}.tar.gz"
  echo "Downloading ${asset}..."
  curl -fsSL "${BASE_URL}/${asset}" -o "${WORK}/${asset}"

  expected="$(awk -v f="${asset}" '$2 == f || $2 == "*"f {print $1}' "${WORK}/checksums.txt" | head -n1)"
  if [ -z "$expected" ]; then
    echo "ERROR: no checksum for ${asset} in checksums.txt" >&2
    exit 1
  fi
  actual="$(sha256sum "${WORK}/${asset}" | awk '{print $1}')"
  if [ "$expected" != "$actual" ]; then
    echo "ERROR: checksum mismatch for ${asset} (expected ${expected}, got ${actual})" >&2
    exit 1
  fi

  mkdir -p "${DEST}/linux-${arch}"
  # Extract only the single lark-cli executable from the archive.
  tar -xzf "${WORK}/${asset}" -C "${WORK}"
  found="$(find "${WORK}" -type f -name lark-cli ! -path "${DEST}/*" | head -n1)"
  if [ -z "$found" ]; then
    echo "ERROR: lark-cli executable not found in ${asset}" >&2
    exit 1
  fi
  install -m 0755 "$found" "${DEST}/linux-${arch}/lark-cli"
  rm -f "$found"
done

# Arch-dispatch launcher. Kept byte-identical to
# LARK_CLI_SANDBOX_LAUNCHER_SCRIPT in
# backend/packages/harness/deerflow/integrations/lark_cli.py
# (a unit test asserts the two never drift).
cat > "${DEST}/bin/lark-cli" <<'LAUNCHER'
#!/bin/sh
set -eu
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  aarch64|arm64) arch=arm64 ;;
  *) echo "Unsupported sandbox architecture: $(uname -m)" >&2; exit 126 ;;
esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$script_dir/../linux-$arch/lark-cli" "$@"
LAUNCHER
chmod 0755 "${DEST}/bin/lark-cli"

printf '{\n  "version": "%s"\n}\n' "$TAG" > "${DEST}/.deerflow-lark-cli-runtime.json"

echo "Staged lark-cli ${TAG} runtime at ${DEST}:"
ls -R "${DEST}"
