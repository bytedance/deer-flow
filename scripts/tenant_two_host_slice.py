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


COMMON_ENV = {
    "ECS_EXECUTOR_SCOPE_PHYSICAL_TEST": "1",
    "TEST_SCOPE_EXECUTION_IMAGE": B_IMAGE,
    "TENANT_TWO_HOST_OWNER": OWNER,
    "TENANT_TWO_HOST_WORKSPACE_ID": "11111111-2222-4333-8333-222222222222",
    "TENANT_TWO_HOST_WORKER_CREDENTIAL": "two-host-worker-node-credential",
    "TENANT_TWO_HOST_ARTIFACT_ROOT": f"{CROOT}/{PHASE}/pool",
    "TENANT_TWO_HOST_WORKSPACE_ROOT": f"{CROOT}/{PHASE}/workspace",
    "PYTHONPATH": "/tmp/source/backend:/tmp/source/backend/packages/harness:/tmp/source/backend/packages/extension-api:/tmp/source/backend/packages/ecs-executor",
    "DEER_FLOW_HOME": "/tmp/tenant-home",
}


def env_flags(env: dict) -> str:
    return " \
  ".join(f"-e {key}={value}" for key, value in env.items())


def clean_phase(host: str) -> None:
    """Remove only this phase's own labeled containers/networks and its dir."""
    must(host, f"""set -eu
for c in $(docker ps -aq --filter label=org.deerflow.tenant.owned={PHASE}); do
  docker rm -fv $c >/dev/null
done
for n in $(docker network ls --filter label=org.deerflow.tenant.owned={PHASE} --format '{{{{.Name}}}}'); do
  docker network rm $n >/dev/null 2>&1 || true
done
rm -rf {CROOT}/{PHASE}
""", what="phase cleanup")


def prepare(host: str, digest: str) -> None:
    clean_phase(host)
    must(host, f"mkdir -p {CROOT}/{PHASE}/{{pool,workspace,evidence,source}} && chmod 700 {CROOT}/{PHASE}", what="phase dirs")
    scp_to(host, f"/private/tmp/{PHASE}-source.tar.gz", f"{CROOT}/{PHASE}/source.tar.gz")
    got = must(host, f"sha256sum {CROOT}/{PHASE}/source.tar.gz | cut -d' ' -f1")
    if got.strip() != digest:
        sys.exit(f"archive hash mismatch on {host}: {got} != {digest}")


def main() -> None:
    if os.environ.get("TENANT_TWO_HOST_SLICE") == "2":
        run_slice_two()
        return
    digest = freeze_archive(f"/private/tmp/{PHASE}-source.tar")
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

    print("[controller] migrations and native seeding")
    must(CONTROLLER, f"""set -eu
docker run --rm --pull=never --network host -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro --entrypoint /bin/sh {NATIVE_IMAGE} -c '
set -eu; rm -rf /tmp/source; mkdir /tmp/source; tar xzf /run/source.tar.gz -C /tmp/source
cd /tmp/source/backend
export PYTHONPATH=/tmp/source/backend:/tmp/source/backend/packages/harness:/tmp/source/backend/packages/extension-api:/tmp/source/backend/packages/ecs-executor
/app/backend/.venv/bin/python - <<PY
import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from deerflow.persistence import bootstrap
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceRow

OWNER = "{OWNER}"
WORKSPACE = "11111111-2222-4333-8333-222222222222"
THREAD = "two-host-slice-one-thread"
RUN = "11111111-1111-4111-8111-111111111111"
CONTEXT = {{"workspace_id": WORKSPACE, "actor_user_id": OWNER, "membership_version": 1, "policy_version": 1}}

async def migrate_native():
    engine = create_async_engine("{native_url}")
    try:
        await bootstrap.bootstrap_schema(engine, backend="postgres")
    finally:
        await engine.dispose()

asyncio.run(migrate_native())
native = sa.create_engine("{native_url}")
with native.begin() as conn:
    conn.execute(sa.insert(UserRow).values(id=OWNER, email="two-host-owner@example.invalid", account_status="active", email_verified_at=datetime.now(UTC)))
    conn.execute(sa.insert(ThreadMetaRow).values(thread_id=THREAD, user_id=OWNER, incarnation="two-host-epoch", workspace_id=WORKSPACE))
    conn.execute(sa.insert(ThreadMetaRow).values(thread_id="two-host-slice-two-thread", user_id=OWNER, incarnation="two-host-epoch", workspace_id=WORKSPACE))
    conn.execute(sa.insert(RunRow).values(run_id=RUN, thread_id=THREAD, user_id=OWNER, status="running", operation_kind="run",
                               thread_incarnation="two-host-epoch", owner_worker_id="two-host-central",
                               workspace_id=WORKSPACE, workspace_context_json=CONTEXT))
    conn.execute(sa.insert(WorkspaceRow).values(id=WORKSPACE, kind="personal", name="two-host", personal_user_id=OWNER))
    conn.execute(sa.insert(WorkspaceMembershipRow).values(workspace_id=WORKSPACE, user_id=OWNER, role="owner", status="active", version=1))
native.dispose()
from ecs_executor.schema import upgrade_schema
executor = sa.create_engine("{executor_url}")
upgrade_schema(executor)
executor.dispose()
print("MIGRATED_AND_SEEDED")
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
  {env_flags(COMMON_ENV)} \\
  -e TEST_SCOPE_EVIDENCE='{CROOT}/{PHASE}/evidence/controller.json' \\
  -v {CROOT}/{PHASE}:{CROOT}/{PHASE} -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro \\
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
  -v {CROOT}/{PHASE}:{CROOT}/{PHASE} \\
  -e TENANT_TWO_HOST_ROLE=worker \\
  -e TENANT_TWO_HOST_URL=http://{CONTROLLER_PRIVATE}:{PORT} \\
  -e TENANT_TWO_HOST_NATIVE_URL='{native_url}' \\
  {env_flags(COMMON_ENV)} \
  -e TEST_SCOPE_EVIDENCE={CROOT}/{PHASE}/evidence/worker.json \
  -e TEST_SCOPE_OWNED_MANIFEST={CROOT}/{PHASE}/evidence/owned.json \
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




REDIS_IMAGE = "sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499"
NATIVE_SECRET = "two-host-native-node-secret-32-bytes-fixed"
INTERNAL_TOKEN = "two-host-internal-auth-token"


def run_slice_two() -> None:
    digest = freeze_archive(f"/private/tmp/{PHASE}-source.tar")
    print(f"[freeze] archive sha256 {digest}")
    prepare(CONTROLLER, digest)
    prepare(WORKER, digest)
    must(CONTROLLER, f"""set -eu
docker rm -fv {PHASE}-pg {PHASE}-redis >/dev/null 2>&1 || true
docker run -d --pull=never --name {PHASE}-pg --label org.deerflow.tenant.owned={PHASE} \
  -p {CONTROLLER_PRIVATE}:55432:5432 -e POSTGRES_PASSWORD=two-host-only -e POSTGRES_DB=tenant \
  --cpus 1 --memory 1g {PG_IMAGE} >/dev/null
for i in $(seq 1 30); do docker exec {PHASE}-pg pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
for db in tenant_native tenant_executor; do docker exec {PHASE}-pg psql -U postgres -c "CREATE DATABASE $db"; done
docker run -d --pull=never --name {PHASE}-redis --label org.deerflow.tenant.owned={PHASE} \
  -p {CONTROLLER_PRIVATE}:6390:6379 {REDIS_IMAGE} >/dev/null
""", what="controller pg+redis")
    base = f"postgresql+psycopg://postgres:two-host-only@{CONTROLLER_PRIVATE}:55432"
    native_url = base + "/tenant_native"
    executor_url = base + "/tenant_executor"
    native_async_url = f"postgresql+asyncpg://postgres:two-host-only@{CONTROLLER_PRIVATE}:55432/tenant_native"
    redis_url = f"redis://{CONTROLLER_PRIVATE}:6390/0"
    print("[controller] slice-two migrations and seeding")
    must(CONTROLLER, f"""set -eu
cat > /tmp/.two-host-migrate.py
docker run --rm --pull=never --network host \\
  -e NATIVE_ASYNC='{native_async_url}' -e NATIVE_SYNC='{native_url}' -e EXECUTOR_SYNC='{executor_url}' \\
  -v /tmp/.two-host-migrate.py:/run/migrate.py:ro -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro \\
  --entrypoint /bin/sh {NATIVE_IMAGE} -c '
set -eu; rm -rf /tmp/source; mkdir /tmp/source; tar xzf /run/source.tar.gz -C /tmp/source
cd /tmp/source/backend
export PYTHONPATH=/tmp/source/backend:/tmp/source/backend/packages/harness:/tmp/source/backend/packages/extension-api:/tmp/source/backend/packages/ecs-executor
/app/backend/.venv/bin/python /run/migrate.py'
rm -f /tmp/.two-host-migrate.py
""", what="slice-two migrations", stdin_text=_SLICE_TWO_MIGRATE)
    common = dict(COMMON_ENV)
    common.update(
        {
            "TENANT_TWO_HOST_NATIVE_URL": native_url,
            "TENANT_TWO_HOST_NATIVE_ASYNC_URL": native_async_url,
            "TENANT_TWO_HOST_REDIS_URL": redis_url,
            "TENANT_TWO_HOST_WORKER_CREDENTIAL": NATIVE_SECRET,
            "DEER_FLOW_INTERNAL_AUTH_TOKEN": INTERNAL_TOKEN,
            "TEST_EXECUTOR_POSTGRES_URL": executor_url,
        }
    )
    print("[controller] start native-controller pytest (background)")
    must(CONTROLLER, f"""set -eu
nohup docker run --rm --pull=never --name {PHASE}-controller --label org.deerflow.tenant.owned={PHASE} \
  --network host \
  -e TENANT_TWO_HOST_ROLE=native-controller -e TENANT_TWO_HOST_NATIVE_PORT={PORT + 1} \
  -v {CROOT}/{PHASE}:{CROOT}/{PHASE} -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro \
  {env_flags(common)} \
  -e TEST_SCOPE_EVIDENCE='{CROOT}/{PHASE}/evidence/native-controller.json' \
  --entrypoint /bin/sh {NATIVE_IMAGE} -c 'mkdir -p /tmp/source && tar xzf /run/source.tar.gz -C /tmp/source && cd /tmp/source/backend \
  && /app/backend/.venv/bin/python -m pytest tests/test_workspace_two_host_physical.py -q --tb=short --no-showlocals' \
  > {CROOT}/{PHASE}/controller.log 2>&1 &
echo $! > {CROOT}/{PHASE}/controller.pid
""", what="native-controller start")
    print("[controller] wait for pool mount id, sync to worker")
    deadline = time.time() + 120
    mount = ""
    while time.time() < deadline:
        mount = must(CONTROLLER, f"cat {CROOT}/{PHASE}/pool/pool-mount-id 2>/dev/null || true").strip()
        if mount:
            break
        time.sleep(2)
    if not mount:
        sys.exit("native controller never created the pool mount id")
    must(WORKER, f"mkdir -p {CROOT}/{PHASE}/pool && printf '%s' '{mount}' > {CROOT}/{PHASE}/pool/pool-mount-id", what="worker mount sync")
    worker_env = dict(common)
    worker_env.update(
        {
            "TENANT_TWO_HOST_ROLE": "native-worker",
            "TENANT_TWO_HOST_NATIVE_EXECUTOR_URL": f"http://{CONTROLLER_PRIVATE}:{PORT + 1}",
            "TENANT_TWO_HOST_NATIVE_NODE_SECRET": NATIVE_SECRET,
            "TEST_SCOPE_EVIDENCE": f"{CROOT}/{PHASE}/evidence/native-worker.json",
        }
    )
    print("[worker] run native-worker pytest")
    must(WORKER, f"""set -eu
docker run --rm --pull=never --name {PHASE}-worker --label org.deerflow.tenant.owned={PHASE} \
  --network host \
  -v {CROOT}/{PHASE}:{CROOT}/{PHASE} -v {CROOT}/{PHASE}/source.tar.gz:/run/source.tar.gz:ro \
  {env_flags(worker_env)} \
  --entrypoint /bin/sh {NATIVE_IMAGE} -c 'mkdir -p /tmp/source && tar xzf /run/source.tar.gz -C /tmp/source && cd /tmp/source/backend \
  && /app/backend/.venv/bin/python -m pytest tests/test_workspace_two_host_physical.py -q --tb=short --no-showlocals'
""", what="native-worker pytest")
    print("[controller] wait for native-controller pytest to finish")
    deadline = time.time() + 300
    while time.time() < deadline:
        running = must(CONTROLLER, f"docker ps --format '{{{{.Names}}}}' | grep -x {PHASE}-controller || true").strip()
        if not running:
            break
        time.sleep(5)
    print(must(CONTROLLER, f"tail -30 {CROOT}/{PHASE}/controller.log"))
    for host in (CONTROLLER, WORKER):
        for remote in (f"{CROOT}/{PHASE}/controller.log", f"{CROOT}/{PHASE}/evidence/native-controller.json", f"{CROOT}/{PHASE}/evidence/native-worker.json"):
            scp_from(host, remote, f"/private/tmp/{PHASE}-artifacts/")
    print(f"[done] slice 2 artifacts in /private/tmp/{PHASE}-artifacts (digest {digest})")


_SLICE_TWO_MIGRATE = """
import asyncio
import os
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceRow

OWNER = "two-host-owner"
WORKSPACE = "11111111-2222-4333-8333-222222222222"


async def migrate_native(engine_url):
    engine = create_async_engine(engine_url)
    try:
        await bootstrap.bootstrap_schema(engine, backend="postgres")
    finally:
        await engine.dispose()


asyncio.run(migrate_native(os.environ["NATIVE_ASYNC"]))
native = sa.create_engine(os.environ["NATIVE_SYNC"])
with native.begin() as conn:
    conn.execute(sa.insert(UserRow).values(id=OWNER, email="two-host-owner@example.invalid", account_status="active", email_verified_at=datetime.now(UTC)))
    conn.execute(sa.insert(ThreadMetaRow).values(thread_id="two-host-slice-two-thread", user_id=OWNER, incarnation="two-host-epoch", workspace_id=WORKSPACE))
    conn.execute(sa.insert(WorkspaceRow).values(id=WORKSPACE, kind="personal", name="two-host", personal_user_id=OWNER))
    conn.execute(sa.insert(WorkspaceMembershipRow).values(workspace_id=WORKSPACE, user_id=OWNER, role="owner", status="active", version=1))
native.dispose()
from ecs_executor.schema import upgrade_schema

executor = sa.create_engine(os.environ["EXECUTOR_SYNC"])
upgrade_schema(executor)
executor.dispose()
print("SLICE_TWO_MIGRATED")
"""


if __name__ == "__main__":
    main()
