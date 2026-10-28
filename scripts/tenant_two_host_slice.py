"""Orchestrate the two-host B slice on the dedicated VPC test machines.

controller 139.196.30.22 (PG + native/executor DBs + worker RPC uvicorn)
worker     47.117.5.254 (real B Docker through OutboundStore over VPC TCP)

Standard library only; driven over SSH with the operator key. Every container
and directory carries the phase's org.deerflow.tenant.owned label/marker;
cleanup removes only exact recorded identities. Source is a deterministic
frozen tarball of the worktree HEAD (same procedure as the Jenkins freezes).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

WORKTREE = Path("/Users/wenbinwang/.codex/worktrees/1d28/deerflow2")
KEY = os.environ.get("TENANT_SSH_IDENTITY", "/Users/wenbinwang/Documents/docs/genbalde/key/genbalde-drama-keypair.pem")
CONTROLLER, WORKER = "139.196.30.22", "47.117.5.254"
CONTROLLER_PRIVATE = "192.168.0.190"
CROOT = "/srv/deerflow-twohost"
PHASE = "two-host-b-slice-20261028-51"
PORT = 8021
NATIVE_IMAGE = "deerflow-native:production-repaired-contract-c6af94a95ae7"
PG_IMAGE = "sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
B_IMAGE = "sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc"  # alpine:3.20 small profile
OWNER = "two-host-owner"


def ssh(host: str, script: str, stdin_text: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", f"root@{host}", script],
        input=stdin_text, capture_output=True, text=True,
    )


def must(host: str, script: str, stdin_text: str = "", what: str = "") -> str:
    result = ssh(host, script, stdin_text)
    if result.returncode:
        sys.exit(f"[{host}] {what or 'ssh step'} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result.stdout


def scp_to(host: str, local: str, remote: str) -> None:
    result = subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", local, f"root@{host}:{remote}"], capture_output=True, text=True)
    if result.returncode:
        sys.exit(f"scp to {host} failed: {result.stderr}")


def scp_from(host: str, remote: str, local: str) -> None:
    subprocess.run(["scp", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", f"root@{host}:{remote}", local], capture_output=True, text=True, check=False)


def freeze_archive(destination: str) -> str:
    """Deterministic HEAD freeze: pinned-date commit-tree + gzip -n."""
    idx, out = f"/tmp/{PHASE}-idx", destination
    env = {**os.environ, "GIT_INDEX_FILE": idx}

    def git(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(WORKTREE), *args], capture_output=True, text=True, env=env)
        if result.returncode:
            sys.exit(f"git {args[0]} failed: {result.stderr}")
        return result.stdout.strip()

    head = git("rev-parse", "HEAD")
    git("read-tree", head)
    tree = git("write-tree")
    date = git("log", "-1", "--format=%cI", head)
    commit_env = {
        **env,
        "GIT_AUTHOR_NAME": "DeerFlow Tenant Freeze",
        "GIT_AUTHOR_EMAIL": "tenant-freeze@deerflow.invalid",
        "GIT_COMMITTER_NAME": "DeerFlow Tenant Freeze",
        "GIT_COMMITTER_EMAIL": "tenant-freeze@deerflow.invalid",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    result = subprocess.run(["git", "-C", str(WORKTREE), "commit-tree", tree, "-m", f"{PHASE} source freeze"], capture_output=True, text=True, env=commit_env)
    if result.returncode:
        sys.exit(f"commit-tree failed: {result.stderr}")
    commit = result.stdout.strip()
    with open(out, "wb") as handle:
        archived = subprocess.run(["git", "-C", str(WORKTREE), "archive", "--format=tar", commit], stdout=handle, env=env)
        if archived.returncode:
            sys.exit("git archive failed")
    subprocess.run(["gzip", "-n", "-9", "-f", out], check=True)
    return subprocess.run(["shasum", "-a", "256", out + ".gz"], capture_output=True, text=True).stdout.split()[0]


PYTEST_ENV_COMMON = (
    "ECS_EXECUTOR_SCOPE_PHYSICAL_TEST=1 "
    f"TEST_SCOPE_EXECUTION_IMAGE={B_IMAGE} "
    "TENANT_TWO_HOST_OWNER=" + OWNER + " "
    "TENANT_TWO_HOST_WORKSPACE_ID=11111111-2222-4333-8333-222222222222 "
    "TENANT_TWO_HOST_WORKER_CREDENTIAL=two-host-worker-node-credential "
    f"TENANT_TWO_HOST_ARTIFACT_ROOT={CROOT}/{PHASE}/pool "
    f"TENANT_TWO_HOST_WORKSPACE_ROOT={CROOT}/{PHASE}/workspace "
    "PYTHONPATH=/tmp/source/backend:/tmp/source/backend/packages/harness:/tmp/source/backend/packages/extension-api:/tmp/source/backend/packages/ecs-executor "
    "DEER_FLOW_HOME=/tmp/tenant-home"
)


def prepare(host: str, digest: str) -> None:
    must(host, f"set -eu; test ! -e {CROOT}/{PHASE} || {{ echo PHASE_EXISTS; exit 3; }}; docker ps -a --format '{{{{.Names}}}}' | grep -q {PHASE} && {{ echo CONTAINER_EXISTS; exit 4; }} || true", what="phase hygiene")
    must(host, f"mkdir -p {CROOT}/{PHASE}/{{pool,workspace,evidence,source}} && chmod 700 {CROOT}/{PHASE}", what="phase dirs")
    scp_to(host, f"/private/tmp/{PHASE}-source.tar.gz", f"{CROOT}/{PHASE}/source.tar.gz")
    got = must(host, f"sha256sum {CROOT}/{PHASE}/source.tar.gz | cut -d' ' -f1")
    if got.strip() != digest:
        sys.exit(f"archive hash mismatch on {host}: {got} != {digest}")


def main() -> None:
    digest = freeze_archive(f"/private/tmp/{PHASE}-source.tar.gz")
    print(f"[freeze] archive sha256 {digest}")
    prepare(CONTROLLER, digest)
    prepare(WORKER, digest)

    print("[controller] postgres")
    must(CONTROLLER, f"""set -eu
docker rm -fv {PHASE}-pg >/dev/null 2>&1 || true
docker run -d --pull=never --name {PHASE}-pg --label org.deerflow.tenant.owned={PHASE} \\
  -p {CONTROLLER_PRIVATE}:55432:5432 -e POSTGRES_PASSWORD=two-host-only -e POSTGRES_DB=tenant \\
  --cpus 1 --memory 1g {PG_IMAGE} >/dev/null
for i in $(seq 1 30); do docker exec {PHASE}-pg pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
for db in tenant_native tenant_executor; do docker exec {PHASE}-pg psql -U postgres -c "CREATE DATABASE $db"; done
""", what="controller postgres")
    base = f"postgresql+psycopg://postgres:two-host-only@{CONTROLLER_PRIVATE}:55432"
    native_url = base + "/tenant_native"
    executor_url = base + "/tenant_executor"

    print("[controller] migrations")
    must(CONTROLLER, f"""set -eu
docker run --rm --pull=never --network host -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro --entrypoint /bin/sh {NATIVE_IMAGE} -c '
set -eu; rm -rf /tmp/source; mkdir /tmp/source; tar xzf /run/source.tar.gz -C /tmp/source
cd /tmp/source/backend
export PYTHONPATH=/tmp/source/backend:/tmp/source/backend/packages/harness:/tmp/source/backend/packages/extension-api:/tmp/source/backend/packages/ecs-executor
/app/backend/.venv/bin/python - <<PY
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pathlib import Path
import deerflow.persistence as p
native = Config(); native.set_main_option("script_location", str(Path(p.__file__).parent / "migrations"))
e = sa.create_engine("{native_url}"); command.upgrade(native, "head"); e.dispose()
import ecs_executor.schema as s
ex = Config(); ex.set_main_option("script_location", str(Path(s.__file__).parent / "migrations"))
e2 = sa.create_engine("{executor_url}"); command.upgrade(ex, "head"); e2.dispose()
print("MIGRATED")
PY'
""", what="migrations")

    print("[controller] start controller pytest (background)")
    must(CONTROLLER, f"""set -eu
printf '[]' > {CROOT}/{PHASE}/evidence/owned.json
nohup docker run --rm --pull=never --name {PHASE}-controller --label org.deerflow.tenant.owned={PHASE} \\
  --network host \\
  -e TENANT_TWO_HOST_ROLE=controller -e TENANT_TWO_HOST_PORT={PORT} \\
  -e TEST_EXECUTOR_POSTGRES_URL='{executor_url}' \\
  -e TENANT_TWO_HOST_NATIVE_URL='{native_url}' \\
  -e {PYTEST_ENV_COMMON} \\
  -e TEST_SCOPE_EVIDENCE='{CROOT}/{PHASE}/evidence/controller.json' \\
  -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro -v {CROOT}/{PHASE}:/run/phase \\
  --entrypoint /bin/sh {NATIVE_IMAGE} -c 'mkdir -p /tmp/source && tar xzf /run/source.tar.gz -C /tmp/source && cd /tmp/source/backend \
  && /app/backend/.venv/bin/python -m pytest tests/test_workspace_two_host_physical.py -q --tb=short --no-showlocals' \\
  > {CROOT}/{PHASE}/controller.log 2>&1 &
echo $! > {CROOT}/{PHASE}/controller.pid
""", what="controller start")

    print("[controller] wait for pool mount id, sync to worker")
    deadline = time.time() + 120
    mount = ""
    while time.time() < deadline:
        mount = must(CONTROLLER, f"cat {CROOT}/{PHASE}/pool/pool-mount-id 2>/dev/null || true").strip()
        if mount:
            break
        time.sleep(2)
    if not mount:
        sys.exit("controller never created the pool mount id")
    must(WORKER, f"mkdir -p {CROOT}/{PHASE}/pool && printf '%s' '{mount}' > {CROOT}/{PHASE}/pool/pool-mount-id && printf '[]' > {CROOT}/{PHASE}/evidence/owned.json", what="worker mount sync")

    print("[worker] run worker pytest")
    must(WORKER, f"""set -eu
docker run --rm --pull=never --name {PHASE}-worker --label org.deerflow.tenant.owned={PHASE} \\
  -v /var/run/docker.sock:/var/run/docker.sock:ro -v /usr/bin/docker:/usr/bin/docker:ro \\
  -v {CROOT}/{PHASE}:/run/phase \\
  -e TENANT_TWO_HOST_ROLE=worker \\
  -e TENANT_TWO_HOST_URL=http://{CONTROLLER_PRIVATE}:{PORT} \\
  -e TENANT_TWO_HOST_NATIVE_URL='{native_url}' \\
  -e {PYTEST_ENV_COMMON} \
  -e TEST_SCOPE_EVIDENCE=/run/phase/evidence/worker.json \
  -e TEST_SCOPE_OWNED_MANIFEST=/run/phase/evidence/owned.json \
  -e DEER_FLOW_HOME=/tmp/tenant-home \
  -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro \
  --entrypoint /bin/sh {NATIVE_IMAGE} -c 'mkdir -p /tmp/source && tar xzf /run/source.tar.gz -C /tmp/source && cd /tmp/source/backend \
  && /app/backend/.venv/bin/python -m pytest tests/test_workspace_two_host_physical.py -q --tb=short --no-showlocals'
""", what="worker pytest")

    print("[controller] wait for controller pytest to finish")
    deadline = time.time() + 300
    while time.time() < deadline:
        running = must(CONTROLLER, f"docker ps --format '{{{{.Names}}}}' | grep -x {PHASE}-controller || true").strip()
        if not running:
            break
        time.sleep(5)
    print(must(CONTROLLER, f"tail -40 {CROOT}/{PHASE}/controller.log"))

    for host in (CONTROLLER, WORKER):
        for remote in (f"{CROOT}/{PHASE}/controller.log", f"{CROOT}/{PHASE}/worker.log", f"{CROOT}/{PHASE}/evidence/controller.json", f"{CROOT}/{PHASE}/evidence/worker.json", f"{CROOT}/{PHASE}/evidence/owned.json"):
            scp_from(host, remote, f"/private/tmp/{PHASE}-artifacts/")
    print(f"[done] artifacts in /private/tmp/{PHASE}-artifacts (digest {digest})")


if __name__ == "__main__":
    main()
