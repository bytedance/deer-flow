#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKERFILE_PATH="$PROJECT_ROOT/docker/sandbox-custom.Dockerfile"

BASE_IMAGE="${BASE_IMAGE:-enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest}"
TARGET_IMAGE="${TARGET_IMAGE:-deer-flow-sandbox:custom}"
BUILD_CONTEXT="${BUILD_CONTEXT:-$PROJECT_ROOT}"

echo "======================================================"
echo "Building DeerFlow custom sandbox image"
echo "======================================================"
echo "BASE_IMAGE:    $BASE_IMAGE"
echo "TARGET_IMAGE:  $TARGET_IMAGE"
echo "DOCKERFILE:    $DOCKERFILE_PATH"
echo "CONTEXT:       $BUILD_CONTEXT"
echo ""

docker pull "$BASE_IMAGE"

docker build \
  --pull \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  -f "$DOCKERFILE_PATH" \
  -t "$TARGET_IMAGE" \
  "$BUILD_CONTEXT"

echo ""
echo "======================================================"
echo "Inspecting built image"
echo "======================================================"
docker image inspect "$TARGET_IMAGE" --format 'ID={{.Id}} Created={{.Created}} Size={{.Size}}'

echo ""
echo "======================================================"
echo "Quick verification inside image"
echo "======================================================"
docker run --rm --entrypoint sh "$TARGET_IMAGE" -lc '
python -c "import crawl4ai, playwright, pypdf; print(\"python_deps_ok\")"
test -d /ms-playwright && echo "playwright_browser_cache_ok"
for p in libgtk-4-1 gstreamer1.0-plugins-base libwoff2dec1; do
  dpkg -s "$p" >/dev/null 2>&1 && echo "$p:installed" || echo "$p:missing"
done
'

echo ""
echo "Done: $TARGET_IMAGE is ready."
