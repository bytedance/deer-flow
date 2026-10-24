#!/bin/sh
# PROPOSAL ONLY. Root must approve execution and immutable image IDs first.
set -eu
set +x
umask 077
[ "$#" -eq 5 ] || { echo 'usage: run_worker.sh SOURCE_TAR SOURCE_SHA256 NATIVE_FULL_IMAGE_ID AIO_FULL_IMAGE_ID RUN_HEX24' >&2; exit 2; }
source_tar=$1
source_sha=$2
native_image=$3
aio_image=$4
run_id=$5
case "$run_id" in *[!0-9a-f]*|'') exit 2;; esac
[ "${#run_id}" -eq 24 ]
python3 - "$source_sha" "$native_image" "$aio_image" "$source_tar" <<'VALIDATE'
import re,sys
from pathlib import Path
assert re.fullmatch(r"[0-9a-f]{64}", sys.argv[1])
assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in sys.argv[2:4])
assert Path(sys.argv[4]).is_absolute() and Path(sys.argv[4]).is_file()
VALIDATE
[ "$(docker image inspect -f '{{.Id}}' "$native_image")" = "$native_image" ]
[ "$(docker image inspect -f '{{.Id}}' "$aio_image")" = "$aio_image" ]
[ "$(docker image inspect -f '{{.Architecture}}' "$native_image")" = "$(docker image inspect -f '{{.Architecture}}' "$aio_image")" ]
printf '%s  %s\n' "$source_sha" "$source_tar" | sha256sum --check
prefix="deer-c-aio-$run_id"
owned_root="/var/tmp/$prefix"
[ ! -e "$owned_root" ]
mkdir -m 700 "$owned_root"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cp "$script_dir/cleanup_exact.py" "$owned_root/cleanup_exact.py"
printf '{"mcpServers":{},"skills":{}}' > "$owned_root/extensions.json"
printf '{}' > "$owned_root/evidence.json"
printf '%s\n' "$native_image" "$aio_image" > "$owned_root/images.txt"
# No existing NAS/customer paths are mounted. host network makes the provider's
# host-loopback AIO API reachable from the administrative test harness.
# Docker socket is administrative access even when the mount is read-only.
cleanup() {
 original=$?
 trap - EXIT HUP INT TERM
 cleanup_status=0
 python3 "$owned_root/cleanup_exact.py" "$owned_root" "$prefix" "$aio_image" > "$owned_root/cleanup.log" 2>&1 || cleanup_status=$?
 [ "$cleanup_status" -eq 0 ] || { cat "$owned_root/cleanup.log" >&2; exit "$cleanup_status"; }
 exit "$original"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# No auto-install, build or pull. Before this approved physical run, separately
# verify image tooling via the read-only image audit described in REVIEW.md.
# The import preflight below runs inside THIS one bounded harness and fails
# before pytest/AIO provisioning if the selected native image lacks test extras.
timeout --signal=TERM --kill-after=20 420 docker run --rm --pull=never \
 --name "deer-c-harness-$run_id" --cidfile "$owned_root/harness.cid" \
 --label "org.deerflow.tenant.owned=$prefix" --label deerflow.role=fixture-harness --network host \
 --cpus .5 --memory 1g --memory-swap 1g --pids-limit 256 \
 -e ECS_C_AIO_PHYSICAL_TEST=1 -e "TEST_AIO_PREFIX=$prefix" \
 -e "TEST_AIO_IMAGE_ID=$aio_image" -e "TEST_AIO_EVIDENCE=$owned_root/evidence.json" \
 -e "TEST_AIO_ROOT=$owned_root" -e "DEER_FLOW_HOME=$owned_root/home" \
 -e "DEER_FLOW_EXTENSIONS_CONFIG_PATH=$owned_root/extensions.json" \
 -e DEER_FLOW_SANDBOX_CPUS=1 -e DEER_FLOW_SANDBOX_MEMORY=1g \
 -e DEER_FLOW_SANDBOX_BIND_HOST=127.0.0.1 -e DEER_FLOW_SANDBOX_HOST=127.0.0.1 \
 -v /var/run/docker.sock:/var/run/docker.sock:ro -v /usr/bin/docker:/usr/bin/docker:ro \
 -v "$owned_root:$owned_root" -v "$source_tar:/run/source.tar.gz:ro" \
 --entrypoint /bin/sh "$native_image" -c '
  set -eu
  /app/backend/.venv/bin/python -c "import pytest, pytest_asyncio, sqlalchemy, aiosqlite, alembic, httpx, langgraph, langchain_core, pydantic, agent_sandbox"
  mkdir "$TEST_AIO_ROOT/source"
  tar xzf /run/source.tar.gz -C "$TEST_AIO_ROOT/source"
  cd "$TEST_AIO_ROOT/source/backend"
  export PYTHONPATH="$PWD:$PWD/tests:$PWD/packages/harness:$PWD/packages/extension-api:$PWD/packages/ecs-executor"
  /app/backend/.venv/bin/python -m pytest tests/test_scoped_c_aio_physical.py::test_scoped_c_aio_capture_stops_exact_container \
   --basetemp="$TEST_AIO_ROOT/tests" -q --tb=short --no-showlocals
 ' > "$owned_root/test.log" 2>&1
# Successful pytest alone is insufficient: normal path (before finally) must
# have observed exact-ID absence, reserved capacity until report, then release.
python3 - "$owned_root/evidence.json" <<'PY'
import json,sys
record=json.load(open(sys.argv[1]))
assert record['running_before_stop'] and record['warm_release_running']
assert record['injected_stop_failed'] and record['running_after_unknown'] and record['capacity_after_unknown']==1
assert record['normal_stop_confirmed'] and record['missing_exact_id_after_stop']
assert record['capacity_before_report']==1 and record['capacity_after_report']==0
assert record['native_status']=='success' and record['native_run_id']
PY
